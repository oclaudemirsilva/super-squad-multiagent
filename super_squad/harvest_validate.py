"""harvest_validate.py — valida red→green os casos colhidos pelo git_harvester, produzindo o GOLD OBJETIVO
dos papéis ATIVOS (code-writer/debugger) SEM autoria manual.

Um caso colhido só vira gold se o oráculo EXECUTA como um bug de verdade:
  • RED   — o teste (pós-fix) roda sobre o código-com-bug (pré-fix) e FALHA. Se PASSA, o teste não pega o
            bug daquele estado → o caso é inútil (descartado). É o `expect_baseline_fail`.
  • GREEN — o teste roda sobre o código CONSERTADO (pós-fix, do próprio commit humano) e PASSA. Se falha, o
            fix depende de coisas que não colhemos (deps/outros arquivos) → descartado.
Só red∧green = gold válido: um MODELO medido depois tem que produzir SEU patch que faz red→green de novo.
A verdade é EXECUÇÃO (não casar o diff humano), então nunca se autora "o patch esperado".

⚠ VAZAMENTO (trava nº1, D-next-session): a fonte do harvest tem que ser FRESCA/PRIVADA e não-memorizada;
dataset público famoso mede "memorizou?", não "raciocina?". A PROVENIÊNCIA fica em cada caso; a decisão de
QUAL fonte usar p/ PROMOÇÃO é humana (D6) — este módulo é a máquina, não o juiz da fonte.

SOLID/DIP: `run_fn` (o sandbox) e `run_git` são injetáveis → testes 100% herméticos (zero WSL/git real).
Reusa `_default_make_workspace`/`RunResult` do execution_ruler (mesma materialização; sem oráculo-overlay
porque aqui NÃO há patch não-confiável — fonte pré/pós-fix vem do git, confiável).
"""
from __future__ import annotations

import shutil
from typing import Callable, Optional

from super_squad.execution_ruler import RunResult, _default_make_workspace, _minimal_env
from super_squad.git_harvester import _default_git_run, harvest_with_report


def _run_files(files: "dict[str, bytes]", test_cmd: "list[str]", timeout_s: float,
               run_fn: Callable, make_workspace: Callable, env_builder: Callable) -> RunResult:
    """Materializa `files`, roda `test_cmd` isolado, limpa. Não levanta (erro → RunResult(spawn_error))."""
    ws = None
    try:
        ws = make_workspace(files)
        return run_fn(test_cmd, ws, timeout_s, env_builder())
    except Exception as e:  # noqa: BLE001
        return RunResult(spawn_error=True, stderr=repr(e))
    finally:
        if ws:
            shutil.rmtree(ws, ignore_errors=True)


def _passed(r: RunResult) -> bool:
    return r.returncode == 0 and not r.timed_out and not r.spawn_error


def _failed_cleanly(r: RunResult) -> bool:
    """Falhou de propósito (o teste reprovou) — NÃO por timeout/erro de spawn (que não são 'red' honesto)."""
    return r.returncode not in (0, None) and not r.timed_out and not r.spawn_error


def validate_red_green(
    buggy_files: "dict[str, bytes]",
    fixed_files: "dict[str, bytes]",
    test_files: "dict[str, bytes]",
    test_cmd: "list[str]",
    *,
    timeout_s: float = 60.0,
    run_fn: "Optional[Callable]" = None,
    make_workspace: "Optional[Callable]" = None,
    env_builder: "Optional[Callable]" = None,
) -> dict:
    """Roda o baseline (bug) e o consertado (fix humano) e devolve o veredito de validade red→green.
    `{valid, red_fail, green_pass, red_rc, green_rc, red_label, green_label}` — nunca levanta."""
    if run_fn is None:
        from super_squad.wsl_sandbox import wsl_sandboxed_run as run_fn
    make_workspace = make_workspace or _default_make_workspace
    env_builder = env_builder or _minimal_env

    red = _run_files({**buggy_files, **test_files}, test_cmd, timeout_s, run_fn, make_workspace, env_builder)
    green = _run_files({**fixed_files, **test_files}, test_cmd, timeout_s, run_fn, make_workspace, env_builder)
    red_fail = _failed_cleanly(red)
    green_pass = _passed(green)

    def _label(r: RunResult) -> str:
        if r.spawn_error:
            return "spawn_error"
        if r.timed_out:
            return "timeout"
        return "pass" if r.returncode == 0 else f"fail:{r.returncode}"

    return {
        "valid": red_fail and green_pass,
        "red_fail": red_fail, "green_pass": green_pass,
        "red_rc": red.returncode, "green_rc": green.returncode,
        "red_label": _label(red), "green_label": _label(green),
        # motivo quando inválido (p/ auditar honesto): por que caiu.
        "reason": ("ok" if red_fail and green_pass else
                   "baseline_nao_falhou" if not red_fail else "fix_nao_passou"),
    }


