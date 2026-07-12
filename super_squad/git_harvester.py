"""git_harvester.py — COLHE golds do histórico do git (verdade HUMANA, sem autoria manual, anti-autofagia).

Um commit-de-fix É a rotulação humana ("isto era um bug"): o pai = código ANTES (input), a mensagem = a
SPEC, e o TESTE que o fix faz passar = o ORÁCULO. O harvester recolhe isso em casos de gold no formato do
`role_eval` com `ruler="execution"`. O modelo medido nunca vê o fix humano (`reference_patch` é só metadado);
ele precisa produzir SEU patch que faz o oráculo passar → o veredito é execução objetiva, não casar diff.

INTEGRIDADE (D6): a verdade vem de commits/testes de HUMANOS reais, não de um modelo → não é autofagia.
CUIDADO DE VAZAMENTO: modelos podem ter MEMORIZADO fixes públicos → preferir repos recentes/privados +
de-dup por fonte (`provenance.repo`). Marcado `origin="human_commit"`, `gold_origin="git-history"`.

SOLID/DIP: `run_git(argv) -> objeto com .returncode/.stdout/.stderr` é a ÚNICA costura de I/O — injeta-se um
fake em teste (zero git real). NUNCA levanta: toda anomalia vira um SKIP com motivo (nunca uma exceção).
stdlib-only; usa só plumbing do git (log/show/diff), nunca GitPython.
"""
from __future__ import annotations

import re
import subprocess
from collections import namedtuple
from typing import Callable, Optional

GitResult = namedtuple("GitResult", "returncode stdout stderr")

_FS = "\x00"   # separador de campo (byte real, na SAÍDA do git)
_RS = "\x1e"   # separador de registro (byte real, na SAÍDA do git)
# No --format enviado ao git usam-se os ESCAPES (%x00/%x1e); passar o byte NUL cru num argv é ilegal
# (ValueError: embedded null character). O git emite os bytes reais, que o parser abaixo separa.
_GFS = "%x00"
_GRS = "%x1e"

_DEFAULT_FIX_KW = ("fix", "fixes", "fixed", "bug", "bugfix", "resolve", "resolves",
                   "closes", "regression", "hotfix", "defect")
# denylist: mata falsos-positivos de substring ('prefix'/'suffix'/'fixture' contêm 'fix').
_KW_DENY = ("fixture", "prefix", "suffix", "affix", "postfix", "infix")
_TEST_PATH_RE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.(py|go|js|ts)$|[^/]*\.test\.(js|ts)$|spec/)")
_SOURCE_EXTS = (".py", ".js", ".ts", ".go", ".java", ".rb", ".rs")
_ISSUE_RE = re.compile(r"(?:closes|fixes|resolves)?\s*#(\d+)|GH-(\d+)", re.IGNORECASE)
_ADDED_TESTFN_RE = re.compile(r"^\+\s*(?:def (test_\w+)|func (Test\w+)|(?:it|test)\(['\"])")


def _default_git_run(repo: str) -> "Callable[[list[str]], GitResult]":
    """Runner real (produção): shell=False, decodifica utf-8 tolerante, nunca levanta (returncode!=0 ok)."""
    def run(args: "list[str]") -> GitResult:
        try:
            p = subprocess.run(["git", "-C", repo, *args], capture_output=True, timeout=60)
            return GitResult(p.returncode,
                             p.stdout.decode("utf-8", errors="replace"),
                             p.stderr.decode("utf-8", errors="replace"))
        except Exception as e:  # noqa: BLE001 — falha de git vira returncode negativo, não exceção
            return GitResult(-1, "", repr(e))
    return run


def _is_fix_message(subject: str, body: str) -> bool:
    text = f"{subject}\n{body}".lower()
    if any(d in text for d in _KW_DENY) and not any(re.search(rf"\b{kw}\b", text) for kw in _DEFAULT_FIX_KW
                                                    if kw not in "".join(_KW_DENY)):
        pass  # deny só bloqueia se não houver keyword LIMPA por word-boundary; segue a checagem abaixo
    if "revert" in text.split("\n", 1)[0]:
        return False
    return any(re.search(rf"\b{re.escape(kw)}\b", text) for kw in _DEFAULT_FIX_KW)


def _classify(name_status: str) -> "tuple[list, list]":
    """Saída de `diff --name-status -M` → (fontes_tocadas[(status,path)], testes_tocados[(status,path)])."""
    srcs, tests = [], []
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0][:1], parts[-1]
        if _TEST_PATH_RE.search(path):
            tests.append((status, path))
        elif path.endswith(_SOURCE_EXTS):
            srcs.append((status, path))
    return srcs, tests


def _test_cmd_for(path: str, added_fn: "Optional[str]", default_cmd) -> "Optional[list]":
    """argv de teste por extensão (runner_map auditável), estreitado à função adicionada quando dá."""
    if path.endswith(".py"):
        target = f"{path}::{added_fn}" if added_fn else path
        return ["python", "-m", "pytest", "-q", target]
    if path.endswith("_test.go") or path.endswith(".go"):
        return ["go", "test", "./..."]
    if path.endswith((".test.js", ".test.ts")):
        return ["npm", "test", "--", path]
    return list(default_cmd) if default_cmd else None


def _added_test_fn(diff_text: str) -> "Optional[str]":
    """Primeira função de teste ADICIONADA no hunk (def test_/func Test/it()) — o gate red→green."""
    for line in diff_text.splitlines():
        m = _ADDED_TESTFN_RE.match(line)
        if m:
            return next((g for g in m.groups() if g), None)
    return None


def _looks_binary(text: str) -> bool:
    if "\x00" in text:
        return True
    if not text:
        return False
    repl = text.count("�")
    return repl / len(text) > 0.30


