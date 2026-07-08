"""test_role_shadow.py - testes hermeticos do motor de shadow-audit por papel. 100% offline:
RoleAuditSpec fake inline, checkpoint em tmp_path, sem rede. Portado do repo de origem do motor
(mesma bateria; so os testes do MOTOR - specs de dominio ficaram la).
Roda: pytest tests/test_role_shadow.py
"""
from __future__ import annotations

import json
from pathlib import Path  # noqa: F401 - specs fake usam Path em varios testes

from super_squad import role_shadow as RSA


def test_roda_e_grava_checkpoint_com_schema(tmp_path):
    """Spec fake com 3 itens, agente discorda no terceiro."""
    def items_fn():
        return [{"key": f"k{i}", "x": i} for i in range(3)]

    def deterministic_fn(item):
        return {"label": "A", "abstain": False}

    def make_agent_fn(budget_usd):
        def agent(item):
            return {"label": "A" if item["x"] < 2 else "B", "cost_usd": 0.001}
        return agent

    spec = RSA.RoleAuditSpec(
        role="test_role",
        items_fn=items_fn,
        deterministic_fn=deterministic_fn,
        make_agent_fn=make_agent_fn,
        gold_fn=None
    )

    checkpoint = tmp_path / "cp.jsonl"
    summary = RSA.run_role_audit(spec, checkpoint, budget_usd=1.0)

    assert summary["n_new"] == 3
    assert summary["n_agree"] == 2
    assert summary["n_disagree"] == 1
    assert summary["agreement_rate"] == round(2/3, 4)
    assert summary["spent_usd"] == 0.003

    lines = checkpoint.read_text().strip().splitlines()
    assert len(lines) == 3
    for line in lines:
        row = json.loads(line)
        assert row["schema"] == "role_shadow_audit/1"
        assert row["role"] == "test_role"
        assert "key" in row
        assert "agree" in row
        assert "cost_usd" in row
        assert "ts" in row


def test_idempotente_segunda_rodada_zero(tmp_path):
    """Rodar duas vezes no mesmo checkpoint processa zero itens na segunda."""
    def items_fn():
        return [{"key": "k0"}, {"key": "k1"}]

    def deterministic_fn(item):
        return {"label": "A", "abstain": False}

    def make_agent_fn(budget_usd):
        def agent(item):
            return {"label": "A", "cost_usd": 0.001}
        return agent

    spec = RSA.RoleAuditSpec(
        role="test_role",
        items_fn=items_fn,
        deterministic_fn=deterministic_fn,
        make_agent_fn=make_agent_fn
    )

    checkpoint = tmp_path / "cp.jsonl"
    RSA.run_role_audit(spec, checkpoint, budget_usd=1.0)
    summary2 = RSA.run_role_audit(spec, checkpoint, budget_usd=1.0)

    assert summary2["n_new"] == 0
    assert summary2["spent_usd"] == 0.0
    lines = checkpoint.read_text().strip().splitlines()
    assert len(lines) == 2


def test_legacy_checkpoint_dedupa(tmp_path):
    """Legacy checkpoint deduplica k0 e k1, só processa k2."""
    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text(
        "\n".join(json.dumps({"key": k, "schema": "role_shadow_audit/1"}) for k in ("k0", "k1")) + "\n",
        encoding="utf-8"
    )

    def items_fn():
        return [{"key": f"k{i}"} for i in range(3)]

    def deterministic_fn(item):
        return {"label": "A", "abstain": False}

    def make_agent_fn(budget_usd):
        def agent(item):
            return {"label": "A", "cost_usd": 0.001}
        return agent

    spec = RSA.RoleAuditSpec(
        role="test_role",
        items_fn=items_fn,
        deterministic_fn=deterministic_fn,
        make_agent_fn=make_agent_fn
    )

    checkpoint = tmp_path / "cp.jsonl"
    summary = RSA.run_role_audit(
        spec, checkpoint, budget_usd=1.0,
        legacy_checkpoints=(legacy,)
    )

    assert summary["n_new"] == 1
    lines = checkpoint.read_text().strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["key"] == "k2"


