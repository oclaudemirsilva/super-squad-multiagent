"""role_eval.py — runner de medição ROLE-AGNÓSTICO (a régua vem do GOLD, não do código).

`code_review_eval` é específico do papel code-reviewer (detecção/over-flag via detect_any/forbid_any).
Este runner generaliza: cada caso do gold declara SUA régua por uma string `ruler` (resolvida por
`rulers.resolve_ruler`) — então UM runner serve qualquer papel consultivo (qa-test-judge, architect,
data-analyst…). Mantém a espinha do outro: N≥5 reps/caso, teto de gasto, checkpoint idempotente
(resume não re-paga), pré-voo de gold opcional (fail-closed). ADITIVO: não toca `code_review_eval`.

Contrato do GOLD (JSON):
    {
      "instruction": "<prompt base do papel>",
      "n_per_case": 5,
      "cases": [
        {"id": "...", "input": "<conteúdo>", "ruler": "contains_any:foo,bar", "gold": <opcional>},
        ...
      ]
    }
Régua por caso: `case["ruler"]` (spec de `resolve_ruler`) tem precedência; sem ela, cai na convenção
do code-review (kind=buggy+detect_any → contains_any; kind=clean+forbid_any → top_bug_forbids) para
rodar golds antigos sem alteração. Conteúdo do caso: `case["input"]` (genérico) OU `diff`(+`language`)
cercado (convenção code-review). Sem régua resolvível → VALIDAÇÃO falha (fail-closed, não mede às cegas).

SOLID/DIP: `run_squad`/`make_job`/`load_role` reusados; testes herméticos injetam fakes. STDLIB + o
próprio pacote. A régua é DETERMINÍSTICA (D6/D7) e só emite veredito — não promove/rosteia (D5).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from super_squad.rulers import (
    resolve_ruler,
    contains_any_ruler,
    top_bug_forbids_ruler,
)
from super_squad.role_shadow import already_checkpointed, append_checkpoint_line


def resolve_case_ruler(case: dict) -> "Optional[Callable]":
    """Devolve a régua determinística do caso. Precedência: `case['ruler']` (spec de resolve_ruler)
    → convenção code-review (detect_any/forbid_any). Sem régua resolvível → None (o chamador trata
    como VALIDAÇÃO reprovada — nunca pontua às cegas)."""
    spec = case.get("ruler")
    if spec:
        return resolve_ruler(spec)
    kind = case.get("kind")
    if kind == "buggy" and case.get("detect_any"):
        return contains_any_ruler(case["detect_any"])
    if kind == "clean" and case.get("forbid_any"):
        return top_bug_forbids_ruler(case["forbid_any"])
    return None


def _case_body(case: dict) -> str:
    """Conteúdo submetido: `input` (genérico) OU `diff`(+`language`) cercado (convenção code-review)."""
    if "input" in case:
        return str(case["input"])
    if "diff" in case:
        lang = case.get("language", "")
        return f"```{lang}\n{case['diff']}\n```"
    return ""


def run_role_eval(
    cases_path,
    persona_path,
    pool,
    *,
    out_path,
    n_per_case=None,
    api_key=None,
    budget_usd=0.40,
    workers=6,
    temperature=0.4,
    timeout=120,
    max_tokens=None,
    clean_preflight_judges=None,
    load_role_fn: "Optional[Callable]" = None,
    run_squad_fn: "Optional[Callable]" = None,
    make_job_fn: "Optional[Callable]" = None,
) -> dict:
    """Mede a persona `persona_path` no gold `cases_path` cruzando `pool` (lista de `(slug,pin,pout)`),
    N reps/caso, régua VINDA DO GOLD por caso. Devolve o resumo `{by_slug, ...}` e escreve em `out_path`.

    Fail-closed: um caso sem régua resolvível ABORTA a validação (não mede sem saber pontuar). Checkpoint
    idempotente por `out_path`. `clean_preflight_judges` (opt-in) roda o pré-voo do gold antes de gastar."""
    if load_role_fn is None:
        from super_squad.roles import load_role as load_role_fn
    if run_squad_fn is None:
        from super_squad.squad import run_squad as run_squad_fn
    if make_job_fn is None:
        from super_squad.squad import make_openrouter_text_job as make_job_fn

    with open(cases_path, encoding="utf-8") as f:
        cases = json.load(f)
    persona = load_role_fn(persona_path)
    system = persona.system_prompt
    n = n_per_case or cases["n_per_case"]

    if not pool:
        raise ValueError("Pool cannot be empty")
    # VALIDAÇÃO fail-closed: toda caso precisa de régua resolvível (senão a medição é cega).
    rulers = {}
    for case in cases["cases"]:
        r = resolve_case_ruler(case)
        if r is None:
            raise ValueError(
                f"caso {case['id']!r} sem régua resolvível — declare `ruler` (spec de resolve_ruler) "
                f"ou a convenção detect_any/forbid_any. O runner não pontua às cegas."
            )
        rulers[case["id"]] = r

    if clean_preflight_judges:
        from super_squad.gold_preflight import assert_clean_cases_valid
        assert_clean_cases_valid(
            cases, system, clean_preflight_judges,
            n=n, api_key=api_key, temperature=temperature, timeout=timeout,
            max_tokens=max_tokens or 800, workers=workers,
        )

    checkpoint_path = Path(f"{out_path}.ckpt.jsonl")
    done_keys = set(already_checkpointed(checkpoint_path)) if checkpoint_path.exists() else set()

    jobs = []
    for case in cases["cases"]:
        prompt = cases["instruction"] + "\n\n" + _case_body(case)
        for slug, pin, pout in pool:
            for rep in range(n):
                key = f"{case['id']}::{slug}::{rep}"
                if key in done_keys:
                    continue
                jobs.append(make_job_fn(
                    key, prompt, slug, pin, pout, system=system,
                    temperature=temperature, timeout=timeout, api_key=api_key, max_tokens=max_tokens,
                ))

    report = run_squad_fn(jobs, workers=workers, budget_usd=budget_usd)
    for r in report.results:
        if r.ok:
            append_checkpoint_line(checkpoint_path, {
                "key": r.key, "text": r.value["text"], "cost_usd": r.cost_usd,
                "latency_ms": r.latency_ms, "slug": r.model,
                "case_id": r.key.split("::")[0], "rep": int(r.key.split("::")[2]),
            })

    all_rows = []
    if Path(checkpoint_path).exists():
        with open(checkpoint_path, encoding="utf-8") as f:
            all_rows = [json.loads(line) for line in f]

    by_slug = defaultdict(lambda: defaultdict(list))
    for row in all_rows:
        cid = row["case_id"]
        if cid not in rulers:
            continue  # linha de um caso que saiu do gold — ignora
        passed = rulers[cid](row["text"])["pass"]
        row = {**row, "passed": passed}
        by_slug[row["slug"]]["all"].append(row)
        by_slug[row["slug"]][cid].append(row)

    case_ids = [c["id"] for c in cases["cases"]]
    summary = {
        "pool": [slug for slug, _, _ in pool],
        "n_per_case": n,
        "spent_total_usd": report.total_cost_usd,
        "budget_hit": report.budget_hit,
        "cases": case_ids,
        "by_slug": {},
    }
    for slug, data in by_slug.items():
        rows = data["all"]
        per_case = {cid: (sum(r["passed"] for r in data[cid]) / len(data[cid]))
                    for cid in case_ids if data.get(cid)}
        summary["by_slug"][slug] = {
            "pass_rate": sum(r["passed"] for r in rows) / len(rows) if rows else 0,
            "avg_cost_usd": sum(r["cost_usd"] for r in rows) / len(rows) if rows else 0,
            "avg_latency_ms": sum(r["latency_ms"] for r in rows) / len(rows) if rows else 0,
            "n_calls": len(rows),
            "per_case": per_case,
        }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return summary


def render_markdown(summary) -> str:
    """Tabela simples ordenada por pass_rate desc, custo asc."""
    slugs = sorted(summary["by_slug"], key=lambda s: (-summary["by_slug"][s]["pass_rate"],
                                                       summary["by_slug"][s]["avg_cost_usd"]))
    lines = ["| Model | Pass Rate | Avg Cost (USD) | Avg Latency (ms) | N |",
             "|-------|-----------|----------------|------------------|---|"]
    for s in slugs:
        d = summary["by_slug"][s]
        lines.append(f"| {s} | {d['pass_rate']:.2f} | {d['avg_cost_usd']:.6f} | "
                     f"{d['avg_latency_ms']:.0f} | {d['n_calls']} |")
    return "\n".join(lines)
