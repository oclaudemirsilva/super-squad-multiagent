# Kickoff da próxima sessão — loop MEDIDO (5/9) ✅ · debugger NÃO PROVADO ✅ · falta fonte FRESCA (Obj 3)

> Prompt de retomada auto-contido (retoma a frio). Gerado ao fim da **6ª sessão autônoma (2026-07-15c)**, que
> **mediu o fechamento do loop** (Obj 1: 5/9) e **refutou o ganho do debugger** (Obj 2: N=1 iludiu, N=5 corrigiu).
> A 5ª sessão fechara os 2 confounds do code-writer + construíra/provara E2E o orquestrador. Leia junto:
> `docs/design/loop-orchestrator.md`, `_candidate_evals/code_writer_2026-07-15/FINDINGS.md` (v2, PRIVADO),
> `super_squad/loop.py`, `DECISIONS.md`. Supersede `KICKOFF_NEXT_SESSION_d_loop.md`.

## Estado ao começar
- Branch `feat/subagent-army-pilot`, suíte **319 verde**, **NÃO pushado** (push é do user).
- Commits desta sessão (`ecd4a23..HEAD`): `981155c` applier tolerante + stderr no veredito · `95568f7`
  loop.py (orquestrador) · `e0692a0` doc do smoke E2E. Harness/medições/smoke em
  `_candidate_evals/code_writer_2026-07-15/` (PRIVADO/gitignored).
- ⚙️ ruflo DESLIGADO (lentidão) — não re-adicionar. `effortLevel=max` é escolha do user. WSL2 Ubuntu UP.
- Saldo OpenRouter ≈ **$1.62** (gasto novo desta sessão: $0.50).

## (c) — O NÚMERO HONESTO v2 (SINAL, não promoção; D5 humano)
code-writer, pool chinês, **N=5, 9 golds MENSURÁVEIS**, régua = `execution_ruler`+`wsl_sandboxed_run`:
- **deepseek-v4-pro = 0.52** (topo as-is; destravado pelo fix de reasoning-tokens) · **minimax-m2.5 = 0.51**
  (PRAGMÁTICO: responde sempre, 0 vazias, mais barato $0.106) · glm-4.7 0.47 · v3.2 0.27 · qwen3-coder 0.24
  · qwen3-235b 0.13. **8/9 golds resolvidos por algum modelo.**
- **Os 2 confounds fechados, com achado HONESTO:** (2) reasoning-truncation era REAL e o GRANDE lever
  (v4-pro 21→8 vazias, 0.31→0.52). (1) applier byte-exato: construí o tolerante, mas ele rescatou só **+2
  passes (minimax)** — os `apply_failed` do qwen são **contexto ALUCINADO** (não whitespace) → a hipótese
  "qwen real ≫ 0.13" foi REFUTADA; o número baixo dos qwen é REAL. (Detalhe no FINDINGS.md v2.)

## (d) — O ORQUESTRADOR DE LOOP: CONSTRUÍDO + PROVADO E2E
- `super_squad/loop.py`: `orchestrate(task, *, budget_usd, max_iters=3, roster_writer, roster_debugger,
  run_fn, ...)` puro/injetável. 5 etapas (ROTEAR→INTEGRAR→VERIFICAR→DEBUGAR→repete) + 4 paradas
  (sucesso/teto/iter/travado). `budget_usd` OBRIGATÓRIO. **13 testes herméticos** + **smoke E2E REAL** (gold
  `a84eac0286`, minimax+WSL, red→green em 1 iter, $0.027 — `smoke_loop_e2e.py`).

## O QUE A 6ª SESSÃO (07-15c) FECHOU — Obj 1 e Obj 2 MEDIDOS
- ✅ **Obj 1 — fechamento do loop nos 9 golds:** writer=minimax (decisão humana), max_iters=3, WSL real, sem
  debugger. **5/9 (56%), TODOS na iter-1, $0.167 ($0.019/gold).** Achado: **iter-2/3 fechou +0** — retry-com-
  stderr de um-modelo-só ≈ single-shot (5/9 casa com pass_all 0.51 do minimax). Valor iterativo do laço NÃO
  vem de graça.
- ✅ **Obj 2 — debugger no laço = NÃO PROVADO.** Proxy nos 4 não-fechados: minimax-dbg **0/4**; glm-4.7-dbg
  pareceu resgatar 1 (`2c6b8cf384` iter-2) a N=1 → **firming N=5 REFUTOU** (as 5 closures do glm foram iter-1
  ⇒ debugger nunca acionado; gold é alta-variância, no_debug fecha 3/5 sozinho). Nenhum efeito positivo
  sobreviveu ao N=5. **Bloqueio metodológico:** os 9 golds fecham cedo demais na iter-1 → o debugger raramente
  é exercido. Medir o debugger exige golds que FALHEM confiável na iter-1 (→ Obj 3). Detalhe: FINDINGS.md v2.
- Harness novo (privado): `measure_loop_closure.py`, `firm_pivotal_gold.py`. Suíte **319 verde** (source intocado).
  Commits `880a9cf` (métrica) + o deste fechamento. Gasto da sessão $0.453; saldo OpenRouter ≈ $1.17.

## OBJETIVO da PRÓXIMA sessão (o degrau que restou)
1. **Fonte de PROMOÇÃO humana/não-memorizada** (trava nº1 do vazamento; firma titular E desbloqueia a medição
   do debugger): plugar BugsInPy/Defects4J/QuixBugs no MESMO `execution_ruler` → golds FRESCOS **e mais duros**
   (falham iter-1 de forma confiável ⇒ o laço itera de verdade ⇒ o debugger é exercido). Promoção = HUMANA
   (D5/D6). 4 travas: vazamento (calibração, NUNCA promoção sem held-out fresco), só origem humana, licença por
   fonte, transferência de domínio (mede lá, REVALIDA no nosso).
2. **(condicional ao 1)** Re-medir o debugger nos golds que falham iter-1 confiável — agora com o diagnóstico
   sendo exercido. Só entra no titular se mover o número (D10). Draft-gold do debugger (autoro, USER bendiz)
   segue como opção se a fonte externa não der golds-que-falham-iter1 suficientes.

## Guardrails (inegociáveis)
- Promoção pra titular é **HUMANA (D5)** — eu meço, o user bendiz. Régua por EXECUÇÃO; o modelo nunca autora
  o juiz (D6/D7). Pool só chinês (D16). Reasoning → `max_tokens≥4000`. Persona verbosa → suffix.
- Commit SELETIVO (`git commit -m "msg" -- <path>`, nunca `-A`); teto ~$1/teste; push é do user.
- **VAZAMENTO (trava nº1):** golds atuais são AI-assistidos + do próprio repo → SINAL. Titular pede gold HUMANO.

## O harness/loop (usar, não reconstruir) — `_candidate_evals/code_writer_2026-07-15/`
- `measure_code_writer.py` (`--stage patches/verdicts/aggregate`, checkpoint JSONL, cap thread-safe; reasoning
  detecta v4-pro/glm → mt=4000). `triage_golds.py` → 9 mensuráveis. `smoke_loop_e2e.py` (E2E do loop).
- Backups da medição v1: `patches.v1.jsonl.bak`/`verdicts.v1.jsonl.bak`. `.env` do ViralCutter = OPENROUTER_API_KEY.