def test_gold_acuracia_dos_dois_lados(tmp_path):
    """Gold humano: k0=A, k1=B. Determinístico sempre A, agente sempre A."""
    def items_fn():
        return [{"key": "k0"}, {"key": "k1"}, {"key": "k2"}]

    def deterministic_fn(item):
        return {"label": "A", "abstain": False}

    def make_agent_fn(budget_usd):
        def agent(item):
            return {"label": "A", "cost_usd": 0.001}
        return agent

    def gold_fn():
        return {"k0": "A", "k1": "B"}

    spec = RSA.RoleAuditSpec(
        role="test_role",
        items_fn=items_fn,
        deterministic_fn=deterministic_fn,
        make_agent_fn=make_agent_fn,
        gold_fn=gold_fn
    )

    checkpoint = tmp_path / "cp.jsonl"
    summary = RSA.run_role_audit(spec, checkpoint, budget_usd=1.0)

    assert summary["n_gold"] == 2
    assert summary["det_gold_acc"] == 0.5
    assert summary["agent_gold_acc"] == 0.5

    lines = checkpoint.read_text().strip().splitlines()
    rows = [json.loads(l) for l in lines]
    row_k0 = next(r for r in rows if r["key"] == "k0")
    assert row_k0["gold"] == "A"
    assert row_k0["det_correct"] is True
    assert row_k0["agent_correct"] is True

    row_k1 = next(r for r in rows if r["key"] == "k1")
    assert row_k1["gold"] == "B"
    assert row_k1["det_correct"] is False
    assert row_k1["agent_correct"] is False

    row_k2 = next(r for r in rows if r["key"] == "k2")
    assert row_k2["gold"] is None
    assert row_k2["det_correct"] is None
    assert row_k2["agent_correct"] is None


def test_agente_levanta_conta_erro_e_segue(tmp_path):
    """Agente levanta RuntimeError em todos os itens: n_error conta, rodada continua."""
    def items_fn():
        return [{"key": f"k{i}"} for i in range(3)]

    def deterministic_fn(item):
        return {"label": "A", "abstain": False}

    def make_agent_fn(budget_usd):
        def agent(item):
            raise RuntimeError("simulado")
        return agent

    spec = RSA.RoleAuditSpec(
        role="test_role",
        items_fn=items_fn,
        deterministic_fn=deterministic_fn,
        make_agent_fn=make_agent_fn
    )

    checkpoint = tmp_path / "cp.jsonl"
    summary = RSA.run_role_audit(spec, checkpoint, budget_usd=1.0)

    assert summary["n_error"] == 3
    assert summary["n_new"] == 3
    assert summary["spent_usd"] == 0.0

    lines = checkpoint.read_text().strip().splitlines()
    for line in lines:
        row = json.loads(line)
        assert row["agree"] is None
        assert "error" in row["agent"]


def test_agente_devolve_none_conta_no_answer(tmp_path):
    """Agente devolve None -> n_no_answer conta."""
    def items_fn():
        return [{"key": f"k{i}"} for i in range(3)]

    def deterministic_fn(item):
        return {"label": "A", "abstain": False}

    def make_agent_fn(budget_usd):
        def agent(item):
            return None
        return agent

    spec = RSA.RoleAuditSpec(
        role="test_role",
        items_fn=items_fn,
        deterministic_fn=deterministic_fn,
        make_agent_fn=make_agent_fn
    )

    checkpoint = tmp_path / "cp.jsonl"
    summary = RSA.run_role_audit(spec, checkpoint, budget_usd=1.0)

    assert summary["n_no_answer"] == 3
    assert summary["n_new"] == 3
    assert summary["spent_usd"] == 0.0

    lines = checkpoint.read_text().strip().splitlines()
    for line in lines:
        row = json.loads(line)
        assert row["agree"] is None
        assert row["agent"] is None  # sem-resposta limpa (teto/painel cego) = null, NAO erro


def test_deterministico_abstem_agree_none(tmp_path):
    """Determinístico abstém -> agree None, agente ainda roda."""
    def items_fn():
        return [{"key": f"k{i}"} for i in range(3)]

    def deterministic_fn(item):
        return {"label": None, "abstain": True}

    def make_agent_fn(budget_usd):
        def agent(item):
            return {"label": "A", "cost_usd": 0.001}
        return agent

    spec = RSA.RoleAuditSpec(
        role="test_role",
        items_fn=items_fn,
        deterministic_fn=deterministic_fn,
        make_agent_fn=make_agent_fn
    )

    checkpoint = tmp_path / "cp.jsonl"
    summary = RSA.run_role_audit(spec, checkpoint, budget_usd=1.0)

    assert summary["n_new"] == 3
    assert summary["spent_usd"] == 0.003

    lines = checkpoint.read_text().strip().splitlines()
    for line in lines:
        row = json.loads(line)
        assert row["agree"] is None


