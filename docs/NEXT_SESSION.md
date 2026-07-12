# Ponto de retomada — próxima sessão

> Âncora de contexto para continuar sem perder o fio. Estado em **2026-07-12** (3ª sessão autônoma, foco
> DESTRAVAR O CODE-WRITER). Branch `feat/subagent-army-pilot`, suíte **~281 verde**, ZERO dívida técnica.
> Leia junto: `docs/ROADMAP.md` (status por track), `docs/INTEGRATION.md` (o que está plugado), `DECISIONS.md`.
>
> **★ 3ª sessão (07-12) FECHOU os elos (a)+(b) do substrato de medição objetiva** (o chão que destrava o
> code-writer): **(a)** `super_squad/wsl_sandbox.py` — `run_fn` OS-sandboxed REAL sobre WSL2 (rede off, FS
> do host escondido via tmpfs, PID iso, efêmero) → o `execution_ruler` saiu do *fail-closed* e EXECUTA
> (17 herméticos + 4 smoke real; commit `b517e53`). **(b)** `super_squad/harvest_validate.py` — valida
> red→green os fix-commits colhidos → **15/16 golds do code-writer PROVADOS mecanicamente** (zero autoria
> manual; commit `9e0a9ae` + fallback file-only). Golds persistidos em `_candidate_evals/golds_code_writer/`.
> Dogfood cumprido: o code-writer rascunhou o `run_fn` ($0.0067); o gate pegou 2 bugs reais dos drafts.
> **PRÓXIMO = (c):** medir o code-writer nesses 15 golds (pool chinês, `system_suffix`, N≥5) e trazer o
> número — a **promoção continua HUMANA (D5)**. Depois, (d) esboçar o orquestrador de loop.

## Onde estamos (uma tela)

O **Super Squad Multiagente** é um motor de roteamento multi-modelo MEDIDO com regime de integridade. A
união das forças:

| Força | Status | Prova |
|---|---|---|
| Subagentes (persona + roster medido) | ✅ integrado | `run_role.py`, `run_roles.py` |
| Skills (playbook composto, gated) | ✅ integrado | `skills.py` + wiring |
| OpenCode (construtor Fase 2) | 🟡 fiado, ENJAULADO (3 portões, não ativa) | `runtimes/{base,hardening,opencode}.py` |
| ruflo (memória/booster/custo) | 🔴 só a costura (`NullBoosterAdapter`) | `routing.py` |

## O que a sessão 07-12(2) entregou (11 commits, `3961435..HEAD`)

- **E1** hardening A1–A5 (`runtimes/hardening.py`) · **E2** sequência §3 do OpenCode fiada+gated (`runtimes/opencode.py`).
- **B3** pré-voo de roster fail-closed · **B4** `system_suffix` (neutraliza ruído de persona verbosa) em `role_eval` E `run_roles`.
- **D2** licença de skill auditável + 1 skill · **D3-máquina** `role_eval(skill_path=...)` (skill-lift).
- **F3** `docs/BENCHMARK_STATEMENT.md` · **INTEGRATION.md** · docstrings/README atualizados · **D15/D16** decididos.

## Medições (privadas, `_candidate_evals/FINDINGS_2026-07-12.md`) — 2 bugs de INSTRUMENTO pegos à mão
- **A2 security-auditor:** persona verbosa fazia o titular PEDIR contexto em vez de auditar (artefato, não fraqueza)
  → consertado com `system_suffix`. Pós-fix o gold SATURA no topo entre os chineses → **não discrimina, NÃO promove.**
- **A3 qa-test-judge:** régua DRAFT estreita sub-contava respostas corretas → alargada por domínio, re-scored do cache.
  Gold é all-buggy (recall-only) → **não promove** sem casos-limpos (over-flag) + bênção humana.

