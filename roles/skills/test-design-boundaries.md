---
name: test-design-boundaries
description: "Playbook consultivo de desenho de teste por partição de equivalência + análise de valor-limite, para julgar se uma suíte cobre o que importa. Só análise, não executa nada."
allowed-tools: Read
license: MIT
source: "prosa própria (MIT); método = partição de equivalência + valor-limite, conhecimento público de teste de software (não há texto de terceiro embutido)"
---

Ao julgar ou propor testes para uma unidade, aplique este método (só raciocínio — não rode código):

1. **Identifique as ENTRADAS e seus domínios** — para cada parâmetro/estado de entrada, qual é o
   conjunto de valores possíveis (tipo, faixa, formato, nulabilidade).
2. **Particione em classes de EQUIVALÊNCIA** — agrupe valores que o código deveria tratar do mesmo jeito
   (uma classe válida + as inválidas relevantes). Um caso por classe cobre a classe inteira; N casos na
   MESMA classe são redundância, não cobertura.
3. **Ataque os VALORES-LIMITE** — para cada faixa, teste no limite e logo além: mínimo, mínimo−1, máximo,
   máximo+1, zero, vazio, um-elemento. É onde off-by-one e overflow vivem.
4. **Cubra o CAMINHO DE ERRO, não só o feliz** — para cada classe inválida, o teste afirma o comportamento
   ESPECIFICADO (levanta? retorna sentinela? ignora?), não apenas "não quebra".
5. **Verifique o ORÁCULO** — cada teste tem de afirmar o RESULTADO correto, não só que rodou sem exceção;
   um teste sem asserção de valor é teatro de cobertura.

Ao julgar uma suíte existente, reprove quando: classes de equivalência inteiras não têm caso; os limites
não são exercidos; só o caminho feliz é coberto; ou há asserções ausentes/triviais (`assert result`).
Elogie concisão: uma suíte mínima que cobre todas as classes + limites vence uma suíte inchada e redundante.
