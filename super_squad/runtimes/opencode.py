"""runtimes/opencode.py — adapter OpenCode do `BuilderRuntime` (SCAFFOLD, execução GATED).

Une o OpenCode à pilha atrás do seam, SEM soltá-lo: `enabled=False` por default → toda chamada volta
`status="blocked"`. Mesmo habilitado, `assert_builder_preconditions` exige worktree + caps + hardening_ack.
E a fiação real do CLI do OpenCode **ainda não foi verificada** contra o binário (as "6 perguntas §9" do
doc de design) — então, mesmo habilitado e com pré-requisitos, o adapter devolve `status="error"` honesto
("wiring pendente de verificação da API real") em vez de disparar um subprocess que poderia se comportar mal.

Para ATIVAR de verdade (Fase 2, pós-receita): (1) OpenCode instalado + §9 verificado; (2) hardening A1–A5;
(3) roster de construtor RE-medido; (4) `enabled=True, hardening_ack=True`. Merge do diff = gate humano.
stdlib-only; o OpenCode é dependência de RUNTIME (binário), não de import.
"""
from __future__ import annotations

from typing import Callable, Optional

from super_squad.runtimes.base import (
    BuilderTask,
    BuilderResult,
    BuilderGateError,
    assert_builder_preconditions,
)


class OpenCodeRuntime:
    """Adapter `BuilderRuntime` → CLI do OpenCode por subprocess. DESABILITADO por default (fail-closed)."""

    def __init__(self, *, enabled: bool = False, hardening_ack: bool = False,
                 binary: str = "opencode", subprocess_run: "Optional[Callable]" = None):
        self._enabled = enabled
        self._hardening_ack = hardening_ack
        self._binary = binary
        self._subprocess_run = subprocess_run  # injetável p/ teste; None = não fia subprocess ainda

    def run(self, task: BuilderTask, on_event: "Optional[Callable]" = None) -> BuilderResult:
        if not self._enabled:
            return BuilderResult(
                task.task_id, status="blocked",
                error="OpenCode runtime DESABILITADO (Fase 2). Habilite só após hardening A1–A5 + "
                      "roster de construtor medido + §9 verificado (enabled=True, hardening_ack=True).",
            )
        # Habilitado: a guarda DURA ainda vale (worktree/caps/ack). Falha → blocked, NÃO executa.
        try:
            assert_builder_preconditions(task, hardening_ack=self._hardening_ack)
        except BuilderGateError as exc:
            return BuilderResult(task.task_id, status="blocked", error=str(exc))
        # Pré-requisitos ok, MAS a fiação real do CLI do OpenCode não foi verificada (§9). Honesto:
        # não disparamos um subprocess não-verificado. Quando §9 estiver fechado, implementar aqui os
        # passos do doc (config efêmera → `opencode run` headless → git diff → parse usage → ledger).
        if self._subprocess_run is None:
            return BuilderResult(
                task.task_id, status="error",
                error="OpenCode CLI wiring PENDENTE de verificação da API real (§9 do doc de design). "
                      "Seam pronto; execução real não fiada até validar as flags/headless do binário.",
            )
        # Caminho de execução real — só quando um subprocess_run verificado for injetado (Fase 2).
        raise NotImplementedError(
            "execução real do OpenCode: implementar os passos §3 do doc após verificar §9. "
            "subprocess_run foi injetado mas a sequência config→run→diff→ledger ainda não está fiada."
        )