## Política vigente (não esquecer)
- **Testes SÓ com IAs chinesas**; âncora frontier externa SUSPENSA (D16).
- Preferir os **melhores/mais eficientes** chineses (não os mais baratos); lista viva em `_candidate_evals/POOL_CHINESE_TOP12.md`.
- **Persona verbosa** → sempre `system_suffix`. **Reasoning models** (glm-*/*-thinking/r1) → `max_tokens≥2000` senão VÊM VAZIOS.
- **Foco atual = ESTRUTURA** (não gastar em mais shootout agora). Gold humano (D6), promoção humana (D5).

## ★ PRIORIDADE-MÃE (user 07-12): subagentes ESPECIALISTAS ATIVOS → automelhoria contínua do projeto

O norte não é "mais revisores"; é **destravar subagentes ESPECIALISTAS que trabalham ATIVAMENTE na melhoria
e evolução do projeto**, formando um loop de **automelhoria contínua**. "Ativo" = quem ESCREVE/CONSERTA/TESTA,
não só quem julga. Os 11 atuais são todos CONSULTIVOS (revisam) → falta a metade que RESOLVE.

**INSIGHT: o loop de automelhoria começa SEM OpenCode**, via o padrão DOGFOOD (writer medido rascunha →
reviewer+qa+security medidos fiscalizam → gate aplica → testes rodam → debugger no erro → repete). O OpenCode
(Fase 2) só AUTOMATIZA o passo "aplica" depois; não é pré-requisito pra começar a evoluir o projeto.

**Subagentes a destravar, em ordem de dependência (D9). Destravar = eu autoro a PERSONA especialista +
autoramos/bendizemos o GOLD (humano, D6) + eu MEÇO (pool chinês, `system_suffix`, N≥5) + firma (D5).
O gargalo é sempre o GOLD, não a persona.**

- **Onda 1 — o FISCAL (torna os ativos confiáveis; firmar PRIMEIRO):**
  1. `code-reviewer` — quase firme; é o gate do output do writer. **Firmar primeiro.**
  2. `qa-test-judge` — endurecer o gold (casos-limpos/over-flag); julga os testes.
- **Onda 2 — os ATIVOS (especialistas que FAZEM; a keystone do "ativo"):**
  3. **`implementer`/`code-writer`** — escreve a mudança. ✅ PERSONA AUTORADA 07-12 (`roles/vendor/code-writer.md`,
     consultiva: devolve o PATCH como texto, o gate aplica — encaixa no dogfood sem OpenCode). Medir + firmar
     (pool chinês). O GOLD dele vem SEM autoria manual (ver abaixo). É o 1º a medir na Onda 2.

### ★ COMO OBTER GOLDS SEM AUTORIA MANUAL (decidido 07-12) — DESTRAVA o code-writer
Distinção: papéis de JUÍZO (over-flag) precisam de verdade humana; papéis ATIVOS têm verdade EXECUTÁVEL.
Para os ativos (writer/test/debugger) a régua é OBJETIVA — não se autora um "patch esperado":
- ✅ **CONSTRUÍDO 07-12 (zero-gasto):** `super_squad/execution_ruler.py` (régua de EXECUÇÃO fail-closed +
  oracle guard + applier stdlib, +21 testes) e `super_squad/git_harvester.py` (colhe fix-commits → gold cases,
  +10 testes, verificado no repo REAL: 15 casos de 120 commits). Fiado no `role_eval` (`ruler=="execution"`).
- ✅ **(a) FEITO 07-12(3ª):** `super_squad/wsl_sandbox.py` — o `run_fn` OS-sandboxed REAL (WSL2: `unshare
  --net --mount --pid`, tmpfs sobre /mnt, workspace ext4 efêmero). O `execution_ruler` EXECUTA (não mais
  fail-closed). Isolamento PROVADO (17 herméticos + 4 smoke real: rede off, /mnt escondido, exit fiel).
  Honesto: kernel compartilhado com a VM WSL2 → cerca forte, não anti-inquilino-hostil (troca por nsjail/
  microVM sem tocar a régua). 3 gotchas do wsl.exe documentados no módulo (`$(...)`/`$?` vazios, posicionais
  descartados, drives 9p). Commit `b517e53`.
- ✅ **(b) FEITO 07-12(3ª):** `super_squad/harvest_validate.py` — valida red→green (RED=árvore-do-pai+teste
  falha; GREEN=árvore-do-fix passa; materializa a árvore COMPLETA via `git archive`, semântica BugsInPy).
  **REAL: 15/16 golds do code-writer PROVADOS** (1 rejeitado corretamente: baseline não falhou). Fallback
  file-only resgata quando o seletor `::função` não coleta (rc4). Golds em `_candidate_evals/golds_code_writer/
  golds_red_green.json` (base64, privado). 11 herméticos. Commit `9e0a9ae` (+ fallback).
  **FALTA (próxima sessão):** (c) medir o `code-writer` nesses 15 golds (pool chinês, `system_suffix`, N≥5)
  → trazer o número → **firmar é HUMANO (D5)**. O `run_role` já roda o papel; falta rodar o `execution_ruler`
  com esses golds contra o output do writer (loop de avaliação por execução).
- **LINHA DURA:** o modelo MEDIDO nunca autora o próprio juiz. Harvestar trabalho de OUTROS humanos = ok.
- **CUIDADO DE VAZAMENTO:** modelos podem ter MEMORIZADO fixes públicos famosos → preferir commits recentes/privados,
  de-dup por fonte (group_key=source), senão o número mente pra cima. Vale a lição do split-por-source já medida.
- Para papéis de JUÍZO (qa over-flag, security): baratear o humano via COLHER (git/issues/CVEs) + DRAFT→ratificar
  + o gate `gold_preflight` (D12). Não elimina o humano; torna-o minutos, não horas.

### ★ FONTES EXTERNAS DE VERDADE (decidido 07-12) — expertise que não temos + golds sem autorar
Trazer verdade HUMANA/institucional de fora enriquece o repo (mais papéis medidos, expertise emprestada).
Ordem de adoção:
1. **`security-auditor` over-flag (destrava A2):** OWASP Benchmark + NIST Juliet/SARD — código rotulado
   vulnerável vs. seguro em pares = exatamente o eixo de over-flag que falta. + um held-out FRESCO por cima.
2. **`code-writer`/`debugger` (oráculo executável):** BugsInPy / Defects4J / QuixBugs (bug real + teste) — via o
   `execution_ruler`. Mutation testing = bugs objetivos sem rótulo.
3. **Harvester de CVEs recentes + commits frescos** de repos que NÃO são nossos e o modelo não viu → fonte
   contínua não-memorizada.
**4 TRAVAS (a nº1 é a que mais importa):**
- (1) **VAZAMENTO/memorização** = maior risco: dataset público famoso mede "memorizou?", não "raciocina?" →
  usar como CALIBRAÇÃO/smoke, NUNCA como gold de PROMOÇÃO. O gold que firma titular fica FRESCO/privado + held-out.
- (2) **Só origem HUMANA/institucional** — dataset gerado por LLM = importar autofagia dos outros. Verificar proveniência.
- (3) **Licença POR FONTE** (D2) — ler antes de empacotar (alguns são research-only).
- (4) **Transferência de domínio** (D11) — gold externo = prior fraco; mede lá, REVALIDA no nosso domínio.
Fronteira: fonte externa HUMANA = enriquece; gerada por modelo, ou de promoção sem held-out fresco = perigo.
  4. **`test-author`** — escreve testes p/ a mudança → o loop se auto-verifica.
  5. **`debugger`** — diagnostica falhas no loop (persona existe; falta gold).
- **Onda 3 — meta/estrutura (guardam a evolução):**
  6. `architect-reviewer` — a estrutura não apodrece enquanto evolui.
  7. `eval-engineer` — melhora os próprios golds/réguas (automelhoria da MEDIÇÃO).
- **Onda 4 — especialistas de DOMÍNIO do produto** (quando apontar o loop pro ViralCutter/FrameOracle):
  ex. pipeline-de-vídeo · caption/kinetic-text · modelagem · render/ffmpeg. Precisam de golds de domínio.

**O loop (automelhoria contínua):** `implementer` rascunha → painel medido (`code-reviewer`+`qa`+`security`)
fiscaliza → gate aplica (eu; depois OpenCode) → suíte roda → `debugger` no erro → repete, com critério de
parada + teto de gasto. É o `docs/design/flywheel-bootstrap.md`, faltando o ORQUESTRADOR de loop (esboçar).

---

## FASE 2 / OpenCode — automatiza o passo "aplica" (em RAMPA, não a chave a frio)

> **AUTORIZAÇÃO do user (07-12): "vc pode ligar o opencode"** — o portão HUMANO de `enabled=True` está
> LIBERADO (o Claude pode ativar). MAS dois pré-requisitos FÍSICOS continuam de pé, independentes de permissão:
> **(0) o OpenCode NÃO está instalado** nesta máquina (verificado 07-12: fora do PATH, sem `~/.opencode`, não é
> pacote npm global) → **instalar primeiro**; **(§9) as flags reais do binário não foram verificadas** → o
> `command_builder=None` recusa por design até validar. Ou seja: autorização ≠ capacidade. Sequência abaixo.

Ordem acordada (flywheel D9: o fiscal medido vem ANTES do construtor). "Iniciar" = rampa de acesso segura;
`enabled=True` é o FIM da rampa, numa tarefa trivial, com o user no gate do merge.

**Passo 0 (pré-requisito físico):** INSTALAR o OpenCode + confirmar que roda. Sem binário, nada de §9/ativação.

**Eu faço sozinho (zero-gasto, nada ativa):**
1. **Esboçar o ORQUESTRADOR DE LOOP** — decompõe problema → roteia pros subagentes → integra → VERIFICA
   (régua/juiz determinístico) → critério de parada + teto de gasto. Construtor segue GATED. É a peça que
   falta pra "loop por horas" ter sentido (hoje só há `run_roles` = 1 fan-out, sem laço/verificação/parada).
2. **Medir um BUILDER em modo CONSULTIVO (D8)** — diff no prompt, nada toca o disco; sinal de qualidade de
   construção sem risco. Pool chinês (D16), `system_suffix` ligado, `max_tokens≥2000`.

**Precisa do HUMANO (a §9 reserva supervisão):**
3. **Verificar a §9 JUNTOS** — rodar o OpenCode UMA vez com o user olhando p/ aprender as flags reais
   (headless, parse de usage, permissões). Sem isso o `command_builder` recusa por design (portão 3 do E2).
4. **Firmar ≥1 fiscal (code-reviewer)** — endurecer 1 gold + medir + o user bendiz (D5/D6). É o gate que
   fiscaliza o construtor.

**Só DEPOIS de (3)+(4):** 1º build ENJAULADO numa tarefa trivial, `enabled=True`+`hardening_ack=True`, user
no gate do merge. Critério de "pode ligar": §9 verificada + 1 fiscal medido + loop-com-verificação existe +
tarefa trivial + user no merge.

### Depois da Fase 2 (backlog, mesma prioridade honesta)
- **Golds mais DUROS (humano, D6)** — os atuais SATURAM; A3 precisa de casos-limpos + régua verdict-aware;
  A2 vulns mais sutis + mais clean traps; apertar réguas de detecção permissivas ("alg"/"signature"/"redirect").
- **A4 architect-reviewer / A5 debugger** — autorar gold DRAFT + medir.
- **Conectar o ruflo (Track C)** — `claude mcp add ruflo …` + booster callable-de-Python → medir 3 braços
  (só squad / +booster / +memória) → plugar só o que mover o número.

## Fica com o humano (não fazer sozinho)
Bênção de golds (D6) · promoções de roster (D5) · ativar OpenCode (`enabled=True`) · conectar ruflo MCP ·
abrir PR `feat/subagent-army-pilot`→main · nome do produto (F4) · repo privado de medições (F2).

## Comandos de retomada
```
# suíte (da raiz do repo)
cd /c/Users/ClaudemirNotebook/labs/super-squad-multiagent && python -m pytest -q
# chave + rosters vêm da .env PRIVADA do ViralCutter (ver driver _env.py no scratchpad da sessão)
# saldo OpenRouter: GET https://openrouter.ai/api/v1/credits (Bearer key)
# medir um papel: super_squad.role_eval.run_role_eval(gold, persona, pool, system_suffix=..., preflight_pool=True)
```
