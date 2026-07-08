"""Testes do motor da Super Squad Multiagent — determinísticos, SEM rede, SEM custo.

Cobre: execução paralela + soma de custo, teto de orçamento (skip determinístico),
fail-soft, telemetria (eventos + sink que quebra não derruba), helpers de custo, e o
adapter OpenRouter com `openrouter_messages_raw` mockado.

Roda da raiz do repo:
    python -m pytest tests/test_squad.py -q
"""
from __future__ import annotations

import json

from super_squad import squad
from super_squad.squad import (
    Job,
    JobResult,
    aggregate_panel_verdicts,
    cost_from_openrouter_usage,
    estimate_cost,
    make_jsonl_sink,
    make_openrouter_text_job,
    make_openrouter_vision_job,
    parse_verdict_keyword,
    run_squad,
)


def _job(key: str, value="ok", cost: float = 0.0) -> Job:
    return Job(key=key, run=lambda: (value, cost), model=key)


def test_all_jobs_run_and_costs_accumulate():
    jobs = [_job(f"j{i}", value=i, cost=0.01) for i in range(3)]
    rep = run_squad(jobs, workers=3)
    assert rep.n_ok == 3
    assert rep.n_error == 0
    assert rep.n_skipped == 0
    assert rep.budget_hit is False
    assert round(rep.total_cost_usd, 6) == 0.03
    assert {r.value for r in rep.results} == {0, 1, 2}


def test_no_budget_runs_all():
    jobs = [_job(f"j{i}", cost=1.0) for i in range(5)]
    rep = run_squad(jobs, workers=2, budget_usd=None)
    assert rep.n_ok == 5
    assert rep.budget_hit is False


def test_budget_cap_skips_remaining_deterministic():
    # workers=1 -> execução sequencial -> ordem determinística
    jobs = [_job(f"j{i}", cost=0.5) for i in range(5)]
    rep = run_squad(jobs, workers=1, budget_usd=1.0)
    # j0: gasto 0.5 (<1 -> refila), j1: gasto 1.0 (>=1 -> para). j2..j4 pulados.
    assert rep.n_ok == 2
    assert rep.n_skipped == 3
    assert rep.budget_hit is True
    assert round(rep.total_cost_usd, 6) == 1.0
    skipped = [r for r in rep.results if r.status == "skipped_budget"]
    assert len(skipped) == 3
    assert all(r.cost_usd == 0.0 and r.ok is False for r in skipped)


def test_fail_soft_one_job_raises_does_not_kill_squad():
    def boom():
        raise ValueError("estourou")

    jobs = [_job("ok1"), Job("bad", boom, model="bad"), _job("ok2")]
    rep = run_squad(jobs, workers=3)
    assert rep.n_ok == 2
    assert rep.n_error == 1
    bad = next(r for r in rep.results if r.key == "bad")
    assert bad.ok is False
    assert "ValueError" in bad.error and "estourou" in bad.error


def test_telemetry_events_emitted():
    events: list = []
    jobs = [_job("j0"), _job("j1")]
    run_squad(jobs, workers=2, on_event=events.append)
    kinds = [e["event"] for e in events]
    assert kinds[0] == "squad_start"
    assert kinds[-1] == "squad_done"
    assert kinds.count("job_done") == 2
    done = next(e for e in events if e["event"] == "squad_done")
    assert done["n_ok"] == 2


def test_make_jsonl_sink_writes_one_line_per_event(tmp_path):
    out = tmp_path / "events.jsonl"
    sink = make_jsonl_sink(out)
    run_squad([_job("j0"), _job("j1")], workers=2, on_event=sink)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(l) for l in lines]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "squad_start" and kinds[-1] == "squad_done"
    assert kinds.count("job_done") == 2
    assert all("ts" in e for e in events)  # sink carimba timestamp — run_squad não emite isso


def test_make_jsonl_sink_creates_parent_dirs(tmp_path):
    out = tmp_path / "nested" / "dir" / "events.jsonl"
    sink = make_jsonl_sink(out)
    sink({"event": "squad_start", "workers": 1, "budget_usd": None})
    assert out.exists()


def test_make_jsonl_sink_never_raises_on_unwritable_path():
    sink = make_jsonl_sink("Z:\\caminho\\que\\nao\\existe\\events.jsonl")
    sink({"event": "squad_start"})  # não deve levantar (best-effort, mesmo contrato do on_event)


def test_telemetry_sink_that_raises_never_crashes_squad():
    def bad_sink(_ev):
        raise RuntimeError("sink quebrado")

    rep = run_squad([_job("j0")], on_event=bad_sink)
    assert rep.n_ok == 1  # sink que levanta é ignorado (best-effort)


