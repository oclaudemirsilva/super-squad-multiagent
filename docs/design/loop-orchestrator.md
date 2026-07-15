# Orquestrador de loop — o laço que falta pra automelhoria contínua (esboço, D9)

> Registro de design (zero-gasto, solo). Hoje o squad tem **um fan-out** (`run_roles`) — dispara N
> papéis uma vez e devolve texto. Falta o **laço**: decompor → rotear → integrar → **VERIFICAR por
> execução** → (debugar no erro) → repetir, com **critério de parada** e **teto de gasto**. Este doc
> especifica esse laço. Promoção continua HUMANA (D5); gold de mão humana (D6); a verificação é
> DETERMINÍSTICA e por EXECUÇÃO — nunca modelo-julga-modelo (D6/D7). Complementa
> `flywheel-bootstrap.md` (que é o loop de MEDIÇÃO por-papel; este é o loop de RUNTIME que RESOLVE
> uma tarefa).

## O que já existe (peças provadas, não reconstruir)

| Estágio do laço | Peça que já existe | Prova |
|---|---|---|
| ROTEAR (fan-out) | `run_role` / `run_roles` (persona + roster medido, concorrente, fail-soft) | 281 testes |
| INTEGRAR (aplicar o patch) | `execution_ruler._default_apply` (diff unificado OU arquivo-inteiro, whole-or-nothing, contenção de caminho) | herméticos |
| VERIFICAR (execução) | `execution_ruler(run_fn=wsl_sandboxed_run)` — aplica o patch, roda o teste confiável isolado (rede off, /mnt escondido) | 17 herméticos + smoke real |
| GOLD objetivo | `harvest_validate` (red→green) + `git_harvester` | 9/15 golds mensuráveis medidos (sessão 07-15) |
| Teto + checkpoint | `run_squad(budget_usd=...)` + JSONL idempotente | harness `measure_code_writer.py` (07-15) |

**O harness de medição do code-writer (07-15) já é um proto-orquestrador de UM tiro:** fan-out de
patches (pago) → verify por execução ($0, WSL) → agrega, com checkpoint e cap. O orquestrador de loop
é esse mesmo substrato **fechado num laço com realimentação** (o erro do teste volta pro próximo tiro).

## O laço (runtime, resolve UMA tarefa bem-especificada)

```
orchestrate(task, *, max_iters=3, budget_usd=1.0, roster_writer, roster_debugger):
  ctx = decompose(task)                       # 1. DECOMPOR
  history = []
  para iter em 1..max_iters:
    if spent >= budget_usd: parar("teto")     #    GUARDA de gasto (dura)
    draft = route("code-writer", ctx+history, roster_writer)   # 2. ROTEAR (fan-out N modelos)
    patch = pick(draft)                        #    escolhe o candidato (titular, ou o 1º que aplica)
    applied = integrate(patch, base_files)     # 3. INTEGRAR (apply whole-or-nothing)
    if not applied.ok:
      history += falha_de_apply(applied); continue
    verdict = verify(applied, test_cmd, run_fn=wsl_sandboxed_run)   # 4. VERIFICAR por execução
    if verdict.pass:
      return Sucesso(patch, iter, spent)       #    PARADA: passou (critério objetivo)
    diag = route("debugger", ctx+verdict.stderr, roster_debugger)   # 5. DEBUGAR no erro
    history += diag                            #    realimenta o próximo tiro
  return Falha(melhor_tentativa, motivo, spent)  # PARADA: max_iters ou teto
```

### Estágios (cada um mapeia numa peça existente)

1. **DECOMPOR** — corta a tarefa no que cabe num tiro de escritor: `spec + arquivo(s)-alvo + teste que
   deve passar`. Hoje isso é o `compose_input` do harness. Tarefas grandes viram vários alvos-de-teste
   (um laço externo por teste). *Não* pede módulo novo às cegas (lição 07-15: 6/15 golds eram feature-
   commits que exigiam autorar módulo inteiro → mis-scoped; o decompositor tem que dar TODO o contexto
   que o teste importa, ou o alvo é impossível).
