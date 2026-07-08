"""Chokepoint unico das chamadas OpenRouter (OpenAI-compativel) do super_squad.

OpenRouter e um roteador: UMA chave -> muitos modelos (Gemini, Claude, DeepSeek,
GPT...), todos via o mesmo endpoint OpenAI-compativel. E o que torna o painel
CROSS-LAB do squad barato de operar: o slug do modelo vai na REQUISICAO, entao um
roster inteiro (varios provedores) roda com uma unica credencial. stdlib-only
(urllib) de proposito — sem o SDK `openai`, pra manter o pacote importavel em
qualquer ambiente sem adicionar dependencia.

Endpoint: OpenAI-compativel https://openrouter.ai/api/v1/chat/completions.
Modelos: slugs no formato `provider/model` (ex. 'google/gemini-2.5-flash',
'anthropic/claude-3.5-sonnet', 'deepseek/deepseek-chat'). Confira o catalogo vivo em
https://openrouter.ai/models — os slugs mudam; por isso TIERS sao override-por-env.
Tiers canonicos:
    flash -> modelo barato (DEFAULT; volume/iteracao)
    pro   -> modelo forte (raciocinio/visao)

Visao: `openrouter_chat_vision()` usa o formato OpenAI de content multipart
({type:'image_url'}); escolha um modelo multimodal (ex. Gemini/Claude/GPT-4o) via
`model=`/tier ao chamar.

Headers de atribuicao (opcionais, so entram se setados): `OPENROUTER_APP_URL` ->
HTTP-Referer e `OPENROUTER_APP_TITLE` -> X-Title (aparecem nos rankings do OpenRouter).

Chave: SO de env `OPENROUTER_API_KEY`; aceita `api_key=` explicito (DI, p/ quem injeta
de um Settings que leu .env). NUNCA hardcode; NUNCA loga (nem em excecao — corpo de
erro truncado, chave so no header).
"""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request

# Base configuravel por env; o caminho OpenAI-compativel e fixo. Default = endpoint publico.
_BASE = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")

# Tiers canonicos -> slug de modelo. flash = barato (default), pro = raciocinio/visao.
# Default aponta pro Gemini via OpenRouter (o objetivo: desbloquear o Gemini). Override
# por env sem tocar codigo — os slugs do OpenRouter podem mudar (ver /models).
TIERS: dict[str, str] = {
    "flash": os.environ.get("OPENROUTER_MODEL_FLASH", "google/gemini-2.5-flash"),
    "pro": os.environ.get("OPENROUTER_MODEL_PRO", "google/gemini-2.5-pro"),
}
# Tier default do gateway; override por env sem tocar codigo (AI_OPENROUTER_TIER=pro).
DEFAULT_TIER = os.environ.get("AI_OPENROUTER_TIER", "flash")


class OpenRouterError(RuntimeError):
    """Falha de chamada OpenRouter (HTTP/transporte/resposta). Mensagem NUNCA contem a chave."""


