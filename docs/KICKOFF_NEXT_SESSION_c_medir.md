# Kickoff da próxima sessão — (c) MEDIR o code-writer

> Prompt de retomada auto-contido (retoma a frio). Gerado ao fim da 3ª sessão autônoma (2026-07-12), que
> fechou os elos (a) sandbox WSL2 real + (b) validação red→green. Leia junto: `docs/NEXT_SESSION.md`
> (âncora principal) e `DECISIONS.md` (D17).

## Estado ao começar
- Branch `feat/subagent-army-pilot`, suíte **281 verde**, árvore limpa, **NÃO pushado**.
- Commits da 3ª sessão: `b517e53` (a: wsl_sandbox) · `9e0a9ae` (b: harvest_validate) · `3cca5c0` (b: fallback + docs).

## OBJETIVO ÚNICO = (c) medir o code-writer nos 15 golds e trazer o NÚMERO
A promoção pra titular continua **HUMANA (D5)** — eu meço, o user bendiz. **Não** é pra "ligar o loop" ainda.

## O que já existe (usar, não reconstruir)
- **Golds:** `_candidate_evals/golds_code_writer/golds_red_green.json` — 15 casos red→green PROVADOS, bytes em base64 (privado/gitignored). Regeneráveis por `super_squad.harvest_validate.harvest_and_validate(repo)`.
- **Sandbox:** `super_squad/wsl_sandbox.py` → `wsl_sandboxed_run` (`isolation_capable=True`; exige WSL2 Ubuntu UP).
- **Régua:** `super_squad/execution_ruler.py` → `execution_ruler(buggy_files, test_cmd, test_files=…, run_fn=wsl_sandboxed_run)(patch_do_modelo)` → `{"pass": bool, "label": …}`.
- **Braçal:** `super_squad/run_role.py` → `run_role("code-writer", task_input, roster=[(slug,pin,pout)], max_tokens=…, budget_usd=…)`.
- **Persona:** `roles/vendor/code-writer.md` (consultiva: devolve o PATCH como texto; o gate aplica).
- **Pool:** `_candidate_evals/POOL_CHINESE_TOP12.md` (o code-writer **NÃO** tem roster no `.env` → passe `roster=` explícito).
- **Chave/rosters:** `.env` PRIVADA do ViralCutter (`OPENROUTER_API_KEY` + `AI_SQUAD_ROSTER_*`). Driver de env: carregar a `.env` no `os.environ` antes de chamar o braçal.

## O loop de medição (montar)
Para cada gold → `task_input` = spec + código-com-bug + o teste que falha → `run_role("code-writer", …)` → pega o patch (texto) → `execution_ruler(...)(patch)` → pass/fail. Agregue **pass_rate por modelo** sobre os 15 golds, **N≥5** (rode o subconjunto forte do pool). Custo: teto ~$1/teste.

## Guardrails (não esquecer)
- **HONESTO/SÓBRIO**: números reais, falhas primeiro, sem hype.
- **LINHA-DURA**: o modelo medido NUNCA autora o próprio juiz (os testes/oráculo são humanos/meus).
- **Reasoning models** (glm-*/*-thinking/r1/kimi-thinking): `max_tokens≥2000` senão vêm VAZIOS.
- **Persona verbosa** → `system_suffix` ligado (D15). **Pool = SÓ chineses**, qualidade-first (D16).
- **⚠ VAZAMENTO (trava nº1):** estes 15 golds vêm do super-squad (fresco/privado) MAS os fix-commits são
  **AI-assistidos** → servem p/ **SINAL** de medição, não p/ veredito de promoção. Para PROMOÇÃO, prefira
  fonte de fix **HUMANA/não-memorizada** (BugsInPy/Defects4J/QuixBugs via o mesmo `execution_ruler`, ou
  repo privado de terceiros). Fonte de promoção = decisão **HUMANA (D6)**.
- Commit **SELETIVO** (nunca `-A`); push é do user. Dogfood segue: código braçal → squad; Claude no gate.

## Depois de (c)
Esboçar **(d)** o orquestrador de loop (zero-gasto, solo): decompõe → roteia → integra → VERIFICA (execução) → critério de parada + teto de gasto.
