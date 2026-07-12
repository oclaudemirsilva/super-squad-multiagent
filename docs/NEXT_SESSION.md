# Ponto de retomada — próxima sessão

> Âncora de contexto para continuar sem perder o fio. Estado em **2026-07-12** (2ª sessão autônoma, foco
> ESTRUTURA). Branch `feat/subagent-army-pilot`, tudo pushado, suíte **216 verde**, ZERO dívida técnica.
> Leia junto: `docs/ROADMAP.md` (status por track), `docs/INTEGRATION.md` (o que está plugado), `DECISIONS.md`.

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

## Próximos passos — por prioridade (o que destrava mais)

1. **Golds mais DUROS (humano, D6)** — os atuais saturam. Sem isso não firma titular de papel nenhum.
   Concreto: A3 precisa de casos-LIMPOS (over-flag) + régua verdict-aware; A2 precisa de vulns mais sutis
   + mais clean traps; apertar réguas de detecção permissivas (substring "alg"/"signature"/"redirect").
2. **A4 architect-reviewer / A5 debugger** — autorar gold DRAFT (minha mão, marcar DRAFT p/ bênção) + medir.
3. **Ligar o OpenCode (Fase 2)** — verificar §9 (flags reais do binário), injetar `command_builder` verificado,
   `enabled=True` + `hardening_ack=True`. Só depois de um roster de construtor medido.
4. **Conectar o ruflo (Track C)** — `claude mcp add ruflo …` + expor booster callable-de-Python → medir o ganho
   (N≥5, 3 braços: só squad / +booster / +memória) → plugar só o que mover o número.

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
