"""Measure code-reviewer persona performance across OpenRouter models.

This module evaluates how well different LLMs perform as code reviewers against
a ground-truth dataset. It runs N repetitions per test case with idempotent
checkpointing and strict budget control. Results are aggregated by model slug
with detection rates (for buggy cases) and over-flag rates (for clean cases).
"""

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from super_squad.roles import load_role
from super_squad.squad import run_squad, make_openrouter_text_job
from super_squad.rulers import contains_any_ruler, top_bug_forbids_ruler
from super_squad.role_shadow import already_checkpointed, append_checkpoint_line


def run_code_review_eval(
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
) -> dict:
    """Run the code review evaluation across models.

    `clean_preflight_judges` (opt-in, DIP): se uma lista de slugs de juiz for passada, roda o
    PRÉ-VOO DO GOLD (`gold_preflight.assert_clean_cases_valid`) ANTES de gastar no pool inteiro —
    fail-closed: se algum caso-limpo é suspeito de NÃO ser limpo (o juiz medido nomeia a vuln
    proibida), levanta `GoldPreflightError` e NÃO mede. Mata o modo-de-falha 'autor jurou limpo mas
    tinha bug real → over-flag enviesado' na raiz. Default None = pula (compat retroativa)."""
    # Load input data
    with open(cases_path, encoding="utf-8") as f:
        cases = json.load(f)
    persona = load_role(persona_path)
    system = persona.system_prompt
    n = n_per_case or cases["n_per_case"]

    # Validate inputs
    if not pool:
        raise ValueError("Pool cannot be empty")
    for case in cases["cases"]:
        if case["kind"] == "buggy" and not case.get("detect_any"):
            raise ValueError(f"Case {case['id']} is buggy but missing detect_any")
        if case["kind"] == "clean" and not case.get("forbid_any"):
            raise ValueError(f"Case {case['id']} is clean but missing forbid_any")

    # Pré-voo do gold (opt-in, fail-closed): veta caso-limpo suspeito antes de queimar orçamento.
    if clean_preflight_judges:
        from .gold_preflight import assert_clean_cases_valid
        assert_clean_cases_valid(
            cases, system, clean_preflight_judges,
            n=n, api_key=api_key, temperature=temperature, timeout=timeout,
            max_tokens=max_tokens or 800, workers=workers,
        )

    # Prepare checkpoint
    checkpoint_path = Path(f"{out_path}.ckpt.jsonl")
    done_keys = set(already_checkpointed(checkpoint_path)) if checkpoint_path.exists() else set()

    # Build jobs
    jobs = []
    for case in cases["cases"]:
        for slug, pin, pout in pool:
            for rep in range(n):
                key = f"{case['id']}::{slug}::{rep}"
                if key in done_keys:
                    continue
                prompt = (
                    cases["instruction"]
                    + "\n\n```"
                    + case["language"]
                    + "\n"
                    + case["diff"]
                    + "\n```"
                )
                jobs.append(
                    make_openrouter_text_job(
                        key,
                        prompt,
                        slug,
                        pin,
                        pout,
                        system=system,
                        temperature=temperature,
                        timeout=timeout,
                        api_key=api_key,
                        max_tokens=max_tokens,
                    )
                )

    # Run squad and checkpoint results
    report = run_squad(jobs, workers=workers, budget_usd=budget_usd)
    for result in report.results:
        if result.ok:
            append_checkpoint_line(
                checkpoint_path,
                {
                    "key": result.key,
                    "text": result.value["text"],
                    "cost_usd": result.cost_usd,
                    "latency_ms": result.latency_ms,
                    "slug": result.model,
                    "case_id": result.key.split("::")[0],
                    "rep": int(result.key.split("::")[2]),
                },
            )

    # Aggregate results from all checkpoint rows (including previous runs)
    all_rows = []
    if Path(checkpoint_path).exists():
        with open(checkpoint_path, encoding="utf-8") as f:
            all_rows = [json.loads(line) for line in f]

    # Score each row
    case_map = {case["id"]: case for case in cases["cases"]}
    scored_rows = []
    for row in all_rows:
        case = case_map[row["case_id"]]
        if case["kind"] == "buggy":
            passed = contains_any_ruler(case["detect_any"])(row["text"])["pass"]
        else:
            # caso limpo: over-flag SÓ se o TOP_BUG nomear a vuln FALSA específica (forbid_any);
            # levantar preocupação defensável diferente NÃO é over-flag (distingue alucinação de minúcia)
            passed = top_bug_forbids_ruler(case.get("forbid_any", []))(row["text"])["pass"]
        scored_rows.append({**row, "passed": passed})

    # Aggregate by slug
    by_slug = defaultdict(lambda: defaultdict(list))
    for row in scored_rows:
        by_slug[row["slug"]]["all_rows"].append(row)
        by_slug[row["slug"]][f"{row['case_id']}_rows"].append(row)

    summary = {
        "pool": [slug for slug, _, _ in pool],
        "n_per_case": n,
        "spent_total_usd": report.total_cost_usd,
        "budget_hit": report.budget_hit,
        "by_slug": {},
        "cases": [case["id"] for case in cases["cases"]],
    }

    for slug, data in by_slug.items():
        buggy_rows = [r for r in data["all_rows"] if case_map[r["case_id"]]["kind"] == "buggy"]
        clean_rows = [r for r in data["all_rows"] if case_map[r["case_id"]]["kind"] == "clean"]

        per_case = {}
        for case_id in summary["cases"]:
            case_rows = [r for r in data[f"{case_id}_rows"]]
            if not case_rows:
                continue
            case = case_map[case_id]
            if case["kind"] == "buggy":
                passed = sum(r["passed"] for r in case_rows)
                per_case[case_id] = passed / len(case_rows)
            else:
                passed = sum(r["passed"] for r in case_rows)
                per_case[case_id] = passed / len(case_rows)

        summary["by_slug"][slug] = {
            "detection_rate": (
                sum(r["passed"] for r in buggy_rows) / len(buggy_rows) if buggy_rows else 0
            ),
            "clean_rate": (
                sum(r["passed"] for r in clean_rows) / len(clean_rows) if clean_rows else 0
            ),
            "over_flag_rate": (
                1 - (sum(r["passed"] for r in clean_rows) / len(clean_rows)) if clean_rows else 0
            ),
            "avg_cost_usd": (
                sum(r["cost_usd"] for r in data["all_rows"]) / len(data["all_rows"])
            ),
            "avg_latency_ms": (
                sum(r["latency_ms"] for r in data["all_rows"]) / len(data["all_rows"])
            ),
            "n_calls": len(data["all_rows"]),
            "per_case": per_case,
        }

    # Write output
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return summary