def harvest_with_report(
    run_git: "Callable[[list[str]], GitResult]",
    *,
    ref: str = "HEAD",
    since: "Optional[str]" = None,
    max_commits: int = 500,
    default_test_cmd: "Optional[list]" = None,
    max_file_bytes: int = 256 * 1024,
    require_both_signals: bool = False,
    repo_name: str = "repo",
) -> "tuple[list, list]":
    """Colhe casos + devolve `(cases, diagnostics)`. Cada anomalia vira um skip `{sha, reason}` — nunca crash."""
    diags: list = []
    cases: list = []

    fmt = f"%H{_GFS}%P{_GFS}%an{_GFS}%aI{_GFS}%s{_GFS}%b{_GRS}"
    args = ["log", "--no-merges", f"-n{max_commits}", f"--format={fmt}"]
    if since:
        args.append(f"--since={since}")
    args.append(ref)
    res = run_git(args)
    if res.returncode != 0:
        return [], [{"sha": None, "reason": f"rev_list_failed:{(res.stderr or '')[:80]}"}]

    for record in res.stdout.split(_RS):
        record = record.strip("\n")
        if not record:
            continue
        try:
            fields = record.split(_FS)
            if len(fields) < 6:
                diags.append({"sha": None, "reason": "unparsable_record"})
                continue
            sha, parents_s, author, atime, subject, body = fields[:6]
            parents = parents_s.split()
            short = sha[:10]
            if not parents:
                diags.append({"sha": short, "reason": "root"})
                continue
            if len(parents) > 1:
                diags.append({"sha": short, "reason": "merge"})
                continue
            parent = parents[0]

            keyword = _is_fix_message(subject, body)
            ns = run_git(["diff", "--name-status", "-M", parent, sha])
            srcs, tests = _classify(ns.stdout if ns.returncode == 0 else "")
            structural = bool(srcs and tests)
            if not (keyword or structural):
                continue  # não é fix → ignora silencioso (não é anomalia)
            if require_both_signals and not (keyword and structural):
                diags.append({"sha": short, "reason": "low_confidence"})
                continue

            # oráculo: precisa de um teste ADICIONADO/MODIFICADO (senão não há gate red→green).
            oracle = next(((s, p) for s, p in tests if s in ("A", "M")), None)
            if not oracle:
                diags.append({"sha": short, "reason": "no_oracle"})
                continue
            _, testpath = oracle
            tdiff = run_git(["diff", parent, sha, "--", testpath])
            added_fn = _added_test_fn(tdiff.stdout if tdiff.returncode == 0 else "")

            test_cmd = _test_cmd_for(testpath, added_fn, default_test_cmd)
            if test_cmd is None:
                diags.append({"sha": short, "reason": "no_runner"})
                continue

            # buggy_files = fontes tocadas NO ESTADO DO PAI (o "antes").
            buggy: "dict[str, bytes]" = {}
            oversized = False
            for _s, p in srcs:
                blob = run_git(["show", f"{parent}:{p}"])
                if blob.returncode != 0:
                    continue  # arquivo novo (não existia no pai) → não faz parte do "antes"
                if _looks_binary(blob.stdout):
                    continue
                data = blob.stdout.encode("utf-8", errors="replace")
                if len(data) > max_file_bytes:
                    oversized = True
                    continue
                buggy[p] = data
            if not buggy:
                diags.append({"sha": short, "reason": "too_large" if oversized else "no_buggy_source"})
                continue

            # test_files = teste NO ESTADO DO COMMIT (pós-fix) — o oráculo confiável.
            tblob = run_git(["show", f"{sha}:{testpath}"])
            if tblob.returncode != 0 or _looks_binary(tblob.stdout):
                diags.append({"sha": short, "reason": "oracle_unreadable"})
                continue
            test_files = {testpath: tblob.stdout.encode("utf-8", errors="replace")}

            issue = _ISSUE_RE.search(f"{subject}\n{body}")
            issue_ref = f"#{issue.group(1) or issue.group(2)}" if issue else None
            detected = [d for d, on in (("keyword", keyword), ("structural", structural)) if on]

            cases.append({
                "case_id": f"{repo_name}@{short}",
                "role": "debugger",
                "ruler": "execution",
                "spec": _redact(f"{subject}\n\n{body}".strip()),
                "issue_ref": issue_ref,
                "buggy_files": buggy,
                "test_files": test_files,
                "test_cmd": test_cmd,
                "setup_cmd": None,
                "timeout_s": 60,
                "expect": "exit0",
                "expect_baseline_fail": None,   # PROVISIONAL até validar red→green (humano/held-out)
                "reference_patch_ref": f"{parent}..{sha}",  # só metadado; NUNCA vai pro modelo
                "provenance": {"repo": repo_name, "sha": sha, "parent": parent, "author": author,
                               "author_time": atime, "detected_by": detected,
                               "confidence": "high" if keyword and structural else "medium"},
                "origin": "human_commit",
                "gold_origin": "git-history",
            })
        except Exception as e:  # noqa: BLE001 — um commit ruim vira skip, nunca derruba a colheita
            diags.append({"sha": record[:10], "reason": f"error:{type(e).__name__}"})
            continue

    cases.sort(key=lambda c: c["provenance"]["author_time"])
    return cases, diags


def harvest(run_git=None, *, repo: str = ".", **kw) -> list:
    """Assinatura simples (só a lista). `run_git` default = git real em `repo`. Ver `harvest_with_report`."""
    if run_git is None:
        run_git = _default_git_run(repo)
    kw.setdefault("repo_name", repo.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "repo")
    cases, _ = harvest_with_report(run_git, **kw)
    return cases


def _redact(text: str) -> str:
    from super_squad.runtimes.hardening import redact_secrets
    return redact_secrets(text)
