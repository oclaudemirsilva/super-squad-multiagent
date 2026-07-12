"""runtimes/hardening.py — primitivas PURAS/injetáveis dos guarda-corpos A1–A5 da Fase 2 (E1).

O seam `base.py` DECLARA o que um construtor pode tocar (`PermissionProfile`) e exige worktree+caps+ack
(`assert_builder_preconditions`). Este módulo é a APLICAÇÃO desses limites — as primitivas que o runtime
agêntico chama para NÃO estourar o raio de explosão:

  A1 (raio de explosão)  `WorktreeManager`   — cria/destrói a worktree isolada (o sandbox).
  A2 (segredo)           `redact_secrets`    — tira chaves/tokens de prompts/outputs/logs.
  A3 (injection)         `is_bash_allowed`   — só executável allowlistado, sem encadeamento de shell.
  A5 (teto mid-loop)     `SpendGuard`        — corta o loop ao estourar o orçamento da sessão.
  composição             `enforce_permission`— despacha write/bash/network sobre um `PermissionProfile`.

Fail-CLOSED em toda decisão de segurança: na dúvida, NEGA. PURO (nenhum I/O real fora do `subprocess_run`
INJETADO no `WorktreeManager`) → testável 100% hermético. stdlib-only. `SpendGuard` é o teto POR-SESSÃO
(em memória, mid-loop) e complementa o `spend_ledger` (teto GLOBAL por janela dia/mês, persistente) — os
dois portões atuam em granularidades diferentes, não se sobrepõem.
"""
from __future__ import annotations

import os
import re
import shlex
import threading
from contextlib import contextmanager
from typing import Callable

from super_squad.runtimes.base import PermissionProfile


# --- A2 — redação de segredo -------------------------------------------------------------------

# Ordem importa: o padrão específico do OpenRouter (`sk-or-v1-…`, com hífens) vem ANTES do genérico
# `sk-…` (que exige alfanumérico contíguo e não casaria a chave com hífens sozinho).
_SECRET_PATTERNS = (
    r"sk-or-v1-[A-Za-z0-9]{24,}",                 # chave OpenRouter
    r"sk-[A-Za-z0-9]{24,}",                        # chave estilo OpenAI
    r"Bearer\s+[A-Za-z0-9._\-]{20,}",             # token Bearer em header
    r"AKIA[0-9A-Z]{16}",                          # AWS access key id
    r"(?mi)^\s*(?:API[ _-]?KEY|SECRET|TOKEN|PASSWORD)\s*=\s*\S+",  # atribuição que cheira a segredo
)


def redact_secrets(text: str, *, extra_patterns: "tuple[str, ...]" = ()) -> str:
    """Substitui segredos por `[REDACTED]`. PURO, nunca levanta (entrada não-str vira str()),
    IDEMPOTENTE (redigir texto já redigido não muda nada). `extra_patterns` = regexes do chamador.
    Fail-closed: um padrão inválido do chamador é PULADO, não derruba a redação dos demais."""
    if not isinstance(text, str):
        text = str(text)
    for pattern in (*_SECRET_PATTERNS, *extra_patterns):
        try:
            text = re.sub(pattern, "[REDACTED]", text)
        except re.error:
            continue  # padrão externo quebrado não anula a redação dos padrões válidos
    return text


# --- A3 — allowlist de bash --------------------------------------------------------------------

class BashNotAllowed(RuntimeError):
    """Comando bash fora da allowlist ou com encadeamento de shell (fail-closed A3)."""


# Operadores que permitiriam rodar algo FORA da allowlist mesmo com o 1º token permitido:
# encadeamento/pipe/redireção/substituição/expansão + quebras de linha (dois comandos numa string).
_SHELL_METACHARS = re.compile(r"[;&|><`$\n\r()]")


def is_bash_allowed(command: str, allowlist: "tuple[str, ...]") -> bool:
    """True só se o executável (1º token via shlex) está na allowlist E o comando não contém
    metacaracteres de shell. allowlist vazia = NADA liberado. shlex quebrado = False. Fail-closed."""
    if not allowlist:
        return False
    if _SHELL_METACHARS.search(command):
        return False  # encadeamento poderia escapar a allowlist → nega mesmo com 1º token válido
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False  # aspas quebradas → não dá pra raciocinar sobre o comando → nega
    if not tokens:
        return False
    return tokens[0] in allowlist


def assert_bash_allowed(command: str, allowlist: "tuple[str, ...]") -> None:
    """Levanta `BashNotAllowed` (com o comando redigido) se `is_bash_allowed` reprovar."""
    if not is_bash_allowed(command, allowlist):
        raise BashNotAllowed(f"comando não permitido pela allowlist A3: {redact_secrets(command)!r}")


# --- A1 — worktree (raio de explosão) ----------------------------------------------------------

class WorktreeError(RuntimeError):
    """Falha ao criar/remover a worktree isolada (A1)."""


