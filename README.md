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
| `roles.py` | **The subagent layer.** Ingests a persona (VoltAgent-style frontmatter + body = system prompt) → `RoleSpec` (`load_role`/`load_roles_dir`); `classify_single_shot` splits *consultative* (reviewer/auditor/analyst — runs on the engine today, inert) from *builder* (declares Write/Edit/Bash — needs the Phase-2 runtime); `make_role_job` turns a single-shot persona + model into a `run_squad` job. Domain-blind: it transports the prompt, it doesn't know what the role does. **A subagent = persona (portable prompt) + measured model (private roster) + optional skill** — see `docs/design/subagent-portability.md`. |
| `code_review_eval.py` | Reference **per-role measurement runner** (template for new roles): runs one consultative persona across N models, N>=5 reps/case, against a private gold, with a spend cap and an idempotent checkpoint; scores detection (`contains_any`) × over-flag (`top_bug_clean`) × cost × latency; orders by cost-benefit; **never rosters** (D5). |
| `execution_ruler.py` | **Objective ruler for ACTIVE roles** (code-writer/debugger): applies the model's PATCH to the buggy code, runs the gold's TRUSTED test, pass = the test now succeeds. Truth is EXECUTABLE, not opinion — so golds need no hand-authored "expected output". Trust-split (patch is the only untrusted input; argv-only, `shell=False`); `require_isolation=True` **fail-closed** (refuses without an injected OS-sandboxed `run_fn` — a tempdir+subprocess is a correctness fence, not a security boundary); oracle hard-guard (re-materializes tests AFTER apply; strips planted `conftest.py`/`*.pth`); stdlib whole-or-nothing applier; NEVER raises. |
| `git_harvester.py` | **Harvests golds from git history** (human truth, no manual authoring, anti-autophagy): a fix-commit → parent=buggy input, message=spec, the test it makes pass=oracle. Two signals (keyword + source∧test co-change), false-positive gates (skip merge/root/no-oracle/no-runner). `run_git` injected (sole I/O seam); NEVER crashes (anomaly→skip). The human fix is metadata only — the model never sees it; the verdict is objective execution, so gold stays human-origin (`origin=human_commit`). |
| `rulers.py` | Ready-made **deterministic rulers** for the fiscal (one per role was always DIY): `json_valid` (strict about markdown fences), `numeric_close` (pulls the numeric answer out of prose, pt-BR/en), `length_window`, `contains_all`, `contains_any`, `contains_none`, `exact_match`, `keyword_verdict`, `set_f1`, `top_bug_clean` (clean-case verdict by the committed `TOP_BUG:` line) + `resolve_ruler` for JSON suites. Pure, stdlib-only. |
| `bench.py` | **Roster bootstrap (step 0):** fan a task **suite** across a model **pool** → matrix of cost / latency / quality + per-role leaderboard + suggested roster. Quality comes only from a deterministic ruler **or** multiple collaborators' ratings aggregated by median — never model-judges-model (D6/D7). Dry-run by default; `--preflight` composes guard B6; it **suggests** but never rosters (D5). |
| `role_eval.py` | **Role-agnostic measurement runner** (generalizes `code_review_eval`): the ruler comes from the GOLD per case (`resolve_ruler`), so one runner measures any consultative role. N>=5, spend cap, idempotent checkpoint. Opt-ins (all default-off, additive): `clean_preflight_judges` (gold pre-flight D12), `preflight_pool` (roster pre-flight B3, dead slug aborts), `system_suffix` (task-forcing to neutralize verbose-persona protocol noise, D15), `skill_path` (compose a skill to measure skill-lift, D3/D10). Never rosters (D5). |
| `run_role.py` / `run_roles.py` | **The front doors.** `run_role` runs ONE measured subagent in one call; `run_roles` runs N in a single concurrent fan-out (persona + roster + optional `skill` + optional `instruction`/`system_suffix`), fail-soft per task, opt-in roster pre-flight. Consultative (system prompt injected, no tools execute). |
| `skills.py` | **The skill layer (D10).** Ingests a playbook (`SkillSpec`) and `compose_system(persona, skill)` fuses it onto the persona system prompt. Gate: a skill that executes code (`requires_script`) raises `SkillGateError` in single-shot (Phase 2). License provenance per skill (`license`/`license_cleared`, human check, D2). |
| `routing.py` | **The ruflo-union seam (D14).** `RoutingProvider` + `MeasuredRoutingProvider` (trivial intent + booster → $0; else → measured titular) + `NullBoosterAdapter` (ruflo absent → graceful fallback to the model). Scaffold: real booster/memory needs ruflo connected (Track C, human). |
| `runtimes/base.py` | **The Phase-2 builder seam.** `BuilderRuntime` protocol + `BuilderTask`/`BuilderResult` + `PermissionProfile` + `NullBuilderRuntime` (fail-closed default) + `assert_builder_preconditions` (worktree + caps + human `hardening_ack` or it blocks). |
| `runtimes/hardening.py` | **A1–A5 enforcement primitives (D-security).** `redact_secrets` (A2), `is_bash_allowed` (A3, anti-shell-chaining), `WorktreeManager` (A1, blast radius, `session` always removes), `SpendGuard` (A5, mid-loop cap), `enforce_permission` (fail-closed dispatch over a `PermissionProfile`). Pure, injectable, hermetic. |
| `runtimes/opencode.py` | **OpenCode builder adapter — sequence wired, execution GATED.** §3 flow (global budget → ephemeral config → headless run → git diff → parse usage → ledger) + telemetry, all injectable. Three hard gates: `enabled=False` · preconditions · `command_builder=None` (refuses to guess the real CLI flags until §9 is human-verified). Never runs the binary on its own. |

