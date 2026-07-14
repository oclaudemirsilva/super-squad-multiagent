"""Chokepoint unico das chamadas OpenAI-compativeis do super_squad (OpenRouter e Qwen Cloud).

OpenRouter e um roteador: UMA chave -> muitos modelos (Gemini, Claude, DeepSeek,
GPT...), todos via o mesmo endpoint OpenAI-compativel. E o que torna o painel
CROSS-LAB do squad barato de operar: o slug do modelo vai na REQUISICAO, entao um
roster inteiro (varios provedores) roda com uma unica credencial. stdlib-only
(urllib) de proposito — sem o SDK `openai`, pra manter o pacote importavel em
qualquer ambiente sem adicionar dependencia.

MULTI-PROVIDER (aditivo): toda funcao aceita `provider=` (um `providers.Provider`). `None` =
OPENROUTER — o comportamento de HOJE, inalterado. O outro provider nomeado e `QWEN_CLOUD`
(Alibaba Cloud Model Studio / DashScope, tambem OpenAI-compativel — ver `qwen_cloud.py`). O
provider decide base_url, env da chave, tiers e atribuicao; retry/backoff/timeout/extracao sao
COMPARTILHADOS aqui (nada de HTTP duplicado por provider).

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

Chave: SO de env — `OPENROUTER_API_KEY` no OpenRouter, `DASHSCOPE_API_KEY` no Qwen Cloud (o
provider ativo diz QUAL env); aceita `api_key=` explicito (DI, p/ quem injeta de um Settings que
leu .env). NUNCA hardcode; NUNCA loga (nem em excecao — corpo de erro truncado, chave so no
header).
"""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request

from .providers import OPENROUTER, Provider

# Compat: nomes de modulo que sempre existiram, agora derivados do provider OpenRouter.
# `_BASE` = base_url do OpenRouter (env OPENROUTER_BASE_URL); `TIERS` e o MESMO objeto de
# OPENROUTER.tiers (flash = barato/default, pro = raciocinio/visao; override por env
# OPENROUTER_MODEL_FLASH/PRO — os slugs mudam, ver https://openrouter.ai/models).
_BASE = OPENROUTER.base_url
TIERS: dict[str, str] = OPENROUTER.tiers
# Tier default do gateway; override por env sem tocar codigo (AI_OPENROUTER_TIER=pro).
DEFAULT_TIER = os.environ.get("AI_OPENROUTER_TIER", "flash")


class OpenRouterError(RuntimeError):
    """Falha de chamada ao provider (HTTP/transporte/resposta). Mensagem NUNCA contem a chave.

    Nome mantido por compatibilidade (era o unico provider); vale pra qualquer provider — a
    mensagem NOMEIA o provider ativo (ex.: "qwen_cloud HTTP 401: ...")."""


def _provider(provider: "Provider | None") -> Provider:
    """`None` -> OPENROUTER (default retrocompativel: caller antigo nao muda de comportamento)."""
    return provider or OPENROUTER


def _api_key(api_key: str | None = None, provider: "Provider | None" = None) -> str:
    """Chave: `api_key=` explicito (DI) vence; senao a env DO PROVIDER (`api_key_env`:
    OPENROUTER_API_KEY / DASHSCOPE_API_KEY). NUNCA aparece em log/excecao. Erro acionavel se
    ausente — e o erro NOMEIA o provider e a env certa."""
    prov = _provider(provider)
    key = api_key or os.environ.get(prov.api_key_env)
    if not key:
        raise OpenRouterError(
            f"{prov.name} indisponivel: defina {prov.api_key_env} no ambiente "
            "(ou passe api_key=). A chave nunca e hardcoded nem logada."
        )
    return key


def _resolve_model(tier: str | None, model: str | None,
                   provider: "Provider | None" = None) -> str:
    """`model` explicito (slug cru) vence; senao mapeia o `tier` (flash/pro) NO PROVIDER ativo
    (ex.: flash = 'google/gemini-2.5-flash' no OpenRouter, 'qwen-plus' no Qwen Cloud)."""
    if model:
        return model
    prov = _provider(provider)
    t = tier or DEFAULT_TIER
    if t not in prov.tiers:
        raise OpenRouterError(
            f"tier {prov.name} desconhecido: {t!r}. Use {sorted(prov.tiers)} ou passe model=."
        )
    return prov.tiers[t]


def _headers(key: str, provider: "Provider | None" = None) -> dict[str, str]:
    """Auth + content-type; + atribuicao opcional (so no provider que a suporta E so se as env
    vars estiverem setadas). HTTP-Referer/X-Title sao ESPECIFICOS do OpenRouter (rankings) —
    provider com `attribution=False` (ex. Qwen Cloud/DashScope) NAO os recebe.
    A chave vai SO aqui, no header — nunca no corpo, nunca em log/excecao."""
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if not _provider(provider).attribution:
        return h
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


