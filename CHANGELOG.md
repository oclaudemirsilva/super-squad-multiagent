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