def test_cost_from_openrouter_usage_explicit_cost_wins():
    assert cost_from_openrouter_usage({"cost": 0.0123}, 1.0, 2.0) == 0.0123


def test_cost_from_openrouter_usage_from_tokens():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}
    # 1M in * $0.30 + 0.5M out * $0.90 = 0.30 + 0.45 = 0.75
    assert round(cost_from_openrouter_usage(usage, 0.30, 0.90), 6) == 0.75


def test_cost_from_openrouter_usage_robust_to_missing():
    assert cost_from_openrouter_usage(None, 1.0, 2.0) == 0.0
    assert cost_from_openrouter_usage({}, 1.0, 2.0) == 0.0


def test_estimate_cost():
    # 5 calls, 2000 in + 200 out, $0.30/$0.90:
    # per = 2000/1e6*0.3 + 200/1e6*0.9 = 0.0006 + 0.00018 = 0.00078
    assert estimate_cost(5, 2000, 200, 0.30, 0.90) == round(5 * 0.00078, 6)


def test_make_openrouter_text_job_mocked(monkeypatch):
    from super_squad import openrouter

    def fake_raw(messages, **kw):
        assert kw["model"] == "z-ai/glm-4.6v"
        return {"choices": [{"message": {"content": "veredito GOOD"}}],
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}}

    monkeypatch.setattr(openrouter, "openrouter_messages_raw", fake_raw)

    job = make_openrouter_text_job("cand1", "julga isso", "z-ai/glm-4.6v", 0.30, 0.90)
    value, cost = job.run()
    assert value == {"model": "z-ai/glm-4.6v", "text": "veredito GOOD"}
    assert round(cost, 6) == 0.30  # 1M tokens de entrada * $0.30/Mtok
    assert job.model == "z-ai/glm-4.6v"


def test_squad_end_to_end_with_mocked_openrouter(monkeypatch):
    from super_squad import openrouter

    def fake_raw(messages, **kw):
        return {"choices": [{"message": {"content": f"ok:{kw['model']}"}}],
                "usage": {"cost": 0.002}}

    monkeypatch.setattr(openrouter, "openrouter_messages_raw", fake_raw)

    models = ["z-ai/glm-4.6v", "google/gemini-3.1-flash-lite", "qwen/qwen3-vl-32b-instruct"]
    jobs = [make_openrouter_text_job(f"cand-{m}", "julga", m, 0.3, 0.9) for m in models]
    rep = run_squad(jobs, workers=3, budget_usd=1.0)
    assert rep.n_ok == 3
    assert round(rep.total_cost_usd, 6) == 0.006  # 3 * $0.002
    assert all(r.value["text"].startswith("ok:") for r in rep.results if r.ok)


# ── make_openrouter_vision_job (peer de texto, custo via usage) ────────────

def test_make_openrouter_vision_job_mocked(monkeypatch):
    from super_squad import openrouter

    def fake_raw(prompt, images, **kw):
        assert kw["model"] == "google/gemini-3.1-flash-lite"
        assert images == ["data:image/jpeg;base64,SRC", "data:image/jpeg;base64,REV"]
        return {"choices": [{"message": {"content": "GOOD - fiel"}}],
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}}

    monkeypatch.setattr(openrouter, "openrouter_chat_vision_raw", fake_raw)

    job = make_openrouter_vision_job(
        "panel-gemini", "julga o par", ["data:image/jpeg;base64,SRC", "data:image/jpeg;base64,REV"],
        "google/gemini-3.1-flash-lite", 0.25, 1.50,
    )
    value, cost = job.run()
    assert value == {"model": "google/gemini-3.1-flash-lite", "text": "GOOD - fiel"}
    assert round(cost, 6) == 0.25  # 1M tokens de entrada * $0.25/Mtok
    assert job.model == "google/gemini-3.1-flash-lite"


# ── parse_verdict_keyword (genérico, extraído do padrão de vlm_adapter) ────

def test_parse_verdict_keyword_basico():
    assert parse_verdict_keyword("GOOD - reproduz bem") == "GOOD"
    assert parse_verdict_keyword("esta OK no geral") == "OK"
    assert parse_verdict_keyword("BAD - texto diferente") == "BAD"
    assert parse_verdict_keyword("nenhuma palavra-chave") == "BAD"  # default conservador


