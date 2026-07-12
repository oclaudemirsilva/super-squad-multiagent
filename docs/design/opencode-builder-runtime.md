# Design — OpenCode Builder Runtime adapter

> Status (07-12): SEAM IMPLEMENTADO + gated; execução real NÃO fiada. `super_squad/runtimes/base.py`
> (contrato + `NullBuilderRuntime` fail-closed + `assert_builder_preconditions`) e `runtimes/opencode.py`
> (adapter DESABILITADO por default) existem e são testados (12 testes). Unir ≠ soltar: sem worktree +
> caps + `hardening_ack` humano, não executa; e mesmo habilitado devolve erro honesto até §9 ser verificada.
> Para ATIVAR (Fase 2, pós-receita): OpenCode instalado + §9 verificado + hardening A1–A5 + roster de
> construtor RE-medido + `enabled=True, hardening_ack=True`. Merge do diff = gate humano.

## 1. Onde encaixa

Empilhamento do exército:

| Camada | Peça | Faz |
|---|---|---|
| 4 governança | **Super Squad** (este repo) | roteia modelo por papel (medido), teto/telemetria, painel de juízes, gate |
| 2 runtime | **OpenCode** (externo) | loop agêntico: escreve+roda+conserta código |
| 4 humano | **Claude Code** | spec, particiona, gate/merge |

O motor (`super_squad/squad.py`) é single-shot: `job -> (valor, custo)`. Ele **não** tem
tool-loop. Os papéis CONSTRUTORES precisam de um runtime agêntico. OpenCode é esse runtime.

**Invariante de acoplamento:** o motor clean-room NUNCA importa OpenCode. OpenCode entra
atrás de uma abstração (`BuilderRuntime`), exatamente como OpenRouter entra atrás de
`Job.run`. O adapter é opcional e importável sem o binário instalado (só falha ao ser
CHAMADO, não ao ser importado) — mesmo invariante de "importável em qualquer ambiente".

## 2. A abstração (o seam) — `super_squad/runtimes/base.py`

Puro, stdlib, zero dependência. É o contrato de que o resto do sistema depende.

```
@dataclass(frozen=True)
class BuilderTask:
    task_id: str
    role: str                 # papel do catálogo (persona)
    system_prompt: str        # corpo da persona convertida
    instruction: str          # o que fazer nesta tarefa
    model_slug: str           # slug OpenRouter que o Super Squad ESCOLHEU (medido p/ construtor)
    workspace: str            # caminho da worktree isolada (cwd do runtime)
    max_steps: int            # cap duro de passos agênticos
    max_tokens: int | None    # cap de tokens da sessão (se o runtime suportar)
    timeout_s: int            # cap de wall-clock
    permission: "PermissionProfile"   # o que o runtime pode tocar

@dataclass(frozen=True)
class BuilderResult:
    task_id: str
    status: str               # "ok" | "error" | "timeout" | "budget" | "empty_diff"
    diff: str                 # git diff da worktree (o produto a ser JULGADO)
    files_changed: list[str]
    cost_usd: float           # custo REAL da sessão (p/ o ledger)
    steps: int
    transcript_path: str | None
    error: str | None

class BuilderRuntime(Protocol):
    def run(self, task: BuilderTask, on_event=None) -> BuilderResult: ...
```

`on_event` é o MESMO callback de telemetria do motor (`squad.make_jsonl_sink` etc.) — OCP:
o runtime só emite eventos, quem liga no sink decide.

Default injetável = `NullBuilderRuntime` que levanta "nenhum runtime configurado" — assim o
sistema importa e roda os single-shot mesmo sem OpenCode instalado.

## 3. O adapter — `super_squad/runtimes/opencode.py`

Implementa `BuilderRuntime` fazendo **subprocess** do CLI do OpenCode (caixa-preta,
swappable). Passos de `run(task)`:

1. **Pré-voo de teto GLOBAL** — `spend_ledger.check_budget(...)` ANTES de lançar. Janela
   diária esgotada → devolve `status="budget"` sem gastar. (o motor já tem isso; reusar).
2. **Preparar a worktree** — recebe `task.workspace` já isolada (quem chama cria via
   `git worktree add`); o adapter só opera dentro dela. Sandbox = a worktree.
3. **Escrever config efêmera do OpenCode** no workspace: provider=openrouter +
   `OPENROUTER_API_KEY` (do env do processo, nunca logado) + `model = task.model_slug` +
   um "agent"/mode cujo system prompt = `task.system_prompt` + perfil de permissão
   (write só na worktree, bash allowlist, sem rede além da API do modelo).
4. **Invocar headless** — `opencode run <instruction>` (não-interativo) com cwd=workspace,
   `timeout=task.timeout_s`, cap de passos. [VERIFICAR flags reais — ver §9.]