## The methodology

1.  **Measured roster or no roster.** A model only enters a role after being measured on **your** ground-truth with N>=5 per decision (never N=1 anecdotes). The registry ships empty by design — copying someone else's roster skips the step that makes the system work. The cold-start (**step 0**) — deciding *which* models to measure first — is `bench.py`: it fans a task suite across a candidate pool and returns the cost/latency/quality matrix that seeds the decision, and it **suggests** but never picks the roster for you.
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

## Reusing a subagent in another project

A subagent is not code — it is `persona (prompt) + measured model (config) + optional skill`, so it
travels as config, not a dependency. To reuse a **measured** subagent in another project, carry:

1. the **persona** file (`roles/vendor/<role>.md`, public, MIT);
2. the **roster line** you measured (`<slug>:<price_in>:<price_out>`, private — your ground-truth is your edge, D1);
3. any runner that injects the persona's `system_prompt` into a model call.

The simplest path is the **front door** `run_role` — it loads the persona, picks the rostered model,
runs it consultatively (system prompt injected, no tools execute), and returns the verdict:

```python
from super_squad.run_role import run_role   # needs env AI_SQUAD_ROSTER_CODE_REVIEWER + OPENROUTER_API_KEY
out = run_role("code-reviewer", my_code_or_diff, budget_usd=0.05)
print(out["model"], out["text"])            # titular verdict; pass panel=True to run the whole roster
```

Or from the shell, one command (any session/agent, no internals):

```bash
export OPENROUTER_API_KEY=sk-or-...
export AI_SQUAD_ROSTER_CODE_REVIEWER="<your measured slug>:<pin>:<pout>"   # private roster line
python -m super_squad.run_role code-reviewer "Review this: <code>"
```

**Several subagents at once** — `run_roles` runs N roles in a single concurrent fan-out (all jobs share
the worker pool and the spend cap; a role with an empty roster fails that task, not the batch):

```python
from super_squad.run_roles import run_roles
out = run_roles([
    {"role": "code-reviewer", "input": diff},
    {"role": "security-auditor", "input": diff},
])
for t in out["tasks"]:
    print(t["role"], "→", (t["results"][0]["text"] if not t["error"] else t["error"]))
```

The target roster of roles (the 12 most important, in dependency order) lives in [`roles/MANIFEST.md`](roles/MANIFEST.md).

The same subagent also runs from another project's own OpenRouter call (`system=spec.system_prompt`,
`model=<slug>`), from an AI gateway, or back inside Claude Code / Codex / OpenCode (the personas came from
those catalogs). `run_role` is **consultative** (read & judge, no tool execution) — for a persona that
declares builder tools it runs as an advisor; actual building is Phase 2. **Portable ≠ trustworthy:** only a persona with a *measured* roster line (N>=5 vs your gold)
is a subagent you can trust; without measurement it is a portable prompt of unknown quality/cost. The roster
was measured against a specific gold — it transfers as a strong prior; **re-validate** (`candidate_eval`) if
the target task differs materially. Today all subagents are consultative (read & judge); builders are Phase 2.

## Where the architecture lives (read next, if you are an agent landing here)

- `DECISIONS.md` — the design decisions D1–D16 (why the roster ships empty, why measurement is private, etc.).
- `docs/INTEGRATION.md` — **honest integration map** of the union (subagents ✅ · skills ✅ · OpenCode 🟡 wired-but-gated · ruflo 🔴 seam-only), with the file that proves each claim.
- `docs/ROADMAP.md` — status per track (A–F), honest.
- `docs/BENCHMARK_STATEMENT.md` — the public anonymized benchmark claim (method + value, no slug/number).
- `docs/design/subagent-portability.md` — what a subagent is and the full reuse contract.
- `docs/design/flywheel-bootstrap.md` — the self-improving loop: measure roles in dependency order (reviewer → qa → architect → security → debugger → builders), on OpenRouter, the best measured model per role.
- `docs/design/opencode-builder-runtime.md` — the Phase-2 builder-runtime seam: **sequence wired + hardening implemented, execution gated** (`enabled=False` + §9 unverified); merge = human.
- `docs/design/ruflo-union-routing-seam.md` — the `RoutingProvider` seam uniting the fleet with a substrate (this engine = model authority; ruflo = cross-session memory + cost + $0 tier-1 booster). **Seam scaffolded (`routing.py`), real ruflo NOT connected** (Track C, human, D14).
- `docs/security/threat-model.md` — A1–A5 execution hardening; **enforcement primitives now implemented in `runtimes/hardening.py`** (hard pre-reqs before any builder runs).

## What stays yours

Your roster, your golds, your checkpoints, and your spend ledgers are user data, not repo data. The `.gitignore` already excludes runtime artifacts (`ground_truth/`, `rosters/`, `_candidate_evals/`); those reports are worth versioning in **your** private project as the audit trail of promotion decisions.

## License

MIT