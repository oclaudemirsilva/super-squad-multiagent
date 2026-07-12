# Decisões de projeto (registro corrido)

## D1 — Roster nasce VAZIO (2026-07-08)
O diferencial do sistema é o regime de medição, não uma lista de modelos. Publicar um
roster "recomendado" convidaria a pular a etapa que faz o sistema funcionar (medir contra
o SEU ground-truth, N>=5 por decisão). O custo é a demo exigir 1 env a mais; aceito.

## D2 — stdlib-only no core (2026-07-08)
`urllib` em vez de SDK; zero dependências obrigatórias. Motivo: o motor precisa ser
importável em qualquer ambiente (CI, container mínimo, script avulso) sem resolver árvore
de dependências. Pillow é extra opcional só para helpers de visão.

## D3 — Dry-run por default em TUDO que gasta (2026-07-08)
`dispatch(execute=False)` devolve o plano; `--execute` é o único caminho que gasta.
Scripts que gastam $ são CLIs de humano — nunca CI.

## D4 — Chave ausente = falha de PRÉ-VOO, não de runner (2026-07-08)
O catálogo do OpenRouter é público, então o pré-voo "passava" sem chave e o lote inteiro
rodava fail-soft com agent=null silencioso (custo 0, checkpoint poluído). Achado em
produção no projeto de origem no dia da extração; o guard aborta antes de rodar.

## D5 — Fiscalização NUNCA auto-rewira (2026-07-08)
`role_shadow` e `candidate_eval` medem e reportam; promoção/rebaixamento de modelo e peso
de voto são decisão humana. O loop que se auto-ajusta com a própria medição é o caminho
mais curto para o viés compartilhado invisível.

## D6 — Gold é de mão humana, sempre (2026-07-08)
Nenhuma saída de modelo entra como ground-truth (anti-autofagia). O motor lê golds,
jamais escreve.

## D7 — bench: qualidade objetiva OU humana agregada, nunca modelo (2026-07-08)
O bootstrap de roster (`bench.py`) mede custo/latência sozinho, mas a QUALIDADE só vem de
régua determinística (`rulers.py`) OU da experiência de VÁRIOS colaboradores agregada por
mediana (`ratings`) — nunca de um modelo julgando outro (D6), nunca do palpite de um só. O
bench ORDENA e SUGERE o roster (o mais barato que passou por função); promoção segue decisão
humana com N>=5 (D1/D5). Motivo: a partida a frio (escolher a 1ª lista a medir) faltava entre
os degraus — sem ela cada adotante improvisava o benchmark à mão.

## D8 — Classificação single-shot governa o RUNTIME, não a MEDIÇÃO (2026-07-11)
Uma persona pode declarar tools de construtor (Write/Edit/Bash) e ainda assim ser MEDIDA em
modo consultivo: o diff vai inline no prompt, o modelo só responde texto, nada toca o disco.
`make_role_job` recusa a persona-construtor (guarda de runtime, correta), mas o runner de
medição (`code_review_eval`) monta o job direto com o `system_prompt` da persona. Motivo: medir
"quão bom é o CÉREBRO deste papel" é separável de "este papel tem permissão de escrever no
disco". A régua consultiva mede o cérebro; o runtime agêntico (Fase 2) é outro portão.

## D9 — Flywheel auto-construtor: ordem por dependência, loop em OpenRouter (2026-07-11)
Os papéis são medidos/rosteados numa sequência em que cada um AJUDA a construir o próximo,
e o loop de construção roda em OpenRouter (não no orquestrador caro). Ordem: os consultivos
que constroem-e-verificam primeiro — code-reviewer (gate) → qa/test-judge → architect-reviewer
→ security-auditor (porteiro da Fase 2, A1-A5) → debugger — e só então os CONSTRUTORES da Fase 2,
já fiscalizados pelo trio medido. Conforme um papel é rosteado, ele SUBSTITUI o humano no passo
correspondente do loop (o code-writer rosteado rascunha; o reviewer rosteado faz o gate). O
roster de cada papel = fronteira de CUSTO-BENEFÍCIO medida (detecção por centavo, over-flag como
penalidade, latência como desempate) — nunca chute. Promoção continua humana e com N>=5 (D1/D5);
gold continua de mão humana (D6). Ver `docs/design/flywheel-bootstrap.md`.

