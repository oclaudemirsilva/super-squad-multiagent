> ⚠️ **SUPERSEDED** — cumprido (4ª sessão: confounds fechados + loop construído/E2E). Entrada ATUAL: `KICKOFF_NEXT_SESSION.md`. Mantido só como histórico.

# Kickoff da próxima sessão — (c) MEDIDO ✅ · construir (d) o orquestrador de loop

> Prompt de retomada auto-contido (retoma a frio). Gerado ao fim da 4ª sessão autônoma (2026-07-15), que
> **fechou (c)** (mediu o code-writer nos golds red→green) e **esboçou (d)** (design do orquestrador de loop).
> Leia junto: `docs/design/loop-orchestrator.md` (o esboço de (d)), `_candidate_evals/code_writer_2026-07-15/
> FINDINGS.md` (o número + confounds, PRIVADO), `docs/NEXT_SESSION.md` (âncora), `DECISIONS.md`.

## Estado ao começar
- Branch `feat/subagent-army-pilot`, suíte **281 verde**, **NÃO pushado** (push é do user).
- Commits desta sessão: `docs/design/loop-orchestrator.md` (d) + este kickoff. O harness de medição e os
  resultados ficam em `_candidate_evals/code_writer_2026-07-15/` (PRIVADO/gitignored, não commitado).
- ⚙️ **Ambiente:** ruflo (10 plugins + MCP) foi DESLIGADO nesta sessão por lentidão — ver
  `MEMORY.md` do ViralCutter. Não re-adicionar sem querer. `effortLevel=max` é escolha do user.

## (c) — O NÚMERO (SINAL, não promoção; D5 humano)
code-writer, pool chinês, **N=5, 9 golds MENSURÁVEIS**, régua = `execution_ruler`+`wsl_sandboxed_run`, $1.31:
- **minimax/minimax-m2.5 = 0.47** (topo as-is, responde sempre, $0.106) · deepseek-v4-pro 0.58 quando-responde
  (mas 21/45 vazias) · glm-4.7 0.31 · deepseek-v3.2 0.27 · qwen3-coder 0.24 · qwen3-235b 0.13.
- **8/9 golds resolvidos por ALGUM modelo** → os golds são resolvíveis; a taxa individual é suprimida por
  INSTRUMENTO, não incapacidade.

### ⚠ 2 confounds de instrumento a consertar ANTES de crer nos números baixos (a memória: teto baixo = bug)
1. **`apply_failed` massivo** (qwen3-235b 31/45, qwen3-coder 27/45): o `_default_apply` casa hunk BYTE-EXATO;
   modelos emitem diff com contexto off → não cola. **Fix de maior alavanca:** applier tolerante (fuzzy) ou
   pedir arquivo-inteiro. Re-medir → a taxa dos qwen deve subir MUITO.
2. **Vazias/reasoning-truncation** (v4-pro 21/45, glm 14/45): max_tokens baixo p/ modelo que raciocina.
   **Fix:** max_tokens≥4000 p/ v4-pro/glm; re-medir só as células vazias (checkpoint não re-paga o resto).
- **BUG JÁ CONSERTADO nesta sessão** (senão dava 0/15 falso): o ruler materializava só os arquivos-tocados →
  ImportError na coleta. Agora base = **árvore-do-pai completa** (git archive, cache por SHA). Ver `build_ruler`.
- **Denominador honesto 9/15:** 6 golds eram commits de FEATURE que exigiam CRIAR módulos novos que o modelo
  nem recebe (mis-scoped). `triage_golds.py` separa (verdict MENSURAVEL vs GREEN_NAO_PASSA).

## OBJETIVOS da próxima sessão (em ordem)
1. **Consertar os 2 confounds e re-medir** (fecha o número honesto do code-writer): applier tolerante +
   max_tokens≥4000 p/ reasoning. Custo ~$1. É o pré-requisito p/ um número que discrimina de verdade.
2. **Construir (d) o orquestrador de loop** — `super_squad/loop.py` conforme `docs/design/loop-orchestrator.md`:
   `orchestrate(task, *, max_iters, budget_usd, roster_writer, roster_debugger, run_fn)` puro/injetável
   (testes herméticos, zero rede/WSL), espelhando o harness. Gold do loop = os 9 golds mensuráveis como
   tarefas E2E (o loop fecha red→green sozinho em ≤3 iter + teto de $). Métrica: taxa de fechamento por iter.
3. **Fonte de PROMOÇÃO humana/não-memorizada** (trava nº1 do vazamento): plugar BugsInPy/Defects4J/QuixBugs
   no MESMO `execution_ruler` → gold FRESCO p/ firmar titular. Promoção = HUMANA (D5/D6).

## O harness (usar, não reconstruir) — `_candidate_evals/code_writer_2026-07-15/`
- `measure_code_writer.py` — driver: `--sanity` ($0 red) · `triage`(no `triage_golds.py`) · `--stage all/patches/
  verdicts/aggregate` · `--n 5 --measurable-only --models "<csv>" --budget 2.0`. 2 etapas (patches PAGO +
  verdicts $0/WSL), checkpoint JSONL (resume não re-paga), dedup por hash, cap de gasto thread-safe.
- `triage_golds.py` → `triage_result.json` (9 mensuráveis). `build_ruler` usa árvore-do-pai completa.
- Pool vivo (12/12) + preços em `POOL_CHINESE_TOP12.md`. `.env` do ViralCutter = OPENROUTER_API_KEY.

## Guardrails (inegociáveis)
- Promoção pra titular é **HUMANA (D5)** — eu meço, o user bendiz. Régua por EXECUÇÃO; o modelo nunca autora
  o juiz (D6/D7). Pool só chinês (D16). Reasoning → max_tokens≥2000 (agora ≥4000). Persona verbosa → suffix.
- Commit SELETIVO (`git commit -m "msg" -- <path>`, nunca `-A`); teto ~$1/teste; push é do user.
- **VAZAMENTO (trava nº1):** golds atuais são AI-assistidos + do próprio repo → SINAL. Titular pede gold HUMANO.
