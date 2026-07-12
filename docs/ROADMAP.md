# Roadmap — a máquina unificada

> O que falta para a pilha `subagente (D11) + skill (D10) → modelo MEDIDO (este motor) → substrato ruflo (D14)`
> virar uma máquina-de-resolver-problemas autônoma, barata e auditável. Status honesto por track.
> Números/slugs medidos NÃO entram aqui (moat, D1) — ficam no roster privado.

Legenda: ✅ feito · 🔄 em andamento · ⬜ a fazer · 🔒 bloqueado (pré-req)

## Track A — Firmar o CÉREBRO (papéis medidos; a ordem é o flywheel, D9)

- ✅ **A1. Papel #1 `code-reviewer`** — gold duro simétrico (6 bugs + 4 gêmeos-limpos), medido N≥10;
  workhorse custo-frontier identificado. *Pendente humano:* cravar a promoção (D5).
- 🔄 **A2. Papel #2 `security-auditor`** — re-medido (gold humano, 5 buggy + 2 clean over-flag; N=5;
  pool CHINÊS). ACHADO HONESTO nº1 (instrumento): a persona de catálogo verbosa manda "query context
  manager first" e o titular OBEDECIA — emitia JSON de pedido-de-contexto em vez de auditar (pass baixo,
  artefato PURO do instrumento). Corrigido com `system_suffix` task-forcing (B4); re-medido → o titular
  salta pro topo. ACHADO nº2
  (saturação): pós-fix, a maioria dos modelos chineses fica quase no teto (detecção satura; réguas de detecção
  permissivas) → o gold NÃO discrimina o topo; o eixo over-flag só separa o mais fraco (over-flag no caso
  constant-time). SEM barra frontier (política 07-12: só chineses). AÇÃO p/ FIRMAR: (a) sempre aplicar o
  `system_suffix` com personas verbosas; (b) gold precisa de casos MAIS DUROS (humano) p/ separar o topo.
  NÃO promove (D5; dado saturado não justifica). Números privados em `_candidate_evals/` (gitignored).
- 🔄 **A3. Papel #3 `qa/test-judge`** — gold DRAFT hand-revisado + medido EXPLORATÓRIO (recall-only, N=5,
  pool all-Chinese). ACHADO HONESTO: as réguas iniciais eram estreitas demais e SUB-contavam respostas
  CORRETAS (um modelo forte dizia "does not verify that dividing by zero raises ValueError" e a régua
  marcava como miss) — pego lendo os outputs à mão; réguas dos casos 1&2 alargadas por domínio e
  re-scored do cache ($0). LIMITE: gold é all-buggy → mede recall, NÃO over-flag → NÃO promove. BLOQUEADO
  em humano: bênção do gold DRAFT (D6) + autorar casos-limpos (eixo over-flag) + régua verdict-aware.
- ⬜ **A4. Papel #4 `architect-reviewer`** — gold + medir.
- ⬜ **A5. Papel #5 `debugger`** — gold + medir.
- ✅ **A6. Gate anti-erro-de-autor** (`gold_preflight`) — veta caso-limpo "não-limpo" antes de gastar (D12).
  *Usar em TODO gold novo (A2–A5).*

## Track B — Runner role-agnóstico (velocidade, DIP)

- ✅ **B1.** `role_eval.py` — runner ROLE-AGNÓSTICO: régua vem do gold via `resolve_ruler` (fallback p/ a
  convenção code-review, roda golds antigos). Fail-closed sem régua. Aditivo (não toca `code_review_eval`). +6 testes.
- ✅ **B2.** Checkpoint idempotente + teto de gasto (herdados no runner genérico).
- ✅ **B3.** Pré-voo de gold (`gold_preflight`) wired no `role_eval` (`clean_preflight_judges`). Pré-voo de
  ROSTER (`preflight.assert_roster_live`, catálogo vivo) agora wired como guarda opt-in fail-closed em
  `run_roles` (`preflight=`, distinct roles) e `role_eval` (`preflight_pool=`, adapta o pool). Default OFF na
  lib (preserva testes herméticos + DIP: pré-voo exige rede); a CLI de `run_roles` liga por default
  (`--no-preflight` desliga). Injetável → teste hermético. +6 testes; verificado live (slug morto ABORTA
  antes de gastar).

