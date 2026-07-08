"""preflight.py — pré-voo do Super Squad Multiagent (guarda B6: roster vivo antes de gastar).

ANTES de disparar um lote (que gasta $ real por horas sem supervisão), confirma que cada slug do
roster que vai ser usado ainda EXISTE no catálogo vivo do OpenRouter e compara o preço vivo com o
configurado no roster. Um lote longo num slug descontinuado falharia no meio e queimaria
tempo/parte do gasto; um preço que subiu silenciosamente estoura o orçamento estimado.

FAIL-CLOSED só pro que importa: slug AUSENTE bloqueia o disparo (`assert_roster_live` levanta).
Drift de preço e data de expiração próxima são WARNINGS (reportados, não bloqueiam) — o roster
ainda funciona, só precisa de atenção humana.

SOLID/DIP: `list_models_fn` e `roster_fn` são INJETADOS (default = OpenRouter real + registry),
então os testes rodam 100% herméticos (catálogo mockado, zero rede). PURO onde dá:
`parse_model_catalog` não faz I/O. Módulo FOLHA (só importa registry+openrouter do próprio pacote).
"""
from __future__ import annotations

from typing import Callable, Optional

_MTOK = 1_000_000.0  # preço do OpenRouter vem em USD/token; roster guarda USD/Mtok.
_DEFAULT_PRICE_TOL_FRAC = 0.05  # >5% de diferença relativa (in OU out) conta como drift.


class PreflightError(RuntimeError):
    """Pré-voo reprovou de forma BLOQUEANTE (slug do roster ausente no catálogo vivo)."""


def _to_price_per_mtok(raw: object) -> Optional[float]:
    """USD/token (string ou número do OpenRouter) -> USD/Mtok. Ausente/ilegível -> None."""
    if raw is None:
        return None
    try:
        return float(raw) * _MTOK
    except (TypeError, ValueError):
        return None


def parse_model_catalog(models_data: dict) -> dict:
    """Catálogo cru do `/models` -> `{slug: {price_in_per_mtok, price_out_per_mtok,
    expiration_date}}`. PURO (sem I/O). Robusto a entrada estranha: item sem `id` é ignorado,
    preço ilegível vira None (o chamador decide o que fazer — nunca levanta aqui)."""
    out: dict = {}
    for m in (models_data or {}).get("data") or []:
        if not isinstance(m, dict):
            continue
        slug = m.get("id")
        if not slug:
            continue
        pricing = m.get("pricing") or {}
        out[slug] = {
            "price_in_per_mtok": _to_price_per_mtok(pricing.get("prompt")),
            "price_out_per_mtok": _to_price_per_mtok(pricing.get("completion")),
            "expiration_date": m.get("expiration_date"),
        }
    return out


def _rel_drift(roster: float, live: Optional[float]) -> Optional[float]:
    """Diferença relativa |live-roster|/roster. `live` None -> None (não dá pra comparar).
    `roster` 0 (modelo grátis no roster) -> 0.0 se live também ~0, senão 1.0 (mudou de grátis
    pra pago = drift máximo)."""
    if live is None:
        return None
    if roster == 0:
        return 0.0 if live == 0 else 1.0
    return abs(live - roster) / roster


def preflight_roster(
    roles: "list[str]", *,
    list_models_fn: Optional[Callable[[], dict]] = None,
    roster_fn: Optional[Callable[[str], "tuple[tuple[str, float, float], ...]"]] = None,
    price_tol_frac: float = _DEFAULT_PRICE_TOL_FRAC,
) -> dict:
    """Confere os slugs de `roles` contra o catálogo vivo. NÃO levanta — devolve um relatório
    estruturado (use `assert_roster_live` pra transformar slug-ausente em erro bloqueante).

    Injeção (DIP): `list_models_fn() -> catálogo cru` (default `openrouter_list_models`);
    `roster_fn(role) -> ((slug,pin,pout),...)` (default `registry.squad_roster`). Testes passam
    fakes — zero rede.

    Relatório: `{ok, checked, missing[], drifted[], expiring[], details{role:[...]}}`. `ok` = nenhum
    slug ausente (a única condição bloqueante). `drifted`/`expiring` são só avisos."""
    if list_models_fn is None:
        from .openrouter import openrouter_list_models as list_models_fn  # lazy: sem rede se injetado
    if roster_fn is None:
        from . import registry
        roster_fn = registry.squad_roster

    catalog = parse_model_catalog(list_models_fn())

    missing: list = []
    drifted: list = []
    expiring: list = []
    details: dict = {}
    checked = 0

    for role in roles:
        role_rows: list = []
        for slug, roster_in, roster_out in roster_fn(role):
            checked += 1
            info = catalog.get(slug)
            exists = info is not None
            live_in = info["price_in_per_mtok"] if exists else None
            live_out = info["price_out_per_mtok"] if exists else None
            exp = info["expiration_date"] if exists else None

            drift_in = _rel_drift(roster_in, live_in)
            drift_out = _rel_drift(roster_out, live_out)
            is_drift = any(d is not None and d > price_tol_frac for d in (drift_in, drift_out))

            row = {
                "slug": slug, "exists": exists,
                "roster_in": roster_in, "roster_out": roster_out,
                "live_in": live_in, "live_out": live_out,
                "drift_in": drift_in, "drift_out": drift_out,
                "expiration_date": exp,
            }
            role_rows.append(row)

            if not exists:
                missing.append({"role": role, "slug": slug})
            else:
                if is_drift:
                    drifted.append({"role": role, "slug": slug,
                                    "roster": (roster_in, roster_out), "live": (live_in, live_out)})
                if exp:
                    expiring.append({"role": role, "slug": slug, "expiration_date": exp})
        details[role] = role_rows

    return {"ok": not missing, "checked": checked, "missing": missing,
            "drifted": drifted, "expiring": expiring, "details": details}


def assert_roster_live(
    roles: "list[str]", *,
    list_models_fn: Optional[Callable[[], dict]] = None,
    roster_fn: Optional[Callable[[str], "tuple[tuple[str, float, float], ...]"]] = None,
    price_tol_frac: float = _DEFAULT_PRICE_TOL_FRAC,
) -> dict:
    """Roda o pré-voo e LEVANTA `PreflightError` se algum slug do roster estiver ausente no
    catálogo vivo (condição bloqueante — não dispare um lote num slug morto). Devolve o relatório
    completo em caso de sucesso (pra quem quiser logar drift/expiração como aviso). Mesma injeção
    de `preflight_roster`."""
    report = preflight_roster(roles, list_models_fn=list_models_fn, roster_fn=roster_fn,
                              price_tol_frac=price_tol_frac)
    if not report["ok"]:
        slugs = ", ".join(f"{m['role']}:{m['slug']}" for m in report["missing"])
        raise PreflightError(
            f"pré-voo do Super Squad REPROVOU: {len(report['missing'])} slug(s) do roster ausente(s) "
            f"no catálogo vivo do OpenRouter [{slugs}]. NÃO disparar o lote — atualize o roster "
            f"(registry.SQUAD_ROSTER ou env AI_SQUAD_ROSTER_<ROLE>) com slugs válidos."
        )
    return report
