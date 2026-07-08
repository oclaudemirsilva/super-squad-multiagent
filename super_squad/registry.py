"""registry.py — roster de modelos por PAPEL do Super Squad Multiagent.

Este arquivo nasce VAZIO de propósito: o roster é a parte que É SUA. A metodologia do
squad (ver README) manda cada papel ser preenchido com modelos MEDIDOS contra o SEU
ground-truth (N>=5 por decisão, nunca N=1/N=2) — copiar o roster de outra pessoa é pular
exatamente a etapa que faz o sistema funcionar.

Formato: `SQUAD_ROSTER[role] = ((slug, price_in_per_mtok, price_out_per_mtok), ...)`.
Preços em USD por MILHÃO de tokens, do catálogo vivo https://openrouter.ai/models — o
pré-voo (`preflight.assert_roster_live`) confere slug vivo + drift de preço antes de
cada lote, então um preço desatualizado é reportado, não silencioso.

Override SEM tocar código (útil em CI/experimentos): env `AI_SQUAD_ROSTER_<ROLE>` =
CSV `slug1:pin1:pout1,slug2:pin2:pout2,...`.

Pesos de voto (`SQUAD_ROLE_WEIGHTS`, opcional): só depois de MEDIR cegueira/acerto por
modelo (ver `squad.aggregate_panel_verdicts` — o peso corrige "2 cegos vencem 1 correto"
sem criar veto unilateral). Default: todo mundo peso 1.0.
"""
from __future__ import annotations

import os

# Preencha com os SEUS papéis/modelos medidos. Exemplo (comentado) da forma esperada:
# SQUAD_ROSTER: dict[str, tuple[tuple[str, float, float], ...]] = {
#     "vision_judge": (
#         ("google/gemini-2.5-flash", 0.30, 2.50),
#         ("qwen/qwen3-vl-32b-instruct", 0.104, 0.416),
#     ),
#     "code": (("deepseek/deepseek-chat", 0.27, 1.10),),
# }
SQUAD_ROSTER: "dict[str, tuple[tuple[str, float, float], ...]]" = {}

# `{role: {model_slug: peso}}` — só com dado (ver docstring do módulo).
SQUAD_ROLE_WEIGHTS: "dict[str, dict[str, float]]" = {}


def squad_roster(role: str) -> "tuple[tuple[str, float, float], ...]":
    """Frota `(slug, price_in_per_mtok, price_out_per_mtok)` p/ um papel. Override por env
    `AI_SQUAD_ROSTER_<ROLE>` = CSV `slug1:pin1:pout1,...` (stdlib-only, sem parser externo).
    Papel desconhecido -> tupla vazia (fail-soft; o chamador decide o que fazer com painel
    vazio — `aggregate_panel_verdicts` já trata `n_valid=0` como fail-closed)."""
    override = os.getenv(f"AI_SQUAD_ROSTER_{role.upper()}")
    if override:
        out = []
        for part in override.split(","):
            slug, pin, pout = part.split(":")
            out.append((slug.strip(), float(pin), float(pout)))
        return tuple(out)
    return SQUAD_ROSTER.get(role, ())


def squad_roles() -> "list[str]":
    return sorted(SQUAD_ROSTER)


def squad_role_weights(role: str) -> "dict[str, float]":
    return SQUAD_ROLE_WEIGHTS.get(role, {})
