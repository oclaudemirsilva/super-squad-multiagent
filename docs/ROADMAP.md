# Roadmap — a máquina unificada

> O que falta para a pilha `subagente (D11) + skill (D10) → modelo MEDIDO (este motor) → substrato ruflo (D14)`
> virar uma máquina-de-resolver-problemas autônoma, barata e auditável. Status honesto por track.
> Números/slugs medidos NÃO entram aqui (moat, D1) — ficam no roster privado.

Legenda: ✅ feito · 🔄 em andamento · ⬜ a fazer · 🔒 bloqueado (pré-req)

## Track A — Firmar o CÉREBRO (papéis medidos; a ordem é o flywheel, D9)

- ✅ **A1. Papel #1 `code-reviewer`** — gold duro simétrico (6 bugs + 4 gêmeos-limpos), medido N≥10;
  workhorse custo-frontier identificado. *Pendente humano:* cravar a promoção (D5).
- 🔄 **A2. Papel #2 `security-auditor`** — firmar contra a barra frontier única (gold já existe; re-medir).
- ⬜ **A3. Papel #3 `qa/test-judge`** — autorar gold (D6, mão humana) + vendorizar persona + medir.
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

## Track C — União com ruflo (o SUBSTRATO, D14)

- ✅ **C0.** Seam desenhado (`docs/design/ruflo-union-routing-seam.md`); ruflo confirmado 3-tier só-Claude.
- 🔄 **C1.** `routing.py` SCAFFOLD: `Route`/`Task`/`RoutingProvider` + `MeasuredRoutingProvider` (intent trivial
  + booster → $0; senão → titular medido) + `NullBoosterAdapter` (ruflo não plugado → fallback gracioso pro
  modelo). +7 testes. Falta o `BoosterAdapter` REAL (WASM/ruflo) — plugar + MEDIR o ganho (depende de C2).
- 🔒 **C2.** Ligar o MCP do ruflo (`claude mcp add ruflo …`, USER) + `memory-bridge` (Graph-RAG cross-sessão).
- ⬜ **C3.** Experimento N≥5, 3 braços: (A) Super Squad só · (B) +booster $0 · (C) +memória ruflo. Medir o ganho.
- ⬜ **C4.** Plugar SÓ o braço que mover o número (mesmo gate do D10). Se não move, fica fora.

## Track D — Skills (a CAPACIDADE, D10)

- ✅ **D1.** `skills.py` — ingestor `SkillSpec` (espelha `roles.py`, reusa o parser): `compose_system`
  funde persona⊕skill. +7 testes.
- ⬜ **D2.** Licença POR-skill (catálogo MIT não cobre o upstream linkado — ler antes de empacotar). Registrado
  na docstring; a checagem é humana (o módulo não baixa/empacota, só ingere arquivo local).
- ⬜ **D3.** Medir `persona+skill` vs `persona-sozinha` (N≥5) via `role_eval`; skill que não move o número não entra.
- ✅ **D4.** Gate no lugar: `compose_system` RECUSA skill que executa código (`requires_script`) em single-shot
  (`SkillGateError`) — script/tool-de-construtor = Fase 2 atrás do hardening A1–A5.

## Track E — Construtores Fase 2 (agentic — o mais ARRISCADO, gated)

- ✅ **E0.** Seam `BuilderRuntime` IMPLEMENTADO + gated: `super_squad/runtimes/base.py` (contrato +
  `NullBuilderRuntime` fail-closed + `assert_builder_preconditions`) + `runtimes/opencode.py` (adapter
  DESABILITADO por default). +12 testes. Unido à pilha, NÃO solto (sem worktree/caps/hardening_ack não executa).
- 🔒 **E1.** Hardening A1–A5 (raio de explosão · segredo · injection · supply-chain · teto mid-loop) — pré-req DURO.
- 🔄 **E2.** Adapter OpenCode existe (scaffold); execução REAL não fiada — falta §9 (verificar flags/headless do
  binário) + `enabled=True`. Só ATIVA pós-hardening + roster de construtor medido.
- 🔒 **E3.** Roster de construtor RE-medido (persona-construtora medida em modo consultivo primeiro, D8).

## Track F — Governança, produto, reuso

- ✅ **F1.** `run_role` + CLI (porta da frente: usar um subagent medido com UMA chamada).
- ⬜ **F2.** Repo PRIVADO de medições (versionar/backup os números fora do público, D1).
- ⬜ **F3.** Declaração pública ANONIMIZADA do benchmark (método + valor, sem slug/número).
- ⬜ **F4.** Nome do produto (em aberto — o atual subvende o moat de medição/custo-frontier).

## Ordem sugerida (caminho crítico)

A2/A3 (mais papéis medidos = mais moat) **em paralelo com** B1 (runner genérico acelera todos os papéis).
C1–C4 (união ruflo) quando ≥3 papéis firmes derem massa crítica pra medir o ganho de memória. D e E são
camadas posteriores, gated por medição e hardening. F corre em background.
