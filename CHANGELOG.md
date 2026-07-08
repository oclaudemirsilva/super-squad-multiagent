# Changelog

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