def _api_key(api_key: str | None = None) -> str:
    """Chave: `api_key=` explicito (DI) vence; senao env `OPENROUTER_API_KEY`.
    NUNCA aparece em log/excecao. Erro acionavel se ausente."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise OpenRouterError(
            "OpenRouter indisponivel: defina OPENROUTER_API_KEY no ambiente "
            "(ou passe api_key=). A chave nunca e hardcoded nem logada."
        )
    return key


def _resolve_model(tier: str | None, model: str | None) -> str:
    """`model` explicito (slug cru) vence; senao mapeia o `tier` (flash/pro)."""
    if model:
        return model
    t = tier or DEFAULT_TIER
    if t not in TIERS:
        raise OpenRouterError(
            f"tier OpenRouter desconhecido: {t!r}. Use {sorted(TIERS)} ou passe model=."
        )
    return TIERS[t]


def _headers(key: str) -> dict[str, str]:
    """Auth + content-type; + atribuicao opcional (so se as env vars estiverem setadas).
    A chave vai SO aqui, no header — nunca no corpo, nunca em log/excecao."""
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    referer = os.environ.get("OPENROUTER_APP_URL")
    title = os.environ.get("OPENROUTER_APP_TITLE")
    if referer:
        h["HTTP-Referer"] = referer
    if title:
        h["X-Title"] = title
    return h


# Tentativas totais p/ blip transitorio (429/5xx/queda de conexao). 1 = sem retry.
_MAX_ATTEMPTS = max(1, int(os.environ.get("OPENROUTER_MAX_ATTEMPTS", "3") or "3"))


def _is_retryable_status(code: int) -> bool:
    """Status HTTP transitorio (vale re-tentar). 4xx de cliente (400/401/403) NAO."""
    return code in (408, 429) or 500 <= code < 600


def _backoff_seconds(attempt: int, base: float = 0.5, cap: float = 4.0) -> float:
    """Backoff exponencial com full jitter: espera em [0, min(cap, base*2^(n-1))]."""
    exp = min(cap, base * (2 ** max(0, attempt - 1)))
    return random.random() * exp


def _post(body: dict, key: str, timeout: int) -> dict:
    """POST /chat/completions -> JSON. Erros viram OpenRouterError SEM vazar a chave
    (que so vai no header). Corpo de erro truncado pra ser acionavel sem despejar tudo.

    Retry de blip TRANSITORIO e RAPIDO (429/5xx/queda de conexao) — esses respondem na
    hora, entao algumas tentativas cabem no orcamento. Timeout (abort) NAO e re-tentado:
    re-esperar o timeout inteiro estouraria o budget. OPENROUTER_MAX_ATTEMPTS controla."""
    data = json.dumps(body).encode("utf-8")
    last_err: OpenRouterError = OpenRouterError("OpenRouter: falha desconhecida")
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        req = urllib.request.Request(
            f"{_BASE}/chat/completions",
            data=data,
            headers=_headers(key),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:  # noqa: BLE001 — corpo de erro e best-effort
                detail = "<sem corpo>"
            last_err = OpenRouterError(f"OpenRouter HTTP {e.code}: {detail}")
            if _is_retryable_status(e.code) and attempt < _MAX_ATTEMPTS:
                time.sleep(_backoff_seconds(attempt))
                continue
            raise last_err from None
        except (TimeoutError, urllib.error.URLError) as e:
            # timeout NAO re-tenta (custoso); outra queda de transporte re-tenta (rapida).
            # socket.timeout e alias de TimeoutError no 3.10+, entao isinstance cobre os dois.
            reason = getattr(e, "reason", e)
            is_timeout = isinstance(e, TimeoutError) or isinstance(reason, TimeoutError)
            last_err = OpenRouterError(f"OpenRouter transporte: {reason}")
            if not is_timeout and attempt < _MAX_ATTEMPTS:
                time.sleep(_backoff_seconds(attempt))
                continue
            raise last_err from None
    raise last_err


def _extract_text(data: dict) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise OpenRouterError(f"OpenRouter resposta inesperada: {type(e).__name__}") from None
    # `content` pode vir null (resposta filtrada/refusal/só-tool) — a chave existe mas é None,
    # então nenhuma exceção sobe. Honra o contrato `-> str` (senão o None vaza pro caller como
    # se fosse sucesso). Vazio vira "".
    return content if isinstance(content, str) else ""


def openrouter_messages_raw(
    messages: list[dict],
    system: str | None = None,
    tier: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: str | None = None,
    tools: list[dict] | None = None,
    tool_choice: "str | dict | None" = None,
    max_tokens: int | None = None,
) -> dict:
    """Multi-turn → retorna o JSON CRU da /chat/completions (choices[0].message pode ter
    `tool_calls`). Use quando precisar dos tool_calls (function-calling/agente); `openrouter_messages`
    e o atalho texto-so sobre esta. `tools`/`tool_choice` = formato OpenAI ({type:function,...}) —
    OpenRouter e OpenAI-compativel, entao vao crus. `api_key=` vence o env (DI). Levanta
    OpenRouterError sem vazar a chave."""
    key = _api_key(api_key)
    resolved = _resolve_model(tier, model)
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)

    body: dict = {"model": resolved, "messages": msgs, "temperature": temperature, "stream": False}
    if tools:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return _post(body, key, timeout)


def openrouter_messages(
    messages: list[dict],
    system: str | None = None,
    tier: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: str | None = None,
) -> str:
    """Multi-turn → retorna SO o texto. `messages` = [{"role": "user"|"assistant"|
    "system", "content": str|list}, ...] no formato OpenAI (OpenRouter e OpenAI-compativel,
    entao vai cru). `system=` e prependido como uma message role='system' (conveniencia;
    tambem da pra passar dentro de `messages`). `model=` (slug cru) vence o tier; `api_key=`
    vence o env (DI). Levanta OpenRouterError sem vazar a chave. Atalho texto-so sobre
    openrouter_messages_raw (sem tools)."""
    data = openrouter_messages_raw(
        messages, system=system, tier=tier, model=model,
        temperature=temperature, timeout=timeout, api_key=api_key,
    )
    return _extract_text(data)


def openrouter_chat(
    prompt: str,
    system: str | None = None,
    tier: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: str | None = None,
) -> str:
    """Atalho single-turn → retorna SO o texto. Assinatura espelha openai_chat/
    deepseek_chat (troca de provider = trocar import). `model=` (slug cru) vence o
    tier. `api_key=` explicito vence o env (DI). Delega a openrouter_messages."""
    return openrouter_messages(
        [{"role": "user", "content": prompt}],
        system=system,
        tier=tier,
        model=model,
        temperature=temperature,
        timeout=timeout,
        api_key=api_key,
    )


def openrouter_chat_vision_raw(
    prompt: str,
    images: list[str],
    system: str | None = None,
    tier: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: str | None = None,
) -> dict:
    """Peer BRUTO de openrouter_chat_vision: retorna o JSON CRU da API (com `usage`) em vez
    de so o texto. Existe pro caller que precisa CUSTEAR a chamada (ex. squad.py
    make_openrouter_vision_job) — openrouter_chat_vision descarta `usage` ao extrair so o
    texto, entao motores de custo usam este em vez daquele (mesma relacao de
    openrouter_messages_raw p/ openrouter_messages). Mesmo formato multipart OpenAI
    ({type:'text'} + {type:'image_url'})."""
    key = _api_key(api_key)
    resolved = _resolve_model(tier, model)
    content: list[dict] = [{"type": "text", "text": prompt}]
    for url in images:
        content.append({"type": "image_url", "image_url": {"url": url}})

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})

    return _post(
        {"model": resolved, "messages": messages, "temperature": temperature, "stream": False},
        key,
        timeout,
    )


def openrouter_chat_vision(
    prompt: str,
    images: list[str],
    system: str | None = None,
    tier: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: str | None = None,
) -> str:
    """Chat multimodal (texto + imagens) → retorna SO o texto.

    `images` = lista de URLs http(s) OU data-URIs (ex. 'data:image/jpeg;base64,...').
    Monta o content multipart do formato OpenAI ({type:'text'} + {type:'image_url'}).
    ESCOLHA um modelo multimodal via `model=` ou tier (Gemini/Claude/GPT-4o fazem visao);
    um modelo so-texto vai rejeitar as imagens. `api_key=` explicito vence o env (DI).
    Levanta OpenRouterError sem vazar a chave.
    Atalho texto-so sobre openrouter_chat_vision_raw (sem usage; mesma relacao de
    openrouter_messages p/ openrouter_messages_raw)."""
    data = openrouter_chat_vision_raw(
        prompt, images, system=system, tier=tier, model=model,
        temperature=temperature, timeout=timeout, api_key=api_key,
    )
    return _extract_text(data)


def openrouter_chat_audio(
    prompt: str,
    audio_b64: str,
    audio_format: str = "mp3",
    system: str | None = None,
    tier: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    timeout: int = 180,
    api_key: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Chat multimodal com ÁUDIO (texto + 1 clipe de áudio) → retorna SO o texto.

    `audio_b64` = o áudio inteiro em base64 (sem o prefixo `data:`); `audio_format` =
    contêiner ('mp3'|'wav'|'m4a'|...). Monta o content multipart do formato OpenAI
    ({type:'text'} + {type:'input_audio', input_audio:{data, format}}) — OpenRouter é
    OpenAI-compatível, então vai cru. ESCOLHA um modelo que aceite áudio (Gemini faz;
    probe live: 40s de fala → ~6s, com timestamps por segmento). Um modelo sem áudio
    rejeita o clipe. `max_tokens` cobre transcrições longas (senão o modelo trunca).
    `api_key=` explícito vence o env (DI). Levanta OpenRouterError sem vazar a chave."""
    key = _api_key(api_key)
    resolved = _resolve_model(tier, model)
    content: list[dict] = [
        {"type": "text", "text": prompt},
        {"type": "input_audio", "input_audio": {"data": audio_b64, "format": audio_format}},
    ]
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})

    body: dict = {"model": resolved, "messages": messages, "temperature": temperature, "stream": False}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    data = _post(body, key, timeout)
    return _extract_text(data)


