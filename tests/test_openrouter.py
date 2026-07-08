"""Testes do retry do chokepoint OpenRouter (Fase 1). Sem rede — urlopen mockado."""
from __future__ import annotations

import io
import urllib.error

from super_squad import openrouter as o


def test_is_retryable_status():
    for s in (408, 429, 500, 502, 503, 504):
        assert o._is_retryable_status(s), s
    for s in (200, 301, 400, 401, 403, 404, 422):
        assert not o._is_retryable_status(s), s


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_post_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(o, "_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(o, "_backoff_seconds", lambda *a, **k: 0.0)  # sem sleep real
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:  # 1ª tentativa: 429 transitório
            raise urllib.error.HTTPError("u", 429, "rate limited", {}, None)
        return _FakeResp(b'{"choices":[{"message":{"content":"ok"}}]}')

    monkeypatch.setattr(o.urllib.request, "urlopen", fake_urlopen)
    out = o._post({"model": "x", "messages": []}, "key", 5)
    assert out["choices"][0]["message"]["content"] == "ok"
    assert calls["n"] == 2  # re-tentou exatamente uma vez


def test_post_no_retry_on_client_error(monkeypatch):
    monkeypatch.setattr(o, "_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(o, "_backoff_seconds", lambda *a, **k: 0.0)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 400, "bad request", {}, None)

    monkeypatch.setattr(o.urllib.request, "urlopen", fake_urlopen)
    raised = False
    try:
        o._post({"model": "x", "messages": []}, "key", 5)
    except o.OpenRouterError:
        raised = True
    assert raised
    assert calls["n"] == 1  # 400 de cliente NÃO é re-tentado


def test_post_no_retry_on_timeout(monkeypatch):
    monkeypatch.setattr(o, "_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(o, "_backoff_seconds", lambda *a, **k: 0.0)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise TimeoutError("timed out")

    monkeypatch.setattr(o.urllib.request, "urlopen", fake_urlopen)
    raised = False
    try:
        o._post({"model": "x", "messages": []}, "key", 5)
    except o.OpenRouterError:
        raised = True
    assert raised
    assert calls["n"] == 1  # timeout NÃO é re-tentado (custoso)