## D10 — Skills (capabilities) são camada OPCIONAL sobre personas, gated (2026-07-11)
Persona = QUEM (system prompt/papel); skill = COMO (procedimento/playbook, ex. catálogos
"awesome-agent-skills"). Uma skill injeta contexto num job do mesmo jeito que a persona injeta
o system prompt — um `SkillSpec` espelhando `roles.py` é a costura. Mas NÃO se adota por fé:
(a) licença é POR-SKILL (o catálogo ser MIT não cobre o upstream linkado — ler antes de
empacotar); (b) skill com SCRIPT executável = execução de código = Fase 2 atrás do hardening
A1-A5, não é grátis; (c) só entra no roster se MEDIR melhor que persona-sozinha contra o gold
(N>=5). Skill que não move o número não é adotada.

## D11 — Subagent = persona portável + roster privado; é o ativo mais transportável (2026-07-11)
Um subagent NÃO é código: é `persona (prompt) + modelo medido (config) + skill opcional`. A persona
é 100% portável (texto MIT, é input) e roda em qualquer host — este `run_squad`, um AI Gateway, a
chamada própria de outro projeto, ou de volta em Claude Code/Codex/OpenCode (de onde veio). O que
viaja com o subagent é `{persona_file, slug, preço}`. MAS: portável ≠ confiável — só a persona COM
linha de roster medida (N>=5, gold humano) é um subagent confiável; sem medição é persona portável
de qualidade desconhecida. O roster é medido contra um gold específico → transfere como prior forte,
revalide se a tarefa-alvo difere. Ver `docs/design/subagent-portability.md`.

## D12 — Pré-voo do GOLD: veta caso-limpo "não-limpo" antes de gastar (2026-07-11)
Modo de falha recorrente (≥2×): o autor humano marca um trecho como LIMPO (sem bug), mas ele tem um
problema legítimo e sutil (`os.path.basename` sozinho NÃO impede escape via symlink; `for...of await`
sequencial tem custo de performance). A régua de over-flag então conta a minúcia CORRETA do modelo
como "alucinação", e a medição sai enviesada — descoberto só lendo os outputs à mão, DEPOIS de queimar
orçamento. `gold_preflight.py` mata isso na raiz: antes de usar um caso-limpo como âncora, roda a
persona por um JUIZ MEDIDO N vezes e, se a taxa em que ele nomeia a vuln PROIBIDA passa do limiar, o
caso é SUSPEITO → reprova fail-closed com os motivos citados. Ponto fino: a régua do gate ESPELHA a de
scoring (`top_bug_forbids_ruler`), não `top_bug_clean_ruler` — um caso limpo de verdade ainda levanta
preocupações defensáveis DIFERENTES que não são over-flag; puni-las geraria suspeito falso (a v1 do
gate errou exatamente nisso e o dogfood pegou). Integridade preservada (D6): o modelo SINALIZA pra banca
humana, não autora nem remove o caso. Wired opt-in no runner (`clean_preflight_judges`).

## D14 — União com ruflo: Super Squad é a autoridade de modelo; ruflo é substrato (2026-07-12)
Composição-alvo numa pilha só: **subagente (persona, D11) + skill (capacidade, D10) → roda no MODELO
MEDIDO (este motor: roster custo-frontier + gate) → sobre SUBSTRATO (ruflo: memória Graph-RAG cross-sessão,
custo, Agent Booster Tier-1 $0)**. Verificado por leitura (2026-07-12): o roteador de modelo do ruflo é
3-tier SÓ-Claude (booster WASM / Haiku / Sonnet-Opus) — NÃO entrega modelo heterogêneo. Logo o roteamento
de modelo é responsabilidade DESTE motor (o roster medido); o ruflo NÃO decide execução de runtime. Fronteira
dura: roteamento medido/determinístico no runtime; roteamento neural/aprendido do ruflo fica no dev-loop
(nunca produção). Integridade intacta: memória do ruflo é recall/contexto, jamais ground-truth (D6);
promoção segue humana (D5). Seam `RoutingProvider` desenhado em `docs/design/ruflo-union-routing-seam.md`
— NÃO implementado: plugar só o braço que MOVER o número num experimento N≥5 (mesmo gate do D10).

## D13 — Política de shootout: uma âncora frontier + teto de gasto (2026-07-11)
Cada shootout de papel fixa UMA âncora frontier como barra de referência (a que já se mostrou
custo-dominante entre os frontier na medição privada) e concentra o pool nos candidatos baratos —
o objetivo é achar o mais barato que EMPATA a barra, pra baratear o workhorse. A âncora já medida no
mesmo gold é REUSADA, nunca re-rodada. Cada medição roda com teto de gasto (`budget_usd`, fail-soft:
para ao bater o teto). QUAIS modelos são a âncora e os candidatos, e os números, ficam no roster
PRIVADO (D1) — o repo público carrega só a política.
