"""runtimes — seam do RUNTIME AGÊNTICO (Fase 2, construtores). Ver docs/design/opencode-builder-runtime.md.

O motor single-shot (`squad.py`) roda `job -> (valor, custo)` — não tem tool-loop. Papéis CONSTRUTORES
(escrevem+rodam código) precisam de um runtime agêntico externo (OpenCode candidato). Este pacote é o
SEAM (DIP): o motor clean-room nunca importa OpenCode; o runtime entra atrás de `BuilderRuntime`.

SEGURANÇA: execução de construtor é FAIL-CLOSED por design — `NullBuilderRuntime` (default) recusa, e
`assert_builder_preconditions` bloqueia sem worktree isolada + caps + confirmação humana do hardening
A1–A5. Unir ≠ soltar: o adapter existe e está na pilha, mas não executa código sem os pré-requisitos.
"""
from super_squad.runtimes.base import (  # noqa: F401
    PermissionProfile,
    BuilderTask,
    BuilderResult,
    BuilderRuntime,
    NullBuilderRuntime,
    BuilderGateError,
    assert_builder_preconditions,
)
