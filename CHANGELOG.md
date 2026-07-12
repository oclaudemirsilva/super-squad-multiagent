# Changelog

## Não lançado

- **D3 (máquina)** — `role_eval(skill_path=...)`: compõe o playbook de uma skill ao system prompt da persona
  (reusa `skills.compose_system`, `load_skill_fn`/`compose_fn` injetáveis; o gate D10 sobe — skill de
  construtor levanta `SkillGateError`). É a costura para MEDIR `persona+skill` vs `persona-sozinha`. +1 teste.

- **B4** — `role_eval(system_suffix=...)`: neutralizador opt-in de ruído de protocolo. Personas de catálogo
  verbosas ("query context manager first") fazem alguns modelos PEDIREM contexto em vez de executar a tarefa,
  confundindo a medição (o modelo parece fraco; é o instrumento). O sufixo task-forcing anexa ao system prompt
  da persona SEM tocar o gold humano. Achado ao medir security-auditor à mão (o titular "falhava" só emitindo
  JSON de pedido-de-contexto). +1 teste.

- **D2** — proveniência de LICENÇA por-skill vira campo de primeira classe: `SkillSpec.license`/`.source`
  (frontmatter) + `.license_cleared` fail-closed (licença ausente/DRAFT/UNKNOWN = não liberada). Ingerida
  uma skill consultiva real (`roles/skills/test-design-boundaries.md`, MIT, prosa própria; método =
  partição de equivalência + valor-limite, conhecimento público). +3 testes. Vendorizar skill de terceiro
  segue passo humano (o módulo não baixa/empacota); a proveniência agora é auditável, não só docstring.

- **E2** — `runtimes/opencode.py`: sequência §3 do adapter FIADA (pré-voo teto global → config efêmera →
  invocação headless → git diff → parse usage → ledger) + telemetria `builder_start`/`builder_end` (OCP,
  fail-soft). Tudo INJETÁVEL (subprocess/command_builder/parse_usage/check_budget/record_spend/write_config)
  → exercitado 100% com fakes (+6 testes). 3 portões: `enabled=False` · `assert_builder_preconditions` ·
  `command_builder=None` (§9 não verificada → recusa montar argv, não adivinha flags). Config referencia a
  chave por env, nunca embute o valor. NÃO ativa o binário — segue gate humano.

- **E1** — `runtimes/hardening.py`: primitivas PURAS/injetáveis de aplicação dos guarda-corpos A1–A5 da
  Fase 2. `redact_secrets` (A2, idempotente) · `is_bash_allowed`/`assert_bash_allowed` (A3, anti-encadeamento
  de shell) · `WorktreeManager` com `session` try/finally (A1, raio de explosão) · `SpendGuard` thread-safe
  (A5, teto mid-loop) · `enforce_permission` (despacho fail-closed sobre `PermissionProfile`). stdlib-only,
  0 rede/0 I/O real (subprocess injetado). +18 testes. Complementa o `spend_ledger` (teto global por janela);
  não ATIVA construtor (segue gated por E2 + hardening_ack humano). Rascunho braçal (deepseek), gate/fix meu:
  docstring de módulo reordenada, `capture_output/text` no subprocess, quebra-de-linha na detecção de shell.

- **B3** — guarda de pré-voo de ROSTER (`preflight.assert_roster_live`, catálogo vivo do OpenRouter)
  wired como opt-in fail-closed nas duas portas de gasto: `run_roles(preflight=...)` (checa os papéis
  distintos) e `role_eval.run_role_eval(preflight_pool=...)` (adapta o `pool` a um roster sintético).
  Slug ausente ABORTA o lote ANTES de gastar. Default OFF na lib (preserva os testes herméticos + DIP —
  o pré-voo exige rede); a CLI de `run_roles` liga por default (`--no-preflight` p/ debug offline).
  `preflight_fn`/`preflight_pool_fn` injetáveis. +6 testes herméticos; verificado live (slug morto aborta).

