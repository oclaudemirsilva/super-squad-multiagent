"""test_code_writer.py — testes herméticos do agente `code` (Super Squad).
100% offline: roster/run_squad/make_job injetados por fake.
Roda: pytest tests/test_code_writer.py
"""
from __future__ import annotations

import pytest

from super_squad import code_writer as CW

_ROSTER = lambda role: (("fake/deepseek", 0.1, 0.3),)


def _rep(text, ok=True, cost=0.0004):
    if ok:
        R = type("Rep", (), {"results": [type("JR", (), {"ok": True, "value": {"text": text}})()],
                             "total_cost_usd": cost})
    else:
        R = type("Rep", (), {"results": [type("JR", (), {"ok": False, "error": text})()],
                             "total_cost_usd": 0.0})
    return R()


def test_strip_markdown_fences_remove_cerca_completa():
    assert CW._strip_markdown_fences("```python\nprint('oi')\n```") == "print('oi')"


def test_strip_markdown_fences_sem_cerca_mantem_intacto():
    assert CW._strip_markdown_fences("codigo puro\nsem cerca") == "codigo puro\nsem cerca"


def test_strip_markdown_fences_cerca_no_meio_nao_mexe():
    texto = "explicacao\n```python\nx = 1\n```\nresto"
    assert CW._strip_markdown_fences(texto) == texto


def test_writer_devolve_codigo_sem_cerca():
    rs = lambda jobs, workers=1, budget_usd=0.0: _rep("```python\ndef f():\n    return 1\n```")
    writer = CW.make_squad_code_writer(roster_fn=_ROSTER, run_squad_fn=rs, make_job_fn=lambda **k: k)
    r = writer("escreva uma funcao")
    assert r["code"] == "def f():\n    return 1"
    assert r["cost_usd"] == 0.0004


def test_writer_propaga_system_prompt():
    seen = {}

    def make_job(**k):
        seen.update(k)
        return k

    rs = lambda jobs, workers=1, budget_usd=0.0: _rep("codigo")
    writer = CW.make_squad_code_writer(roster_fn=_ROSTER, run_squad_fn=rs, make_job_fn=make_job)
    writer("spec", system="voce e um engenheiro senior")
    assert seen["system"] == "voce e um engenheiro senior"


def test_chamada_falha_levanta():
    rs = lambda jobs, workers=1, budget_usd=0.0: _rep("timeout", ok=False)
    writer = CW.make_squad_code_writer(roster_fn=_ROSTER, run_squad_fn=rs, make_job_fn=lambda **k: k)
    with pytest.raises(RuntimeError, match="chamada do code writer falhou"):
        writer("spec")


def test_orcamento_esgotado_levanta_sem_chamar_painel():
    called = []

    def rs(jobs, workers=1, budget_usd=0.0):
        called.append(1)
        return _rep("nao devia chegar aqui")

    writer = CW.make_squad_code_writer(roster_fn=_ROSTER, run_squad_fn=rs, make_job_fn=lambda **k: k,
                                       budget_usd=0.0)
    with pytest.raises(RuntimeError, match="orçamento"):
        writer("spec")
    assert called == []


def test_roster_vazio_levanta_na_construcao():
    with pytest.raises(RuntimeError, match="roster VAZIO"):
        CW.make_squad_code_writer(roster_fn=lambda role: ())