5. **Coletar** — `git -C workspace diff` = o `diff`/`files_changed`; parse do transcript/usage
   do OpenCode → `cost_usd`, `steps`. Falha de parse = fail-soft (cost estimado, flag).
6. **Registrar gasto** — `spend_ledger.record_spend(cost_usd)` pós-run + `on_event(...)`.
7. Devolver `BuilderResult`.

O adapter é stdlib-only (subprocess + json + pathlib). A dependência do OpenCode é de
RUNTIME (o binário), não de import.

## 4. Teto de gasto (3 camadas — e a limitação honesta)

- **Antes:** pré-voo do teto global (recusa se a janela esgotou).
- **Durante:** caps DUROS de `max_steps` / `max_tokens` / `timeout_s` passados ao OpenCode.
- **Depois:** custo REAL parseado → `spend_ledger`.

⚠️ **Limitação honesta:** hard-stop de $ NO MEIO do loop só é possível se o OpenCode expõe
um hook de spend/step. Se não expõe, os caps de passo/tempo são a única contenção mid-loop
— é o guarda-corpo, não um teto exato. Isso é um dos itens de §9 a verificar. Enquanto
incerto, dimensionar `max_steps` conservador e tratar o teto por-sessão como estimativa.

## 5. Telemetria

Cada sessão emite via `on_event`: `builder_start` (task_id, role, model), `builder_end`
(status, cost_usd, steps, n_files, diff_bytes). Alimenta o MESMO `telemetry_panel`. Passos
internos do OpenCode são opacos além do transcript — parse best-effort, documentar o que
não dá pra ver (buraco de observabilidade conhecido, perigo nº4 da análise).

## 6. Segurança / raio de explosão

`PermissionProfile` traduzido pra config do OpenCode: write só na worktree; bash com
allowlist (ou sandbox do OpenCode); rede só pra API do modelo. **Raio de explosão = a
worktree** — um construtor ruim suja um branch descartável, nunca o repo principal. Merge
é gate humano/Claude, nunca automático. (bate com `feedback_corpus_integrity_over_compliance`:
promoção só por mão humana.)

## 7. Paralelismo (a frota)

O exército = N `BuilderTask` rodados via `run_squad`/`parallel`, cada job =
`lambda t=task: runtime.run(t)`. Cada tarefa na SUA worktree → zero conflito por
construção. O `spend_ledger` global (dia/mês) cerca a frota inteira, não só a sessão.
Concorrência limitada pelo pool do motor. Claude Code particiona as tarefas e faz o gate
dos merges — trabalha em PARALELO com a frota, em camada diferente.

## 8. Integração com o Super Squad (fluxo ponta-a-ponta)

```
tarefa
  → ROUTE     Super Squad escolhe (persona, model_slug medido p/ construtor)
  → PREFLIGHT teto global (spend_ledger) + slug vivo (preflight)
  → WORKTREE  git worktree add (isolamento)
  → BUILD     runtime.run(BuilderTask)  ← OpenCode agêntico
  → JUDGE     painel de juízes avalia BuilderResult.diff (make_vlm/text panel)
  → GATE      GOOD → PR/merge (humano) · OK → needs_review · BAD → descarta worktree
  → LEDGER    record_spend + telemetria
```

O painel de juízes é o MESMO regime dos single-shot — a fiscalização cobre o construtor
sem código novo de juiz. Só o RUNTIME é novo.

## 9. Perguntas a verificar contra a API REAL do OpenCode (antes de implementar)

1. Invocação headless/não-interativa exata (`opencode run`? server + API? flags de
   cwd/model/agent/config?).
2. Expõe usage/custo por sessão de forma parseável (JSON)? Em que formato?
3. Existe hook de spend/step pra hard-stop mid-loop, ou só cap de passos/tempo?
4. Como definir o system prompt do "agent" por sessão (config file? flag? env?).
5. Perfil de permissão / sandbox: granularidade real (write-scope, bash allowlist, rede).
6. Aceita `OPENROUTER_API_KEY` + slug arbitrário direto, ou precisa de mapeamento de provider?

Até essas 6 respondidas, este design é o CONTRATO (estável); os detalhes de subprocess do §3
são provisórios.

## 10. Postura de dependência (o que fica clean-room)

- `runtimes/base.py` — puro, stdlib, no repo standalone (o seam é IP nosso).
- `runtimes/opencode.py` — stdlib no import; depende do binário OpenCode em runtime.
- `runtimes/null.py` — default seguro.
- OpenCode é **adapter swappable**: trocar por runner próprio (opção "build") = escrever
  outro `BuilderRuntime`, sem tocar motor/maestro/juízes. A decisão build-vs-adopt fica
  reversível por construção.
```
