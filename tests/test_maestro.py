"""test_maestro.py — testes herméticos do dispatcher do maestro. 100% offline: workflows fake
injetados via monkeypatch, guardas injetadas (preflight_fn/check_budget_fn/record_spend_fn),
zero rede/ledger real. Portado do repo de origem do motor (mesma bateria; só o que era
específico dos workflows de domínio ficou lá).
Roda: pytest tests/test_maestro.py
"""
from __future__ import annotations

import pytest

from super_squad import maestro as SM
from super_squad.preflight import PreflightError


def _spec(name, runner, *, roles=("vision_judge",), budget=0.10, spends=True):
    return SM.WorkflowSpec(name=name, roles=roles, runner=runner,
                           default_budget_usd=budget, description="teste", spends_money=spends)


@pytest.fixture()
def wf(monkeypatch):
    """Injeta um workflow fake no registry (restaura sozinho via monkeypatch)."""
    calls: list = []

    def runner(*, budget_usd, limit=None, event_sink=None, **extra):
        calls.append({"budget_usd": budget_usd, "limit": limit, "extra": extra})
        return {"spent_usd": 0.02, "n_new": 1}

    spec = _spec("_test_wf", runner)
    monkeypatch.setitem(SM.WORKFLOWS, "_test_wf", spec)
    monkeypatch.delenv("AI_SQUAD_DAILY_BUDGET_USD", raising=False)
    return calls


def test_register_duplicado_levanta():
    spec = _spec("_test_dup", lambda **k: {})
    SM.register(spec)
    try:
        with pytest.raises(ValueError, match="duplicado"):
            SM.register(spec)
    finally:
        del SM.WORKFLOWS["_test_dup"]


def test_dispatch_desconhecido_lista_conhecidos(wf):
    out = SM.dispatch("_nao_existe")
    assert out["ok"] is False and out["ran"] is False
    assert "_test_wf" in out["known"]


def test_dry_run_default_nao_roda(wf):
    out = SM.dispatch("_test_wf")
    assert out["ok"] is True and out["ran"] is False
    assert out["plan"]["workflow"] == "_test_wf"
    assert wf == []  # runner NUNCA chamado sem execute=True


def test_execute_roda_e_registra_ledger(wf, tmp_path):
    recorded: list = []
    out = SM.dispatch("_test_wf", execute=True, skip_preflight=True,
                      ledger_path=tmp_path / "ledger.jsonl",
                      record_spend_fn=lambda p, s, workflow: recorded.append((str(p), s, workflow)))
    assert out["ok"] is True and out["ran"] is True
    assert out["result"]["n_new"] == 1
    assert len(wf) == 1 and wf[0]["budget_usd"] == 0.10  # default do spec
    assert recorded == [(str(tmp_path / "ledger.jsonl"), 0.02, "_test_wf")]


def test_preflight_slug_morto_bloqueia_sem_rodar(wf):
    def boom(roles):
        raise PreflightError("slug morto: fake/m1")

    out = SM.dispatch("_test_wf", execute=True, preflight_fn=boom)
    assert out["ok"] is False and out["ran"] is False
    assert "pré-voo" in out["error"] or "pre-voo" in out["error"]
    assert wf == []


def test_preflight_sem_chave_openrouter_bloqueia_workflow_que_gasta(wf, monkeypatch):
    """O catálogo do pré-voo é PÚBLICO, então sem OPENROUTER_API_KEY um workflow que gasta $
    passaria no pré-voo e rodaria fail-soft inteiro com agent=None (custo 0, checkpoint
    poluído). Chave ausente + spends_money=True + caminho REAL do pré-voo (sem preflight_fn
    injetado) = ABORTA antes de importar/rodar qualquer coisa (hermético: retorna antes do
    import lazy)."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = SM.dispatch("_test_wf", execute=True)
    assert out["ok"] is False and out["ran"] is False
    assert "OPENROUTER_API_KEY" in out["error"]
    assert wf == []


def test_preflight_catalogo_inacessivel_segue_com_warning(wf, tmp_path):
    def unreachable(roles):
        raise ConnectionError("sem rede")

    out = SM.dispatch("_test_wf", execute=True, preflight_fn=unreachable,
                      ledger_path=tmp_path / "l.jsonl", record_spend_fn=lambda *a, **k: None)
    assert out["ok"] is True and out["ran"] is True
    assert "warning" in (out["preflight"] or {})
    assert len(wf) == 1


def test_teto_global_esgotado_bloqueia(wf):
    out = SM.dispatch("_test_wf", execute=True, skip_preflight=True,
                      daily_ceiling_usd=1.0,
                      check_budget_fn=lambda p, c: {"blocked": True, "remaining": 0.0})
    assert out["ok"] is False and out["ran"] is False
    assert "esgotado" in out["error"]
    assert wf == []


def test_teto_global_clampa_o_budget(wf, tmp_path):
    out = SM.dispatch("_test_wf", execute=True, skip_preflight=True,
                      daily_ceiling_usd=1.0, budget_usd=0.30,
                      check_budget_fn=lambda p, c: {"blocked": False, "remaining": 0.05},
                      ledger_path=tmp_path / "l.jsonl", record_spend_fn=lambda *a, **k: None)
    assert out["ok"] is True
    assert wf[0]["budget_usd"] == 0.05  # clampado ao restante da janela
    assert out["effective_budget_usd"] == 0.05


def test_spends_money_false_pula_gate_e_ledger(monkeypatch):
    calls: list = []
    gate_calls: list = []

    def runner(*, budget_usd, limit=None, event_sink=None, **extra):
        calls.append(budget_usd)
        return {"spent_usd": 0.0}

    spec = _spec("_test_free", runner, roles=(), spends=False)
    monkeypatch.setitem(SM.WORKFLOWS, "_test_free", spec)
    out = SM.dispatch("_test_free", execute=True, daily_ceiling_usd=1.0,
                      check_budget_fn=lambda p, c: gate_calls.append(1) or {"blocked": True},
                      record_spend_fn=lambda *a, **k: gate_calls.append(2))
    assert out["ok"] is True and out["ran"] is True
    assert gate_calls == []  # nem gate nem ledger tocados
    assert calls == [0.10]


def test_runner_levanta_vira_ok_false(monkeypatch):
    def boom(*, budget_usd, limit=None, event_sink=None, **extra):
        raise RuntimeError("quebrou no meio")

    monkeypatch.setitem(SM.WORKFLOWS, "_test_boom", _spec("_test_boom", boom))
    monkeypatch.delenv("AI_SQUAD_DAILY_BUDGET_USD", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-teste-fake")  # passa o guard; catálogo nem é chamado
    out = SM.dispatch("_test_boom", execute=True, skip_preflight=True)
    assert out["ok"] is False and out["ran"] is True
    assert "quebrou" in out["error"]


def test_extra_kwargs_chegam_ao_runner(wf, tmp_path):
    SM.dispatch("_test_wf", execute=True, skip_preflight=True, limit=7,
                extra={"rerun_tag": "::r2"}, ledger_path=tmp_path / "l.jsonl",
                record_spend_fn=lambda *a, **k: None)
    assert wf[0]["limit"] == 7
    assert wf[0]["extra"] == {"rerun_tag": "::r2"}


def test_plan_puro_sem_efeito(wf):
    p = SM.plan("_test_wf", budget_usd=0.05, limit=3)
    assert p["workflow"] == "_test_wf"
    assert p["roles"] == ["vision_judge"]
    assert p["budget_usd"] == 0.05 and p["limit"] == 3
    assert SM.plan("_nao_existe")["error"].startswith("workflow desconhecido")
