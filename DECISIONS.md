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