def _default_fetch_tree(repo: str) -> Callable:
    """Materializa a árvore COMPLETA do repo num ref via `git archive` (UMA chamada, binário → tar).
    Necessário porque um teste importa módulos-irmãos que o harvest de 'só-arquivos-tocados' não traz →
    green nunca passaria (medido: 16/16 fix_nao_passou). Semântica BugsInPy/Defects4J."""
    import io
    import subprocess
    import tarfile

    def fetch(ref: str) -> "dict[str, bytes]":
        try:
            p = subprocess.run(["git", "-C", repo, "archive", "--format=tar", ref],
                               capture_output=True, timeout=120)
            if p.returncode != 0:
                return {}
            out: "dict[str, bytes]" = {}
            with tarfile.open(fileobj=io.BytesIO(p.stdout)) as tf:
                for m in tf.getmembers():
                    if not m.isfile() or m.size > 512 * 1024:  # pula binário grande/dir
                        continue
                    fh = tf.extractfile(m)
                    if fh is not None:
                        out[m.name] = fh.read()
            return out
        except Exception:  # noqa: BLE001 — falha de git = árvore vazia (caso vira skip no chamador)
            return {}

    return fetch


def harvest_and_validate(
    repo: str,
    *,
    since: "Optional[str]" = None,
    max_commits: int = 300,
    timeout_s: float = 60.0,
    run_git: "Optional[Callable]" = None,
    fetch_tree: "Optional[Callable]" = None,
    run_fn: "Optional[Callable]" = None,
    harvest_fn: "Optional[Callable]" = None,
    limit: "Optional[int]" = None,
) -> "tuple[list, list]":
    """Colhe fix-commits de `repo`, materializa a ÁRVORE COMPLETA no pai (bug) e no fix, valida red→green e
    devolve `(validated, report)`. RED = árvore-do-pai + o teste no estado do fix (o teste novo ainda não
    existe no pai); GREEN = árvore-do-fix. Cada validado ganha `expect_baseline_fail=True` + a validação.
    `report` lista TODOS os tentados com o motivo (auditável). Nunca levanta."""
    run_git = run_git or _default_git_run(repo)
    fetch_tree = fetch_tree or _default_fetch_tree(repo)
    harvest_fn = harvest_fn or harvest_with_report
    cases, _diags = harvest_fn(run_git, since=since, max_commits=max_commits,
                               repo_name=repo.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "repo")
    validated: list = []
    report: list = []
    for case in cases:
        if limit is not None and len(validated) >= limit:
            break
        sha = case["provenance"]["sha"]
        parent = case["provenance"]["parent"]
        parent_tree = fetch_tree(parent)
        fix_tree = fetch_tree(sha)
        if not parent_tree or not fix_tree:
            report.append({"case_id": case["case_id"], "reason": "sem_arvore"})
            continue
        # RED = árvore-do-pai + o TESTE no estado do fix (o teste que pega o bug); GREEN = árvore-do-fix.
        red_files = {**parent_tree, **case["test_files"]}
        v = validate_red_green(red_files, fix_tree, {}, case["test_cmd"],
                               timeout_s=timeout_s, run_fn=run_fn)
        report.append({"case_id": case["case_id"], "reason": v["reason"],
                       "red": v["red_label"], "green": v["green_label"]})
        if v["valid"]:
            case = dict(case)
            case["expect_baseline_fail"] = True
            case["validation"] = {k: v[k] for k in ("red_rc", "green_rc", "red_label", "green_label")}
            validated.append(case)
    return validated, report
