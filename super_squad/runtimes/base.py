"""runtimes/base.py — o SEAM `BuilderRuntime` (puro, stdlib, zero dependência). O contrato de que o
resto do sistema depende; nenhum runtime concreto é importado aqui.

Fail-closed por design: `NullBuilderRuntime` (default) recusa executar, e `assert_builder_preconditions`
bloqueia qualquer construtor sem os guarda-corpos DUROS (worktree isolada = raio de explosão A1; caps de
passo/tempo = teto mid-loop A5; confirmação humana de que A1–A5 foram tratados). Unir o OpenCode à pilha
NÃO o solta: sem os pré-requisitos, não executa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol


class BuilderGateError(RuntimeError):
    """Execução de construtor BLOQUEADA (pré-requisitos de segurança da Fase 2 não atendidos)."""


@dataclass(frozen=True)
class PermissionProfile:
    """O que o runtime pode tocar. Defaults CONSERVADORES (fail-closed): escreve só na worktree,
    nenhum comando bash liberado, sem rede além da API do modelo."""
    write_paths: "tuple[str, ...]" = ()      # vazio = só a worktree (cwd); nunca o repo principal
    bash_allowlist: "tuple[str, ...]" = ()   # vazio = nenhum comando arbitrário
    network: bool = False                    # sem rede além da chamada ao modelo


@dataclass(frozen=True)
class BuilderTask:
    """Uma tarefa de construtor. `workspace` = worktree ISOLADA (o sandbox); caps DUROS obrigatórios."""
    task_id: str
    role: str
    system_prompt: str
    instruction: str
    model_slug: str
    workspace: str
    max_steps: int
    timeout_s: int
    max_tokens: "Optional[int]" = None
    permission: PermissionProfile = field(default_factory=PermissionProfile)


@dataclass(frozen=True)
class BuilderResult:
    """Produto de uma sessão de construtor. `diff` = git diff da worktree (o que será JULGADO por humano)."""
    task_id: str
    status: str  # "ok" | "error" | "timeout" | "budget" | "empty_diff" | "blocked"
    diff: str = ""
    files_changed: "tuple[str, ...]" = ()
    cost_usd: float = 0.0
    steps: int = 0
    transcript_path: "Optional[str]" = None
    error: "Optional[str]" = None


class BuilderRuntime(Protocol):
    """Contrato do runtime agêntico. `on_event` = mesmo callback de telemetria do motor (OCP)."""
    def run(self, task: BuilderTask, on_event: "Optional[Callable]" = None) -> BuilderResult: ...


class NullBuilderRuntime:
    """Default fail-closed: NENHUM runtime configurado → recusa. O sistema importa e roda os single-shot
    sem OpenCode instalado; só tentar CONSTRUIR sem runtime levanta."""
    def run(self, task: BuilderTask, on_event: "Optional[Callable]" = None) -> BuilderResult:
        raise BuilderGateError(
            "nenhum BuilderRuntime configurado (Fase 2 não habilitada). Construtores exigem um runtime "
            "agêntico atrás do seam + hardening A1–A5. Ver docs/design/opencode-builder-runtime.md."
        )


def assert_builder_preconditions(task: BuilderTask, *, hardening_ack: bool) -> None:
    """Guarda DURA antes de qualquer execução de construtor (fail-closed). Levanta `BuilderGateError`
    listando o que falta. `hardening_ack` = confirmação HUMANA de que A1–A5 (raio de explosão, segredo,
    injection, supply-chain, teto mid-loop) foram tratados — nunca default True."""
    reasons: list = []
    if not task.workspace:
        reasons.append("sem worktree isolada (A1 — raio de explosão = a worktree, nunca o repo principal)")
    if not task.max_steps or task.max_steps <= 0:
        reasons.append("sem cap de passos (A5 — teto mid-loop)")
    if not task.timeout_s or task.timeout_s <= 0:
        reasons.append("sem timeout de wall-clock")
    if not hardening_ack:
        reasons.append("hardening A1–A5 não confirmado pelo humano (segredo/injection/supply-chain)")
    if reasons:
        raise BuilderGateError("execução de construtor BLOQUEADA: " + "; ".join(reasons))
