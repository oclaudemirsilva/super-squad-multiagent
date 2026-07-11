# Personas vendorizadas (catálogo de terceiros)

Estas personas são **vendorizadas de repositórios de terceiros**, incluídas aqui como
combustível do exército de subagents (input da esteira de ingestão). Cada uma é o system
prompt de um papel; o Super Squad as consome como `RoleSpec` (ver `super_squad/roles.py`).

## Fonte e licença

Copiadas de **VoltAgent — awesome subagents** (MIT License):

- `security-auditor.md`, `code-reviewer.md`
  — https://github.com/VoltAgent/awesome-claude-code-subagents (categories/04-quality-security/)
- `competitive-analyst.md`
  — https://github.com/VoltAgent/awesome-claude-code-subagents (categories/10-research-analysis/)

> MIT License — Copyright (c) VoltAgent.
> Permission is hereby granted, free of charge, to any person obtaining a copy of this
> software and associated documentation files, to deal in the Software without restriction,
> including the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
> sell copies. The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.

O conteúdo dos `.md` é dos autores originais. A maquinaria que os ingere e roteia (este
módulo) é do Super Squad (MIT, ver LICENSE na raiz).
