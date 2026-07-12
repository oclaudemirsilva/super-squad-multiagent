"""skills.py — ingestão de SKILLS (capacidades/playbooks) → SkillSpec + composição com persona.

Espelha `roles.py` (D10): persona = QUEM (system prompt); skill = COMO (procedimento/playbook, ex.
catálogos "awesome-agent-skills"). Uma skill injeta CONTEXTO num job do mesmo jeito que a persona
injeta o system prompt — `compose_system(persona, skill)` funde os dois. DOMAIN-BLIND e stdlib-only
(reusa o parser de frontmatter de `roles.py`, DRY).

GATE D10 (não adotar por fé):
- **Script executável = Fase 2.** Uma skill que referencia rodar um script (.py/.sh) ou pede tool de
  construtor (Bash/Write/Edit) é EXECUÇÃO DE CÓDIGO → só atrás do hardening A1–A5. `requires_script`
  marca isso; `compose_system` RECUSA compor uma skill dessas em modo single-shot (fail-closed).
- **Licença é POR-SKILL** (o catálogo ser MIT não cobre o upstream linkado) — este módulo NÃO baixa
  nem empacota; só ingere um arquivo local que o humano já colocou. (registro; a checagem é humana.)
- **Só entra no roster se MEDIR melhor que persona-sozinha (N≥5).** Este módulo COMPÕE; medir o ganho
  é do runner (`role_eval`) — a skill que não move o número não é adotada.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from super_squad.roles import split_frontmatter, _parse_tools, _BUILDER_TOOLS

# sinais de que a skill EXECUTA código (→ Fase 2): menção a rodar script, ou tool de construtor.
_SCRIPT_RE = re.compile(r"(?:\b(?:python|node|bash|sh|npx|\./)\s+\S+\.(?:py|sh|mjs|js|ts))"
                        r"|(?:run\s+the\s+script)|(?:execute\s+\S+\.(?:py|sh))", re.IGNORECASE)


@dataclass(frozen=True)
class SkillSpec:
    """Skill normalizada. `procedure` é o corpo (o playbook, o que se injeta junto do system prompt);
    `allowed_tools` são as tools que a skill declara; `requires_script` True = executa código (Fase 2).

    Proveniência de LICENÇA (D10, checagem humana): `license` e `source` vêm do frontmatter. `license`
    ausente/`DRAFT`/`UNKNOWN` → `license_cleared=False` (a licença ainda NÃO foi confirmada por humano).
    O módulo só CARREGA e EXPÕE isso; não baixa nem empacota — a bênção da licença é do humano."""
    name: str
    description: str
    procedure: str
    allowed_tools: "tuple[str, ...]"
    requires_script: bool
    license: Optional[str] = None
    source: Optional[str] = None
    source_path: Optional[str] = None

    @property
    def license_cleared(self) -> bool:
        """True só se há uma licença explícita e não-provisória. Fail-closed: sem licença = não liberada."""
        lic = (self.license or "").strip().upper()
        return bool(lic) and lic not in {"DRAFT", "UNKNOWN", "TBD", "PENDING"}


def _detect_requires_script(front: dict, body: str, tools: "tuple[str, ...]") -> bool:
    """Fase-2 sse: alguma tool declarada é de construtor, OU o corpo/frontmatter manda rodar script."""
    if any(t.lower() in _BUILDER_TOOLS for t in tools):
        return True
    hay = f"{front.get('allowed-tools','')}\n{body}"
    return bool(_SCRIPT_RE.search(hay))


def parse_skill(text: str, source_path: "Optional[str]" = None) -> SkillSpec:
    """Skill (frontmatter + corpo) → SkillSpec. `name` cai pro basename se ausente. Aceita
    `allowed-tools` (formato skills) ou `tools` (formato persona) como fonte das tools."""
    front, body = split_frontmatter(text)
    tools = _parse_tools(front.get("allowed-tools", front.get("tools", "")))
    name = front.get("name") or (Path(source_path).stem if source_path else "unnamed")
    return SkillSpec(
        name=name,
        description=front.get("description", ""),
        procedure=body.strip(),
        allowed_tools=tools,
        requires_script=_detect_requires_script(front, body, tools),
        license=front.get("license") or None,
        source=front.get("source") or None,
        source_path=source_path,
    )


def load_skill(path: "str | Path") -> SkillSpec:
    p = Path(path)
    return parse_skill(p.read_text(encoding="utf-8"), source_path=str(p))


def load_skills_dir(dirpath: "str | Path") -> "dict[str, SkillSpec]":
    """Carrega `*.md`/`SKILL.md` de um diretório (não-recursivo) → {name: SkillSpec}."""
    out: "dict[str, SkillSpec]" = {}
    for p in sorted(Path(dirpath).glob("*.md")):
        spec = load_skill(p)
        out[spec.name] = spec
    return out


class SkillGateError(RuntimeError):
    """Composição recusada: a skill executa código (Fase 2) e não pode entrar em single-shot."""


def compose_system(persona_system: str, skill: SkillSpec, *, allow_script: bool = False) -> str:
    """Funde o system prompt da persona com o playbook da skill → um único system prompt.
    GATE D10: se `skill.requires_script` e não `allow_script`, LEVANTA `SkillGateError` (skill que
    executa código é Fase 2, atrás do hardening A1–A5 — não roda no motor single-shot por fé)."""
    if skill.requires_script and not allow_script:
        raise SkillGateError(
            f"skill {skill.name!r} executa código (Fase 2) — precisa do hardening A1–A5 e do runtime "
            f"agêntico, não do motor single-shot. Compor só com allow_script=True (ciente do risco)."
        )
    return f"{persona_system.strip()}\n\n## Skill aplicada — {skill.name}\n{skill.procedure.strip()}"
