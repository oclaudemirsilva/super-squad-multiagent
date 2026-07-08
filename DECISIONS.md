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
