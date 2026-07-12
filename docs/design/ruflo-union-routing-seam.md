# Seam de união com ruflo — `RoutingProvider` (design, não implementado)

> Status: **DESIGN**. Nada aqui está implementado. A disciplina (D10) é **medir o ganho N≥5 antes de
> plugar** — este doc descreve a costura e o experimento que a justifica, não código a mergear por fé.

## Motivação — uma pilha só

A visão é compor quatro camadas num stack único, cada uma fazendo o que faz melhor:

```
  subagente (QUEM — persona portável, D11)
    + skill (COMO — capacidade/playbook, D10)
      → roda no MODELO MEDIDO (Super Squad: roster custo-frontier + gate de integridade)
        → sobre SUBSTRATO (ruflo: memória Graph-RAG cross-sessão, custo, Agent Booster Tier-1)
```

## Fato que determina a forma da união (verificado por leitura, 2026-07-12)

O roteador de modelo do ruflo (`intelligence-route`, base `claude-flow`) é **3-tier só-Claude**:

| Tier | Handler | Custo | Quando |
|---|---|---|---|
| 1 | Agent Booster (WASM local) | **$0** | transforms determinísticos triviais (var→const, add-types, remove-console…) — pula o LLM |
| 2 | Haiku | ~$0.0002 | baixa complexidade |
| 3 | Sonnet/Opus | $0.003–0.015 | raciocínio/arquitetura/segurança |

Ele **não roteia modelos heterogêneos** (o "Eixo B" — escolher o provedor/modelo mais barato que serve
a tarefa entre várias famílias). O `agentic-flow` (que upstream fala com múltiplos provedores) é
dependência do ruflo, mas está wired só para token-optimizer + agent-booster, com fallback inerte.

**Consequência:** na união, **o Super Squad é a autoridade de roteamento de modelo** — é a única camada
que entrega o Eixo B. O ruflo entra como **substrato** (memória/custo) e como **fornecedor do Tier-1 $0**.

## O seam — `RoutingProvider`

Uma interface fina (DIP) que responde "para esta tarefa, qual EXECUTOR?". Um `Route` é o veredito:

```
class Route:
    tier: "booster" | "model"        # $0 local  vs  chamada a modelo
    handler: str                     # id do transform booster  OU  slug de modelo do roster
    est_cost_usd: float
    rationale: str                   # auditável (por que este tier/handler)

class RoutingProvider(Protocol):
    def route(self, task: TaskSpec) -> Route: ...
```

Ordem de decisão (barata → cara), toda determinística:

1. **Tier-1 trivial → Agent Booster do ruflo ($0).** Se a tarefa casa um intent de transform determinístico
   (a lista fechada do booster), roteia para o WASM local — nenhum token gasto. Ganho grátis que o
   Super Squad hoje não colhe.
2. **Resto → roster MEDIDO do Super Squad (OpenRouter).** O modelo é o titular medido do papel (o mais
   barato que empata a barra frontier no gold), via `run_role`. Determinístico: o roster vem da medição,
   não de palpite.

O adapter do booster fica atrás do seam (`BoosterAdapter`), injetável — igual ao `BuilderRuntime`/OpenCode:
o motor não importa ruflo direto; um adapter opcional o expõe, e some com fallback se o ruflo não estiver
instalado (mesmo padrão graceful do próprio ruflo).

## Fronteira de determinismo (regra dura, já existente)

- **Runtime = só roteamento MEDIDO/DETERMINÍSTICO** (roster do Super Squad, temp=0). Auditável, reprodutível.
- **Roteamento neural/aprendido do ruflo (SONA) = dev-loop APENAS**, nunca no runtime (Cloud Run Rule #2).
  Pode *sugerir* no dev-loop; não *decide* execução de produção.

Não borrar as duas. O `RoutingProvider` de runtime é o do Super Squad; o do ruflo, se usado, roteia só
o Tier-1 booster (que é determinístico, não neural).

## Integridade preservada

- **D6 (gold de mão humana):** a memória Graph-RAG do ruflo é CONTEXTO/recall, jamais entra como ground-truth.
- **D5 (promoção humana):** o roster continua promovido por humano com N≥5; o ruflo não auto-rewira.
- **Anti-autofagia:** nenhuma saída de modelo (nem memória do ruflo) vira juiz de si mesma.

## O experimento que justifica plugar (antes de mergear)

Hipótese: **união barateia sem perder qualidade.** Medir, no mesmo gold de um papel, três braços N≥5:

1. **A — Super Squad sozinho** (roster medido, sem booster, sem memória).
2. **B — + Agent Booster Tier-1** (tarefas triviais desviadas p/ $0): mede fração desviada e $ economizado
   sem queda de detecção/over-flag.
3. **C — + memória Graph-RAG do ruflo** (recall de casos passados no prompt): mede se detecção sobe ou o
   custo cai a qualidade igual.

Plugar só o braço que **move o número** (o mesmo gate do D10 para skills). Se B/C não melhoram, ficam fora
— o Super Squad sozinho já é a linha de base honesta.

## Fora de escopo aqui

Implementação do `RoutingProvider`/`BoosterAdapter`, wiring do MCP do ruflo, e o runner do experimento.
Só entram depois que o gold do papel-alvo estiver firme e o experimento acima estiver desenhado como
código medível. Ver `flywheel-bootstrap.md` (ordem de papéis) e `subagent-portability.md` (contrato do subagente).