def render_markdown(summary) -> str:
    """Render summary as markdown table."""
    slugs = sorted(
        summary["by_slug"].keys(),
        key=lambda s: (
            -summary["by_slug"][s]["detection_rate"],
            summary["by_slug"][s]["avg_cost_usd"],
        ),
    )

    lines = [
        "| Model | Detection Rate | Over-Flag Rate | Avg Cost (USD) | Avg Latency (ms) |",
        "|-------|----------------|----------------|----------------|------------------|",
    ]

    for slug in slugs:
        data = summary["by_slug"][slug]
        lines.append(
            f"| {slug} | {data['detection_rate']:.2f} | {data['over_flag_rate']:.2f} | "
            f"{data['avg_cost_usd']:.6f} | {data['avg_latency_ms']:.0f} |"
        )

    return "\n".join(lines)


def main(argv=None):
    """CLI entry point."""
    if argv is None:
        argv = sys.argv[1:]

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("cases", help="Path to cases JSON file")
    parser.add_argument("persona", help="Path to persona role file")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--budget", type=float, default=0.40, help="Budget in USD")
    parser.add_argument(
        "--slug",
        action="append",
        help="Model slug and pricing as slug:price_in:price_out",
    )
    args = parser.parse_args(argv)

    pool = []
    for slug_spec in args.slug:
        parts = slug_spec.split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid slug spec: {slug_spec}")
        slug, pin, pout = parts
        pool.append((slug, float(pin), float(pout)))

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY environment variable not set")

    summary = run_code_review_eval(
        args.cases,
        args.persona,
        pool,
        out_path=args.out,
        budget_usd=args.budget,
        api_key=api_key,
    )

    print(render_markdown(summary))
    print(
        f"\nspent=${summary['spent_total_usd']:.6f}  n_per_case={summary['n_per_case']}  "
        f"budget_hit={summary['budget_hit']}"
    )


if __name__ == "__main__":
    main()