- `rulers` — biblioteca de réguas DETERMINÍSTICAS reutilizáveis para o fiscal (o repo não
  trazia nenhuma pronta): `json_valid` (estrito a cerca markdown), `numeric_close` (extrai a
  resposta numérica, pt-BR/en), `length_window`, `contains_all` (sem acento), `exact_match`,
  `keyword_verdict` (ponte p/ `squad.parse_verdict_keyword`), `set_f1`; + `resolve_ruler` p/
  suites em JSON. Puras, stdlib-only, herméticas.
- `bench` — bootstrap de roster (o "degrau 0": pool × suite -> matriz de custo/latência/
  qualidade + pontuação por função + sugestão). Qualidade só de régua determinística OU de
  ratings humanos de VÁRIOS colaboradores agregados por mediana — nunca modelo-julga-modelo
  (D6/D7). Dry-run por default; `--preflight` compõe a guarda B6. Sugere, mas não rosteia (D5).
- +25 testes herméticos (rulers + bench); suíte total 104, 0 rede.
- `rulers` — +`contains_any` (recall com sinônimos: passa se QUALQUER frase aparece) e
  `contains_none` (over-flag GROSSO: passa se NENHUMA frase de ataque aparece); ambas no
  `resolve_ruler`. São o instrumento do papel code-reviewer (detecção × over-flag).
- `code_review_eval` — runner de medição de UM papel consultivo cruzando N modelos, N>=5
  repetições/caso, contra ground-truth privado, com teto de gasto e checkpoint idempotente
  (resume não re-paga). Persona que declara tools de construtor é medida em modo CONSULTIVO
  (diff inline, sem disco) — a classificação single-shot governa o RUNTIME, não a MEDIÇÃO (D8).
  Agrega detecção (recall do bug plantado) × over-flag (falso-positivo em diff limpo) × custo ×
  latência; ORDENA por custo-benefício; NÃO rosteia (D5). CLI + `render_markdown`.
- +18 testes herméticos (rulers novos + runner com `run_squad` real sobre thunks mockados,
  incl. idempotência do checkpoint); suíte total 122, 0 rede.
- `rulers.top_bug_clean_ruler` — scoring de caso-limpo pelo veredito `TOP_BUG:` (imune à review
  que NOMEIA o pitfall evitado; conserta o falso-positivo da `contains_none`). +1 teste (suíte 123).
- `squad.make_openrouter_text_job` — parâmetro `max_tokens` (teto de saída: custo previsível +
  comparação justa entre modelos de um painel).
- docs: `design/flywheel-bootstrap.md` (loop auto-construtor, 2 eixos) e
  `design/subagent-portability.md` (subagent = persona portável + roster privado; contrato de reuso).
  Decisões D8-D11.
- `run_role` — **a PORTA DA FRENTE**: `run_role(role, input)` (ou CLI `python -m super_squad.run_role
  <papel> "<input>"`) carrega a persona, escolhe o modelo rosteado (env `AI_SQUAD_ROSTER_<PAPEL>`) e
  devolve o veredito. Consultivo (injeta system prompt, nenhuma tool executa). É o que permite OUTRO
  projeto/sessão usar um subagent medido com UMA chamada. `panel=True` roda todo o roster. +4 testes.
- `registry`: env de override normaliza hífen→underscore (`AI_SQUAD_ROSTER_CODE_REVIEWER`, settável no
  shell; forma antiga com hífen ainda lida como fallback). Suíte 127.
- `gold_preflight` — **pré-voo do GOLD** (D12): veta CASO-LIMPO "não-limpo" ANTES de gastar. Roda a
  persona por um juiz MEDIDO N vezes e, se ele nomeia a vuln PROIBIDA acima do limiar, reprova
  fail-closed com os motivos (revisão humana — o modelo SINALIZA, não autora; D6 intacto). Régua do
  gate ESPELHA a de scoring (`top_bug_forbids_ruler`), não `top_bug_clean_ruler` — preocupação
  defensável DIFERENTE não é over-flag (a v1 errou nisso; o dogfood pegou). Mata o modo-de-falha
  recorrente "autor jurou limpo mas tinha bug real → over-flag enviesado".
