# Benchmark statement (public, anonymized)

> O que este projeto AFIRMA e COMO mede — sem publicar slugs, preços ou os números medidos. Esses ficam
> no roster PRIVADO (ver `DECISIONS.md` D1). A afirmação aqui é de MÉTODO + valor qualitativo; qualquer
> pessoa reproduz o método contra o SEU próprio ground-truth e obtém os SEUS números.

## A tese, em uma frase

Para muitos papéis consultivos (revisar código, auditar segurança, julgar testes), **o modelo mais barato
que EMPATA o frontier no seu ground-truth não é o frontier** — e a diferença de custo é grande. O valor do
sistema não é uma lista de modelos; é o **regime de medição** que acha esse modelo por papel e pega o
próprio erro antes de gastar.

## O que é medido

Por papel, num gold de mão humana:

- **Detecção** — o papel nomeia o problema que o caso-com-bug contém (recall via régua determinística).
- **Over-flag** — num caso LIMPO, o papel NÃO inventa um problema proibido (precisão; alucinação é penalidade).
- **Custo por decisão** e **latência** como critérios de desempate.

A régua é DETERMINÍSTICA e vem do gold (`rulers.resolve_ruler`), nunca de um modelo julgando outro.

## Como é medido (o regime)

1. **N≥5 por decisão** (nunca N=1/N=2) — repetições com fontes/casos DISTINTOS. Amostra pequena mente:
   uma "régua de 100%" com N=2 caiu para uma fração disso quando N cresceu.
2. **Uma âncora frontier por papel** — a barra de referência. Medida uma vez e REUSADA, nunca re-rodada.
3. **Teto de gasto por medição** (fail-soft) — a medição para ao bater o teto; nada roda sem chave viva
   (pré-voo fail-closed).
4. **Pré-voo do gold** — antes de usar um caso "limpo" como âncora, um juiz medido tenta nomear a vuln
   proibida; se acha demais, o caso é SUSPEITO e reprova (o autor humano do gold erra de formas sutis, e a
   régua de over-flag herdaria o erro). Achado ao ler os outputs à mão, depois de queimar orçamento — por
   isso virou portão.
5. **Anti-autofagia** — o modelo medido JAMAIS autora o próprio juiz. O gold é de mão humana; o motor lê
   golds, nunca os escreve. Promoção de modelo a titular é decisão humana, nunca auto-rewire da própria
   medição (o loop que se auto-ajusta pela própria régua é o caminho mais curto para o viés invisível).

## A afirmação de valor (anonimizada)

No papel que já firmamos (revisão de código), num ground-truth simétrico de mão humana (casos com bug +
gêmeos limpos), medido com N≥10:

- Um modelo de peso aberto **substancialmente mais barato empatou a âncora frontier** em detecção E em não
  inventar problema (over-flag), a uma **fração do custo por detecção**.
- O instrumento de medição pegou **os próprios bugs do autor** (casos "limpos" que não eram; artefato de
  max_tokens que esvaziava respostas de um modelo) ANTES de virar número publicado — a medição consertou
  a si mesma ao ser feita com honestidade.

Números exatos (quais modelos, qual fração de custo, quais preços) NÃO são publicados: são o diferencial
medido (D1). O que é público é o método e o fato de que a lacuna existe e é reprodutível.

## Postura honesta (limitações)

- **Um papel firme, os outros em andamento.** A tese está provada em um papel; os demais estão sendo medidos
  na mesma disciplina. Não extrapolamos de um papel para "todos os papéis".
- **O gold é específico.** Um roster medido contra um gold transfere como PRIOR forte, não como garantia —
  revalide se a tarefa-alvo difere do gold.
- **Sem número público é uma escolha, não uma evasão.** A metodologia é totalmente aberta; reproduza-a
  contra o SEU gold. Copiar um roster de terceiros pularia exatamente a etapa que faz o sistema funcionar.

## Reproduzir

Monte um gold de mão humana no contrato de `role_eval` (casos com régua determinística), rode
`super_squad.role_eval.run_role_eval(gold, persona, pool, ...)` cruzando o SEU pool de candidatos contra a
SUA âncora, N≥5. O runner entrega pass-rate/custo/latência por modelo; a promoção é sua.
