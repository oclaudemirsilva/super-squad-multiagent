"""Testes do pré-voo do Super Squad (super_squad/preflight.py) — herméticos, SEM rede, SEM custo.

Cobre: parse do catálogo cru, detecção de slug ausente (bloqueante), drift de preço e data de
expiração (avisos, não bloqueiam), e `assert_roster_live` levantando só quando falta slug.

Roda da raiz do repo:
    python -m pytest tests/test_preflight.py -q
"""
from __future__ import annotations

import pytest

from super_squad import preflight
from super_squad.preflight import (
    PreflightError,
    assert_roster_live,
    parse_model_catalog,
    preflight_roster,
)


# ── catálogo fake no formato REAL do /models (shape confirmado ao vivo 2026-07-04) ───────────
def _fake_catalog(extra: "list[dict] | None" = None) -> dict:
    data = [
        {"id": "z-ai/glm-4.6v", "pricing": {"prompt": "0.0000003", "completion": "0.0000009"}},
        {"id": "google/gemini-3.5-flash", "pricing": {"prompt": "0.0000015", "completion": "0.000009"}},
        {"id": "qwen/qwen3-vl-32b-instruct", "pricing": {"prompt": "0.000000104", "completion": "0.000000416"}},
        {"id": "example/model-x", "pricing": {"prompt": "0.0000003", "completion": "0.0000012"}},
    ]
    if extra:
        data.extend(extra)
    return {"data": data}


def _roster_vision(role: str):
    # espelha registry.SQUAD_ROSTER["vision_judge"] (preços em USD/Mtok)
    assert role == "vision_judge"
    return (
        ("z-ai/glm-4.6v", 0.30, 0.90),
        ("google/gemini-3.5-flash", 1.50, 9.0),
        ("qwen/qwen3-vl-32b-instruct", 0.104, 0.416),
    )


def test_parse_model_catalog_converte_para_mtok():
    cat = parse_model_catalog(_fake_catalog())
    assert cat["z-ai/glm-4.6v"]["price_in_per_mtok"] == pytest.approx(0.30)
    assert cat["z-ai/glm-4.6v"]["price_out_per_mtok"] == pytest.approx(0.90)
    assert cat["google/gemini-3.5-flash"]["expiration_date"] is None


def test_parse_robusto_a_lixo():
    cat = parse_model_catalog({"data": [
        {"id": "sem/preco"},                       # sem pricing
        {"pricing": {"prompt": "1"}},              # sem id -> ignorado
        "nao-é-dict",                              # item estranho -> ignorado
        {"id": "preco/ilegivel", "pricing": {"prompt": "abc", "completion": None}},
    ]})
    assert "sem/preco" in cat and cat["sem/preco"]["price_in_per_mtok"] is None
    assert cat["preco/ilegivel"]["price_in_per_mtok"] is None
    assert len(cat) == 2  # o sem-id não entra


def test_roster_todo_presente_e_ok():
    rep = preflight_roster(["vision_judge"], list_models_fn=_fake_catalog, roster_fn=_roster_vision)
    assert rep["ok"] is True
    assert rep["checked"] == 3
    assert rep["missing"] == []
    assert rep["drifted"] == []
    assert rep["expiring"] == []


def test_slug_ausente_bloqueia():
    def catalog_sem_qwen():
        return {"data": [m for m in _fake_catalog()["data"] if m["id"] != "qwen/qwen3-vl-32b-instruct"]}
    rep = preflight_roster(["vision_judge"], list_models_fn=catalog_sem_qwen, roster_fn=_roster_vision)
    assert rep["ok"] is False
    assert rep["missing"] == [{"role": "vision_judge", "slug": "qwen/qwen3-vl-32b-instruct"}]


def test_assert_levanta_so_quando_falta_slug():
    def catalog_sem_glm():
        return {"data": [m for m in _fake_catalog()["data"] if m["id"] != "z-ai/glm-4.6v"]}
    with pytest.raises(PreflightError) as exc:
        assert_roster_live(["vision_judge"], list_models_fn=catalog_sem_glm, roster_fn=_roster_vision)
    assert "z-ai/glm-4.6v" in str(exc.value)
    # e NÃO levanta quando tudo presente (devolve o relatório):
    rep = assert_roster_live(["vision_judge"], list_models_fn=_fake_catalog, roster_fn=_roster_vision)
    assert rep["ok"] is True


def test_drift_de_preco_e_aviso_nao_bloqueia():
    def catalog_caro():
        # dobra o preço do qwen no catálogo vivo
        data = []
        for m in _fake_catalog()["data"]:
            if m["id"] == "qwen/qwen3-vl-32b-instruct":
                m = {"id": m["id"], "pricing": {"prompt": "0.000000208", "completion": "0.000000832"}}
            data.append(m)
        return {"data": data}
    rep = preflight_roster(["vision_judge"], list_models_fn=catalog_caro, roster_fn=_roster_vision)
    assert rep["ok"] is True  # drift NÃO bloqueia
    assert len(rep["drifted"]) == 1
    assert rep["drifted"][0]["slug"] == "qwen/qwen3-vl-32b-instruct"


def test_expiracao_e_aviso_nao_bloqueia():
    def catalog_expira():
        data = []
        for m in _fake_catalog()["data"]:
            if m["id"] == "google/gemini-3.5-flash":
                m = {**m, "expiration_date": "2026-08-10"}
            data.append(m)
        return {"data": data}
    rep = preflight_roster(["vision_judge"], list_models_fn=catalog_expira, roster_fn=_roster_vision)
    assert rep["ok"] is True
    assert rep["expiring"] == [{"role": "vision_judge", "slug": "google/gemini-3.5-flash",
                                "expiration_date": "2026-08-10"}]


def test_default_usa_registry_real(monkeypatch):
    """Sem roster_fn injetado, cai no registry.squad_roster de verdade — que neste pacote nasce
    VAZIO e lê o roster por env (`AI_SQUAD_ROSTER_<ROLE>`). Catálogo continua mockado (zero rede)."""
    monkeypatch.setenv("AI_SQUAD_ROSTER_VISION_JUDGE", "google/gemini-3.5-flash:0.10:0.40")
    rep = preflight_roster(["vision_judge"], list_models_fn=_fake_catalog)
    assert rep["ok"] is True
    assert rep["checked"] == 1
    # e SEM env nem roster no registry: nada a checar (roster vazio é fail-soft no pré-voo;
    # quem bloqueia painel vazio é o consumidor)
    monkeypatch.delenv("AI_SQUAD_ROSTER_VISION_JUDGE")
    rep2 = preflight_roster(["vision_judge"], list_models_fn=_fake_catalog)
    assert rep2["checked"] == 0
