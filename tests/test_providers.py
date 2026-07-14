"""Testes dos providers nomeados (openrouter | qwen_cloud) e do seu efeito no chokepoint.

Sem rede e sem chave real — urlopen mockado, chave fake. Cobre o que NÃO pode regredir:
base_url/env-da-chave por provider, atribuição SÓ no OpenRouter, tier->slug por provider,
override por env, e mensagem de erro que NOMEIA o provider certo SEM vazar a chave.
"""
from __future__ import annotations

import io

import pytest

from super_squad import openrouter as o
from super_squad import providers as p

FAKE_KEY = "sk-fake-NUNCA-VAZA-0123456789"


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(monkeypatch) -> dict:
    """Mocka urlopen e devolve o dict onde a Request capturada é guardada."""
    seen: dict = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.headers)  # urllib normaliza p/ Capitalized-Case
        seen["body"] = req.data
        return _FakeResp(b'{"choices":[{"message":{"content":"ok"}}]}')

    monkeypatch.setattr(o.urllib.request, "urlopen", fake_urlopen)
    return seen


# ── catálogo de providers ───────────────────────────────────────────────────

def test_openrouter_preserva_defaults_de_hoje(monkeypatch):
    # Defaults SEM env (hermético: o ambiente de quem roda não muda o veredito).
    for env in ("OPENROUTER_BASE_URL", "OPENROUTER_MODEL_FLASH", "OPENROUTER_MODEL_PRO"):
        monkeypatch.delenv(env, raising=False)
    prov = p._build_openrouter()
    assert prov.name == "openrouter"
    assert prov.base_url == "https://openrouter.ai/api/v1"
    assert prov.api_key_env == "OPENROUTER_API_KEY"
    assert prov.tiers == {"flash": "google/gemini-2.5-flash", "pro": "google/gemini-2.5-pro"}
    assert prov.attribution is True
    # E o objeto EXPORTADO é esse provider (o que o chokepoint usa quando provider=None).
    assert p.OPENROUTER.name == "openrouter"
    assert p.OPENROUTER.api_key_env == "OPENROUTER_API_KEY"
    assert p.OPENROUTER.attribution is True


def test_qwen_cloud_aponta_pro_dashscope_intl(monkeypatch):
    for env in ("QWEN_CLOUD_BASE_URL", "QWEN_MODEL_FLASH", "QWEN_MODEL_PRO"):
        monkeypatch.delenv(env, raising=False)
    prov = p._build_qwen_cloud()
    assert prov.name == "qwen_cloud"
    assert prov.base_url == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    assert prov.base_url == p.DASHSCOPE_INTL_BASE_URL
    assert prov.api_key_env == "DASHSCOPE_API_KEY"
    assert prov.tiers == {"flash": "qwen-plus", "pro": "qwen-max"}
    assert prov.attribution is False  # HTTP-Referer/X-Title são do OpenRouter
    assert p.QWEN_CLOUD.name == "qwen_cloud"
    assert p.QWEN_CLOUD.api_key_env == "DASHSCOPE_API_KEY"
    assert p.QWEN_CLOUD.attribution is False


def test_get_provider_e_default_provider(monkeypatch):
    assert p.get_provider("qwen_cloud") is p.QWEN_CLOUD
    assert p.get_provider("OpenRouter") is p.OPENROUTER  # case-insensitive
    with pytest.raises(ValueError):
        p.get_provider("nao-existe")

    monkeypatch.delenv("AI_SQUAD_PROVIDER", raising=False)
    assert p.default_provider() is p.OPENROUTER  # compatibilidade: default = openrouter
    monkeypatch.setenv("AI_SQUAD_PROVIDER", "qwen_cloud")
    assert p.default_provider() is p.QWEN_CLOUD