def test_parse_verdict_keyword_adversarial():
    assert parse_verdict_keyword("BAD, this is not good") == "BAD"  # primeira posição
    assert parse_verdict_keyword("this LOOKS fine actually") == "BAD"  # 'LOOKS' não casa 'OK'
    assert parse_verdict_keyword("OK mostly, not BAD") == "OK"


# ── aggregate_panel_verdicts (voto majoritário/consenso; puro, sem rede) ───

def _panel_result(model: str, text: str, *, ok: bool = True, error=None) -> JobResult:
    value = {"model": model, "text": text} if ok else None
    return JobResult(key=model, model=model, ok=ok, value=value, cost_usd=0.0, latency_ms=1, error=error)


def test_aggregate_panel_majority_wins():
    results = [_panel_result("a", "GOOD - ok"), _panel_result("b", "GOOD"), _panel_result("c", "BAD")]
    out = aggregate_panel_verdicts(results)
    assert out["verdict"] == "GOOD"
    assert out["n_valid"] == 3
    assert out["consensus"] == round(2 / 3, 4)
    assert len(out["panel"]) == 3


def test_aggregate_panel_tie_breaks_conservative():
    # 1x GOOD, 1x BAD -> empate -> BAD vence (mais conservador)
    results = [_panel_result("a", "GOOD"), _panel_result("b", "BAD")]
    out = aggregate_panel_verdicts(results)
    assert out["verdict"] == "BAD"
    assert out["consensus"] == 0.5


def test_aggregate_panel_errors_excluded_from_vote_but_listed():
    results = [_panel_result("a", "GOOD"), _panel_result("b", "", ok=False, error="timeout")]
    out = aggregate_panel_verdicts(results)
    assert out["verdict"] == "GOOD"
    assert out["n_valid"] == 1
    assert out["consensus"] == 1.0
    errored = next(p for p in out["panel"] if p["model"] == "b")
    assert errored["ok"] is False and errored["verdict"] is None and errored["error"] == "timeout"


def test_aggregate_panel_all_failed_is_fail_closed():
    results = [_panel_result("a", "", ok=False, error="boom"), _panel_result("b", "", ok=False, error="boom")]
    out = aggregate_panel_verdicts(results)
    assert out["verdict"] == "BAD"
    assert out["n_valid"] == 0
    assert out["consensus"] == 0.0


# ── aggregate_panel_verdicts com weights (achado 2026-07-04: 2 votos cegos vencendo 1 correto) ──

def test_aggregate_panel_weighted_ties_instead_of_losing():
    """2 modelos peso-1 dizem GOOD (cegos), 1 modelo peso-2 diz OK (correto) -> empate 2-2 ->
    tie-break conservador escolhe OK. Sem peso, GOOD venceria 2-1 (achado real do painel)."""
    results = [_panel_result("blind1", "GOOD"), _panel_result("blind2", "GOOD"), _panel_result("sharp", "OK")]
    out = aggregate_panel_verdicts(results, weights={"sharp": 2.0})
    assert out["verdict"] == "OK"
    assert out["consensus"] == 0.5  # 2/4 (peso total)


def test_aggregate_panel_weighted_still_loses_to_unanimous_more_conservative():
    """O peso maior NÃO é veto unilateral: se os outros 2 concordam em algo MAIS conservador,
    o empate favorece o mais cauteloso de qualquer lado (nunca reduz cautela)."""
    results = [_panel_result("blind1", "BAD"), _panel_result("blind2", "BAD"), _panel_result("sharp", "GOOD")]
    out = aggregate_panel_verdicts(results, weights={"sharp": 2.0})
    assert out["verdict"] == "BAD"  # 2 (BAD) vs 2 (GOOD peso-2) -> empate -> BAD mais conservador


def test_aggregate_panel_weighted_wins_outright_with_one_ally():
    """Peso 2 + 1 aliado peso-1 vence outright (3 vs 1), não precisa de tie-break."""
    results = [_panel_result("sharp", "OK"), _panel_result("ally", "OK"), _panel_result("blind", "GOOD")]
    out = aggregate_panel_verdicts(results, weights={"sharp": 2.0})
    assert out["verdict"] == "OK"
    assert out["consensus"] == round(3 / 4, 4)


def test_aggregate_panel_no_weights_is_byte_identical_to_before():
    """weights=None (default) preserva o comportamento anterior -- nenhuma regressão."""
    results = [_panel_result("a", "GOOD - ok"), _panel_result("b", "GOOD"), _panel_result("c", "BAD")]
    out = aggregate_panel_verdicts(results)
    assert out["verdict"] == "GOOD" and out["consensus"] == round(2 / 3, 4)
