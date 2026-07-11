"""roles.py — ingestão de personas (catálogo de subagents) → RoleSpec + job builder.

Converte uma persona no formato dos catálogos de subagents (frontmatter YAML simples +
corpo = system prompt) num `RoleSpec` normalizado, e monta um Job do motor a partir de
(papel, input, modelo). DOMAIN-BLIND: este módulo não sabe o que o papel FAZ — só
transporta o system prompt e classifica se é single-shot (consultivo) ou construtor.

Clean-room / stdlib-only: parser de frontmatter PRÓPRIO (sem PyYAML). O frontmatter dos
catálogos é key:value plano (name/description/tools/model). YAML aninhado seria over-
engineering hoje — se um dia precisar, aí se considera a dependência.

Classificação single-shot vs construtor sai das TOOLS que a própria persona declara — é um
sinal medido do autor da persona, não um chute nosso. Papel sem tool de escrita/bash =
single-shot (roda no motor `run_squad`, INERTE, sem tocar disco). Papel com Write/Edit/Bash
= construtor (precisa do runtime agêntico da Fase 2; ver docs/design/opencode-builder-runtime.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Tools que caracterizam um CONSTRUTOR (escreve/roda código) — presença de qualquer uma
# tira o papel do modo single-shot inerte. Comparação case-insensitive.
_BUILDER_TOOLS = {"write", "edit", "multiedit", "bash", "notebookedit", "run"}


@dataclass(frozen=True)
class RoleSpec:
    """Persona normalizada. `system_prompt` é o corpo (o que vai no `system=` do modelo);
    `declared_tools` são as tools que a persona pede (fonte da classificação); `single_shot`
    True = roda no motor sem tocar disco."""
    name: str
    description: str
    system_prompt: str
    declared_tools: "tuple[str, ...]"
    model_hint: str
    single_shot: bool
    source_path: Optional[str] = None


def split_frontmatter(text: str) -> "tuple[dict, str]":
    """Separa `---\\nfrontmatter\\n---\\ncorpo`. Sem frontmatter → ({}, texto inteiro).
    Tolerante a CRLF e a espaços/linhas em branco antes do primeiro `---`."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text
    # remove o primeiro '---' e procura o fechamento
    rest = stripped[3:]
    end = rest.find("\n---")
    if end == -1:
        return {}, text
    block = rest[:end]
    body = rest[end + 4:]  # pula '\n---'
    # o corpo pode começar com o resto da linha do '---' de fechamento + '\n'
    nl = body.find("\n")
    if nl != -1:
        body = body[nl + 1:]
    return _parse_front_lines(block), body.lstrip("\n")


def _parse_front_lines(block: str) -> dict:
    """Parser de frontmatter plano (key: value). Desfaz aspas simples/duplas do valor.
    Ignora linhas em branco e linhas sem ':' (não tenta ser YAML completo de propósito)."""
    out: dict = {}
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def _parse_tools(value: str) -> "tuple[str, ...]":
    if not value:
        return ()
    return tuple(t.strip() for t in value.split(",") if t.strip())


def classify_single_shot(tools: "tuple[str, ...]") -> bool:
    """single-shot (consultivo/inerte) sse NENHUMA tool declarada for de construtor.
    Papel sem tools declaradas → single-shot (default seguro: não recebe disco/bash)."""
    return not any(t.lower() in _BUILDER_TOOLS for t in tools)


def parse_persona(text: str, source_path: "Optional[str]" = None) -> RoleSpec:
    """Persona (frontmatter + corpo) → RoleSpec. `name` cai pro basename se ausente."""
    front, body = split_frontmatter(text)
    tools = _parse_tools(front.get("tools", ""))
    name = front.get("name") or (Path(source_path).stem if source_path else "unnamed")
    return RoleSpec(
        name=name,
        description=front.get("description", ""),
        system_prompt=body.strip(),
        declared_tools=tools,
        model_hint=front.get("model", "inherit"),
        single_shot=classify_single_shot(tools),
        source_path=source_path,
    )


def load_role(path: "str | Path") -> RoleSpec:
    p = Path(path)
    return parse_persona(p.read_text(encoding="utf-8"), source_path=str(p))


def load_roles_dir(dirpath: "str | Path") -> "dict[str, RoleSpec]":
    """Carrega todas as personas `*.md` de um diretório → {name: RoleSpec}. Não-recursivo."""
    out: "dict[str, RoleSpec]" = {}
    for p in sorted(Path(dirpath).glob("*.md")):
        spec = load_role(p)
        out[spec.name] = spec
    return out


def make_role_job(
    key: str,
    spec: RoleSpec,
    task_input: str,
    model: str,
    price_in_per_mtok: float,
    price_out_per_mtok: float,
    *,
    api_key: "Optional[str]" = None,
    temperature: float = 0.2,
    timeout: int = 120,
):
    """Monta um Job do motor (`run_squad`) que roda ESTE papel sobre `task_input` usando
    `model`. O system prompt do papel vira `system=`; o input do usuário vira o prompt.

    Guarda-corpo: só papéis single-shot podem virar Job do motor — um construtor precisa do
    runtime agêntico (Fase 2), não do motor. Levanta ValueError se tentar o atalho errado.

    Import LAZY de squad (mesmo idioma dos módulos de alto nível: motor sem acoplamento de
    import no topo; testes mockam `super_squad.openrouter.openrouter_messages_raw`)."""
    if not spec.single_shot:
        raise ValueError(
            f"papel {spec.name!r} é CONSTRUTOR (tools {spec.declared_tools}); "
            "precisa do runtime agêntico da Fase 2, não do motor single-shot."
        )
    from .squad import make_openrouter_text_job
    return make_openrouter_text_job(
        key, task_input, model, price_in_per_mtok, price_out_per_mtok,
        system=spec.system_prompt, temperature=temperature, timeout=timeout, api_key=api_key,
    )
