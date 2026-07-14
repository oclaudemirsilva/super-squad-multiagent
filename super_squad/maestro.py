"""maestro.py — dispatcher de WORKFLOWS do Super Squad Multiagent.

O registry OCP de workflows que compõe os papéis do squad em pipelines executáveis com
TODAS as guardas num único ponto: pré-voo de slug/preço/chave (B6, `preflight.assert_roster_live`)
→ teto de gasto global (B5, `spend_ledger`) → runner do workflow (checkpoint incremental +
telemetria) → registro do gasto no ledger. Workflow novo = 1 `WorkflowSpec` registrado — o
dispatcher não muda; cada spec declara estaticamente quais PAPÉIS usa, então o pré-voo cobre
exatamente o que o workflow vai gastar.

SEGURO POR DEFAULT: `dispatch(..., execute=False)` é DRY-RUN — devolve o plano e não gasta nada;
`--execute` no CLI é o ÚNICO caminho que dispara. Erros viram dicts (`ok=False`), nunca exceção
crua. Script que gasta $ é CLI de humano — NUNCA invocado por CI.

Este módulo nasce SEM workflows registrados: quem usa registra os seus (ver demo/). Convenção:
workflows de shadow-audit chamados `shadow_<papel>` aceitam `rerun_tag` (re-medição periódica —
a cadência "C9" da metodologia: re-rodar o mesmo shadow com um sufixo de época, ex. `::2026-08`).

Uso típico (depois de registrar seus workflows):
    dispatch("meu_workflow")                      # dry-run: só o plano
    dispatch("meu_workflow", execute=True, ...)   # roda com as guardas
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# Ledger default no cwd de quem roda (append-only; NÃO versione o seu — está no .gitignore).
DEFAULT_SPEND_LEDGER = Path(os.environ.get("SQUAD_SPEND_LEDGER", ".squad_spend/ledger.jsonl"))


@dataclass(frozen=True)
class WorkflowSpec:
    """Um workflow registrável. `roles` = papéis do squad que ele usa (escopo do pré-voo);
    `runner(budget_usd=, limit=, event_sink=, **extra) -> dict` DEVE devolver `spent_usd` (o
    dispatcher registra no ledger); `spends_money=False` pula gate/ledger (workflow 100% local)."""
    name: str
    roles: "tuple[str, ...]"
    runner: Callable[..., dict]
    default_budget_usd: float
    description: str
    spends_money: bool = True


WORKFLOWS: "dict[str, WorkflowSpec]" = {}


def register(spec: WorkflowSpec) -> None:
    """Registra um workflow (OCP: novo pipeline = nova chamada aqui, dispatcher intocado)."""
    if spec.name in WORKFLOWS:
        raise ValueError(f"workflow duplicado: {spec.name!r}")
    WORKFLOWS[spec.name] = spec


def plan(name: str, *, budget_usd: "float | None" = None, limit: "int | None" = None) -> dict:
    """Plano PURO (dry-run): o que rodaria, com que papéis e teto — sem gastar nada."""
    spec = WORKFLOWS.get(name)
    if spec is None:
        return {"error": f"workflow desconhecido: {name!r}", "known": sorted(WORKFLOWS)}
    return {"workflow": spec.name, "roles": list(spec.roles),
            "budget_usd": budget_usd if budget_usd is not None else spec.default_budget_usd,
            "limit": limit, "spends_money": spec.spends_money, "description": spec.description}


def dispatch(
    name: str, *, execute: bool = False, budget_usd: "float | None" = None,
    limit: "int | None" = None, extra: "dict | None" = None, skip_preflight: bool = False,
    ledger_path=DEFAULT_SPEND_LEDGER, daily_ceiling_usd: "float | None" = None,
    preflight_fn: "Optional[Callable]" = None, check_budget_fn: "Optional[Callable]" = None,
    record_spend_fn: "Optional[Callable]" = None, event_sink=None,
) -> dict:
    """Despacha um workflow com as guardas compostas. DRY-RUN por default (`execute=False` →
    devolve só o plano). Deps injetáveis (DIP) — testes herméticos sem rede/ledger real.
    Ordem: plano → [execute?] → pré-voo dos papéis do spec (chave ausente ou slug morto ABORTA;
    catálogo inacessível = warning e segue) → teto global (janela esgotada ABORTA; senão CLAMPA
    o budget da rodada ao restante) → runner → registra `spent_usd` no ledger (best-effort).
    Runner que levanta vira `ok=False`."""
    spec = WORKFLOWS.get(name)
    if spec is None:
        return {"ok": False, "ran": False,
                "error": f"workflow desconhecido: {name!r}", "known": sorted(WORKFLOWS)}

    budget = budget_usd if budget_usd is not None else spec.default_budget_usd
    the_plan = plan(name, budget_usd=budget, limit=limit)
    if not execute:
        return {"ok": True, "plan": the_plan, "ran": False}

    # B6 — pré-voo dos papéis que ESTE workflow declara usar
    preflight_report = None
    if spec.roles and not skip_preflight:
        if preflight_fn is None:
            # Guard do caminho REAL: o catálogo do pré-voo é endpoint PÚBLICO (não exige chave),
            # então um workflow que gasta $ SEM a chave passaria no pré-voo e rodaria fail-soft
            # até o fim com agent=None em todos os itens (custo 0, checkpoint poluído). Chave
            # ausente = falha de pré-voo, não de runner. Escape: --skip-preflight.
            # A chave é a DO PROVIDER ATIVO (env AI_SQUAD_PROVIDER; default openrouter ->
            # OPENROUTER_API_KEY, comportamento de sempre; qwen_cloud -> DASHSCOPE_API_KEY).
            from .providers import default_provider  # noqa: E402 (lazy)
            prov = default_provider()
            if spec.spends_money and not os.getenv(prov.api_key_env):
                return {"ok": False, "ran": False, "plan": the_plan,
                        "error": f"pré-voo bloqueou: {prov.api_key_env} ausente no ambiente — "
                                 "workflow que gasta $ rodaria fail-soft com agent=None silencioso "
                                 "(exporte a chave antes de disparar)"}
            if prov.name == "openrouter":
                from .preflight import assert_roster_live as preflight_fn  # noqa: E402 (lazy)
        if preflight_fn is None:
            # Só o OpenRouter tem o catálogo /models com `pricing` que o pré-voo confere; noutro
            # provider (ex. qwen_cloud) o roster é de slugs DELE — checar contra o OpenRouter
            # reprovaria slug vivo. Sem catálogo = sem checagem de slug (warning explícito),
            # nunca um bloqueio falso.
            preflight_report = {"ok": None,
                                "warning": f"pré-voo de slug/preço só existe p/ openrouter; "
                                           f"provider ativo = {prov.name} — checagem pulada"}
        else:
            from .preflight import PreflightError  # noqa: E402 (lazy)
            try:
                preflight_report = preflight_fn(list(spec.roles))
            except PreflightError as exc:
                return {"ok": False, "ran": False, "plan": the_plan,
                        "error": f"pré-voo bloqueou (slug morto no roster): {exc}"}
            except Exception as exc:  # noqa: BLE001 — catálogo inacessível não bloqueia (warning)
                preflight_report = {"ok": None, "warning": f"catálogo inacessível: {exc!r}"}

    # B5 — teto de gasto GLOBAL (opcional; env AI_SQUAD_DAILY_BUDGET_USD como fallback)
    effective = budget
    budget_status = None
    if spec.spends_money:
        ceiling = daily_ceiling_usd
        if ceiling is None:
            env_ceiling = os.getenv("AI_SQUAD_DAILY_BUDGET_USD")
            ceiling = float(env_ceiling) if env_ceiling else None
        if ceiling is not None:
            if check_budget_fn is None:
                from .spend_ledger import check_budget as check_budget_fn  # noqa: E402
            try:
                budget_status = check_budget_fn(ledger_path, ceiling)
            except Exception as exc:  # noqa: BLE001 — ledger quebrado não bloqueia (fail-soft)
                budget_status = {"error": repr(exc)}
            if budget_status.get("blocked"):
                return {"ok": False, "ran": False, "plan": the_plan,
                        "error": "teto de gasto global esgotado — não disparando",
                        "budget_status": budget_status}
            remaining = budget_status.get("remaining")
            if isinstance(remaining, (int, float)):
                effective = min(budget, float(remaining))

    try:
        result = spec.runner(budget_usd=effective, limit=limit, event_sink=event_sink,
                             **(extra or {}))
    except Exception as exc:  # noqa: BLE001 — runner nunca propaga exceção crua
        return {"ok": False, "ran": True, "plan": the_plan, "error": repr(exc)}

    spent = float((result or {}).get("spent_usd") or 0.0)
    if spent > 0 and spec.spends_money and ledger_path is not None:
        try:
            if record_spend_fn is None:
                from .spend_ledger import record_spend as record_spend_fn  # noqa: E402
            record_spend_fn(ledger_path, spent, workflow=name)
        except Exception:  # noqa: BLE001 — registro é best-effort, nunca invalida o resultado
            pass

    return {"ok": True, "ran": True, "plan": the_plan, "result": result,
            "effective_budget_usd": effective, "preflight": preflight_report,
            "budget_status": budget_status}


def main(argv=None) -> int:
    """CLI genérico sobre os workflows REGISTRADOS por quem importou este módulo (ver demo/)."""
    import argparse

    ap = argparse.ArgumentParser(description="Maestro do Super Squad — dispatcher de workflows")
    ap.add_argument("workflow", nargs="?", default=None, choices=[None, *sorted(WORKFLOWS)])
    ap.add_argument("--list", action="store_true", help="lista os workflows registrados")
    ap.add_argument("--execute", action="store_true",
                    help="RODA de verdade (default = dry-run, não gasta nada)")
    ap.add_argument("--budget-usd", type=float, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--rerun-tag", default="",
                    help="(shadow_*) sufixo de re-medição periódica, ex. ::2026-08")
    ap.add_argument("--skip-preflight", action="store_true")
    ap.add_argument("--daily-budget-usd", type=float, default=None)
    ap.add_argument("--spend-ledger", default=str(DEFAULT_SPEND_LEDGER))
    a = ap.parse_args(argv)

    if a.list or a.workflow is None:
        for name in sorted(WORKFLOWS):
            s = WORKFLOWS[name]
            print(f"  {name}  [roles={','.join(s.roles)}] (${s.default_budget_usd}) — {s.description}")
        return 0

    extra: dict = {}
    if a.workflow.startswith("shadow_"):
        extra = {"rerun_tag": a.rerun_tag}

    out = dispatch(a.workflow, execute=a.execute, budget_usd=a.budget_usd, limit=a.limit,
                   extra=extra, skip_preflight=a.skip_preflight,
                   ledger_path=Path(a.spend_ledger), daily_ceiling_usd=a.daily_budget_usd)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
