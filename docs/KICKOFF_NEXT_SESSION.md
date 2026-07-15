# Kickoff da próxima sessão — (c) RE-MEDIDO honesto ✅ · (d) loop CONSTRUÍDO+E2E ✅ · falta métrica + gold humano

> Prompt de retomada auto-contido (retoma a frio). Gerado ao fim da **5ª sessão autônoma (2026-07-15b)**, que
> **fechou os 2 confounds de instrumento** (número honesto do code-writer) e **construiu + provou E2E** o
> orquestrador de loop. Leia junto: `docs/design/loop-orchestrator.md`, `_candidate_evals/code_writer_2026-07-15/
> FINDINGS.md` (v2, PRIVADO), `super_squad/loop.py`, `DECISIONS.md`. Supersede `KICKOFF_NEXT_SESSION_d_loop.md`.

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

## OBJETIVOS da próxima sessão (em ordem)
1. **Métrica de fechamento do loop nos 9 golds** (fecha o (d) com número): rodar `orchestrate` nos 9 golds
   mensuráveis com WSL real + writer medido → taxa de fechamento por ITERAÇÃO + custo. Pré-req: decidir o
   roster do writer (minimax pragmático, ou painel v4-pro+minimax+glm). ~$0.30-0.50 (pago).
2. **Debugger no laço — mede o ganho** (iter-2 com diagnóstico vs. re-tentar cego). BLOQUEIO: o `debugger`
   não tem gold MEDIDO (persona existe). Só entra se mover o número (disciplina D10). Autorar gold DRAFT +
   medir (pool chinês, N≥5) OU usar os próprios 9 golds como proxy (o loop que não fecha na iter-1 → debugger
   → fecha na iter-2?).
3. **Fonte de PROMOÇÃO humana/não-memorizada** (trava nº1 do vazamento; firma titular): plugar
   BugsInPy/Defects4J/QuixBugs no MESMO `execution_ruler` → gold FRESCO. Promoção = HUMANA (D5/D6). 4 travas:
   vazamento (usar como calibração, NUNCA promoção sem held-out fresco), só origem humana, licença por fonte, transferência de domínio.

## Guardrails (inegociáveis)
- Promoção pra titular é **HUMANA (D5)** — eu meço, o user bendiz. Régua por EXECUÇÃO; o modelo nunca autora
  o juiz (D6/D7). Pool só chinês (D16). Reasoning → `max_tokens≥4000`. Persona verbosa → suffix.
- Commit SELETIVO (`git commit -m "msg" -- <path>`, nunca `-A`); teto ~$1/teste; push é do user.
- **VAZAMENTO (trava nº1):** golds atuais são AI-assistidos + do próprio repo → SINAL. Titular pede gold HUMANO.

## O harness/loop (usar, não reconstruir) — `_candidate_evals/code_writer_2026-07-15/`
- `measure_code_writer.py` (`--stage patches/verdicts/aggregate`, checkpoint JSONL, cap thread-safe; reasoning
  detecta v4-pro/glm → mt=4000). `triage_golds.py` → 9 mensuráveis. `smoke_loop_e2e.py` (E2E do loop).
- Backups da medição v1: `patches.v1.jsonl.bak`/`verdicts.v1.jsonl.bak`. `.env` do ViralCutter = OPENROUTER_API_KEY.