def _post(body: dict, key: str, timeout: int, provider: "Provider | None" = None) -> dict:
    """POST {provider.base_url}/chat/completions -> JSON. Erros viram OpenRouterError SEM vazar a
    chave (que so vai no header) e NOMEANDO o provider ativo. Corpo de erro truncado pra ser
    acionavel sem despejar tudo.

    Retry de blip TRANSITORIO e RAPIDO (429/5xx/queda de conexao) — esses respondem na
    hora, entao algumas tentativas cabem no orcamento. Timeout (abort) NAO e re-tentado:
    re-esperar o timeout inteiro estouraria o budget. OPENROUTER_MAX_ATTEMPTS controla.

    Transporte COMPARTILHADO por todos os providers (OpenRouter, Qwen Cloud/DashScope): eles sao
    OpenAI-compativeis, entao o que muda e so base_url/headers — nada de HTTP duplicado."""
    prov = _provider(provider)
    data = json.dumps(body).encode("utf-8")
    last_err: OpenRouterError = OpenRouterError(f"{prov.name}: falha desconhecida")
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        req = urllib.request.Request(
            f"{prov.base_url}/chat/completions",
            data=data,
            headers=_headers(key, prov),
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
            last_err = OpenRouterError(f"{prov.name} HTTP {e.code}: {detail}")
            if _is_retryable_status(e.code) and attempt < _MAX_ATTEMPTS:
                time.sleep(_backoff_seconds(attempt))
                continue
            raise last_err from None
        except (TimeoutError, urllib.error.URLError) as e:
            # timeout NAO re-tenta (custoso); outra queda de transporte re-tenta (rapida).
            # socket.timeout e alias de TimeoutError no 3.10+, entao isinstance cobre os dois.
            reason = getattr(e, "reason", e)
            is_timeout = isinstance(e, TimeoutError) or isinstance(reason, TimeoutError)
            last_err = OpenRouterError(f"{prov.name} transporte: {reason}")
            if not is_timeout and attempt < _MAX_ATTEMPTS:
                time.sleep(_backoff_seconds(attempt))
                continue
            raise last_err from None
    raise last_err


def _extract_text(data: dict, provider: "Provider | None" = None) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise OpenRouterError(
            f"{_provider(provider).name} resposta inesperada: {type(e).__name__}") from None
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
    provider: "Provider | None" = None,
) -> dict:
    """Multi-turn → retorna o JSON CRU da /chat/completions (choices[0].message pode ter
    `tool_calls`). Use quando precisar dos tool_calls (function-calling/agente); `openrouter_messages`
    e o atalho texto-so sobre esta. `tools`/`tool_choice` = formato OpenAI ({type:function,...}) —
    os providers sao OpenAI-compativeis, entao vao crus. `api_key=` vence o env (DI).
    `provider=` (None = OpenRouter) escolhe base_url/chave/tiers. Levanta OpenRouterError sem
    vazar a chave."""
    prov = _provider(provider)
    key = _api_key(api_key, prov)
    resolved = _resolve_model(tier, model, prov)
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
    return _post(body, key, timeout, prov)


def openrouter_messages(
    messages: list[dict],
    system: str | None = None,
    tier: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: str | None = None,
    provider: "Provider | None" = None,
) -> str:
    """Multi-turn → retorna SO o texto. `messages` = [{"role": "user"|"assistant"|
    "system", "content": str|list}, ...] no formato OpenAI (os providers sao OpenAI-compativeis,
    entao vai cru). `system=` e prependido como uma message role='system' (conveniencia;
    tambem da pra passar dentro de `messages`). `model=` (slug cru) vence o tier; `api_key=`
    vence o env (DI); `provider=` (None = OpenRouter) escolhe o endpoint. Levanta
    OpenRouterError sem vazar a chave. Atalho texto-so sobre openrouter_messages_raw (sem tools)."""
    data = openrouter_messages_raw(
        messages, system=system, tier=tier, model=model,
        temperature=temperature, timeout=timeout, api_key=api_key, provider=provider,
    )
    return _extract_text(data, provider)