class WorktreeManager:
    """Cria/destrói a worktree git ISOLADA que delimita o raio de explosão (A1). O `subprocess_run` é
    INJETADO (DIP) — assinatura estilo `subprocess.run(args, capture_output=True, text=True, timeout=...)`
    com `.returncode`/`.stdout`/`.stderr`. Nenhum I/O direto aqui: o teste passa um fake e roda hermético."""

    def __init__(self, *, subprocess_run: Callable):
        self._run = subprocess_run

    def _git(self, args: "list[str]", timeout_s: int) -> object:
        return self._run(["git", *args], capture_output=True, text=True, timeout=timeout_s)

    def add(self, base_repo: str, worktree_path: str, branch: str, timeout_s: int = 60) -> None:
        """`git -C <base_repo> worktree add -b <branch> <worktree_path>`; returncode != 0 → WorktreeError."""
        res = self._git(["-C", base_repo, "worktree", "add", "-b", branch, worktree_path], timeout_s)
        if res.returncode != 0:
            raise WorktreeError(f"falha ao criar worktree: {redact_secrets(getattr(res, 'stderr', '') or '')}")

    def remove(self, base_repo: str, worktree_path: str, timeout_s: int = 60) -> None:
        """`git -C <base_repo> worktree remove --force <worktree_path>`; returncode != 0 → WorktreeError."""
        res = self._git(["-C", base_repo, "worktree", "remove", "--force", worktree_path], timeout_s)
        if res.returncode != 0:
            raise WorktreeError(f"falha ao remover worktree: {redact_secrets(getattr(res, 'stderr', '') or '')}")

    @contextmanager
    def session(self, base_repo: str, worktree_path: str, branch: str, timeout_s: int = 60):
        """Context manager: add no enter, remove SEMPRE no exit (try/finally) — a worktree não vaza
        nem se o corpo levantar. Yielda `worktree_path`."""
        self.add(base_repo, worktree_path, branch, timeout_s=timeout_s)
        try:
            yield worktree_path
        finally:
            self.remove(base_repo, worktree_path, timeout_s=timeout_s)


# --- A5 — teto mid-loop ------------------------------------------------------------------------

class BudgetExceeded(RuntimeError):
    """Orçamento da sessão do construtor estourado mid-loop (A5)."""


class SpendGuard:
    """Teto de gasto POR-SESSÃO, thread-safe (o fan-out é concorrente). `.add(cost)` acumula e, se o
    total passar do orçamento, levanta `BudgetExceeded` — mas conta o custo que estourou ANTES de
    levantar (o total reflete o gasto real). Fail-closed: orçamento estourado corta o loop."""

    def __init__(self, budget_usd: float):
        self._budget = float(budget_usd)
        self._spent = 0.0
        self._lock = threading.Lock()

    def add(self, cost_usd: float) -> float:
        with self._lock:
            self._spent += float(cost_usd)
            total = self._spent
        if total > self._budget:
            raise BudgetExceeded(f"orçamento mid-loop estourado: ${total:.6f} > ${self._budget:.6f}")
        return total

    @property
    def spent(self) -> float:
        with self._lock:
            return self._spent

    @property
    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self._budget - self._spent)


# --- composição — aplica um PermissionProfile --------------------------------------------------

class PermissionDenied(RuntimeError):
    """Ação negada pelo `PermissionProfile` (fail-closed)."""


def _is_within(target: str, root: str) -> bool:
    """True se `target` está sob `root` (ou é ele). Normaliza ambos (colapsa `..`) e compara prefixo
    com separador — impede escape por `..`. NÃO resolve symlink: é uma barreira de CAMINHO (defesa em
    profundidade sobre a worktree A1), não uma sandbox de FS. O runtime real deve rodar dentro da
    worktree isolada; esta checagem é o segundo cinto, não o único."""
    nt = os.path.normpath(target)
    nr = os.path.normpath(root)
    return nt == nr or nt.startswith(nr + os.sep)


def enforce_permission(profile: PermissionProfile, *, action: str, target: str) -> None:
    """Despacha a decisão sobre um `PermissionProfile`. Fail-closed em tudo:
      write   → `target` precisa estar sob algum `profile.write_paths` (vazio = bloqueia TODO write;
                o chamador passa a worktree explicitamente como caminho permitido).
      bash    → delega a `assert_bash_allowed(target, profile.bash_allowlist)`.
      network → nega se `not profile.network`.
      outro   → ação desconhecida = nega (nunca "passa por omissão")."""
    if action == "write":
        if not profile.write_paths:
            raise PermissionDenied("escrita bloqueada: write_paths vazio (nenhum caminho liberado)")
        if not any(_is_within(target, p) for p in profile.write_paths):
            raise PermissionDenied(f"caminho de escrita fora do permitido: {redact_secrets(target)!r}")
    elif action == "bash":
        assert_bash_allowed(target, profile.bash_allowlist)
    elif action == "network":
        if not profile.network:
            raise PermissionDenied("acesso à rede bloqueado por este PermissionProfile")
    else:
        raise PermissionDenied(f"ação desconhecida (fail-closed): {action!r}")