def test_env_override_de_base_e_tiers(monkeypatch):
    monkeypatch.setenv("QWEN_CLOUD_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/")
    monkeypatch.setenv("QWEN_MODEL_FLASH", "qwen-turbo")
    monkeypatch.setenv("QWEN_MODEL_PRO", "qwen3-max")
    prov = p._build_qwen_cloud()
    assert prov.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"  # rstrip('/')
    assert prov.tiers == {"flash": "qwen-turbo", "pro": "qwen3-max"}

    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://localhost:3099/v1")
    monkeypatch.setenv("OPENROUTER_MODEL_FLASH", "deepseek/deepseek-chat")
    assert p._build_openrouter().base_url == "http://localhost:3099/v1"
    assert p._build_openrouter().tiers["flash"] == "deepseek/deepseek-chat"


# ── chokepoint: base_url, chave e headers POR provider ──────────────────────

def test_post_usa_base_url_do_provider(monkeypatch):
    seen = _capture(monkeypatch)
    o._post({"model": "qwen-plus", "messages": []}, FAKE_KEY, 5, p.QWEN_CLOUD)
    assert seen["url"] == f"{p.QWEN_CLOUD.base_url}/chat/completions"
    assert "dashscope-intl.aliyuncs.com/compatible-mode/v1" in seen["url"]

    o._post({"model": "x", "messages": []}, FAKE_KEY, 5)  # provider=None -> OpenRouter
    assert seen["url"] == f"{p.OPENROUTER.base_url}/chat/completions"
    assert seen["url"] == f"{o._BASE}/chat/completions"  # _BASE segue sendo o do OpenRouter


def test_chave_vem_da_env_do_provider(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "ds-key")
    assert o._api_key() == "or-key"                     # default = openrouter
    assert o._api_key(provider=p.OPENROUTER) == "or-key"
    assert o._api_key(provider=p.QWEN_CLOUD) == "ds-key"
    assert o._api_key("injetada", p.QWEN_CLOUD) == "injetada"  # DI vence a env


def test_atribuicao_so_no_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_APP_URL", "https://frameoracle.com")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "Super Squad")

    h_or = o._headers(FAKE_KEY, p.OPENROUTER)
    assert h_or["HTTP-Referer"] == "https://frameoracle.com"
    assert h_or["X-Title"] == "Super Squad"

    h_qwen = o._headers(FAKE_KEY, p.QWEN_CLOUD)
    assert "HTTP-Referer" not in h_qwen and "X-Title" not in h_qwen
    assert h_qwen["Authorization"] == f"Bearer {FAKE_KEY}"  # auth SEMPRE; só no header


def test_tier_resolve_por_provider():
    # provider=None resolve pelos tiers do OpenRouter (e TIERS continua sendo esse mapa).
    assert o._resolve_model("flash", None) == p.OPENROUTER.tiers["flash"] == o.TIERS["flash"]
    assert o._resolve_model("flash", None, p.QWEN_CLOUD) == "qwen-plus"
    assert o._resolve_model("pro", None, p.QWEN_CLOUD) == "qwen-max"
    assert o._resolve_model(None, "qwen3-max", p.QWEN_CLOUD) == "qwen3-max"      # slug cru vence
    with pytest.raises(o.OpenRouterError) as exc:
        o._resolve_model("turbo", None, p.QWEN_CLOUD)
    assert "qwen_cloud" in str(exc.value)


# ── erros: NOMEIAM o provider, NUNCA contêm a chave ─────────────────────────

def test_erro_de_chave_ausente_nomeia_provider_e_env(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(o.OpenRouterError) as exc:
        o._api_key(provider=p.QWEN_CLOUD)
    msg = str(exc.value)
    assert "qwen_cloud" in msg and "DASHSCOPE_API_KEY" in msg
    assert "OPENROUTER_API_KEY" not in msg


def test_erro_http_nomeia_provider_e_nao_vaza_a_chave(monkeypatch):
    monkeypatch.setattr(o, "_MAX_ATTEMPTS", 1)

    def fake_urlopen(req, timeout=None):
        raise o.urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(o.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(o.OpenRouterError) as exc:
        o._post({"model": "qwen-plus", "messages": []}, FAKE_KEY, 5, p.QWEN_CLOUD)
    msg = str(exc.value)
    assert msg.startswith("qwen_cloud HTTP 401")
    assert FAKE_KEY not in msg