- `code_review_eval` — parâmetro opt-in `clean_preflight_judges`: roda o pré-voo do gold (fail-closed)
  antes de gastar no pool inteiro. Default None = compat retroativa. +8 testes herméticos; suíte 136.
- docs: `design/ruflo-union-routing-seam.md` — seam `RoutingProvider` da união com ruflo (este motor =
  autoridade de modelo/Eixo B; ruflo = substrato memória/custo/booster-$0). Design, não implementado;
  plugar só o braço que mover o número num experimento N≥5 (D14).
- `run_roles` — **porta PARALELA**: roda N papéis (subagents) num único fan-out concorrente do `run_squad`
  (jobs de todos os papéis dividem workers + teto de gasto). Fail-soft por tarefa (papel sem roster vira
  erro DAQUELA tarefa, não do lote). Função + CLI (`python -m super_squad.run_roles tasks.json`). +7 testes
  herméticos; suíte 143.
- `roles/MANIFEST.md` — os 12 subagentes mais importantes em ordem de dependência (Fase 1 consultivos +
  Fase 2 construtor), com o rito de "entrar em ação sem gastar pra testar" (persona MIT + roster semeado
  com prior chinês via env; medir gradual, D9/D10). `docs/ROADMAP.md` — backlog por track.
- `role_eval` — runner de medição ROLE-AGNÓSTICO: régua vem do gold via `resolve_ruler` (fallback p/ a
  convenção code-review). Fail-closed sem régua; checkpoint + teto + pré-voo de gold herdados. +6 testes.
- `skills` — ingestor `SkillSpec` (espelha `roles.py`) + `compose_system` (persona⊕skill) com gate D10
  (skill que executa código = Fase 2, `SkillGateError`). +7 testes.
- `routing` — SCAFFOLD do seam `RoutingProvider` (Tier-1 trivial → booster $0; resto → titular medido;
  `NullBoosterAdapter` = fallback enquanto ruflo não plugado). +7 testes.
- 8 personas consultivas autoradas (draft do workhorse chinês, gate humano) p/ os papéis do manifesto;
  proveniência distinta do catálogo (`roles/vendor/README.md`). Suíte total **163**, 0 rede.
- `run_roles` — `skill` opt-in por tarefa: compõe o playbook da skill ao system prompt (D10), com o gate
  (skill que executa código = Fase 2 → tarefa erra fail-soft). Une a 3ª força (skills) ao fan-out. +3 testes.
- `runtimes/` — seam `BuilderRuntime` (Fase 2): `base.py` (contrato + `NullBuilderRuntime` fail-closed +
  `assert_builder_preconditions`) + `opencode.py` (adapter DESABILITADO por default; blocked sem worktree +
  caps + `hardening_ack`; execução real não fiada até §9). Une o OpenCode à pilha SEM soltá-lo. +12 testes. Suíte **180**.

## 0.1.0 — 2026-07-08

Primeira extração pública do motor (clean-room a partir do projeto de origem, onde cada
peça roda em produção desde 2026-07):

- `openrouter` — cliente stdlib-only (texto/visão/áudio/catálogo), chave só por env.
- `registry` — roster por papel; nasce vazio, override por env `AI_SQUAD_ROSTER_<ROLE>`.
- `squad` — fan-out concorrente com teto por rodada, telemetria injetável, voto ponderado
  com desempate conservador.
- `preflight` (B6) — slug vivo + drift de preço antes de gastar; chave ausente aborta.
- `spend_ledger` (B5) — teto global por janela com escada de alerta 50/75/90/100%.
- `maestro` — workflows registráveis com guardas compostas; dry-run por default.
- `role_shadow` — shadow-audit: régua determinística × agente × gold humano, checkpoint
  idempotente, épocas de re-auditoria via `key_suffix`.
- `candidate_eval` — avaliação de candidato sem tocar o roster titular.
- `code_writer` — papel `code` com defesa anti-cerca-markdown.
- demo `sentiment_judge` end-to-end (rodada de referência: régua 4/6, painel 6/6,
  $0.00017) + 79 testes herméticos.
