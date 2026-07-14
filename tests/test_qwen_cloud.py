"""Testes da fachada Qwen Cloud (Alibaba Cloud Model Studio / DashScope) e do job de squad.

Sem rede e sem chave real — urlopen mockado, DASHSCOPE_API_KEY fake. O que está sendo fixado:
a fachada NÃO tem HTTP próprio (delega ao chokepoint com provider=QWEN_CLOUD), o request sai
pro endpoint DashScope com o slug qwen certo, os headers de atribuição do OpenRouter NÃO vão
junto, e um roster inteiro roda no Qwen Cloud via `make_qwen_text_job`.
"""
from __future__ import annotations

import io
import json

import pytest

from super_squad import openrouter as o
from super_squad import providers as p
from super_squad import qwen_cloud as q
from super_squad.squad import make_qwen_text_job, make_text_job, run_squad

FAKE_KEY = "sk-dashscope-fake-NUNCA-VAZA-0123456789"


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def http(monkeypatch):
    """Mocka urlopen; devolve a lista de requests capturadas (url, headers, body decodificado)."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", FAKE_KEY)
    monkeypatch.delenv("AI_SQUAD_PROVIDER", raising=False)
    seen: list = []

    def fake_urlopen(req, timeout=None):
        seen.append({"url": req.full_url,
                     "headers": dict(req.headers),
                     "body": json.loads(req.data.decode("utf-8"))})
        return _FakeResp(json.dumps({
            "choices": [{"message": {"content": "POS"}}],
            "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0},
        }).encode("utf-8"))

    monkeypatch.setattr(o.urllib.request, "urlopen", fake_urlopen)
    return seen


# ── fachada nomeada ─────────────────────────────────────────────────────────

def test_qwen_chat_bate_no_dashscope_com_o_slug_do_tier(http):
    out = q.qwen_chat("Classifique: adorei o produto", tier="flash", temperature=0.0)
    assert out == "POS"
    req = http[0]
    assert req["url"] == f"{p.QWEN_CLOUD.base_url}/chat/completions"
    assert "dashscope-intl.aliyuncs.com" in req["url"]
    assert req["body"]["model"] == "qwen-plus"          # tier flash do Qwen Cloud
    assert req["body"]["messages"] == [{"role": "user", "content": "Classifique: adorei o produto"}]


def test_qwen_chat_tier_pro_e_slug_cru(http):
    q.qwen_chat("oi", tier="pro")
    assert http[0]["body"]["model"] == "qwen-max"
    q.qwen_chat("oi", model="qwen3-max")               # slug cru vence o tier
    assert http[1]["body"]["model"] == "qwen3-max"


def test_qwen_messages_multi_turn_com_system(http):
    out = q.qwen_messages(
        [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
         {"role": "user", "content": "c"}],
        system="voce e um classificador", model="qwen-plus",
    )
    assert out == "POS"
    msgs = http[0]["body"]["messages"]
    assert msgs[0] == {"role": "system", "content": "voce e um classificador"}
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]


def test_qwen_messages_raw_devolve_usage_pra_custear(http):
    data = q.qwen_messages_raw([{"role": "user", "content": "a"}], model="qwen-plus")
    assert data["usage"]["prompt_tokens"] == 1_000_000  # cru: o motor de custo precisa disso


def test_sem_headers_de_atribuicao_do_openrouter(http, monkeypatch):
    # Mesmo com as envs de atribuição setadas, elas são do OpenRouter — não vão pro DashScope.
    monkeypatch.setenv("OPENROUTER_APP_URL", "https://frameoracle.com")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "Super Squad")
    q.qwen_chat("oi", model="qwen-plus")
    headers = {k.lower(): v for k, v in http[0]["headers"].items()}
    assert "http-referer" not in headers
    assert "x-title" not in headers
    assert headers["authorization"] == f"Bearer {FAKE_KEY}"  # a chave vai SÓ no header


def test_fachada_usa_a_chave_do_dashscope_e_nao_a_do_openrouter(monkeypatch, http):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key-que-nao-deve-ser-usada")
    q.qwen_chat("oi", model="qwen-plus")
    assert http[0]["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"


def test_erro_sem_chave_nomeia_qwen_cloud_e_dashscope(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(o.OpenRouterError) as exc:
        q.qwen_chat("oi", model="qwen-plus")
    msg = str(exc.value)
    assert "qwen_cloud" in msg and "DASHSCOPE_API_KEY" in msg


def test_erro_http_do_qwen_nao_vaza_a_chave(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", FAKE_KEY)
    monkeypatch.setattr(o, "_MAX_ATTEMPTS", 1)

    def fake_urlopen(req, timeout=None):
        raise o.urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(o.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(o.OpenRouterError) as exc:
        q.qwen_chat("oi", model="qwen-plus")
    msg = str(exc.value)
    assert msg.startswith("qwen_cloud HTTP 401")
    assert FAKE_KEY not in msg


# ── squad rodando no Qwen Cloud (o caminho da demo) ─────────────────────────

def test_make_qwen_text_job_custeia_e_bate_no_dashscope(http):
    job = make_qwen_text_job("cand1", "julga isso", "qwen-plus", 0.30, 0.90)
    value, cost = job.run()
    assert value == {"model": "qwen-plus", "text": "POS"}
    assert round(cost, 6) == 0.30                       # 1M tokens de entrada * $0.30/Mtok
    assert http[0]["url"] == f"{p.QWEN_CLOUD.base_url}/chat/completions"


def test_roster_inteiro_no_qwen_cloud_via_run_squad(http):
    slugs = ["qwen-plus", "qwen-max", "qwen3-max"]
    jobs = [make_text_job(f"cand-{s}", "julga", s, 0.3, 0.9, provider=p.QWEN_CLOUD) for s in slugs]
    rep = run_squad(jobs, workers=3, budget_usd=1.0)
    assert rep.n_ok == 3
    assert {r["url"] for r in http} == {f"{p.QWEN_CLOUD.base_url}/chat/completions"}
    assert sorted(r["body"]["model"] for r in http) == sorted(slugs)


def test_make_text_job_default_continua_no_openrouter(monkeypatch, http):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    job = make_text_job("cand1", "julga", "google/gemini-2.5-flash", 0.3, 0.9)  # provider=None
    job.run()
    assert http[0]["url"] == f"{p.OPENROUTER.base_url}/chat/completions"