- ✅ **B4.** `role_eval(system_suffix=...)` — neutralizador opt-in de RUÍDO DE PROTOCOLO. Personas de
  catálogo verbosas mandam "query context manager first" e alguns modelos OBEDECEM (emitem pedido de
  contexto em vez de auditar) → confundem a medição. Um sufixo task-forcing corrige SEM tocar o gold humano.
  Descoberto medindo A2 (o titular atual "falhava" só por emitir JSON de pedido-de-contexto). +1 teste.
- ✅ **B5.** GOLDS OBJETIVOS sem autoria manual (destrava os papéis ATIVOS): `execution_ruler.py` (aplica o
  patch → roda o teste confiável → pass; fail-closed de isolamento, oracle hard-guard, NUNCA levanta) +
  `git_harvester.py` (colhe fix-commits do histórico → gold cases; verdade HUMANA, anti-autofagia; run_git
  injetável, nunca crasha). Fiado no `role_eval` (`ruler=="execution"`, `exec_run_fn` injetável). Projetado+
  red-teamed por workflow; +33 testes; verificado no repo real (15 casos/120 commits). FALTA: run_fn
  OS-sandboxed real + harvest de commits frescos + validar red→green + medir o code-writer.

## Track C — União com ruflo (o SUBSTRATO, D14)

- ✅ **C0.** Seam desenhado (`docs/design/ruflo-union-routing-seam.md`); ruflo confirmado 3-tier só-Claude.
- 🔄 **C1.** `routing.py` SCAFFOLD: `Route`/`Task`/`RoutingProvider` + `MeasuredRoutingProvider` (intent trivial
  + booster → $0; senão → titular medido) + `NullBoosterAdapter` (ruflo não plugado → fallback gracioso pro
  modelo). +7 testes. Falta o `BoosterAdapter` REAL (WASM/ruflo) — plugar + MEDIR o ganho (depende de C2).
- 🔒 **C2.** Ligar o MCP do ruflo (`claude mcp add ruflo …`, USER) + `memory-bridge` (Graph-RAG cross-sessão).
  VERIFICADO 07-12: neste boot o ruflo NÃO está conectado como MCP server (`claude mcp list` só mostra
  Google Drive/Gmail/Calendar) e não há binário de booster no PATH — só os agent-subtypes/skills do plugin.
  Além do `mcp add`, falta uma COSTURA callable-de-Python: o `routing.py` é lib stdlib standalone e não
  alcança um tool MCP do Claude Code direto → o `BoosterAdapter` REAL precisa do booster exposto por
  HTTP/CLI/WASM. Dois pré-reqs humanos, não-triviais.
- ⬜ **C3.** Experimento N≥5, 3 braços: (A) Super Squad só · (B) +booster $0 · (C) +memória ruflo. Medir o ganho.
- ⬜ **C4.** Plugar SÓ o braço que mover o número (mesmo gate do D10). Se não move, fica fora.

## Track D — Skills (a CAPACIDADE, D10)

- ✅ **D1.** `skills.py` — ingestor `SkillSpec` (espelha `roles.py`, reusa o parser): `compose_system`
  funde persona⊕skill. +7 testes.
- 🔄 **D2.** Licença POR-skill agora é campo de PRIMEIRA CLASSE: `SkillSpec.license`/`.source` do frontmatter +
  `.license_cleared` fail-closed (ausente/DRAFT/UNKNOWN = NÃO liberada). Uma skill consultiva real ingerida
  (`roles/skills/test-design-boundaries.md`, MIT, prosa própria) passa o gate. +3 testes. Vendorizar uma skill
  de TERCEIRO (com a licença real do upstream) segue passo HUMANO — o módulo não baixa/empacota; agora a
  proveniência é auditável em vez de só docstring.