def test_limit_para_no_n(tmp_path):
    """Limit=2 processa apenas dois itens."""
    def items_fn():
        return [{"key": f"k{i}"} for i in range(5)]

    def deterministic_fn(item):
        return {"label": "A", "abstain": False}

    def make_agent_fn(budget_usd):
        def agent(item):
            return {"label": "A", "cost_usd": 0.001}
        return agent

    spec = RSA.RoleAuditSpec(
        role="test_role",
        items_fn=items_fn,
        deterministic_fn=deterministic_fn,
        make_agent_fn=make_agent_fn
    )

    checkpoint = tmp_path / "cp.jsonl"
    summary = RSA.run_role_audit(spec, checkpoint, budget_usd=1.0, limit=2)

    assert summary["n_new"] == 2
    lines = checkpoint.read_text().strip().splitlines()
    assert len(lines) == 2


def test_key_suffix_rerun_tag(tmp_path):
    """Sufixo de re-rodada permite reprocessar os mesmos itens."""
    def items_fn():
        return [{"key": f"k{i}"} for i in range(3)]

    def deterministic_fn(item):
        return {"label": "A", "abstain": False}

    def make_agent_fn(budget_usd):
        def agent(item):
            return {"label": "A", "cost_usd": 0.001}
        return agent

    spec = RSA.RoleAuditSpec(
        role="test_role",
        items_fn=items_fn,
        deterministic_fn=deterministic_fn,
        make_agent_fn=make_agent_fn
    )

    checkpoint = tmp_path / "cp.jsonl"
    RSA.run_role_audit(spec, checkpoint, budget_usd=1.0, key_suffix="")
    summary2 = RSA.run_role_audit(spec, checkpoint, budget_usd=1.0, key_suffix="::r2")

    assert summary2["n_new"] == 3
    lines = checkpoint.read_text().strip().splitlines()
    assert len(lines) == 6
    for line in lines[3:]:
        row = json.loads(line)
        assert row["key"].endswith("::r2")


def test_deterministico_levanta_fail_soft(tmp_path):
    """Determinístico levanta -> linha registra erro, rodada segue."""
    def items_fn():
        return [{"key": f"k{i}"} for i in range(2)]

    def deterministic_fn(item):
        raise ValueError("simulado")

    def make_agent_fn(budget_usd):
        def agent(item):
            return {"label": "A", "cost_usd": 0.001}
        return agent

    spec = RSA.RoleAuditSpec(
        role="test_role",
        items_fn=items_fn,
        deterministic_fn=deterministic_fn,
        make_agent_fn=make_agent_fn
    )

    checkpoint = tmp_path / "cp.jsonl"
    summary = RSA.run_role_audit(spec, checkpoint, budget_usd=1.0)

    assert summary["n_new"] == 2
    lines = checkpoint.read_text().strip().splitlines()
    for line in lines:
        row = json.loads(line)
        assert row["deterministic"]["label"] is None
        assert row["deterministic"]["abstain"] is True
        assert "error" in row["deterministic"]
        assert row["agree"] is None


def test_gold_acc_do_agente_sem_regua(tmp_path):
    """Papel SEM régua determinística (label None/abstain, ex. font_typography): o agente tem
    denominador PRÓPRIO — bug 07-06: n_gold ficava 0 e agent_gold_acc saía None mesmo com os
    acertos gravados por linha."""
    spec = RSA.RoleAuditSpec(
        role="sem_regua",
        items_fn=lambda: [{"key": "k0"}, {"key": "k1"}],
        deterministic_fn=lambda item: {"label": None, "abstain": True},
        make_agent_fn=lambda b: (lambda item: {"label": "A", "cost_usd": 0.0}),
        gold_fn=lambda: {"k0": "A", "k1": "B"},
    )
    summary = RSA.run_role_audit(spec, tmp_path / "cp.jsonl", budget_usd=1.0)
    assert summary["n_gold"] == 0 and summary["det_gold_acc"] is None
    assert summary["n_gold_agent"] == 2
    assert summary["agent_gold_acc"] == 0.5

