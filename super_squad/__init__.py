"""Super Squad Multiagent — orquestração multi-modelo COM regime de fiscalização.

Camadas (de baixo pra cima; cada uma importável sozinha):
  openrouter    — cliente stdlib-only (1 chave -> N modelos; chave SÓ por env)
  registry      — roster por papel (nasce vazio: você MEDE e preenche o seu)
  squad         — motor de fan-out (jobs, teto por rodada, voto ponderado)
  preflight     — guarda B6: slug vivo + drift de preço + chave presente, ANTES de gastar
  spend_ledger  — guarda B5: teto de gasto global por janela (dia/mês), append-only
  maestro       — workflows registráveis com guardas compostas (dry-run por default)
  role_shadow   — shadow audit: régua determinística × agente × gold humano
  candidate_eval— avaliar modelo candidato SEM tocar o roster titular
  code_writer   — papel `code`: spec -> rascunho (quem chama audita e decide)
"""
__version__ = "0.1.0"
