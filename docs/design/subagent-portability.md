# Portabilidade de subagent — o ativo mais transportável do projeto

> Registro de design. Um subagent NÃO é código: é **persona (prompt) + modelo medido (config) +
> skill opcional**. Isso o torna transportável pra qualquer projeto ou host sem arrastar
> dependência. Este documento fixa o que transfere, o que é privado, e o contrato de reuso.

## O que é um subagent (3 partes, todas config/texto)

| Parte | O que é | Portável? | Onde vive |
|---|---|---|---|
| **persona** | system prompt = o papel (*quem*) | 100% (texto MIT, é *input*) | `roles/vendor/*.md` (público) |
| **modelo medido** | slug + preço = quem RODA o papel | sim, mas é o edge | roster PRIVADO (D1), env `AI_SQUAD_ROSTER_<PAPEL>` |
| **skill** (opcional) | procedimento/capacidade (*como*) | sim, gated (D10) | futuro `SkillSpec` |

Não há código travado: o motor (`run_squad`) é domain-blind e provider-agnóstico. Um subagent é
`{persona, slug, preço}` — um punhado de config que roda onde houver um modelo pra injetar o prompt.

## Onde um subagent pode ser reusado

O mesmo subagent (persona + slug) roda, sem adaptação de código:
- do `run_squad` deste repo (`roles.make_role_job` + motor);
- do **AI Gateway** de outro serviço (o motor é uma folha importável);
- da chamada OpenRouter própria de outro projeto (só injeta `system=persona.system_prompt`, `model=slug`);
- **de volta num Claude Code / Codex / OpenCode** — as personas VIERAM desses catálogos, lá são nativas.

## Contrato de reuso (o artefato mínimo que viaja)

Pra reusar um subagent MEDIDO em outro projeto, carregue:
1. o arquivo da **persona** (`roles/vendor/<papel>.md`, público, MIT);
2. a **linha de roster** (`<slug>:<pin>:<pout>`, privada — via env override, nunca commitada);
3. qualquer runner que injete `system_prompt` numa chamada de modelo (o deste repo ou o seu).

```
# exemplo: reusar o code-reviewer noutro projeto
AI_SQUAD_ROSTER_CODE-REVIEWER="<slug medido>:<pin>:<pout>"   # linha privada, do seu roster
# + roles/vendor/code-reviewer.md  (persona pública)
```

## Fronteiras honestas (o que limita o reuso)

- **Portável ≠ confiável.** Uma persona reusada SEM medição roda, mas você não sabe qualidade/custo.
  "Reusar persona" e "reusar subagent confiável" são coisas diferentes — a segunda exige a linha de
  roster medida (N>=5, gold humano). O catálogo é inventário; medição é o que vira agente.
- **Roster é medido contra um GOLD específico.** A persona transfere 100%; a *escolha de modelo*
  transfere como PRIOR FORTE. Se a tarefa do projeto-alvo difere materialmente do gold que mediu o
  roster, **revalide** antes de confiar (candidate_eval vs o titular).
- **Só consultivo.** Subagents single-shot leem e julgam. Como CONSTRUTOR (escreve/roda código),
  ainda não — é Fase 2, atrás do hardening A1-A5.
- **Personas são Claude/Codex-origin.** Reusá-las nesses hosts é nativo; rodá-las num modelo chinês
  é um TRANSFER — medido, não assumido (ver `flywheel-bootstrap.md`).

## Estado atual (honesto)

Personas no repo: 3 (`code-reviewer`, `security-auditor`, `competitive-analyst`). **Subagents
MEDIDOS e transportáveis-com-confiança: 1** (code-reviewer). Catálogo ingerível: ~325 personas MIT
(potencial, não medido). O flywheel existe pra virar "portável" em "medido", um papel por vez.
