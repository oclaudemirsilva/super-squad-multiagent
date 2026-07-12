"""runtimes/opencode.py — adapter OpenCode do `BuilderRuntime` (sequência §3 FIADA, execução GATED).

Une o OpenCode à pilha atrás do seam, SEM soltá-lo. A sequência do doc de design (§3) — pré-voo de teto
global → config efêmera → invocação headless → git diff → parse de usage → ledger — está agora FIADA e
exercitada por testes herméticos (subprocess INJETADO). Três portões duros continuam valendo, nesta ordem:

  1. `enabled=False` (default) → toda chamada volta `status="blocked"`. O binário nunca é tocado.
  2. `assert_builder_preconditions` → sem worktree + caps + `hardening_ack` humano, `status="blocked"`.
  3. `command_builder=None` (default) → as flags REAIS do CLI não foram verificadas (§9 do doc). Sem um
     `command_builder` VERIFICADO injetado, o adapter recusa montar o argv (`status="error"`) em vez de
     adivinhar flags e disparar um subprocess que poderia se comportar mal. É o "não fiada até §9".

Ou seja: a lógica de orquestração é testável AGORA (com fakes), mas rodar o binário DE VERDADE exige um
humano injetar um `command_builder` verificado + `enabled=True` + `hardening_ack=True` + roster de construtor
medido. Merge do diff = gate humano. stdlib-only; OpenCode é dependência de RUNTIME (binário), não de import.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from super_squad.runtimes.base import (
    BuilderTask,
    BuilderResult,
    BuilderGateError,
    assert_builder_preconditions,
)
from super_squad.runtimes.hardening import redact_secrets


def build_opencode_config(task: BuilderTask) -> dict:
    """Config efêmera (PURA) que traduz a `BuilderTask` + `PermissionProfile` pro OpenCode. NUNCA embute
    o valor da chave — referencia o env var (`{env:OPENROUTER_API_KEY}`), pra chave jamais ir a disco/log.
    O perfil de permissão vira o raio de explosão: write só na worktree, bash allowlist, rede só p/ o modelo."""
    perm = task.permission
    return {
        "provider": "openrouter",
        "api_key_env": "OPENROUTER_API_KEY",
        "model": task.model_slug,
        "agent": {"system_prompt": task.system_prompt, "max_steps": task.max_steps,
                  "max_tokens": task.max_tokens},
        "permission": {
            "write_paths": list(perm.write_paths) or [task.workspace],  # vazio = só a worktree
            "bash_allowlist": list(perm.bash_allowlist),
            "network": perm.network,
        },
    }


def _emit(on_event: "Optional[Callable]", event: str, **fields) -> None:
    """Telemetria fail-soft (OCP): um sink que levanta NÃO derruba a sessão do construtor."""
    if on_event is None:
        return
    try:
        on_event({"event": event, **fields})
    except Exception:  # noqa: BLE001 — observabilidade nunca quebra a execução
        pass


class OpenCodeRuntime:
    """Adapter `BuilderRuntime` → CLI do OpenCode por subprocess. DESABILITADO por default (fail-closed).

    Injeção (DIP, tudo testável sem rede/binário):
      `subprocess_run`   — estilo subprocess.run(argv, cwd=, capture_output=True, text=True, timeout=, env=).
      `command_builder`  — `(task, config_path, binary) -> argv[list[str]]`. DEFAULT None = §9 não verificada
                           → recusa (o repo não adivinha as flags reais do binário). Fase 2 injeta o verificado.
      `parse_usage`      — `(completed_process) -> {cost_usd, steps}`. Default: estimativa fail-soft flagada.
      `check_budget_fn`  — pré-voo de teto GLOBAL (default `spend_ledger.check_budget` se `ledger_path` dado).
      `record_spend_fn`  — registra o gasto real pós-run (default `spend_ledger.record_spend`).
      `write_config_fn`  — escreve a config efêmera na worktree (default: Path.write_text)."""

    def __init__(self, *, enabled: bool = False, hardening_ack: bool = False, binary: str = "opencode",
                 subprocess_run: "Optional[Callable]" = None, command_builder: "Optional[Callable]" = None,
                 parse_usage: "Optional[Callable]" = None, check_budget_fn: "Optional[Callable]" = None,
                 record_spend_fn: "Optional[Callable]" = None, write_config_fn: "Optional[Callable]" = None,
                 ledger_path: "Optional[str]" = None, ledger_ceiling_usd: "Optional[float]" = None):
        self._enabled = enabled
        self._hardening_ack = hardening_ack
        self._binary = binary
        self._subprocess_run = subprocess_run
        self._command_builder = command_builder
        self._parse_usage = parse_usage or _default_parse_usage
        self._check_budget_fn = check_budget_fn
        self._record_spend_fn = record_spend_fn
        self._write_config_fn = write_config_fn or (lambda p, s: Path(p).write_text(s, encoding="utf-8"))
        self._ledger_path = ledger_path
        self._ledger_ceiling_usd = ledger_ceiling_usd

    def run(self, task: BuilderTask, on_event: "Optional[Callable]" = None) -> BuilderResult:
        # Portão 1 — desabilitado: o binário nunca é tocado.
        if not self._enabled:
            return BuilderResult(
                task.task_id, status="blocked",
                error="OpenCode runtime DESABILITADO (Fase 2). Habilite só após hardening A1–A5 + "
                      "roster de construtor medido + §9 verificado (enabled=True, hardening_ack=True).",
            )
        # Portão 2 — guarda dura (worktree/caps/ack). Falha → blocked, NÃO executa.
        try:
            assert_builder_preconditions(task, hardening_ack=self._hardening_ack)
        except BuilderGateError as exc:
            return BuilderResult(task.task_id, status="blocked", error=str(exc))
        # Portão 3 — §9 não verificada: sem subprocess OU sem command_builder verificado, recusa honesta.
        if self._subprocess_run is None:
            return BuilderResult(
                task.task_id, status="error",
                error="OpenCode CLI wiring PENDENTE: injete um `subprocess_run` verificado (§9 do doc).",
            )
        if self._command_builder is None:
            return BuilderResult(
                task.task_id, status="error",
                error="flags reais do CLI do OpenCode NÃO verificadas (§9): injete um `command_builder` "
                      "verificado. O repo não adivinha as flags do binário nem dispara execução às cegas.",
            )
        # Pré-requisitos + wiring presentes → roda a sequência §3 (fail-soft: qualquer erro vira status honesto).
        return self._run_session(task, on_event)

    def _run_session(self, task: BuilderTask, on_event: "Optional[Callable]") -> BuilderResult:
        # §3.1 — pré-voo de teto GLOBAL (recusa sem gastar se a janela esgotou).
        if self._check_budget_fn is not None:
            budget = self._check_budget_fn()
            if budget.get("blocked"):
                _emit(on_event, "builder_end", task_id=task.task_id, status="budget", cost_usd=0.0)
                return BuilderResult(task.task_id, status="budget",
                                     error=f"teto global esgotado: {budget}")

        _emit(on_event, "builder_start", task_id=task.task_id, role=task.role, model=task.model_slug)
        try:
            # §3.3 — config efêmera na worktree (chave referenciada por env, nunca embutida).
            config = build_opencode_config(task)
            config_path = str(Path(task.workspace) / "opencode.config.json")
            self._write_config_fn(config_path, json.dumps(config, ensure_ascii=False, indent=2))

            # §3.4 — invocação headless. argv vem do command_builder VERIFICADO (§9). cwd = worktree.
            argv = self._command_builder(task, config_path, self._binary)
            proc = self._subprocess_run(argv, cwd=task.workspace, capture_output=True, text=True,
                                        timeout=task.timeout_s)
            if getattr(proc, "returncode", 0) != 0:
                return BuilderResult(
                    task.task_id, status="error", steps=0,
                    error=redact_secrets(f"opencode saiu != 0: {getattr(proc, 'stderr', '') or ''}"))

            # §3.5 — coletar diff + arquivos da worktree.
            diff, files = self._collect_diff(task.workspace)
            usage = self._parse_usage(proc)
            cost = float(usage.get("cost_usd", 0.0))
            steps = int(usage.get("steps", 0))

            # §3.6 — registrar gasto real + telemetria.
            if self._record_spend_fn is not None:
                self._record_spend_fn(cost)
            status = "ok" if diff.strip() else "empty_diff"
            _emit(on_event, "builder_end", task_id=task.task_id, status=status, cost_usd=cost,
                  steps=steps, n_files=len(files), diff_bytes=len(diff))
            return BuilderResult(task.task_id, status=status, diff=diff, files_changed=tuple(files),
                                 cost_usd=cost, steps=steps)
        except TimeoutError as exc:  # subprocess estourou o wall-clock
            _emit(on_event, "builder_end", task_id=task.task_id, status="timeout", cost_usd=0.0)
            return BuilderResult(task.task_id, status="timeout", error=str(exc))
        except Exception as exc:  # noqa: BLE001 — sessão ruim vira status honesto, não derruba a frota
            _emit(on_event, "builder_end", task_id=task.task_id, status="error", cost_usd=0.0)
            return BuilderResult(task.task_id, status="error", error=redact_secrets(str(exc)))

    def _collect_diff(self, workspace: str) -> "tuple[str, list[str]]":
        """`git -C <ws> diff` (produto a julgar) + `--name-only` (arquivos). Falha de git = diff vazio."""
        run = self._subprocess_run
        d = run(["git", "-C", workspace, "diff"], cwd=workspace, capture_output=True, text=True, timeout=60)
        diff = getattr(d, "stdout", "") or ""
        n = run(["git", "-C", workspace, "diff", "--name-only"], cwd=workspace,
                capture_output=True, text=True, timeout=60)
        files = [ln for ln in (getattr(n, "stdout", "") or "").splitlines() if ln.strip()]
        return diff, files


def _default_parse_usage(proc: object) -> dict:
    """Parser fail-soft do usage do OpenCode. Sem formato verificado (§9.2), tenta ler JSON do stdout;
    falhando, devolve custo/passos 0 com flag `estimated` — NUNCA levanta (a sessão já rodou)."""
    try:
        data = json.loads(getattr(proc, "stdout", "") or "{}")
        usage = data.get("usage", data)
        return {"cost_usd": float(usage.get("cost_usd", usage.get("cost", 0.0))),
                "steps": int(usage.get("steps", 0)), "estimated": False}
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        return {"cost_usd": 0.0, "steps": 0, "estimated": True}
