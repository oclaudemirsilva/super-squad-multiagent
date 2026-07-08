"""Testes do teto de gasto global (super_squad/spend_ledger.py) — herméticos, SEM rede, ledger em tmp.

Cobre: registro append-only, soma por janela (dia/mês) com `now` injetado, teto bloqueante,
robustez a linha corrompida, e a escada de alerta 50/75/90/100.

Roda da raiz do repo:
    python -m pytest tests/test_spend_ledger.py -q
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from super_squad import spend_ledger
from super_squad.spend_ledger import (
    alert_level,
    check_budget,
    record_spend,
    window_spend,
)


def _ts(y, m, d, h=12) -> float:
    return datetime(y, m, d, h, tzinfo=timezone.utc).timestamp()


def test_ledger_ausente_soma_zero(tmp_path):
    assert window_spend(tmp_path / "nao_existe.jsonl", window="day") == 0.0


def test_record_e_soma_do_dia(tmp_path):
    led = tmp_path / "led.jsonl"
    record_spend(led, 0.10, workflow="batch_judge", ts=_ts(2026, 7, 4, 9))
    record_spend(led, 0.25, workflow="batch_judge", ts=_ts(2026, 7, 4, 15))
    record_spend(led, 1.00, workflow="batch_judge", ts=_ts(2026, 7, 5, 9))  # outro dia
    assert window_spend(led, window="day", now=_ts(2026, 7, 4, 23)) == pytest.approx(0.35)
    assert window_spend(led, window="day", now=_ts(2026, 7, 5, 1)) == pytest.approx(1.00)


def test_soma_do_mes_agrega_dias(tmp_path):
    led = tmp_path / "led.jsonl"
    record_spend(led, 0.10, ts=_ts(2026, 7, 4))
    record_spend(led, 0.25, ts=_ts(2026, 7, 20))
    record_spend(led, 5.00, ts=_ts(2026, 8, 1))  # outro mês
    assert window_spend(led, window="month", now=_ts(2026, 7, 15)) == pytest.approx(0.35)


def test_check_budget_bloqueia_quando_estoura(tmp_path):
    led = tmp_path / "led.jsonl"
    record_spend(led, 2.00, ts=_ts(2026, 7, 4, 10))
    st = check_budget(led, ceiling_usd=2.00, window="day", now=_ts(2026, 7, 4, 20))
    assert st["blocked"] is True
    assert st["remaining"] == 0.0
    assert st["pct"] == pytest.approx(100.0)


def test_check_budget_permite_com_restante(tmp_path):
    led = tmp_path / "led.jsonl"
    record_spend(led, 0.50, ts=_ts(2026, 7, 4, 10))
    st = check_budget(led, ceiling_usd=2.00, window="day", now=_ts(2026, 7, 4, 20))
    assert st["blocked"] is False
    assert st["remaining"] == pytest.approx(1.50)
    assert st["pct"] == pytest.approx(25.0)


def test_ceiling_zero_bloqueia():
    st = check_budget("qualquer.jsonl", ceiling_usd=0.0, window="day")
    assert st["blocked"] is True


def test_linha_corrompida_nao_derruba_leitura(tmp_path):
    led = tmp_path / "led.jsonl"
    record_spend(led, 0.30, ts=_ts(2026, 7, 4, 10))
    with led.open("a", encoding="utf-8") as fh:
        fh.write("{lixo não-json\n")            # linha corrompida
        fh.write('{"amount_usd": 0.2}\n')        # sem ts -> pulada
    assert window_spend(led, window="day", now=_ts(2026, 7, 4, 20)) == pytest.approx(0.30)


def test_escada_de_alerta():
    assert alert_level(10.0) is None
    assert alert_level(50.0) == 50
    assert alert_level(74.9) == 50
    assert alert_level(75.0) == 75
    assert alert_level(92.0) == 90
    assert alert_level(100.0) == 100
    assert alert_level(150.0) == 100


def test_janela_desconhecida_levanta():
    with pytest.raises(ValueError):
        spend_ledger._window_key(_ts(2026, 7, 4), "semana")