2. **ROTEAR** — `run_roles` dispara o `code-writer` (e, opcional, um painel de N modelos do pool
   chinês). Fail-soft: modelo vazio/erro não derruba o lote.
3. **INTEGRAR** — `_default_apply`: aplica o diff por CONTEÚDO (offset-independente), whole-or-nothing.
   Um patch que não aplica é uma falha honesta que realimenta (não um pass silencioso).
4. **VERIFICAR** — `execution_ruler` roda o teste do gold no `wsl_sandboxed_run` (rede off, host
   escondido, efêmero). `pass = o teste passou`. **É o oráculo** — humano/executável, nunca um modelo.
5. **DEBUGAR** — no fail, o `debugger` recebe o stderr do teste + o diff tentado e propõe o próximo
   passo. É o que fecha o laço de auto-conserto (vs. só re-tentar cego).

## Critérios de parada (todos duros, ordem de precedência)

1. **Sucesso** — `verdict.pass` (objetivo, por execução). Retorna o patch que passou.
2. **Teto de gasto** — `spent >= budget_usd` (acumulado no `run_squad`). Nunca estoura o orçamento.
3. **Iterações** — `iter > max_iters` (default baixo, 3). Evita o laço infinito.
4. **Sem-progresso** — mesmo `stderr`/`label` 2 vezes seguidas ⇒ o modelo travou; para (não queima
   reps idênticos). Espelha o padrão "loop-until-dry" mas invertido (until-stuck).

## Guarda-corpos (inegociáveis, herdados do regime de integridade)

- **APLICAR NO MUNDO REAL = HUMANO (D5).** O orquestrador resolve contra um GOLD (sandbox); levar o
  patch pro repo de verdade é merge humano. "Ligar o loop" em produção é decisão sua, não minha.
- **Oráculo humano/executável (D6/D7).** A verificação é `execution_ruler` — teste que veio de mão
  humana (ou harvestado de humano), rodado isolado. O modelo medido NUNCA autora o próprio juiz.
- **Teto de gasto SEMPRE presente** (arg obrigatório, sem default infinito). Um laço autônomo sem teto
  é um vazamento de dinheiro.
- **Pool chinês (D16), `max_tokens>=2000` p/ reasoning (senão vêm vazios), persona verbosa → suffix.**
- **Zero dívida / resumível (D-durável):** cada iteração checkpointa (patch + veredito) → um kill não
  re-paga. Já é o padrão do harness.

## O que NÃO é (fronteira honesta)

- **Não é o OpenCode.** O OpenCode (Fase 2, gated) automatiza o passo INTEGRAR fora do sandbox (escreve
  no disco de verdade). Este orquestrador integra DENTRO do sandbox de verificação — não precisa de
  OpenCode pra existir, e roda em OpenRouter (braçal barato), não no orquestrador caro.
- **Não promove nada.** Ele RESOLVE tarefas; o ranking/roster continua saindo do loop de MEDIÇÃO
  (`role_eval`, N>=5) com bênção humana.
- **Não decompõe problemas abertos ainda.** A v0 assume tarefa já-especificada com um teste-alvo. O
  decompositor de problemas vagos (spec→testes) é um degrau posterior (e precisa do próprio gold).

## Próximo passo concreto (quando for construir, com gold + teste antes)

1. `super_squad/loop.py` — `orchestrate(task, *, max_iters, budget_usd, roster_writer, roster_debugger,
   run_fn)` puro/injetável (fakes p/ teste hermético; zero rede/WSL nos testes), espelhando o harness.
2. Gold do loop = os **9 golds mensuráveis** (07-15) usados como tarefas E2E: o loop deve fechar red→green
   sozinho num teto de $ e ≤3 iterações. Métrica: taxa de fechamento por iteração + custo.
3. Medir o ganho do **debugger no laço** (iter-2 com diagnóstico vs. re-tentar cego) — só entra se mover
   o número (mesma disciplina do D10 pra skills).
