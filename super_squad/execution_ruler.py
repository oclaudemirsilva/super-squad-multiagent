"""execution_ruler.py — régua OBJETIVA para papéis ATIVOS (code-writer/debugger): aplica o PATCH do
modelo ao código-com-bug e roda o TESTE confiável do gold; `pass = o teste passou`. É o oráculo que
destrava golds SEM autoria manual (a verdade é EXECUTÁVEL, não uma opinião).

⚠ SEGURANÇA (honesto, não maquiado): um `tempdir + subprocess` é uma CERCA DE CORRETUDE, NÃO um limite
de segurança. NÃO impede egress de rede, leitura de arquivos do host, exploit de kernel, etc. O isolamento
REAL vem do `run_fn` INJETADO (um runner OS-sandboxed: `unshare -n` / nsjail / firejail / container / microVM
descartável). Por isso `require_isolation=True` por DEFAULT: sem um runner marcado `isolation_capable`, a régua
RECUSA executar (fail-closed) — a menos que o chamador passe `allow_unsandboxed=True` EXPLÍCITO.

TRUST SPLIT: `text` (o patch do modelo) é a ÚNICA entrada NÃO-confiável. `test_cmd`/`setup_cmd` são argv
LISTAS (shell=False sempre) → o patch nunca vira comando, só vira DADO escrito num arquivo. O ORÁCULO
(`test_files`) é re-materializado DEPOIS do apply, então um patch NÃO pode adulterar o próprio juiz
(nem plantar `conftest.py`/`sitecustomize.py`/`*.pth` que rodam código na coleta).

Contrato de régua (rulers.py): `ruler(text, gold=None) -> {"pass": bool, "label": str, ...}`, NUNCA levanta
(um try/except externo mapeia qualquer erro interno → `pass=False, label="ruler_error"`). Tudo INJETÁVEL
(`run_fn`/`apply_fn`/`make_workspace`/`env_builder`/`redact`) → testes 100% herméticos (zero subprocess/rede).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional

# Nomes que EXECUTAM código na coleta do pytest/import — o patch nunca pode criá-los (senão roda antes
# mesmo do teste "confiável"). Re-materializamos só o conjunto confiável; qualquer um destes é barrado.
_COLLECTION_HOOKS = ("conftest.py", "sitecustomize.py", "usercustomize.py")


@dataclass(frozen=True)
class ApplyResult:
    """Resultado de aplicar o patch. `touched` = caminhos escritos (p/ detectar adulteração do oráculo)."""
    ok: bool
    reason: str = ""
    unsafe: bool = False
    files: "dict[str, bytes]" = field(default_factory=dict)
    touched: "tuple[str, ...]" = ()


@dataclass(frozen=True)
class RunResult:
    """Resultado de rodar um argv. `timed_out`/`spawn_error` separam os modos de falha do returncode."""
    returncode: "Optional[int]" = None
    timed_out: bool = False
    spawn_error: bool = False
    stdout: str = ""
    stderr: str = ""


# ── contenção de caminho (fail-closed) ─────────────────────────────────────────

def _is_contained(relpath: str) -> bool:
    """True se `relpath` é seguro sob a raiz da worktree: sem absoluto, sem `..` que escape, sem NUL."""
    if not relpath or "\x00" in relpath:
        return False
    if os.path.isabs(relpath) or (len(relpath) >= 2 and relpath[1] == ":"):  # POSIX/Windows abs
        return False
    norm = os.path.normpath(relpath).replace("\\", "/")
    return not (norm == ".." or norm.startswith("../"))


# ── applier stdlib (exato por CONTEÚDO, offset-independente, whole-or-nothing) ──

def _split_keep(text: str) -> "list[str]":
    return text.splitlines(keepends=True)


def _parse_unified_diff(text: str) -> "Optional[dict[str, list]]":
    """Diff unificado → {path: [hunk, ...]}, onde cada hunk é uma lista de ops `(op, linha)` com
    `op ∈ {"ctx","del","add"}` na ORDEM emitida. None se não parece diff.
    Ignora os offsets `@@ -a,b +c,d @@` de propósito: localizamos o hunk pelo CONTEÚDO (contexto+removidas),
    então números de linha desatualizados que o modelo emitiu não importam. As ops taggeadas preservam
    quais linhas são contexto (mantemos as do ARQUIVO) vs. adicionadas (usamos as do MODELO) — isso permite
    o casamento tolerante (whitespace) sem reescrever a indentação real do arquivo."""
    lines = text.splitlines()
    if not any(l.startswith(("diff --git", "--- ", "@@ ")) for l in lines):
        return None
    out: "dict[str, list]" = {}
    path: "Optional[str]" = None
    ops: "list[tuple[str, str]]" = []
    in_hunk = False

    def flush():
        nonlocal ops
        if path is not None and ops:
            out.setdefault(path, []).append(ops)
        ops = []

    for l in lines:
        if l.startswith("+++ "):
            flush()
            p = l[4:].strip()
            path = p[2:] if p.startswith("b/") else p
            in_hunk = False
        elif l.startswith("--- ") or l.startswith("diff --git") or l.startswith("index "):
            continue
        elif l.startswith("@@"):
            flush()
            in_hunk = True
        elif in_hunk and path is not None:
            if l.startswith("+"):
                ops.append(("add", l[1:] + "\n"))
            elif l.startswith("-"):
                ops.append(("del", l[1:] + "\n"))
            elif l.startswith(" "):
                ops.append(("ctx", l[1:] + "\n"))
            elif l.startswith("\\"):  # "\ No newline at end of file"
                continue
            else:
                flush()
                in_hunk = False
    flush()
    return out or None


def _norm_rstrip(s: str) -> str:
    """Tolerância nível 1: ignora só whitespace À DIREITA (trailing ws, `\\r`, newline final).
    Seguro — não muda o significado da linha em Python."""
    return s.rstrip()


def _norm_ws(s: str) -> str:
    """Tolerância nível 2: ignora TODO whitespace (indentação/espaçamento). Mais permissivo → só
    para LOCALIZAR o bloco; a linha REESCRITA continua vindo do arquivo (contexto) ou do modelo (add)."""
    return "".join(s.split())


def _find_unique(cur: "list[str]", before: "list[str]", norm: "Callable[[str], str]") -> int:
    """Índice ÚNICO onde `before` casa em `cur` sob a normalização `norm`. -1 se não casa;
    -2 se AMBÍGUO (>1 posição) — nesse caso recusamos aplicar (não adivinha)."""
    n = len(before)
    nb = [norm(x) for x in before]
    hits = [i for i in range(len(cur) - n + 1) if [norm(x) for x in cur[i:i + n]] == nb]
    if not hits:
        return -1
    if len(hits) > 1:
        return -2
    return hits[0]


def _apply_hunks(content: str, hunks: "list") -> "Optional[str]":
    """Aplica os hunks de UM arquivo por busca de CONTEÚDO, whole-or-nothing por arquivo. Localiza o bloco
    contexto+removidas com tolerância graduada a whitespace; ao reescrever, mantém a linha ORIGINAL do
    arquivo para contexto/removidas e usa a linha do MODELO só para adições. Retorna None se QUALQUER hunk
    não localizar seu bloco (ou for ambíguo na tolerância) → `apply_failed` honesto (nunca aplica no lugar errado)."""
    cur = _split_keep(content)
    for hunk in hunks:
        before = [t for op, t in hunk if op in ("ctx", "del")]
        if not before:                       # inserção pura sem contexto = ambígua sem offset → falha honesta
            return None
        # tolerância graduada: exato (first-match, compat) → rstrip único → ws-insensível único.
        n = len(before)
        idx = next((i for i in range(len(cur) - n + 1) if cur[i:i + n] == before), -1)
        if idx < 0:
            for norm in (_norm_rstrip, _norm_ws):
                idx = _find_unique(cur, before, norm)
                if idx >= 0:
                    break
                if idx == -2:                # ambíguo sob esta norma → não escala p/ norma mais frouxa
                    return None
        if idx < 0:
            return None                       # bloco não encontrado → apply_failed
        segment: "list[str]" = []
        si = idx
        for op, t in hunk:
            if op == "ctx":
                segment.append(cur[si]); si += 1     # preserva a linha REAL do arquivo (indentação inclusa)
            elif op == "del":
                si += 1                               # consome e descarta
            else:                                     # add: linha do modelo, verbatim
                segment.append(t)
        cur = cur[:idx] + segment + cur[si:]
    return "".join(cur)


def _default_apply(text: str, base_files: "dict[str, bytes]", *, patch_target: "Optional[str]" = None) -> ApplyResult:
    """Aplica o patch (diff unificado OU arquivo inteiro) sobre `base_files`. Whole-or-nothing global:
    se qualquer arquivo-alvo falhar, nada é escrito (`ok=False`). Contenção de caminho antes de tudo."""
    raw = (text or "").strip()
    if not raw:
        return ApplyResult(ok=False, reason="empty_patch")
    diff = _parse_unified_diff(text)
    new_files = dict(base_files)
    touched: "list[str]" = []
    if diff is not None:
        for path, hunks in diff.items():
            if not _is_contained(path):
                return ApplyResult(ok=False, reason=f"unsafe_path:{path}", unsafe=True)
            base = base_files.get(path, b"").decode("utf-8", errors="replace")
            applied = _apply_hunks(base, hunks)
            if applied is None:
                return ApplyResult(ok=False, reason=f"hunk_not_found:{path}")
            new_files[path] = applied.encode("utf-8")
            touched.append(path)
        return ApplyResult(ok=True, files=new_files, touched=tuple(touched))
    # modo arquivo-inteiro: precisa de um alvo explícito (do gold) — nunca adivinha.
    if not patch_target:
        return ApplyResult(ok=False, reason="no_diff_no_target")
    if not _is_contained(patch_target):
        return ApplyResult(ok=False, reason=f"unsafe_path:{patch_target}", unsafe=True)
    new_files[patch_target] = raw.encode("utf-8")
    return ApplyResult(ok=True, files=new_files, touched=(patch_target,))


# ── workspace + run (as duas costuras de I/O; produção injeta as reais) ─────────

def _default_make_workspace(files: "dict[str, bytes]") -> str:
    """Materializa `files` num tempdir novo (contenção reforçada). Levanta se algum path escapar
    (o chamador captura → unsafe_path). Só cria dirs sob a raiz; recusa symlink."""
    root = tempfile.mkdtemp(prefix="exec_ruler_")
    for rel, data in files.items():
        if not _is_contained(rel):
            raise ValueError(f"unsafe_path:{rel}")
        dest = os.path.join(root, rel)
        real = os.path.realpath(dest)
        if os.path.commonpath([real, os.path.realpath(root)]) != os.path.realpath(root):
            raise ValueError(f"unsafe_path:{rel}")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
    return root


def _minimal_env() -> "dict[str, str]":
    """Env mínimo (allowlist): sem AWS_*/OPENAI_*/tokens/proxy → um patch executado não lê segredos do host."""
    base = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1"}
    return {k: v for k, v in base.items() if v}


def _default_run(argv, cwd, timeout_s, env):  # pragma: no cover — fail-closed: exige runner isolado injetado
    """Runner DEFAULT = fail-closed. NÃO é `isolation_capable`, então a régua recusa usá-lo com
    require_isolation=True. Produção injeta um runner OS-sandboxed (unshare/nsjail/container)."""
    raise RuntimeError(
        "execution_ruler: nenhum run_fn ISOLADO injetado. Um tempdir+subprocess não é sandbox de segurança — "
        "injete um run_fn OS-sandboxed (isolation_capable=True) ou passe allow_unsandboxed=True ciente do risco."
    )


def _expect_ok(expect: str, r: RunResult) -> bool:
    """`exit0` → rc==0. `exit0+substring:FOO` → rc==0 E 'FOO' na saída CONFIÁVEL capturada (nunca
    um auto-relato do patch)."""
    if r.returncode != 0:
        return False
    if expect.startswith("exit0+substring:"):
        needle = expect.split(":", 1)[1]
        return needle in (r.stdout or "") or needle in (r.stderr or "")
    return True


def execution_ruler(
    buggy_files: "dict[str, bytes]",
    test_cmd: "list[str]",
    *,
    test_files: "Optional[dict[str, bytes]]" = None,
    setup_cmd: "Optional[list[str]]" = None,
    patch_target: "Optional[str]" = None,
    timeout_s: float = 30.0,
    expect: str = "exit0",
    require_isolation: bool = True,
    allow_unsandboxed: bool = False,
    apply_fn: "Optional[Callable]" = None,
    run_fn: "Optional[Callable]" = None,
    make_workspace: "Optional[Callable]" = None,
    env_builder: "Optional[Callable]" = None,
    redact: "Optional[Callable]" = None,
):
    """Fábrica: devolve `ruler(text, gold=None) -> dict`. `text` = patch do modelo (NÃO-confiável). Todo o
    resto é gold CONFIÁVEL. Fail-closed em toda decisão; NUNCA levanta pro chamador."""
    apply_fn = apply_fn or _default_apply
    run_fn = run_fn or _default_run
    make_workspace = make_workspace or _default_make_workspace
    env_builder = env_builder or _minimal_env
    if redact is None:
        from super_squad.runtimes.hardening import redact_secrets as redact
    test_files = test_files or {}
    protected = set(test_files) | set(_COLLECTION_HOOKS)

    def _verdict(passed, label, r: "Optional[RunResult]" = None, extra=None):
        # `stderr` (redigido) é exposto p/ o DEBUG do orquestrador de loop realimentar o próximo tiro;
        # o env é mínimo (sem segredos) e passa pelo redator de todo jeito. Aditivo — não quebra o contrato.
        d = {"pass": passed, "label": label,
             "returncode": (r.returncode if r else None),
             "detail": redact(str(extra)) if extra else "",
             "stderr": redact(r.stderr) if (r and getattr(r, "stderr", "")) else ""}
        return d

    def ruler(text: str, gold: object = None) -> dict:
        # Portão de ISOLAMENTO (fail-closed): sem runner isolado e sem opt-out explícito, NÃO executa.
        if require_isolation and not allow_unsandboxed and not getattr(run_fn, "isolation_capable", False):
            return _verdict(False, "isolation_required",
                            extra="run_fn não é isolation_capable; passe allow_unsandboxed=True ciente do risco")
        ws = None
        try:
            # 1) aplica o patch sobre o código-com-bug (whole-or-nothing; contenção de caminho).
            res = apply_fn(text, buggy_files, patch_target=patch_target)
            if not res.ok:
                return _verdict(False, "unsafe_path" if res.unsafe else "apply_failed", extra=res.reason)
            # 2) ORÁCULO HARD-GUARD: se o patch tocou um caminho protegido (teste/hook), marca — e de todo
            #    jeito RE-MATERIALIZA o conjunto confiável POR CIMA, então o veredito não confia no que o
            #    patch escreveu no oráculo.
            patched_oracle = bool(set(res.touched) & protected)
            tree = dict(res.files)
            for p in list(tree):
                base = os.path.basename(p)
                if (base in _COLLECTION_HOOKS or p.endswith(".pth")) and p not in test_files:
                    tree.pop(p, None)               # remove hook plantado pelo patch (não estava no confiável)
            tree.update(test_files)                  # oráculo confiável por cima (overlay estrito pós-apply)
            ws = make_workspace(tree)
            env = env_builder()
            # 3) setup (confiável) se houver.
            if setup_cmd:
                rs = run_fn(setup_cmd, ws, timeout_s, env)
                if rs.timed_out:
                    return _verdict(False, "setup_timeout")
                if rs.spawn_error or rs.returncode != 0:
                    return _verdict(False, "run_error" if rs.spawn_error else "setup_failed", rs)
            # 4) teste (confiável) — o veredito.
            rt = run_fn(test_cmd, ws, timeout_s, env)
            if rt.timed_out:
                return _verdict(False, "test_timeout")
            if rt.spawn_error:
                return _verdict(False, "run_error", rt)
            if _expect_ok(expect, rt):
                label = "patched_oracle_pass" if patched_oracle else "pass"
                return _verdict(True, label, rt)
            return _verdict(False, "test_fail", rt)
        except Exception as e:  # noqa: BLE001 — a régua NUNCA levanta pro chamador (contrato)
            return _verdict(False, "ruler_error", extra=repr(e))
        finally:
            if ws:
                shutil.rmtree(ws, ignore_errors=True)

    return ruler
