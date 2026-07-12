"""Smoke REAL do wsl_sandbox — exige WSL2 Ubuntu (pula limpo onde não houver). Prova, de ponta a ponta,
que o `execution_ruler` (antes fail-closed) AGORA executa de verdade com isolamento honesto:
  • red→green: patch correto → o teste do gold PASSA; patch errado → falha (o oráculo é execução real).
  • rede BLOQUEADA: abrir socket externo falha dentro da cela.
  • FS do host ESCONDIDO: /mnt/c some no mount namespace.

Não é hermético (roda WSL de verdade), por isso é marcado `wsl` e skip-if-unavailable — a suíte hermética
(test_wsl_sandbox.py) cobre o contrato sem WSL. Aqui o valor é a PROVA física do isolamento.
"""
from __future__ import annotations

import functools
import subprocess

import pytest

from super_squad.execution_ruler import execution_ruler
from super_squad.wsl_sandbox import wsl_sandboxed_run


@functools.lru_cache(maxsize=1)
def _wsl_available() -> bool:
    try:
        p = subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "python", "-m", "pytest", "--version"],
                           capture_output=True, text=True, timeout=30)
        return p.returncode == 0
    except Exception:  # noqa: BLE001
        return False


pytestmark = [
    pytest.mark.wsl,
    pytest.mark.skipif(not _wsl_available(), reason="WSL2 Ubuntu com pytest indisponível"),
]

_ENV = {"LANG": "C.UTF-8", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}

# gold: código-com-bug (subtrai em vez de somar) + teste confiável que exige a soma.
_BUGGY = {"m.py": b"def add(a, b):\n    return a - b\n"}
_TEST = {"test_m.py": b"from m import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"}
_TEST_CMD = ["python", "-m", "pytest", "-q", "test_m.py"]

# patch (arquivo inteiro) que CONSERTA o bug: subtração → soma.
_GOOD_PATCH = "def add(a, b):\n    return a + b\n"
# patch que NÃO conserta (multiplica): o oráculo tem que reprovar.
_BAD_PATCH = "def add(a, b):\n    return a * b\n"


def _ruler():
    return execution_ruler(_BUGGY, _TEST_CMD, test_files=_TEST, patch_target="m.py",
                           run_fn=wsl_sandboxed_run, timeout_s=60.0, env_builder=lambda: _ENV)


def test_red_to_green_correct_patch_passes():
    v = _ruler()(_GOOD_PATCH)
    assert v["pass"] is True, v
    assert v["label"] == "pass"


def test_wrong_patch_fails_the_oracle():
    v = _ruler()(_BAD_PATCH)
    assert v["pass"] is False, v
    assert v["label"] == "test_fail"


def test_network_egress_blocked():
    argv = ["python", "-c", "import socket; socket.create_connection(('1.1.1.1', 53), 3)"]
    r = wsl_sandboxed_run(argv, _WS := _mkws(), 25.0, _ENV)
    assert r.returncode != 0 and not r.spawn_error, (r.returncode, r.stderr)


def test_host_filesystem_hidden():
    argv = ["bash", "-c", "ls /mnt/c >/dev/null 2>&1 && echo VISIBLE || echo HIDDEN"]
    r = wsl_sandboxed_run(argv, _mkws(), 25.0, _ENV)
    assert (r.stdout or "").strip() == "HIDDEN", (r.returncode, r.stdout, r.stderr)


def _mkws() -> str:
    """Um workspace host vazio (os testes de isolamento não precisam de arquivos)."""
    import tempfile
    return tempfile.mkdtemp(prefix="wsl_smoke_")
