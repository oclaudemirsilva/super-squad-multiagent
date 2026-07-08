"""code_writer.py — papel `code` do Super Squad (geração de código pesado por delegação).

O padrão de operação que este papel viabiliza: o modelo BARATO escreve o rascunho a partir de
uma especificação; um revisor FORTE (humano ou modelo de gate) audita antes de aplicar. Este
módulo NÃO substitui o julgamento no gate: o agente PROPÕE código; quem chama decide se
revisa/edita/aplica. Não roda testes, não commita, não decide arquitetura — só gera texto a
partir de uma especificação.

⚠ Defesa empírica: modelos de código às vezes ignoram a instrução explícita "sem markdown" e
devolvem o código cercado por ```python ... ```. Este módulo defende contra isso
(`_strip_markdown_fences`) em vez de confiar cegamente na instrução do prompt.

Roda: python -m super_squad.code_writer   (auto-demo hermética, sem rede)
"""
from __future__ import annotations

import re
from typing import Callable, Optional

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_+-]*\n(.*)\n```\s*$", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    """Remove UMA cerca de crases envolvendo o texto inteiro (```lang\\n...\\n```), se presente.
    Cerca no MEIO do texto (não envolvendo tudo) é deixada intacta — só o caso comum de o modelo
    ignorar 'sem markdown' e embrulhar a resposta inteira."""
    stripped = text.strip()
    m = _FENCE_RE.match(stripped)
    return m.group(1) if m else stripped


def make_squad_code_writer(
    *, budget_usd: float = 0.10, roster_fn: "Optional[Callable]" = None,
    run_squad_fn: "Optional[Callable]" = None, make_job_fn: "Optional[Callable]" = None,
) -> "Callable[..., dict]":
    """Devolve `writer_fn(spec, *, system=None) -> {"code", "raw", "cost_usd"}`. `spec` é a
    especificação/prompt completo (o chamador monta o contexto — este módulo não sabe nada sobre
    o domínio do código pedido). Levanta RuntimeError se o roster estiver vazio ou a chamada
    falhar (fail-fast por chamada — o CHAMADOR decide fail-soft)."""
    if roster_fn is None:
        from . import registry  # noqa: E402 (lazy)
        roster_fn = registry.squad_roster
    if run_squad_fn is None:
        from .squad import run_squad as run_squad_fn  # noqa: E402 (lazy)
    if make_job_fn is None:
        from .squad import make_openrouter_text_job as make_job_fn  # noqa: E402 (lazy)

    roster = roster_fn("code")
    if not roster:
        raise RuntimeError("papel code com roster VAZIO — preencha registry.SQUAD_ROSTER['code'] "
                           "ou env AI_SQUAD_ROSTER_CODE (ver registry.py)")
    slug, pin, pout = roster[0]
    spent = {"total": 0.0}

    def writer_fn(spec: str, *, system: "str | None" = None) -> dict:
        remaining = max(0.0, budget_usd - spent["total"])
        if remaining <= 0.0:
            raise RuntimeError(f"orçamento do code writer esgotado (budget_usd={budget_usd})")
        job = make_job_fn(key=f"code::{spec[:30]}", prompt=spec, model=slug,
                          price_in_per_mtok=pin, price_out_per_mtok=pout,
                          system=system, temperature=0.1, timeout=180)
        report = run_squad_fn([job], workers=1, budget_usd=remaining)
        spent["total"] += report.total_cost_usd
        r = report.results[0]
        if not r.ok:
            raise RuntimeError(f"chamada do code writer falhou: {r.error}")
        raw = (r.value or {}).get("text", "")
        return {"code": _strip_markdown_fences(raw), "raw": raw, "cost_usd": report.total_cost_usd}

    return writer_fn


def _demo() -> None:
    def roster(role):
        return (("fake/model", 0.1, 0.3),)

    def rs(jobs, workers=1, budget_usd=0.0):
        R = type("Rep", (), {
            "results": [type("JR", (), {"ok": True, "value": {"text": "```python\nprint('oi')\n```"}})()],
            "total_cost_usd": 0.0004})
        return R()

    writer = make_squad_code_writer(roster_fn=roster, run_squad_fn=rs, make_job_fn=lambda **k: k)
    print("codigo gerado ->", repr(writer("escreva um hello world")["code"]))


if __name__ == "__main__":
    _demo()
