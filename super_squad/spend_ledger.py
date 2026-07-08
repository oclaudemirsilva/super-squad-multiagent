"""spend_ledger.py — teto de gasto GLOBAL persistente do Super Squad (guarda B5).

O `run_squad` já tem teto de custo POR-RODADA + a chave OpenRouter capada (o cinto duro). Mas
"disparar e sair por horas / vários lotes" pode ACUMULAR gasto sem um teto por JANELA (dia/mês) que
o próprio sistema respeite. Este ledger é a fonte de verdade única desse acumulado: cada rodada que
gasta $ registra 1 linha; o gate de disparo soma a janela corrente e recusa começar se o teto já
estourou (fail-closed), além de emitir a escada de alerta 50/75/90/100%.

Append-only (sobrevive a crash, mesmo espírito do `make_jsonl_sink`). PURO onde dá: `alert_level`
e `check_budget` não fazem I/O além de ler o ledger. Janela em UTC (determinístico; testes injetam
`now`). Módulo FOLHA — zero dependência externa; qualquer workflow do squad pode usar.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Degraus de alerta (% do teto). O gate loga o MAIOR degrau cruzado a cada disparo.
_ALERT_RUNGS = (50, 75, 90, 100)


def _window_key(ts: float, window: str) -> str:
    """Chave da janela em UTC. `day` -> 'YYYY-MM-DD'; `month` -> 'YYYY-MM'."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if window == "day":
        return dt.strftime("%Y-%m-%d")
    if window == "month":
        return dt.strftime("%Y-%m")
    raise ValueError(f"window desconhecida: {window!r} (use 'day' ou 'month')")


def record_spend(path: "str | Path", amount_usd: float, *,
                 workflow: Optional[str] = None, ts: Optional[float] = None) -> None:
    """Append-only: 1 linha JSONL `{ts, amount_usd, workflow}`. Best-effort de durabilidade
    (flush imediato). NÃO deduplica — é um registro de gasto, cada rodada gera o seu."""
    entry = {"ts": time.time() if ts is None else ts,
             "amount_usd": float(amount_usd), "workflow": workflow}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        fh.flush()


def window_spend(path: "str | Path", *, window: str = "day", now: Optional[float] = None) -> float:
    """Soma `amount_usd` das linhas cuja `ts` cai na janela (dia/mês) de `now`. Ledger ausente
    -> 0.0. Linha corrompida é PULADA (nunca derruba a leitura do teto — o gate precisa ser
    robusto pra rodar sem supervisão)."""
    p = Path(path)
    if not p.exists():
        return 0.0
    now = time.time() if now is None else now
    target = _window_key(now, window)
    total = 0.0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if _window_key(float(entry["ts"]), window) == target:
                total += float(entry.get("amount_usd", 0.0))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return round(total, 6)


def check_budget(path: "str | Path", ceiling_usd: float, *,
                 window: str = "day", now: Optional[float] = None) -> dict:
    """`{spent, ceiling, remaining, blocked, pct, window}`. `blocked=True` quando o gasto da
    janela já bateu/passou o teto (fail-closed a jusante). `ceiling<=0` -> blocked (teto zero =
    não dispara nada, semântica igual ao budget=0 do run_squad)."""
    spent = window_spend(path, window=window, now=now)
    if ceiling_usd <= 0:
        return {"spent": spent, "ceiling": ceiling_usd, "remaining": 0.0,
                "blocked": True, "pct": 100.0, "window": window}
    remaining = max(0.0, ceiling_usd - spent)
    pct = spent / ceiling_usd * 100.0
    return {"spent": spent, "ceiling": ceiling_usd, "remaining": round(remaining, 6),
            "blocked": spent >= ceiling_usd, "pct": round(pct, 2), "window": window}


def alert_level(pct: float) -> Optional[int]:
    """Maior degrau da escada (50/75/90/100) que `pct` já cruzou; None se abaixo de 50%."""
    crossed = [r for r in _ALERT_RUNGS if pct >= r]
    return max(crossed) if crossed else None