- 🔄 **D3.** MÁQUINA pronta: `role_eval(skill_path=...)` compõe a skill ao system prompt (mesma costura do
  `run_roles`; gate D10 sobe aqui — skill de construtor = Fase 2 não roda por fé). +1 teste hermético. Falta
  só DISPARAR a medição `persona+skill` vs `persona-sozinha` (N≥5) — deferida (foco atual = estrutura).
- ✅ **D4.** Gate no lugar: `compose_system` RECUSA skill que executa código (`requires_script`) em single-shot
  (`SkillGateError`) — script/tool-de-construtor = Fase 2 atrás do hardening A1–A5.

## Track E — Construtores Fase 2 (agentic — o mais ARRISCADO, gated)

- ✅ **E0.** Seam `BuilderRuntime` IMPLEMENTADO + gated: `super_squad/runtimes/base.py` (contrato +
  `NullBuilderRuntime` fail-closed + `assert_builder_preconditions`) + `runtimes/opencode.py` (adapter
  DESABILITADO por default). +12 testes. Unido à pilha, NÃO solto (sem worktree/caps/hardening_ack não executa).
- 🔄 **E1.** Hardening A1–A5 — primitivas de APLICAÇÃO SHIPPED (`runtimes/hardening.py`, +18 testes):
  `WorktreeManager` (A1 raio de explosão: cria/destrói worktree isolada, `session` sempre remove) ·
  `redact_secrets` (A2: chaves/tokens fora de prompt/output/log, idempotente) · `is_bash_allowed`
  (A3 injection: só executável allowlistado, bloqueia encadeamento de shell) · `SpendGuard` (A5 teto
  mid-loop thread-safe) · `enforce_permission` (despacho fail-closed sobre `PermissionProfile`). A4
  (supply-chain) coberto em parte pelo network-gate + allowlist (sem `pip install` arbitrário); política
  completa de supply-chain e o `hardening_ack` HUMANO seguem pré-req DURO da ATIVAÇÃO (E2).
- 🔄 **E2.** Adapter OpenCode: sequência §3 (pré-voo teto global → config efêmera → invocação headless →
  git diff → parse usage → ledger) agora FIADA e exercitada por testes herméticos (subprocess injetado,
  +6 testes). Telemetria `builder_start`/`builder_end` via `on_event` (fail-soft). 3 portões duros: (1)
  `enabled=False` default; (2) `assert_builder_preconditions`; (3) `command_builder=None` default → recusa
  montar argv até §9 (flags reais do binário) ser verificada por humano com um `command_builder` verificado
  injetado. Config nunca embute a chave (referencia env). NÃO ATIVA: rodar o binário exige humano + roster
  de construtor medido. `enabled=True` + merge do diff = gate humano.
- 🔒 **E3.** Roster de construtor RE-medido (persona-construtora medida em modo consultivo primeiro, D8).

## Track F — Governança, produto, reuso

- ✅ **F1.** `run_role` + CLI (porta da frente: usar um subagent medido com UMA chamada).
- ⬜ **F2.** Repo PRIVADO de medições (versionar/backup os números fora do público, D1).
- ✅ **F3.** Declaração pública ANONIMIZADA do benchmark: `docs/BENCHMARK_STATEMENT.md` (tese + o que/como
  se mede + valor qualitativo + limitações honestas + reproduzir). Zero slug/preço/número medido (auditado).
- ⬜ **F4.** Nome do produto (em aberto — o atual subvende o moat de medição/custo-frontier).

## Ordem sugerida (caminho crítico)

A2/A3 (mais papéis medidos = mais moat) **em paralelo com** B1 (runner genérico acelera todos os papéis).
C1–C4 (união ruflo) quando ≥3 papéis firmes derem massa crítica pra medir o ganho de memória. D e E são
camadas posteriores, gated por medição e hardening. F corre em background.
