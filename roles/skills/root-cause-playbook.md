---
name: root-cause-playbook
description: "Playbook consultivo para isolar a causa-raiz de um defeito a partir de sintoma/stack, sem executar nada."
allowed-tools: Read, Grep
---

Ao aplicar este playbook, siga o método (só análise — não execute comandos nem edite arquivos):

1. **Reproduza mentalmente** o sintoma a partir da evidência dada (log/stack/descrição).
2. **Liste hipóteses** ordenadas por probabilidade × facilidade de descartar.
3. **Bissecção**: para cada hipótese, aponte a menor observação que a confirmaria ou eliminaria.
4. **Reduza ao menor caso** que ainda exibe o defeito (o que é essencial vs incidental).
5. **Comprometa-se com UMA causa-raiz** — a mais provável que explica TODAS as evidências, não só uma.

Evite: consertar sintoma em vez de causa; múltiplas causas quando uma explica tudo; culpar sem evidência.
