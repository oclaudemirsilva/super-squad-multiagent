"""Super Squad Multiagent — orquestração multi-modelo COM regime de fiscalização.

Camadas (de baixo pra cima; cada módulo importável sozinho). Ver `docs/INTEGRATION.md` p/ o STATUS de
integração por força e `docs/design/*.md` p/ os designs.

  # transporte / chave (o chokepoint por onde tudo sai)
  providers        — endpoints OpenAI-compatíveis nomeados (openrouter | qwen_cloud); chave SÓ por env
  openrouter       — chokepoint stdlib-only do transporte (retry/backoff/chave-nunca-vaza)
  qwen_cloud       — fachada nomeada do Alibaba Cloud Model Studio (DashScope) sobre o chokepoint

  # roster / motor de fan-out / guardas de gasto
  registry         — roster por papel (nasce vazio: você MEDE e preenche o seu)
  squad            — motor de fan-out (jobs, teto por rodada, voto ponderado)
  preflight        — guarda B6: slug vivo + drift de preço + chave presente, ANTES de gastar
  spend_ledger     — guarda B5: teto de gasto global por janela (dia/mês), append-only
  maestro          — workflows registráveis com guardas compostas (dry-run por default)

  # subagentes (persona + roster) e composição
  roles            — carrega a persona portável (roles/vendor/*.md) → RoleSpec
  run_role         — a porta da frente: roda UM subagente (persona+roster) sobre um input
  run_roles        — fan-out: N subagentes em paralelo num só lote (fail-soft por tarefa)
  skills           — playbook composto ao system prompt (gated D10; licença por-skill)
  routing          — seam do ruflo: RoutingProvider (intent trivial+booster→$0; senão titular medido)

  # MEDIÇÃO de modelo/papel (a moeda do regime: número + bênção HUMANA, D5)
  rulers           — réguas determinísticas prontas (JSON-válido, numérico, janela, F1, verdito)
  role_shadow      — shadow audit: régua determinística × agente × gold humano
  role_eval        — mede UM papel (persona × pool × gold) → número por-modelo (N≥5)
  candidate_eval   — avaliar modelo candidato SEM tocar o roster titular
  code_review_eval — eval do papel code-reviewer (casos buggy/clean; detecção)
  gold_preflight   — guarda D6 anti-erro-de-autor: veta caso-limpo mal-rotulado ANTES de gastar
  bench            — bootstrap de roster (degrau 0): pool × suite → matriz custo/latência/pontuação
  code_writer      — papel `code`: spec → rascunho (quem chama audita e decide)

  # substrato ATIVO: régua por EXECUÇÃO + o laço que RESOLVE (o modelo nunca autora o juiz, D6/D7)
  execution_ruler  — régua OBJETIVA: aplica o PATCH (applier tolerante) e roda o TESTE isolado → pass/fail
  wsl_sandbox      — run_fn OS-sandboxed REAL (WSL2: rede off, host escondido) que a régua injeta
  git_harvester    — colhe fix-commits do histórico → casos de gold red→green (sem autoria manual)
  harvest_validate — valida red→green os casos colhidos (red falha / green passa; árvore-do-pai completa)
  loop             — orquestrador: rotear→integrar→verificar(execução)→debugar→repete, com teto e paradas

  # construtores Fase 2 (escrevem no disco de verdade) — GATED, não ativam
  runtimes/*       — BuilderRuntime (OpenCode) atrás de 3 portões; merge do diff = humano (D5)
"""
__version__ = "0.1.0"