def openrouter_chat(
    prompt: str,
    system: str | None = None,
    tier: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: str | None = None,
    provider: "Provider | None" = None,
) -> str:
    """Atalho single-turn → retorna SO o texto. Assinatura espelha openai_chat/
    deepseek_chat (troca de provider = trocar import). `model=` (slug cru) vence o
    tier. `api_key=` explicito vence o env (DI). `provider=` (None = OpenRouter) escolhe o
    endpoint — `qwen_cloud.qwen_chat` e a fachada NOMEADA disso p/ o Qwen Cloud.
    Delega a openrouter_messages."""
    return openrouter_messages(
        [{"role": "user", "content": prompt}],
        system=system,
        tier=tier,
        model=model,
        temperature=temperature,
        timeout=timeout,
        api_key=api_key,
        provider=provider,
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
    provider: "Provider | None" = None,
) -> dict:
    """Peer BRUTO de openrouter_chat_vision: retorna o JSON CRU da API (com `usage`) em vez
    de so o texto. Existe pro caller que precisa CUSTEAR a chamada (ex. squad.py
    make_openrouter_vision_job) — openrouter_chat_vision descarta `usage` ao extrair so o
    texto, entao motores de custo usam este em vez daquele (mesma relacao de
    openrouter_messages_raw p/ openrouter_messages). Mesmo formato multipart OpenAI
    ({type:'text'} + {type:'image_url'}). `provider=` (None = OpenRouter): escolha um modelo
    multimodal DO provider ativo (ex. qwen-vl-* no Qwen Cloud)."""
    prov = _provider(provider)
    key = _api_key(api_key, prov)
    resolved = _resolve_model(tier, model, prov)
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
        prov,
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
    provider: "Provider | None" = None,
) -> str:
    """Chat multimodal (texto + imagens) → retorna SO o texto.

    `images` = lista de URLs http(s) OU data-URIs (ex. 'data:image/jpeg;base64,...').
    Monta o content multipart do formato OpenAI ({type:'text'} + {type:'image_url'}).
    ESCOLHA um modelo multimodal via `model=` ou tier (Gemini/Claude/GPT-4o fazem visao);
    um modelo so-texto vai rejeitar as imagens. `api_key=` explicito vence o env (DI).
    `provider=` (None = OpenRouter) escolhe o endpoint. Levanta OpenRouterError sem vazar a chave.
    Atalho texto-so sobre openrouter_chat_vision_raw (sem usage; mesma relacao de
    openrouter_messages p/ openrouter_messages_raw)."""
    data = openrouter_chat_vision_raw(
        prompt, images, system=system, tier=tier, model=model,
        temperature=temperature, timeout=timeout, api_key=api_key, provider=provider,
    )
    return _extract_text(data, provider)


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
    provider: "Provider | None" = None,
) -> str:
    """Chat multimodal com ÁUDIO (texto + 1 clipe de áudio) → retorna SO o texto.

    `audio_b64` = o áudio inteiro em base64 (sem o prefixo `data:`); `audio_format` =
    contêiner ('mp3'|'wav'|'m4a'|...). Monta o content multipart do formato OpenAI
    ({type:'text'} + {type:'input_audio', input_audio:{data, format}}) — OpenRouter é
    OpenAI-compatível, então vai cru. ESCOLHA um modelo que aceite áudio (Gemini faz;
    probe live: 40s de fala → ~6s, com timestamps por segmento). Um modelo sem áudio
    rejeita o clipe. `max_tokens` cobre transcrições longas (senão o modelo trunca).
    `api_key=` explícito vence o env (DI); `provider=` (None = OpenRouter) escolhe o endpoint.
    Levanta OpenRouterError sem vazar a chave."""
    prov = _provider(provider)
    key = _api_key(api_key, prov)
    resolved = _resolve_model(tier, model, prov)
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
    data = _post(body, key, timeout, prov)
    return _extract_text(data, prov)


def openrouter_list_models(timeout: int = 30, api_key: str | None = None,
                           provider: "Provider | None" = None) -> dict:
    """GET /models -> JSON CRU do catálogo público do OpenRouter ({"data": [{id, pricing, ...}]}).

    Endpoint PÚBLICO (não exige chave); se houver `OPENROUTER_API_KEY`/`api_key=`, manda no header
    (inofensivo, e respeita atribuição). Mesmo retry de blip TRANSITÓRIO do `_post` (429/5xx/queda
    de transporte; timeout NÃO re-tenta). Erros viram OpenRouterError sem vazar a chave. Usado pelo
    pré-voo do squad (`preflight.py`) pra confirmar que os slugs do roster existem e
    comparar preço vivo vs. configurado ANTES de disparar um lote.

    `provider=` (None = OpenRouter): o /models de OUTRO provider tem OUTRO schema (o `pricing` do
    pré-voo é do OpenRouter) — por isso o maestro só roda esse pré-voo quando o provider ativo é o
    OpenRouter."""
    prov = _provider(provider)
    key = api_key or os.environ.get(prov.api_key_env)
    headers = _headers(key, prov) if key else {"Content-Type": "application/json"}
    last_err: OpenRouterError = OpenRouterError(f"{prov.name}: falha desconhecida ao listar modelos")
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        req = urllib.request.Request(f"{prov.base_url}/models", headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:  # noqa: BLE001 — corpo de erro é best-effort
                detail = "<sem corpo>"
            last_err = OpenRouterError(f"{prov.name} HTTP {e.code}: {detail}")
            if _is_retryable_status(e.code) and attempt < _MAX_ATTEMPTS:
                time.sleep(_backoff_seconds(attempt))
                continue
            raise last_err from None
        except (TimeoutError, urllib.error.URLError) as e:
            reason = getattr(e, "reason", e)
            is_timeout = isinstance(e, TimeoutError) or isinstance(reason, TimeoutError)
            last_err = OpenRouterError(f"{prov.name} transporte: {reason}")
            if not is_timeout and attempt < _MAX_ATTEMPTS:
                time.sleep(_backoff_seconds(attempt))
                continue
            raise last_err from None
    raise last_err
