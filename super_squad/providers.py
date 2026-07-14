"""providers.py — provedores OpenAI-compativeis do Super Squad (OpenRouter, Qwen Cloud).

Um `Provider` e SO a configuracao de um endpoint OpenAI-compativel: `base_url`, env da chave,
`tiers` (flash/pro -> slug) e se manda os headers de atribuicao. O TRANSPORTE (retry, backoff,
timeout, extracao de texto, "a chave nunca vaza") continua UNICO, no chokepoint `openrouter.py`
— provider novo = mais uma entrada AQUI, zero HTTP duplicado (OCP).

Providers:
- `openrouter` — roteador (1 chave -> N modelos). Manda HTTP-Referer/X-Title (atribuicao) quando
  as envs de app estao setadas. Chave: OPENROUTER_API_KEY.
- `qwen_cloud` — Alibaba Cloud Model Studio (DashScope), modo OpenAI-compativel
  (https://dashscope-intl.aliyuncs.com/compatible-mode/v1). Chave: DASHSCOPE_API_KEY. NAO manda
  os headers de atribuicao (sao especificos do OpenRouter; nao existem la).

Default = `openrouter`: quem nao passa `provider=` continua com o comportamento de HOJE, byte a
byte. Env `AI_SQUAD_PROVIDER=qwen_cloud` troca o provider ATIVO do processo (o que os factories
provider-aware e o pre-voo do maestro usam).

Os objetos sao SNAPSHOT do ambiente no import (mesmo idioma do `TIERS` que ja existia): base/tiers
saem de env com default explicito. Chave: NUNCA aqui — so o NOME da env (`api_key_env`); quem le a
chave e o chokepoint, e so pro header.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Endpoint OpenAI-compativel do Alibaba Cloud Model Studio (DashScope), regiao internacional.
# O caminho `/chat/completions` e o mesmo do OpenAI/OpenRouter — por isso o chokepoint e reusado.
DASHSCOPE_INTL_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


@dataclass(frozen=True)
class Provider:
    """Config de um endpoint OpenAI-compativel.

    `name`        rotulo canonico (aparece nas mensagens de erro: "qwen_cloud HTTP 401: ...").
    `base_url`    raiz da API (o chokepoint concatena `/chat/completions` e `/models`).
    `api_key_env` NOME da env var da chave (a chave em si nunca mora aqui).
    `tiers`       flash (barato/volume) e pro (raciocinio) -> slug de modelo.
    `attribution` manda HTTP-Referer/X-Title? So o OpenRouter entende esses headers.
    """
    name: str
    base_url: str
    api_key_env: str
    tiers: "dict[str, str]"
    attribution: bool = False


def _build_openrouter() -> Provider:
    """OpenRouter com os defaults de HOJE (preserva o comportamento pre-providers)."""
    return Provider(
        name="openrouter",
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
        api_key_env="OPENROUTER_API_KEY",
        tiers={
            "flash": os.environ.get("OPENROUTER_MODEL_FLASH", "google/gemini-2.5-flash"),
            "pro": os.environ.get("OPENROUTER_MODEL_PRO", "google/gemini-2.5-pro"),
        },
        attribution=True,
    )


def _build_qwen_cloud() -> Provider:
    """Qwen Cloud = Alibaba Cloud Model Studio (DashScope) no modo OpenAI-compativel.

    Slugs (catalogo vivo em https://www.alibabacloud.com/help/en/model-studio/models):
    `qwen-plus` (geral/barato) e `qwen-max` (raciocinio mais forte); `qwen3-max` tambem existe.
    Override por env (QWEN_MODEL_FLASH / QWEN_MODEL_PRO) — os slugs mudam, o codigo nao precisa."""
    return Provider(
        name="qwen_cloud",
        base_url=os.environ.get("QWEN_CLOUD_BASE_URL", DASHSCOPE_INTL_BASE_URL).rstrip("/"),
        api_key_env="DASHSCOPE_API_KEY",
        tiers={
            "flash": os.environ.get("QWEN_MODEL_FLASH", "qwen-plus"),
            "pro": os.environ.get("QWEN_MODEL_PRO", "qwen-max"),
        },
        attribution=False,  # HTTP-Referer/X-Title sao do OpenRouter; DashScope nao os usa.
    )


OPENROUTER: Provider = _build_openrouter()
QWEN_CLOUD: Provider = _build_qwen_cloud()

PROVIDERS: "dict[str, Provider]" = {p.name: p for p in (OPENROUTER, QWEN_CLOUD)}

# Compatibilidade: sem `AI_SQUAD_PROVIDER`, o provider ativo continua sendo o OpenRouter.
DEFAULT_PROVIDER_NAME = "openrouter"


def get_provider(name: str) -> Provider:
    """Provider por nome. Nome desconhecido -> ValueError acionavel (lista os conhecidos)."""
    prov = PROVIDERS.get((name or "").strip().lower())
    if prov is None:
        raise ValueError(
            f"provider desconhecido: {name!r}. Conhecidos: {sorted(PROVIDERS)} "
            "(env AI_SQUAD_PROVIDER)."
        )
    return prov


def default_provider() -> Provider:
    """Provider ATIVO do processo: env `AI_SQUAD_PROVIDER` (le a cada chamada — testes/CLI trocam
    sem reimportar), default `openrouter` (compatibilidade com todo caller que ja existe)."""
    return get_provider(os.environ.get("AI_SQUAD_PROVIDER") or DEFAULT_PROVIDER_NAME)
