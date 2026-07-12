# Manifesto dos subagentes — os 12 mais importantes

> A lista dos papéis que o exército vai carregar, em ordem de valor/dependência (o flywheel, D9).
> Persona = MIT, portável (pública). O **modelo medido** de cada papel é PRIVADO (roster via env, D1).
> Medição é GRADUAL — sob necessidade real, não "gastar dólar só pra testar". Um papel entra em ação
> assim que tem persona + um roster semeado (prior chinês), e refina quando for medido.

Legenda: ✅ pronto · 🔄 parcial · ⬜ a fazer · 🔒 gated (Fase 2)
Fase 1 = **consultivo** (lê e julga, roda no motor JÁ, mensurável) · Fase 2 = **construtor** (agentic, atrás do hardening A1–A5).

## Fase 1 — consultivos (o núcleo mensurável)

| # | Papel | O que faz | Persona | Roster |
|---|---|---|---|---|
| 1 | **code-reviewer** | gate de correção/segurança de diff | ✅ | ✅ **medido** (titular ativo, privado) |
| 2 | **qa-test-judge** | julga cobertura e qualidade de testes | ✅ autorada | 🔄 semeado |
| 3 | **architect-reviewer** | design, acoplamento, limites de módulo | ✅ autorada | 🔄 semeado |
| 4 | **security-auditor** | vulnerabilidades, superfície de ataque | ✅ | 🔄 semeado |
| 5 | **debugger** | diagnóstico de causa-raiz a partir de sintoma/stack | ✅ autorada | 🔄 semeado |
| 6 | **performance-auditor** | gargalos, custo, latência, complexidade | ✅ autorada | 🔄 semeado |
| 7 | **api-designer** | contratos/schema/versionamento (casa com API-first) | ✅ autorada | 🔄 semeado |
| 8 | **eval-engineer** | julga prompts/saídas contra critério — meta-útil pro próprio exército | ✅ autorada | 🔄 semeado |
| 9 | **technical-writer** | docs, ADRs, clareza | ✅ autorada | 🔄 semeado |
| 10 | **data-analyst** | métricas, leitura de medição, tabelas | ✅ autorada | 🔄 semeado |
| 11 | **competitive-analyst** | pesquisa de mercado/produto (venture) | ✅ | 🔄 semeado |

> Estado 2026-07-12: **11/11 papéis Fase-1 com persona e roster semeado (prior chinês) → prontos p/
> `run_roles` em paralelo AGORA**. "autorada" = draft do workhorse chinês com gate humano (proveniência
> distinta do catálogo — ver `roles/vendor/README.md`). Medição real (que troca *semeado* → *medido*) é
> gradual, quando fizer sentido (D9). Só `code-reviewer` está medido/ativo.

## Fase 2 — construtor (o horizonte, gated)

| # | Papel | O que faz | Estado |
|---|---|---|---|
| 12 | **backend-builder** | ESCREVE e roda código (agentic) | 🔒 só após hardening A1–A5 + seam BuilderRuntime (E) |

## Como um papel entra em ação (sem gastar pra testar)

1. **Vendorizar a persona** (MIT) em `roles/vendor/<papel>.md`.
2. **Semear o roster** com um prior chinês cross-lab (config, ZERO gasto): env privada
   `AI_SQUAD_ROSTER_<PAPEL>` = `<slug-chines-1>:<pin>:<pout>,<slug-chines-2>:<pin>:<pout>`
   (dois labs diferentes p/ diversidade; os slugs medidos ficam no roster PRIVADO, D1).
3. **Usar já** — `run_role("<papel>", input)` ou vários em paralelo com `run_roles([...])`.
4. **Medir quando fizer sentido** (D9/D10, N≥5, gold de mão humana, gate `gold_preflight`) → o roster
   deixa de ser *prior semeado* e vira *medido*. Shootouts daqui pra frente = **só modelos chineses**.

Ver `docs/ROADMAP.md` (backlog por track) e `DECISIONS.md` (D1 roster privado · D9 ordem · D10 skills · D13/D14).
