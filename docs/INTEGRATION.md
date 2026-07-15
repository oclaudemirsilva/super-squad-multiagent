# Integração — a união das forças numa pilha só (D14)

> Como as peças do "Super Squad Multiagente" se compõem, e o STATUS HONESTO de integração de cada uma.
> A visão (D14): **subagente (persona) + skill (capacidade) → roda no MODELO MEDIDO (este motor) →
> sobre SUBSTRATO (ruflo: memória/custo/booster)**. Nem tudo está plugado — o que está e o que não está,
> abaixo, com o arquivo que prova cada afirmação.

## A pilha (composição-alvo)

```
   tarefa
     │
     ▼
  [SUBAGENTE]  persona portável (roles/vendor/*.md)            ← QUEM faz
     │  + [SKILL] playbook opcional (roles/skills/*.md)        ← COMO faz (gated D10)
     ▼
  [MODELO MEDIDO]  roster custo/qualidade por papel + gate      ← ONDE roda (este motor)
     │             (role_eval mede; registry rosteia; D5 humano promove)
     ▼
  [RUNTIME]  single-shot (squad.py)  |  construtor agêntico (runtimes/BuilderRuntime → OpenCode)
     │                                  (Fase 2, GATED)
     ▼
  [SUBSTRATO ruflo]  memória Graph-RAG cross-sessão · custo · Agent Booster Tier-1 $0   ← (seam, não plugado)
```

## Status por força (verificado no código)

### ✅ Subagentes — INTEGRADO (é o núcleo de execução)
- `run_role(role, input)` roda UM subagente; `run_roles([...])` roda N em paralelo num só fan-out.
- Um subagente = `persona (roles/vendor/*.md) + roster medido (registry / env AI_SQUAD_ROSTER_*)`.
- Consultivo por padrão (injeta o system prompt, lê texto, nenhuma tool executa). Fail-soft por tarefa.
- Arquivos: `super_squad/run_role.py`, `super_squad/run_roles.py`, `super_squad/roles.py`, `registry.py`.

### ✅ Loop ATIVO (auto-conserto verificado por execução) — INTEGRADO (5ª sessão, 07-15b)
- `loop.orchestrate(task, *, budget_usd, ...)` fecha o laço que faltava sobre o fan-out: ROTEAR (`run_role`)
  → INTEGRAR (applier tolerante) → VERIFICAR (`execution_ruler` + `run_fn` OS-sandbox) → DEBUGAR (realimenta
  o stderr) → repete, com 4 paradas (sucesso/teto/iterações/travado). `budget_usd` OBRIGATÓRIO.
- É a metade ATIVA (que RESOLVE) sobre os subagentes consultivos (que julgam). Oráculo por EXECUÇÃO — o
  modelo nunca autora o juiz (D6/D7); aplicar no mundo real = merge humano (D5).
- Substrato de execução (sessões 3-4): `execution_ruler.py` (régua+applier), `wsl_sandbox.py` (`run_fn` real),
  `harvest_validate.py`/`git_harvester.py` (golds red→green). Provado E2E (1 gold, 1 iter, $0.027).
- FALTA medir: taxa de fechamento nos 9 golds + ganho do debugger na iter-2 (gold do `debugger` pendente).
- Arquivos: `super_squad/loop.py` (+ `execution_ruler.py`, `wsl_sandbox.py`, `harvest_validate.py`, `git_harvester.py`).

### ✅ Skills — INTEGRADO (compostas ao system prompt, gated D10)
- `run_roles(..., skill=...)` e `role_eval(..., skill_path=...)` fundem o playbook da skill no system
  prompt via `skills.compose_system`.
- Gate D10: skill que executa código (`requires_script`) levanta `SkillGateError` (Fase 2, não roda por fé).
- Proveniência de licença por-skill (`SkillSpec.license`/`.license_cleared`, checagem humana).
- Arquivos: `super_squad/skills.py`; wiring em `run_roles.py`, `role_eval.py`.

### 🟡 OpenCode (construtores Fase 2) — UNIDO AO SEAM, mas GATED (não ativa)
- `runtimes/base.py` define o contrato `BuilderRuntime` + `assert_builder_preconditions` (fail-closed).
- `runtimes/hardening.py` aplica A1–A5 (worktree, redação de segredo, allowlist de bash, teto mid-loop).
- `runtimes/opencode.py` fia a sequência §3 (config→run→diff→ledger) atrás de **3 portões**: `enabled=False`
  (default) · pré-condições (worktree+caps+`hardening_ack`) · `command_builder=None` (§9 não verificada).
- **Integrado na pilha, NÃO solto**: o binário nunca é tocado sem um humano ligar tudo. Merge do diff = humano.
- Arquivos: `super_squad/runtimes/{base,hardening,opencode}.py`. Design: `docs/design/opencode-builder-runtime.md`.

### 🔴 ruflo (substrato) — SÓ A COSTURA (Null adapter); NÃO plugado
- `routing.py` define `RoutingProvider` + `MeasuredRoutingProvider` (intent trivial + booster → $0; senão →
  titular medido) + **`NullBoosterAdapter`** (ruflo ausente → fallback gracioso pro modelo).
- O ruflo REAL não está integrado. Dois pré-reqs (humanos, não-triviais):
  1. Conectar o MCP do ruflo (`claude mcp add ruflo …`) — verificado 07-12: NÃO conectado neste boot.
  2. Uma interface callable-de-Python p/ o Agent Booster: `routing.py` é lib stdlib standalone e não alcança
     um tool MCP do Claude Code direto → o `BoosterAdapter` REAL precisa do booster exposto por HTTP/CLI/WASM.
- Integridade: memória do ruflo seria recall/contexto, JAMAIS ground-truth (D6); promoção segue humana (D5).
- Arquivo: `super_squad/routing.py`. Design: `docs/design/ruflo-union-routing-seam.md`. Ver ROADMAP Track C.

## Fronteira dura de integridade (vale em toda integração)
- **Gold é humano** (D6): nenhuma saída de modelo vira ground-truth; o motor lê golds, nunca escreve.
- **Promoção é humana** (D5): a fiscalização mede e reporta; não auto-rewira o roster.
- **Roteamento de modelo é DESTE motor** (D14): o ruflo é substrato (memória/custo/booster), não decide modelo.

## Uma frase
Subagentes e skills estão integrados de verdade; OpenCode está unido ao seam mas enjaulado (Fase 2);
ruflo é a única força ainda só-costura, bloqueada em conectar o MCP + expor um booster callable.
