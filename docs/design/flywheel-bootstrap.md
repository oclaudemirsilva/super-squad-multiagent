# Flywheel auto-construtor — ordem por dependência, loop em OpenRouter

> Registro de design (D9/D10). O objetivo é que o Super Squad **se construa**: papéis medidos
> e rosteados numa ordem em que cada um ajuda a erguer o próximo, com o loop de construção
> rodando em OpenRouter (modelos de melhor custo-benefício MEDIDO), não no orquestrador caro.
> Promoção continua humana e com N>=5 (D1/D5); gold continua de mão humana (D6).

## Dois primitivos

| | **Persona / subagent** | **Skill / capability** |
|---|---|---|
| O que é | um PAPEL = *quem* faz (system prompt) | um PROCEDIMENTO = *como* fazer |
| Fonte | catálogos VoltAgent de subagents (~325, MIT) | catálogos de agent-skills (~1.5k, MIT como lista) |
| Na máquina | `roles.py` → `RoleSpec` → job | (futuro) `skills.py` → `SkillSpec` → contexto do job |

Persona (quem) + skill (como) = subagent mais capaz. A skill é injetável no contexto de um job
do mesmo jeito que o `system_prompt` da persona — extensão pequena, mesma costura.

## Ordem por dependência (medir os que CONSTROEM primeiro)

Os consultivos que constroem-e-verificam rodam HOJE (single-shot, inertes) e são exatamente os
que gateiam/guiam a construção do resto:

| # | Papel (consultivo) | Por que aqui | Constrói/destrava |
|---|---|---|---|
| 1 | **code-reviewer** | o *gate*; todo rascunho passa por ele | barra código ruim de qualquer papel seguinte |
| 2 | **qa-expert / test-judge** | rascunho verificado por cobertura, não só estilo | reviewer+QA = par de verificação real |
| 3 | **architect-reviewer** | julga a costura/DIP *antes* de escrever | gate de arquitetura no tempo de spec |
| 4 | **security-auditor** | porteiro da Fase 2 (hardening A1-A5) | destrava os construtores com segurança medida |
| 5 | **debugger** | root-cause quando algo que o squad fez quebra | fecha o loop de auto-conserto |

Só **depois** desse cérebro consultivo medido é que a **Fase 2** abre os CONSTRUTORES
(backend-developer etc.), agora fiscalizados pelo trio reviewer+qa+security **já medido**.

## O loop (por papel)

```
para cada papel na ordem:
  1. GOLD  — humano especifica o ground-truth (bug plantado / veredito conhecido). Pequeno, meu.
  2. DRAFT — braçal (OpenRouter) rascunha a máquina/testes do runner do papel.
  3. GATE  — humano/reviewer revisa o draft (testes herméticos verdes).
  4. MEDIR — runner cruza N modelos, N>=5/caso, contra o gold; sai a tabela custo-benefício.
  5. ROSTER— humano promove a linha medida (override privado AI_SQUAD_ROSTER_<ROLE>).
```

Conforme papéis são rosteados, eles **substituem o humano** nos passos 2–3: o `code-writer`
rosteado faz o DRAFT; o `code-reviewer` rosteado faz o GATE. É aí que o squad passa a se
construir sozinho, em OpenRouter, poupando o orquestrador caro.

## Custo-benefício (como o roster escolhe)

Fronteira medida, não chute: **detecção por centavo** como eixo primário, **over-flag** como
penalidade (um modelo que grita vulnerabilidade em código limpo custa confiança), **latência**
como desempate. A régua é determinística (`rulers.py`) — nunca modelo-julga-modelo (D6/D7).

## Camada de skills (D10) — opcional e gated

Um `SkillSpec` (espelho de `roles.py`) permite persona+skill. Três travas antes de rostear:
1. **Licença por-skill** — o catálogo MIT não cobre o upstream linkado; ler antes de empacotar.
2. **Script executável = Fase 2** — rodar o script é execução de código, atrás do hardening A1-A5.
3. **Medir o ganho** — persona+skill só entra se bater persona-sozinha no gold (N>=5).

## Limitações conhecidas (próximo hardening do loop)

- **Checkpoint não é incremental.** `code_review_eval` só grava o checkpoint DEPOIS do `run_squad`
  fechar o lote — um kill/timeout no meio perde o lote (e o gasto). Mitigação atual: rodar
  POR-MODELO (lotes menores que fecham dentro do timeout). Hardening: cada job auto-checkpoint
  via `on_event`/thunk (cuidado com append concorrente de N workers).
- **Régua de detecção é keyword** (`contains_any`): mede se o bug foi *nomeado*, não se a correção
  está certa — recall-de-menção. Sinal real mas grosso; um juiz de *qualidade da correção* é um
  degrau futuro (e, se for modelo, cai sob D6/D7).
- **Over-flag mede com poucos casos limpos** — sinal direcional, não taxa precisa de FP.