def openrouter_list_models(timeout: int = 30, api_key: str | None = None) -> dict:
    """GET /models -> JSON CRU do catálogo público do OpenRouter ({"data": [{id, pricing, ...}]}).

    Endpoint PÚBLICO (não exige chave); se houver `OPENROUTER_API_KEY`/`api_key=`, manda no header
    (inofensivo, e respeita atribuição). Mesmo retry de blip TRANSITÓRIO do `_post` (429/5xx/queda
    de transporte; timeout NÃO re-tenta). Erros viram OpenRouterError sem vazar a chave. Usado pelo
    pré-voo do squad (`preflight.py`) pra confirmar que os slugs do roster existem e
    comparar preço vivo vs. configurado ANTES de disparar um lote."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    headers = _headers(key) if key else {"Content-Type": "application/json"}
    last_err: OpenRouterError = OpenRouterError("OpenRouter: falha desconhecida ao listar modelos")
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        req = urllib.request.Request(f"{_BASE}/models", headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:  # noqa: BLE001 — corpo de erro é best-effort
                detail = "<sem corpo>"
            last_err = OpenRouterError(f"OpenRouter HTTP {e.code}: {detail}")
            if _is_retryable_status(e.code) and attempt < _MAX_ATTEMPTS:
                time.sleep(_backoff_seconds(attempt))
                continue
            raise last_err from None
        except (TimeoutError, urllib.error.URLError) as e:
            reason = getattr(e, "reason", e)
            is_timeout = isinstance(e, TimeoutError) or isinstance(reason, TimeoutError)
            last_err = OpenRouterError(f"OpenRouter transporte: {reason}")
            if not is_timeout and attempt < _MAX_ATTEMPTS:
                time.sleep(_backoff_seconds(attempt))
                continue
            raise last_err from None
    raise last_err
