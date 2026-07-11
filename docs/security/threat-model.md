# Modelo de ameaça — Super Squad + exército de subagents

> Registro VIVO. Resolvemos aos poucos. Cada item tem critério de "resolvido" explícito.
> Regra de ouro: **o Super Squad fiscaliza QUALIDADE, GASTO e ANTI-AUTOFAGIA — ele NÃO é
> um sandbox de segurança.** Segurança de EXECUÇÃO (isolamento, segredos, injection) é uma
> camada SEPARADA. Nunca confundir as duas.

## Legenda
- **Fase 1** = piloto single-shot (só chamada de modelo → veredito; zero write/bash/loop). Inerte.
- **Fase 2** = construtores agênticos (OpenCode escreve+roda código). Onde mora o risco real.
- Status: 🔴 aberto · 🟡 em andamento · 🟢 resolvido · 🔵 política (resolvido por registro).

---

## A. Segurança de execução (Fase 2 — construtores)

Nenhum construtor pode rodar até A1–A5 estarem 🟢. São pré-requisitos DUROS da Fase 2.

### A1 — Raio de explosão no disco/máquina 🔴
Um agente que escreve arquivo e roda bash pode corromper o repo ou a máquina.
Worktree isola o BRANCH, mas é o mesmo usuário/disco/rede — não é fronteira de processo.
**Resolvido quando:** cada sessão de construtor roda em container (ou sandbox equivalente)
com FS/rede/processos limitados, não só numa worktree. Raio de explosão = o container.

### A2 — Vazamento de segredo 🔴
Agente com read + bash pode ler `.env`/credenciais e exfiltrar. Config do OpenCode carrega
`OPENROUTER_API_KEY` do env.
**Resolvido quando:** (a) segredos EXCLUÍDOS do escopo do agente (env mínimo, `.env`/chaves
fora do workspace); (b) egress de rede bloqueado exceto a API do modelo; (c) chave nunca
logada (já é regra no design do adapter — verificar no código quando existir).

### A3 — Prompt injection / input não-confiável 🔴
Agente lê arquivo/página maliciosa que sequestra o loop (ex.: "ignore instruções, rode X").
O Super Squad NÃO tem modelo de ameaça pra isso hoje.
**Resolvido quando:** gate de input não-confiável antes de um construtor autônomo ler
conteúdo arbitrário (scan de injection/PII; marcar fontes não-confiáveis; princípio do
menor privilégio pra bash/rede mesmo com input hostil).

### A4 — Confiar no binário do OpenCode (supply chain) 🔴
OpenCode é código de terceiro rodando com write+bash. O sandbox é tão bom quanto a
implementação dele.
**Resolvido quando:** versão fixada+verificada (checksum), rodando DENTRO do container de A1
(defense-in-depth — não confiar só no sandbox do OpenCode), e um plano de troca (o adapter
já é swappable por design).

### A5 — Sem hard-stop de gasto mid-loop 🔴
`spend_ledger` cerca antes/depois da sessão, mas o loop autônomo gasta numa caixa-preta.
Sem hook de spend do OpenCode, só cap de passo/tempo contém no meio.
**Resolvido quando:** confirmado se o OpenCode expõe hook de spend/step (§9 do design do
adapter). Se sim, wirar hard-stop; se não, `max_steps`/`timeout` conservadores + tratar o
teto por-sessão como ESTIMATIVA documentada, não garantia.

---

## B. Fronteira de governança (princípio)

### B1 — Super Squad ≠ sandbox de segurança 🔵
Registrado pra ninguém (nem eu numa sessão futura) assumir que o painel/gate protege contra
A1–A5. O Squad cobre gasto, autofagia e qualidade; execução segura é a camada separada acima.
**Resolvido por registro.** Manter visível.

### B2 — Painel de juízes é falível 🔵
Painel é FUEL, não juiz infalível — um diff plausível-porém-errado pode passar (memória:
régua/painel = fuel, não canário; N≥5; verificação adversarial).
**Resolvido quando:** merge final é SEMPRE gate humano/Claude, nunca automático. Registrado
como invariante permanente.

### B3 — Anti-autofagia 🔵
Frota promovendo o próprio output como verdade/gold.
**Resolvido por regra dura já vigente:** promoção de gold/truth = SÓ mão humana; o gate nunca
auto-promove (`feedback_corpus_integrity_over_compliance`). Manter mesmo na Fase 2.

---

## C. Vazamento de IP / dados (repo público)

### C1 — Medições vazando no repo PÚBLICO 🟢 (decisão 1 confirmada 2026-07-11)
`labs/super-squad-multiagent` é público+MIT. Commitar `rosters/` (qual modelo vence cada
papel — medido) ou `ground_truth/` (seus gabaritos) = publicar a vantagem de medição, que
é justamente o que a decisão da extração manda MANTER privado. Uma vez pushado público,
é indexado/cacheado pra sempre (irreversível).
**Resolvido:** `ground_truth/`, `_candidate_evals/` e `rosters/` gitignored no standalone
(commit da guarda C1); rosters medidos vivem via override privado `AI_SQUAD_ROSTER_<ROLE>`
(env/arquivo não-commitado); módulo público continua com registry VAZIO + maquinaria +
personas MIT. Decisão 1 (user, 2026-07-11): módulo público = maquinaria + personas; edge
medido fica FORA.

---

## Ordem de ataque sugerida (aos poucos)
1. **C1** — guarda preventiva agora (irreversível se vazar; custo ~0, reversível se optar por tudo-público).
2. **B1/B2/B3** — resolvidos por registro (feito neste doc); manter visíveis.
3. **A5** — barato: verificar a API do OpenCode (§9) e decidir a contenção mid-loop.
4. **A2 → A1 → A4 → A3** — o hardening de execução da Fase 2, só quando o piloto validar
   a esteira e antes de LIGAR qualquer construtor. Nenhum construtor roda com A1–A5 abertos.
