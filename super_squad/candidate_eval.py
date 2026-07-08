"""candidate_eval.py — harness para avaliar um modelo CANDIDATO sem tocar o roster titular.

A pergunta que responde: "este slug novo merece entrar no roster?" — medida papel por papel
contra os SEUS ground-truths, com orçamento e checkpoint idempotente. O harness NUNCA
escreve no roster: a saída é um relatório JSON; a promoção é decisão HUMANA informada por ele.

DIP: os avaliadores são INJETADOS (`evaluators={"papel": eval_fn}`) — este módulo não sabe
nada sobre o domínio das tarefas. Contrato de cada avaliador:
    eval_fn(slug, pin, pout, spent, budget_usd, limit) -> dict
onde `spent` é o dict compartilhado {"total": float} que o avaliador INCREMENTA a cada
chamada paga (o harness corta a sequência quando o total bate o orçamento) e o dict de
retorno descreve o resultado do papel (n, acertos, taxa, gasto, ... — formato livre, mas
inclua `gasto`). Idempotência: use `EvalCheckpoint` num closure para não re-pagar itens.

Uso (CLI de humano — script que gasta $ NUNCA roda em CI):
    run_candidate_eval("provider/slug-novo", 0.10, 0.40,
                       evaluators={"meu_papel": meu_eval_fn}, budget_usd=0.25)
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from .role_shadow import already_checkpointed, append_checkpoint_line

# Relatórios de candidatos são REPRODUTÍVEIS e vale versioná-los (decisão de promoção auditável).
DEFAULT_OUT_DIR = Path("_candidate_evals")


class EvalCheckpoint:
    """Visão por-KEY idempotente sobre um checkpoint JSONL (`done(key)` antes de pagar;
    `add(key, row)` depois). Compartilhável entre avaliadores do mesmo run."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._done = set(already_checkpointed(self.path))

    def done(self, key: str) -> bool:
        return key in self._done

    def add(self, key: str, row: dict) -> None:
        append_checkpoint_line(self.path, {"key": key, **row})
        self._done.add(key)


def sanitize_slug(slug: str) -> str:
    return re.sub(r"[^\w\-]", "_", slug)


def strip_markdown_code(text: str) -> str:
    """Modelos às vezes ignoram 'sem markdown' e cercam a resposta com ```...``` — defesa
    no parser em vez de confiança no prompt."""
    text = text.strip()
    match = re.search(r"```(?:\w+)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    if text.startswith("```") and text.endswith("```"):
        return text[3:-3].strip()
    return text


def data_uri_from_image_path(image_path: Path) -> Optional[str]:
    """PNG data-URI de um arquivo de imagem (p/ jobs de visão). Requer Pillow (opcional)."""
    try:
        import io
        from PIL import Image
        with Image.open(image_path) as img:
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            b64 = base64.b64encode(buffered.getvalue()).decode()
            return f"data:image/png;base64,{b64}"
    except Exception:  # noqa: BLE001 — helper best-effort; avaliador decide o que fazer com None
        return None


def run_candidate_eval(
    slug: str, pin: float, pout: float, *,
    evaluators: "Dict[str, Callable]",
    roles: "Optional[list[str]]" = None,
    budget_usd: float = 0.25, limit: "Optional[int]" = None,
    out_path: "Optional[Path]" = None,
) -> dict:
    """Roda os avaliadores em sequência com orçamento COMPARTILHADO; corta quando esgota.
    Escreve o relatório JSON em `out_path` (default `_candidate_evals/<slug>.json`) e devolve
    o summary. O checkpoint `<out>.ckpt.jsonl` fica ao lado (idempotência entre re-runs)."""
    if out_path is None:
        out_path = DEFAULT_OUT_DIR / f"{sanitize_slug(slug)}.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    roles_to_run = roles if roles is not None else sorted(evaluators)
    spent: dict = {"total": 0.0}
    summary: dict = {
        "slug": slug, "pin": pin, "pout": pout,
        "budget_usd": budget_usd, "limit": limit,
        "roles_executed": roles_to_run, "timestamp": time.time(),
        "budget_exhausted": False, "spent_total_usd": 0.0, "results": {},
    }

    for role in roles_to_run:
        eval_fn = evaluators.get(role)
        if eval_fn is None:
            summary["results"][role] = {"error": f"papel desconhecido: {role!r}"}
            continue
        try:
            result = eval_fn(slug, pin, pout, spent, budget_usd, limit)
        except Exception as exc:  # noqa: BLE001 — um papel quebrado não derruba o relatório
            result = {"error": repr(exc)}
        summary["results"][role] = result
        summary["spent_total_usd"] = round(spent["total"], 6)
        if spent["total"] >= budget_usd:
            summary["budget_exhausted"] = True
            break

    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
