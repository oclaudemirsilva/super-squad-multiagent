"""qwen_cloud.py — integracao Qwen Cloud (Alibaba Cloud Model Studio / DashScope).

ESTE e o modulo do Alibaba Cloud. O Model Studio expoe os modelos Qwen num endpoint
OPENAI-COMPATIVEL (mesmo shape de `/chat/completions`), entao aqui NAO ha HTTP nenhum: esta
fachada e fina de proposito e delega ao chokepoint unico do pacote (`openrouter.py` — nome
historico: era o unico provider), passando `provider=QWEN_CLOUD`. Retry, backoff, timeout,
truncagem de corpo de erro e o invariante "a chave NUNCA e logada nem entra em excecao" sao
COMPARTILHADOS — nada disso e reimplementado por provider.

    base_url : https://dashscope-intl.aliyuncs.com/compatible-mode/v1   (regiao internacional)
               override por env QWEN_CLOUD_BASE_URL (ex.: endpoint de Pequim)
    chave    : env DASHSCOPE_API_KEY  (so por env; `api_key=` explicito e aceito p/ DI)
    modelos  : tier `flash` -> qwen-plus (geral/barato)   [env QWEN_MODEL_FLASH]
               tier `pro`   -> qwen-max  (raciocinio forte) [env QWEN_MODEL_PRO]
               `model=` (slug cru) vence o tier — ex. 'qwen3-max'.

stdlib-only: sem o SDK `openai`, sem dependencia nova (mesma regra do resto do pacote).

Uso:
    from super_squad.qwen_cloud import qwen_chat
    print(qwen_chat("Explique o teorema de Bayes em uma frase.", tier="flash"))

Squad inteiro no Qwen Cloud (fan-out + teto de custo + telemetria, sem tocar em OpenRouter):
    AI_SQUAD_PROVIDER=qwen_cloud DASHSCOPE_API_KEY=... \
    AI_SQUAD_ROSTER_SENTIMENT_JUDGE="qwen-plus:0.4:1.2,qwen-max:1.6:6.4" \
    python -m demo.toy_squad shadow_sentiment_judge --execute --limit 6
"""
from __future__ import annotations

from . import openrouter as _chokepoint  # lookup por ATRIBUTO (mockavel nos testes)
from .providers import QWEN_CLOUD


def qwen_messages_raw(
    messages: "list[dict]",
    system: "str | None" = None,
    tier: "str | None" = None,
    model: "str | None" = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: "str | None" = None,
    tools: "list[dict] | None" = None,
    tool_choice: "str | dict | None" = None,
    max_tokens: "int | None" = None,
) -> dict:
    """Multi-turn no Qwen Cloud -> JSON CRU da /chat/completions (inclui `usage`, entao serve
    pra CUSTEAR a chamada; `tool_calls` quando `tools` e usado). Delega ao chokepoint com
    provider=QWEN_CLOUD. Levanta OpenRouterError (erro nomeia 'qwen_cloud') sem vazar a chave."""
    return _chokepoint.openrouter_messages_raw(
        messages, system=system, tier=tier, model=model, temperature=temperature,
        timeout=timeout, api_key=api_key, tools=tools, tool_choice=tool_choice,
        max_tokens=max_tokens, provider=QWEN_CLOUD,
    )


def qwen_messages(
    messages: "list[dict]",
    system: "str | None" = None,
    tier: "str | None" = None,
    model: "str | None" = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: "str | None" = None,
) -> str:
    """Multi-turn no Qwen Cloud -> SO o texto. `messages` no formato OpenAI (o DashScope e
    OpenAI-compativel, entao vai cru). Atalho texto-so sobre `qwen_messages_raw`."""
    return _chokepoint.openrouter_messages(
        messages, system=system, tier=tier, model=model, temperature=temperature,
        timeout=timeout, api_key=api_key, provider=QWEN_CLOUD,
    )


def qwen_chat(
    prompt: str,
    system: "str | None" = None,
    tier: "str | None" = None,
    model: "str | None" = None,
    temperature: float = 0.2,
    timeout: int = 120,
    api_key: "str | None" = None,
) -> str:
    """Single-turn no Qwen Cloud -> SO o texto. Assinatura identica a `openrouter_chat` (trocar
    de provider = trocar o import). `model=` (slug cru, ex. 'qwen3-max') vence o tier;
    `api_key=` vence a env DASHSCOPE_API_KEY (DI)."""
    return _chokepoint.openrouter_chat(
        prompt, system=system, tier=tier, model=model, temperature=temperature,
        timeout=timeout, api_key=api_key, provider=QWEN_CLOUD,
    )
