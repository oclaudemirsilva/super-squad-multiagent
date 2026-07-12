"""routing.py — seam `RoutingProvider` da união com ruflo (SCAFFOLD; ver docs/design/ruflo-union-routing-seam.md).

Decide, para uma tarefa, QUAL executor: **Tier-1 trivial → Agent Booster ($0 local)** ou **resto →
titular MEDIDO do roster (OpenRouter)**. Determinístico e auditável (`rationale`) — roteamento de
RUNTIME nunca é o neural/aprendido do ruflo (esse fica no dev-loop, D14/Cloud-Run-Rule-#2).

Estado: SCAFFOLD. O `BoosterAdapter` real (ruflo/WASM) NÃO está plugado — `NullBoosterAdapter` reporta
"indisponível" e o provider cai gracioso pro modelo medido (mesmo padrão de fallback do próprio ruflo).
Plugar o adapter real (e MEDIR o ganho, D14) é passo posterior; a interface e o roteamento já existem
e são testados. SOLID/DIP: `roster_fn` e `booster` injetáveis → teste hermético.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol

# intents de transform triviais/determinísticos que o Agent Booster resolve a $0 (lista do ruflo).
TRIVIAL_INTENTS = frozenset({
    "var-to-const", "add-types", "add-error-handling", "async-await", "add-logging", "remove-console",
})


@dataclass(frozen=True)
class Route:
    """Veredito de roteamento. `tier`='booster' ($0 local) ou 'model' (chamada medida). `handler`=
    id do transform (booster) OU slug do modelo (model). `rationale` é auditável."""
    tier: str
    handler: str
    est_cost_usd: float
    rationale: str


@dataclass(frozen=True)
class Task:
    """Unidade a rotear. `role` escolhe o roster; `intent` (opcional) casa um transform trivial."""
    role: str
    input: str = ""
    intent: "Optional[str]" = None


class BoosterAdapter(Protocol):
    """Adapter do Tier-1 ($0). `available()` diz se dá pra usar; `can_handle(intent)` se cobre o intent."""
    def available(self) -> bool: ...
    def can_handle(self, intent: "Optional[str]") -> bool: ...


class NullBoosterAdapter:
    """Booster AUSENTE (default enquanto o ruflo não está plugado): sempre indisponível → cai pro modelo.
    Substitua por um adapter real (WASM/ruflo) quando for medir o ganho (D14)."""
    def available(self) -> bool:
        return False

    def can_handle(self, intent: "Optional[str]") -> bool:
        return False


class MeasuredRoutingProvider:
    """Roteia: intent trivial + booster disponível → Tier-1 ($0); senão → titular MEDIDO do roster.
    Roster vazio → Route de erro explícita (não roteia às cegas). DIP: `roster_fn`/`booster` injetáveis."""

    def __init__(self, *, roster_fn: "Optional[Callable]" = None, booster: "Optional[BoosterAdapter]" = None):
        if roster_fn is None:
            from super_squad.registry import squad_roster as roster_fn
        self._roster_fn = roster_fn
        self._booster = booster or NullBoosterAdapter()

    def route(self, task: Task) -> Route:
        # 1) Tier-1 $0 se o intent é trivial E o booster consegue.
        if task.intent in TRIVIAL_INTENTS and self._booster.available() and self._booster.can_handle(task.intent):
            return Route(tier="booster", handler=task.intent, est_cost_usd=0.0,
                         rationale=f"intent trivial {task.intent!r} → Agent Booster ($0), sem LLM")
        # 2) Titular medido do roster.
        roster = list(self._roster_fn(task.role))
        if not roster:
            return Route(tier="model", handler="", est_cost_usd=0.0,
                         rationale=f"roster VAZIO p/ papel {task.role!r} — semeie AI_SQUAD_ROSTER_"
                                   f"{task.role.upper().replace('-', '_')} (D1)")
        slug, _pin, pout = roster[0]
        why = (f"intent {task.intent!r} não-trivial → " if task.intent else "") + \
              f"titular medido do papel {task.role!r}"
        return Route(tier="model", handler=slug, est_cost_usd=0.0, rationale=why)
