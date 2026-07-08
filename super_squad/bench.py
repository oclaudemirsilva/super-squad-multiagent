"""bench.py — bootstrap de ROSTER: mede um POOL de modelos num SUITE de tarefas.

O degrau 0 da metodologia. `candidate_eval` mede 1 candidato contra um roster que existe;
`role_shadow` audita um roster em produção. Faltava a partida a frio: "tenho N modelos e M
tipos de função — rode todos, me dê a PONTUAÇÃO por modelo × função (custo, latência, qualidade)
e as saídas lado a lado pra eu decidir quem faz o quê". É este módulo.

EIXOS OBJETIVOS (automáticos, grátis): custo USD, latência, tamanho da saída e — quando a
tarefa traz uma RÉGUA determinística (ver rulers.py) ou GOLD humano — um veredito objetivo.
QUALIDADE SUBJETIVA (opcional): `ratings={task: {slug: [notas...]}}` agrega a EXPERIÊNCIA de
VÁRIOS colaboradores (mediana) — é assim que "a experiência de cada um" entra sem virar
palpite de um só (N>=5, gold humano). Onde não há régua nem rating, a qualidade fica
"human-review" e o relatório traz o texto de cada célula pra um humano pontuar.

O bench NUNCA dá nota com modelo (D6) e NUNCA escolhe o roster sozinho (D1/D5): ele mede,
pontua, ORDENA e SUGERE (o mais barato que passou por função) — a promoção é decisão humana.

SEGURO POR DEFAULT (D3): `run_bench(..., execute=False)` e o CLI sem `--execute` devolvem só o
PLANO + estimativa de custo (não gastam nada). `--preflight` compõe a guarda B6 (slug vivo do
pool) antes de gastar. STDLIB-ONLY (D2); deps injetáveis (DIP) -> teste hermético sem rede.

CLI:
    python -m super_squad.bench SUITE.json                 # dry-run: plano + estimativa
    python -m super_squad.bench SUITE.json --execute --out matriz.json --budget 0.30

SUITE.json = {"tasks": [{"key","prompt","system?","temperature?","ruler?","gold?"}], "pool":
[{"slug","price_in","price_out"}]}. `ruler` é uma string resolvida por rulers.resolve_ruler.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Callable, Optional

Pool = "list[tuple[str, float, float]]"  # (slug, price_in/Mtok, price_out/Mtok)


@dataclass(frozen=True)
class BenchTask:
    """Um tipo de função a medir. `ruler(text, gold) -> {"pass","label",...}` (ver rulers.py)
    é opcional; sem ele a qualidade sai de `ratings` humanos ou fica 'human-review'."""
    key: str
    prompt: str
    system: "Optional[str]" = None
    temperature: float = 0.2
    ruler: "Optional[Callable[[str, object], dict]]" = None
    gold: object = None


def _tok(text: "Optional[str]") -> int:
    return max(1, len(text or "") // 4)  # ~4 chars/token, grosso mas suficiente p/ o teto


def bench_plan(tasks: "list[BenchTask]", pool: Pool, *, budget_usd: float,
               assumed_out_tokens: int = 600) -> dict:
    """Plano PURO (dry-run): quantas células e estimativa GROSSA de custo — sem gastar nada."""
    from .squad import estimate_cost
    cells, est = [], 0.0
    for t in tasks:
        in_tok = _tok(t.system) + _tok(t.prompt)
        for slug, pin, pout in pool:
            c = estimate_cost(1, in_tok, assumed_out_tokens, pin, pout)
            est += c
            cells.append({"task": t.key, "model": slug, "est_cost_usd": round(c, 6)})
    return {"n_cells": len(cells), "n_tasks": len(tasks), "n_models": len(pool),
            "budget_usd": budget_usd, "rough_cost_estimate_usd": round(est, 6),
            "assumed_out_tokens": assumed_out_tokens,
            "note": f"estimativa GROSSA (assume {assumed_out_tokens} tokens de saída/célula); "
                    "custo REAL só no --execute", "cells": cells}


def _aggregate_ratings(values: "Optional[list]") -> "Optional[float]":
    """Mediana das notas de colaboradores (robusta a outlier). Vazio/None -> None."""
    vals = [float(v) for v in (values or []) if isinstance(v, (int, float))]
    return round(statistics.median(vals), 3) if vals else None


def _grade(task: BenchTask, text: str, ratings: "Optional[list]") -> dict:
    """Qualidade de UMA célula. Régua determinística é autoritária p/ `pass`; notas humanas
    entram como `human_score` (mediana). `score01` in [0,1] é o eixo de ordenação (None =
    sem sinal objetivo -> vai pro fim e pede olho humano)."""
    human = _aggregate_ratings(ratings)
    if task.ruler is not None:
        try:
            out = dict(task.ruler(text, task.gold))
        except Exception as exc:  # noqa: BLE001 — régua quebrada vira nota nula, não derruba
            return {"graded": False, "error": repr(exc), "human_score": human}
        out["graded"] = True
        out["human_score"] = human
        out["score01"] = 1.0 if out.get("pass") else 0.0
        return out
    if human is not None:                      # sem régua, mas há experiência de colaboradores
        return {"graded": True, "label": "HUMAN_RATED", "pass": None,
                "human_score": human, "score01": max(0.0, min(1.0, human / 10.0))}
    return {"graded": False, "note": "human-review-required", "human_score": None, "score01": None}


def _rank_key(cell: dict):
    """Ordena células: maior qualidade, depois menor custo, depois menor latência.
    `score01=None` (sem sinal) cai pro fim sem mascarar de bom nem de ruim."""
    q = (cell.get("quality") or {}).get("score01")
    q_rank = -q if isinstance(q, (int, float)) else 1.0  # None -> pior que qualquer nota
    return (q_rank, cell.get("cost_usd") if cell.get("cost_usd") is not None else 9e9,
            cell.get("latency_ms") if cell.get("latency_ms") is not None else 9e9)


def leaderboard(report: dict) -> dict:
    """`{task: [célula ordenada...]}` — a PONTUAÇÃO de cada modelo por função (melhor primeiro)."""
    out: dict = {}
    for t in report.get("tasks", []):
        rows = [dict(c, slug=m) for m, c in report["matrix"][t].items() if c.get("ok")]
        out[t] = sorted(rows, key=_rank_key)
    return out


def _suggest(report_tasks: "list[str]", board: dict) -> dict:
    """Sugestão de roster: o TOPO do leaderboard por função entre os que PASSARAM na régua
    (se houver). Rótulo explícito de que é sugestão — humano confirma (D1/D5)."""
    by_role: dict = {}
    for t in report_tasks:
        ranked = []
        for c in board.get(t, []):
            q = c.get("quality") or {}
            if q.get("graded") and q.get("pass") is False:
                continue  # não sugere quem reprovou numa régua objetiva
            ranked.append({"slug": c["slug"], "cost_usd": c.get("cost_usd"),
                           "latency_ms": c.get("latency_ms"),
                           "quality_label": q.get("label"), "score01": q.get("score01")})
        by_role[t] = ranked
    return {"note": "SUGESTÃO (topo por função entre os aprovados) — promoção é decisão HUMANA "
                    "(D1/D5); confirme com N>=5 antes de rostear.", "by_role": by_role}


def run_bench(
    tasks: "list[BenchTask]", pool: Pool, *,
    budget_usd: float = 0.5, workers: int = 4, execute: bool = False,
    assumed_out_tokens: int = 600, api_key: "Optional[str]" = None,
    ratings: "Optional[dict]" = None, preflight: bool = False,
    list_models_fn: "Optional[Callable[[], dict]]" = None,
    run_squad_fn: "Optional[Callable]" = None, make_job_fn: "Optional[Callable]" = None,
    event_sink=None,
) -> dict:
    """Mede o pool no suite. DRY-RUN por default (`execute=False` -> só o plano). Com `execute`:
    [preflight opcional B6] -> fan-out via `run_squad` -> aplica régua/ratings por célula ->
    matriz + leaderboard + sugestão. `ratings[task][slug] = [notas]` agrega colaboradores.
    Deps injetáveis (DIP) p/ teste hermético: `make_job_fn`/`run_squad_fn`/`list_models_fn`."""
    the_plan = bench_plan(tasks, pool, budget_usd=budget_usd, assumed_out_tokens=assumed_out_tokens)
    if not execute:
        return {"ok": True, "ran": False, "plan": the_plan}

    ratings = ratings or {}
    preflight_report = None
    if preflight:
        try:
            from .preflight import parse_model_catalog
            if list_models_fn is None:
                from .openrouter import openrouter_list_models as list_models_fn
            catalog = parse_model_catalog(list_models_fn())
            missing = [slug for slug, _, _ in pool if slug not in catalog]
            preflight_report = {"checked": len(pool), "missing": missing}
            if missing:
                return {"ok": False, "ran": False, "plan": the_plan, "preflight": preflight_report,
                        "error": f"pré-voo bloqueou: slug(s) do pool ausente(s) no catálogo vivo: {missing}"}
        except Exception as exc:  # noqa: BLE001 — catálogo inacessível não bloqueia (aviso)
            preflight_report = {"warning": f"catálogo inacessível: {exc!r}"}

    if run_squad_fn is None:
        from .squad import run_squad as run_squad_fn
    if make_job_fn is None:
        from .squad import make_openrouter_text_job as make_job_fn

    jobs = []
    for t in tasks:
        for slug, pin, pout in pool:
            jobs.append(make_job_fn(
                key=f"{t.key}::{slug}", prompt=t.prompt, model=slug,
                price_in_per_mtok=pin, price_out_per_mtok=pout,
                system=t.system, temperature=t.temperature, api_key=api_key))

    report = run_squad_fn(jobs, workers=workers, budget_usd=budget_usd, on_event=event_sink)
    res_by_key = {r.key: r for r in report.results}

    cells: dict = {}
    matrix: dict = {t.key: {} for t in tasks}
    for t in tasks:
        for slug, pin, pout in pool:
            k = f"{t.key}::{slug}"
            r = res_by_key.get(k)
            cell_ratings = (ratings.get(t.key) or {}).get(slug)
            if r is None:
                cell = {"ok": False, "status": "missing"}
            elif r.status == "skipped_budget":
                cell = {"ok": False, "status": "skipped_budget"}
            elif not r.ok:
                cell = {"ok": False, "status": "error", "error": r.error}
            else:
                text = (r.value or {}).get("text", "") if isinstance(r.value, dict) else ""
                cell = {"ok": True, "status": "ok", "cost_usd": r.cost_usd,
                        "latency_ms": r.latency_ms, "n_chars": len(text),
                        "quality": _grade(t, text, cell_ratings), "text": text}
            cell["price_in"], cell["price_out"] = pin, pout
            cells[k] = cell
            matrix[t.key][slug] = cell

    result = {"ok": True, "ran": True, "plan": the_plan,
              "total_cost_usd": report.total_cost_usd, "n_ok": report.n_ok,
              "n_error": report.n_error, "n_skipped": report.n_skipped,
              "budget_hit": report.budget_hit, "preflight": preflight_report,
              "tasks": [t.key for t in tasks], "models": [s for s, _, _ in pool],
              "matrix": matrix, "cells": cells}
    board = leaderboard(result)
    result["leaderboard"] = board
    result["suggested_roster"] = _suggest(result["tasks"], board)
    return result


# ── Render humano (markdown) ─────────────────────────────────────────────────

def _row(label: str, values: "list[str]") -> str:
    return "| " + " | ".join([label, *values]) + " |"


def render_markdown(report: dict) -> str:
    """Matriz custo/latência/qualidade + pontuação por função + sugestão, em markdown."""
    if not report.get("ran"):
        p = report["plan"]
        return (f"# Bench (DRY-RUN — nada gasto)\n\n"
                f"{p['n_cells']} células = {p['n_tasks']} funções × {p['n_models']} modelos\n"
                f"Estimativa grossa: **US${p['rough_cost_estimate_usd']}** (teto US${p['budget_usd']})\n\n"
                f"Rode com `--execute` para medir de verdade.")
    tasks, models, M = report["tasks"], report["models"], report["matrix"]
    head = _row("função", models) + "\n|" + "---|" * (len(models) + 1)
    L = ["# Bench — matriz medida", "",
         f"Custo total: **US${report['total_cost_usd']}** · ok={report['n_ok']} "
         f"erro={report['n_error']} pulado={report['n_skipped']}"]

    L += ["", "## Custo (US$)", "", head]
    for t in tasks:
        L.append(_row(t, [f"{M[t][m]['cost_usd']:.5f}" if M[t][m].get("ok")
                          else M[t][m].get("status", "—") for m in models]))
    L += ["", "## Latência (s)", "", head]
    for t in tasks:
        L.append(_row(t, [f"{M[t][m]['latency_ms']/1000:.1f}" if M[t][m].get("ok") else "—"
                          for m in models]))
    L += ["", "## Qualidade (régua objetiva / rating humano)", "", head]
    for t in tasks:
        cells = []
        for m in models:
            c = M[t][m]
            if not c.get("ok"):
                cells.append("—"); continue
            q = c.get("quality") or {}
            if not q.get("graded"):
                cells.append("humano?")
            elif q.get("pass") is None:
                cells.append(f"~{q.get('human_score')}")
            else:
                cells.append(("PASS " if q.get("pass") else "FAIL ") + str(q.get("label", "")))
        L.append(_row(t, cells))

    L += ["", "## Pontuação por função (melhor primeiro)"]
    for t, rows in report["leaderboard"].items():
        rank = ", ".join(f"{r['slug'].split('/')[-1]} (US${(r.get('cost_usd') or 0):.5f})"
                         for r in rows) or "(nenhum ok)"
        L.append(f"- **{t}**: {rank}")

    L += ["", "## Sugestão de roster (humano confirma)"]
    for t, ranked in report["suggested_roster"]["by_role"].items():
        top = ranked[0]["slug"] if ranked else "(nenhum aprovado)"
        L.append(f"- **{t}** → `{top}`")
    L.append("")
    L.append(f"_{report['suggested_roster']['note']}_")
    return "\n".join(L)


# ── CLI (humano; dry-run por default) ────────────────────────────────────────

def main(argv=None) -> int:
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Bench de bootstrap de roster (Super Squad).")
    ap.add_argument("suite", help="JSON com {tasks:[...], pool:[...]}")
    ap.add_argument("--out", default=None, help="grava o relatório JSON (no --execute)")
    ap.add_argument("--execute", action="store_true", help="RODA de verdade (default = dry-run)")
    ap.add_argument("--budget", type=float, default=0.5, help="teto de gasto USD (default 0.5)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--preflight", action="store_true", help="checa slugs do pool vivos (B6)")
    ap.add_argument("--assumed-out-tokens", type=int, default=600)
    a = ap.parse_args(argv)

    from .rulers import resolve_ruler
    data = json.loads(Path(a.suite).read_text(encoding="utf-8"))
    tasks = [BenchTask(key=t["key"], prompt=t["prompt"], system=t.get("system"),
                       temperature=float(t.get("temperature", 0.2)),
                       ruler=resolve_ruler(t.get("ruler")), gold=t.get("gold"))
             for t in data["tasks"]]
    pool = [(m["slug"], float(m["price_in"]), float(m["price_out"])) for m in data["pool"]]
    ratings = data.get("ratings")

    report = run_bench(tasks, pool, budget_usd=a.budget, workers=a.workers, execute=a.execute,
                       assumed_out_tokens=a.assumed_out_tokens, preflight=a.preflight,
                       ratings=ratings)
    print(render_markdown(report))
    if a.execute and a.out and report.get("ran"):
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[bench] relatório JSON -> {a.out}")
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
