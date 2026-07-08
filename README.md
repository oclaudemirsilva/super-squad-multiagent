# super-squad-multiagent

Multi-model orchestration **WITH an oversight regime.** Everyone publishes multi-agent orchestration; almost nobody publishes the **fiscal regime** that keeps the fleet honest. This repo is the generic engine for both: fan-out multi-model via OpenRouter **+** the set of audits that measures each role against a deterministic ruler and human ground-truth.

## Structure

Python package `super_squad/`.

| Module | Purpose |
|--------|---------|
| `openrouter.py` | Standard-library-only OpenRouter client. One key → N models across labs. Key **only** via env `OPENROUTER_API_KEY`, never logged; error bodies truncated. |
| `registry.py` | Per-role model roster. **Ships empty on purpose:** the methodology requires **you** to measure models against **your** ground-truth before rostering them. Env override: `AI_SQUAD_ROSTER_<ROLE>="slug:price_in:price_out,slug2:..."`. Prices are USD per Mtok. |
| `squad.py` | The fan-out engine: `Job`/`JobResult`/`run_squad` (concurrent jobs, per-run USD budget cap, fail-soft collection, injectable telemetry via `on_event`), `make_openrouter_text_job` / `make_openrouter_vision_job` adapters, `parse_verdict_keyword`, `aggregate_panel_verdicts` (majority vote, conservative tie-break BAD>OK>GOOD, optional per-model weights). |
| `preflight.py` | Guard **B6**: BEFORE spending, verify every roster slug still exists in the live OpenRouter catalog and compare live price vs configured (drift = warning; dead slug = hard abort via `PreflightError`). |
| `spend_ledger.py` | Guard **B5**: persistent append-only global spend ledger with a per-window (day/month) ceiling; `check_budget` blocks new batches when the ceiling is hit and emits a 50/75/90/100% alert ladder. |
| `maestro.py` | Workflow dispatcher: `WorkflowSpec(name, roles, runner, default_budget_usd, description, spends_money)` + `register()` + `dispatch()`. **DRY-RUN BY DEFAULT** (`execute=False` returns the plan and spends nothing). Composes the guards in order: missing-API-key abort → preflight → global ceiling (clamps the round budget to what remains) → runner → ledger record. CLI: `--list`, `--execute`, `--budget-usd`, `--limit`, `--rerun-tag`, `--skip-preflight`, `--daily-budget-usd`, `--spend-ledger`. |
| `role_shadow.py` | **The FISCAL:** shadow audit engine. `RoleAuditSpec(role, items_fn, deterministic_fn, make_agent_fn, gold_fn)` + `run_role_audit()` writes one JSONL line per item comparing deterministic ruler vs paid agent vs human gold, idempotent by key (re-runs never re-pay), `key_suffix` for periodic re-audit epochs (e.g. "::2026-08"), returns `agreement_rate`, `det_gold_acc`, `agent_gold_acc`, `spent_usd`. `register_role()` + `make_shadow_runner()` bridge a role into the maestro as workflow `"shadow_<role>"`. |
| `candidate_eval.py` | Evaluate a **CANDIDATE** model slug against your ground-truths role by role **WITHOUT** ever touching the incumbent roster. `run_candidate_eval(slug, pin, pout, evaluators={...}, budget_usd=...)` → JSON report; promotion is a **HUMAN** decision informed by the report. `EvalCheckpoint` gives idempotent re-runs. |
| `code_writer.py` | The `code` role: `make_squad_code_writer(budget_usd)` → `writer_fn(spec)` → `{code, raw, cost_usd}`. A cheap model drafts code from a spec; a strong reviewer (human or gating model) audits before applying. Defends against markdown fences the model adds despite instructions. |

## The methodology

1.  **Measured roster or no roster.** A model only enters a role after being measured on **your** ground-truth with N>=5 per decision (never N=1 anecdotes). The registry ships empty by design — copying someone else's roster skips the step that makes the system work.
2.  **Cross-lab panels.** Judging roles use models from **different labs**; shared blind spots are the failure mode redundancy cannot catch.
3.  **Weighted vote with conservative tie-break.** Weights are only applied with measured evidence. A real finding motivated it: two models confirmed blind to a real defect (N=5, 0/5) outvoted one correct model 2-1 under simple majority; weight 2.0 on the measured-reliable model fixes that without granting unilateral veto (ties resolve to the most conservative verdict BAD>OK>GOOD).
4.  **Shadow audits (the fiscal).** Every role gets a free deterministic ruler run beside the paid agent; disagreements go to **HUMAN review**; the loop measures and reports, it **NEVER** rewires the roster by itself. In one origin role this loop took agreement from 61.76% to 80.39%.
5.  **Human-only ground truth.** Golds are written by human hands only; the system never feeds its own output back as truth (anti-autophagy).
6.  **Abstention over confabulation.** Rulers and agents may return `abstain=true`; an honest "no answer" is tracked separately from an error and from a wrong answer.
7.  **Candidate evaluation without roster contamination.** New models are measured by the same harness, in a separate report, and promoted only by a human.
8.  **Periodic re-audit (cadence).** Re-run shadows with a `key_suffix` epoch tag (e.g. "::2026-08"); drift between epochs is visible in the checkpoints. Model catalogs rot: preflight catches dead slugs and price drift before every batch.

## Safety rails

*   API key only via environment variable; never hardcoded, never logged (error bodies truncated before raising).
*   Dry-run by default everywhere; `--execute` is the only spending path.
*   Three budget layers: per-call/per-round cap → per-run budget → global windowed ceiling.
*   A money-spending workflow with no API key **ABORTS** in preflight (a silent fail-soft run that records `agent=null` on every item is worse than an error).
*   Money-spending scripts are human CLIs; never wire them into CI.

## Quickstart

```bash
git clone https://github.com/oclaudemirsilva/super-squad-multiagent
cd super-squad-multiagent
set OPENROUTER_API_KEY=sk-or-...   # (or export on unix)
set AI_SQUAD_ROSTER_SENTIMENT_JUDGE=google/gemini-2.5-flash:0.30:2.50,deepseek/deepseek-chat:0.27:1.10
python -m demo.toy_squad --list            # see registered demo workflows
python -m demo.toy_squad shadow_sentiment_judge            # dry-run: plan only, spends nothing
python -m demo.toy_squad shadow_sentiment_judge --execute --limit 6   # ~$0.001
```

Pure stdlib, no dependencies to install (Pillow optional for vision helpers). Python 3.10+.

Reference run of the demo (2 models, 6 items, $0.00017): the naive ruler scored 4/6 against
gold — it missed exactly the two negation traps — while the cross-lab panel scored 6/6; the
two ruler×agent disagreements are the audit product that goes to human review, and preflight
flagged a real live-vs-configured price drift on one of the two slugs. That one run exercises
the ruler, the panel, the gold accounting, and guard B6.

## What stays yours

Your roster, your golds, your checkpoints, and your spend ledgers are user data, not repo data. The `.gitignore` already excludes runtime artifacts; `_candidate_evals` reports are worth versioning in **your** project as the audit trail of promotion decisions.

## License

MIT