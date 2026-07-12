# Changelog

## Não lançado

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
