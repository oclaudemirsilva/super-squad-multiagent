"""loop.py — o ORQUESTRADOR DE LOOP (D9): o laço que resolve UMA tarefa bem-especificada por
auto-conserto verificado por EXECUÇÃO. Complementa o `run_roles` (que é UM fan-out sem laço).

O laço (ver `docs/design/loop-orchestrator.md`):
    DECOMPOR → ROTEAR (fan-out do code-writer) → INTEGRAR (apply whole-or-nothing) → VERIFICAR
    (execução isolada) → [DEBUGAR no erro → realimenta] → repete, com critério de PARADA e TETO de gasto.

GUARDA-CORPOS (inegociáveis, herdados do regime de integridade):
- **Oráculo humano/executável (D6/D7):** a verificação é o `execution_ruler` rodando o TESTE do gold isolado
  (`run_fn` OS-sandboxed injetado). O modelo medido NUNCA autora o próprio juiz.
- **Teto de gasto SEMPRE presente:** `budget_usd` é argumento OBRIGATÓRIO (sem default infinito). Um laço
  autônomo sem teto é vazamento de dinheiro. Checado ANTES de cada chamada paga.
- **Aplicar no mundo real = HUMANO (D5).** Este laço resolve contra um GOLD (sandbox); levar o patch pro repo
  de verdade é merge humano. Ele RESOLVE tarefas; não promove roster nem escreve no disco de produção.

SOLID/DIP: tudo INJETÁVEL (`write_fn`/`debug_fn`/`run_fn`/`apply_fn`/`ruler_factory`) → testes 100%
herméticos (zero rede/WSL). Os defaults costuram `run_role` (roteamento medido) + `execution_ruler` (régua).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Callable, Optional

from .execution_ruler import _default_apply, execution_ruler


# ── contrato de dados ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LoopTask:
    """UMA tarefa que cabe num tiro de escritor: spec + arquivo(s)-com-bug + o teste que deve passar.
    `base_files` é o estado 'red' COMPLETO (árvore-do-pai + buggy) — o teste importa o pacote, então
    dar só os changed files quebra a coleta (lição 07-15). `test_files` é o ORÁCULO (re-materializado por
    cima do patch, então o patch não pode adulterar o juiz)."""
    spec: str
    base_files: "dict[str, bytes]"
    test_cmd: "list[str]"
    test_files: "dict[str, bytes]"
    patch_target: "Optional[str]" = None       # 1 arquivo → habilita modo arquivo-inteiro no applier
    setup_cmd: "Optional[list[str]]" = None
    timeout_s: float = 60.0
    expect: str = "exit0"


@dataclass(frozen=True)
class IterRecord:
    """Traço de UMA iteração (para telemetria/depuração do próprio laço)."""
    iter: int
    label: str                                  # veredito da régua (pass/test_fail/apply_failed/…) ou "no_writer_output"
    model: "Optional[str]" = None               # candidato escolhido (o 1º que aplicou)
    passed: bool = False
    cost_usd: float = 0.0
    stderr: str = ""
    diagnosis: str = ""                          # saída do debugger (se houve)


@dataclass(frozen=True)
class LoopResult:
    """Resultado do laço. `reason` ∈ {solved, budget, max_iters, stuck, no_writer_output}."""
    ok: bool
    reason: str
    iters: int
    spent_usd: float
    patch: "Optional[str]" = None               # o patch que passou (ou a melhor tentativa que aplicou)
    history: "list[IterRecord]" = field(default_factory=list)


# ── composição de input (DECOMPOR → texto pro papel) ────────────────────────────

def _decode(d: "dict[str, bytes]") -> "dict[str, str]":
    return {p: (v.decode("utf-8", "replace") if isinstance(v, bytes) else v) for p, v in d.items()}


def compose_writer_input(task: LoopTask, history: "list[IterRecord]") -> str:
    """spec + teste-que-falha + arquivo(s)-com-bug + (se houver) o diagnóstico da iteração anterior.
    Realimenta o erro para o próximo tiro NÃO ser cego."""
    parts = ["# SPECIFICATION (what the change must achieve)", task.spec.strip(), ""]
    parts += ["# FAILING TEST — make it pass; do NOT edit the test", f"# run: {' '.join(task.test_cmd)}"]
    for path, src in _decode(task.test_files).items():
        parts += [f"## {path}", "```python", src, "```", ""]
    parts += ["# CODE TO FIX — produce a unified diff against these file(s)"]
    for path, src in _decode(task.base_files).items():
        if task.patch_target and path != task.patch_target:
            continue                            # só mostra o alvo quando há um (evita despejar a árvore toda)
        parts += [f"## {path}", "```python", src, "```", ""]
    last = history[-1] if history else None
    if last and (last.stderr or last.diagnosis):
        parts += ["# PREVIOUS ATTEMPT FAILED — the test still fails. Fix accordingly.",
                  "## test stderr (truncated)", "```", (last.stderr or "")[:2000], "```"]
        if last.diagnosis:
            parts += ["## debugger diagnosis", last.diagnosis.strip(), ""]
    parts += ["# Output ONLY a unified diff (--- a/path / +++ b/path / @@ hunks) that makes the test pass.",
              "You already have ALL the context you need. Do NOT ask for more; do NOT emit a NEED line."]
    return "\n".join(parts)


def compose_debugger_input(task: LoopTask, patch: str, stderr: str) -> str:
    """O erro do teste + o diff tentado → o debugger propõe o próximo passo (não re-tenta cego)."""
    return "\n".join([
        "# A patch was applied but the test still FAILS. Diagnose WHY in 3-5 lines and say what to change.",
        f"# test: {' '.join(task.test_cmd)}",
        "## attempted patch", "```diff", (patch or "")[:3000], "```",
        "## test stderr", "```", (stderr or "")[:2000], "```",
    ])


# ── adaptadores default (costuram run_role + execution_ruler) ───────────────────

def _default_write_fn(roster_writer, *, roles_dir, budget_usd, max_tokens, temperature, timeout):
    """Fan-out do code-writer via `run_role` (panel = todo o roster). Devolve
    `{results:[{model,text,cost_usd,ok}], spent_usd}` na ordem do roster (titular primeiro)."""
    from .run_role import run_role

    def write_fn(task_input: str) -> dict:
        out = run_role("code-writer", task_input, roles_dir=roles_dir, roster=list(roster_writer),
                       panel=True, budget_usd=budget_usd, max_tokens=max_tokens,
                       temperature=temperature, timeout=timeout)
        return {"results": out["results"], "spent_usd": out.get("spent_usd", 0.0)}
    return write_fn


def _default_debug_fn(roster_debugger, *, roles_dir, budget_usd, max_tokens, temperature, timeout):
    """Titular do debugger via `run_role`. Devolve `{text, spent_usd}`. None-safe: sem roster, no-op."""
    if not roster_debugger:
        return None
    from .run_role import run_role

    def debug_fn(task_input: str) -> dict:
        out = run_role("debugger", task_input, roles_dir=roles_dir, roster=list(roster_debugger),
                       panel=False, budget_usd=budget_usd, max_tokens=max_tokens,
                       temperature=temperature, timeout=timeout)
        return {"text": out.get("text") or "", "spent_usd": out.get("spent_usd", 0.0)}
    return debug_fn


def _build_ruler(task: LoopTask, run_fn, ruler_factory):
    """Régua de EXECUÇÃO do gold (aplica o patch → roda o teste isolado). `run_fn` = OS-sandbox injetado."""
    return ruler_factory(
        task.base_files, task.test_cmd,
        test_files=task.test_files, setup_cmd=task.setup_cmd,
        patch_target=task.patch_target, timeout_s=task.timeout_s, expect=task.expect,
        run_fn=run_fn,
    )


# ── o laço ──────────────────────────────────────────────────────────────────────

def orchestrate(
    task: LoopTask,
    *,
    budget_usd: float,                          # OBRIGATÓRIO (sem default infinito — guarda-corpo)
    max_iters: int = 3,
    roster_writer: "Optional[list]" = None,
    roster_debugger: "Optional[list]" = None,
    run_fn: "Optional[Callable]" = None,
    # costuras injetáveis (testes herméticos passam fakes; produção usa os defaults):
    write_fn: "Optional[Callable]" = None,
    debug_fn: "Optional[Callable]" = None,
    apply_fn: "Optional[Callable]" = None,
    ruler_factory: "Callable" = execution_ruler,
    roles_dir: "str" = "roles/vendor",
    write_budget_usd: float = 0.20,
    write_max_tokens: int = 4000,
    debug_max_tokens: int = 2000,
    temperature: float = 0.4,
    timeout: int = 180,
) -> LoopResult:
    """Resolve `task` fechando red→green por auto-conserto verificado por EXECUÇÃO.

    A cada iteração: ROTEIA (fan-out do writer) → INTEGRA (1º candidato que aplica, whole-or-nothing) →
    VERIFICA (régua roda o teste isolado). No fail, o DEBUGGER diagnostica o stderr e realimenta.

    PARADAS (todas duras, precedência): (1) sucesso `verdict.pass`; (2) teto `spent>=budget_usd`
    (checado ANTES de cada chamada paga); (3) `iter>max_iters`; (4) sem-progresso (mesmo (label,stderr)
    2× seguidas ⇒ travou). Devolve `LoopResult` com o patch que passou (ou a melhor tentativa que aplicou)."""
    if budget_usd <= 0:
        raise ValueError("budget_usd deve ser > 0 (teto de gasto é guarda-corpo obrigatório)")
    apply_fn = apply_fn or _default_apply
    if write_fn is None:
        write_fn = _default_write_fn(roster_writer or [], roles_dir=roles_dir, budget_usd=write_budget_usd,
                                     max_tokens=write_max_tokens, temperature=temperature, timeout=timeout)
    if debug_fn is None and roster_debugger:
        debug_fn = _default_debug_fn(roster_debugger, roles_dir=roles_dir, budget_usd=write_budget_usd,
                                     max_tokens=debug_max_tokens, temperature=temperature, timeout=timeout)
    ruler = _build_ruler(task, run_fn, ruler_factory)

    history: "list[IterRecord]" = []
    spent = 0.0
    best_patch: "Optional[str]" = None          # melhor tentativa que ao menos APLICOU
    last_sig: "Optional[tuple]" = None          # (label, stderr) da iter anterior, p/ detectar travamento

    for it in range(1, max_iters + 1):
        # PARADA 2 — teto (antes de gastar). Nunca estoura o orçamento.
        if spent >= budget_usd:
            return LoopResult(False, "budget", it - 1, round(spent, 6), best_patch, history)

        # ROTEAR — fan-out do writer (titular + roster). Fail-soft já vem do run_role.
        wr = write_fn(compose_writer_input(task, history))
        spent += float(wr.get("spent_usd", 0.0))
        candidates = [r for r in wr.get("results", []) if r.get("ok") and r.get("text")]

        # INTEGRAR — 1º candidato que aplica (whole-or-nothing). Nenhum aplica ⇒ falha honesta que realimenta.
        picked = None
        for cand in candidates:
            if apply_fn(cand["text"], task.base_files, patch_target=task.patch_target).ok:
                picked = cand
                break
        if picked is None:
            label = "apply_failed" if candidates else "no_writer_output"
            rec = IterRecord(it, label, cost_usd=float(wr.get("spent_usd", 0.0)),
                             stderr="(nenhum candidato aplicou)" if candidates else "(writer não respondeu)")
            history.append(rec)
            sig = (label, rec.stderr)
            if last_sig == sig:                 # PARADA 4 — travou no mesmo modo 2× seguidas
                return LoopResult(False, "stuck", it, round(spent, 6), best_patch, history)
            last_sig = sig
            continue

        best_patch = picked["text"]

        # VERIFICAR — a régua aplica de novo e RODA o teste isolado. `pass = o teste passou` (o oráculo).
        verdict = ruler(picked["text"])
        if verdict.get("pass"):
            history.append(IterRecord(it, verdict["label"], picked["model"], True,
                                      float(wr.get("spent_usd", 0.0))))
            return LoopResult(True, "solved", it, round(spent, 6), picked["text"], history)

        stderr = str(verdict.get("stderr") or verdict.get("detail") or "")
        diagnosis = ""
        # DEBUGAR — no fail, diagnostica o stderr e realimenta o próximo tiro (vs. re-tentar cego).
        if debug_fn is not None and spent < budget_usd:
            dg = debug_fn(compose_debugger_input(task, picked["text"], stderr))
            spent += float(dg.get("spent_usd", 0.0))
            diagnosis = dg.get("text") or ""
        rec = IterRecord(it, verdict["label"], picked["model"], False,
                         float(wr.get("spent_usd", 0.0)), stderr, diagnosis)
        history.append(rec)

        sig = (verdict["label"], stderr)
        if last_sig == sig:                     # PARADA 4 — mesmo erro 2× seguidas ⇒ travou
            return LoopResult(False, "stuck", it, round(spent, 6), best_patch, history)
        last_sig = sig

    # PARADA 3 — esgotou as iterações sem fechar.
    return LoopResult(False, "max_iters", max_iters, round(spent, 6), best_patch, history)


# util p/ construir LoopTask a partir de um gold red→green (mesmo formato do harness/harvest_validate)
def task_from_gold(gold: dict, parent_tree: "dict[str, bytes]") -> LoopTask:
    """Converte um gold (base64) + a árvore-do-pai COMPLETA num `LoopTask`. `parent_tree` vem do
    `harvest_validate._default_fetch_tree` (cache por SHA no chamador)."""
    bf = {p: base64.b64decode(b64) for p, b64 in gold["buggy_files"].items()}
    tf = {p: base64.b64decode(b64) for p, b64 in gold["test_files"].items()}
    base = {**parent_tree, **bf}
    tgt = next(iter(bf)) if len(bf) == 1 else None
    return LoopTask(spec=gold["spec"], base_files=base, test_cmd=gold["test_cmd"], test_files=tf,
                    patch_target=tgt, setup_cmd=gold.get("setup_cmd"),
                    timeout_s=float(gold.get("timeout_s", 60)), expect=gold.get("expect", "exit0"))
