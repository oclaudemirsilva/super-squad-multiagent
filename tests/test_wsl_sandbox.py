"""Testes HERMÉTICOS do wsl_sandbox (zero WSL/subprocess real): injetam `_wslpath` (mnt fake) e `_run`
(captura a argv) e verificam o CONTRATO de segurança no SCRIPT construído + o mapeamento de resultados.
O smoke REAL (que exige WSL) mora em test_wsl_sandbox_smoke.py, marcado e opt-in.

Contrato de segurança que estes testes travam (se um refactor apagar um flag, um teste QUEBRA):
  • rede off (`--net`), mount ns + `/mnt` desmontado (host FS escondido), pid ns, cópia p/ ext4.
  • GUARDA-DE-VIDA: `case <mnt> in /mnt/*` — nunca copia a raiz do WSL (mnt fora de /mnt/ → aborta).
  • PATH do Windows NUNCA aparece no script; env limpo (`env -i PATH=<linux>`).
  • ZERO `$(...)` no script (gotcha do wsl.exe) e o wsl.exe recebe SÓ [.., bash, -c, SCRIPT] (sem posicionais).
  • argv viaja no inner base64 (não como comando cru); mapeamento rc 124→timed_out, erro→spawn_error, nunca levanta.
"""
from __future__ import annotations

import base64
import re
import subprocess

from super_squad.wsl_sandbox import wsl_sandboxed_run


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _capture(returncode=0, stdout="ok", stderr=""):
    """Fake de subprocess.run que CAPTURA cada chamada e devolve um proc fixo."""
    calls = []

    def run(argv, **kw):
        calls.append({"argv": argv, "kw": kw})
        return _FakeProc(returncode, stdout, stderr)

    return run, calls


MNT = "/mnt/c/Users/me/AppData/Local/Temp/exec_ruler_ab12"
WIN_CWD = r"C:\Users\me\AppData\Local\Temp\exec_ruler_ab12"
ENV = {"PATH": r"C:\Windows\System32;C:\secret\bin", "LANG": "C.UTF-8",
       "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}


def _script_of(calls):
    """O SCRIPT é o argv[6] da última chamada ao _run (wsl.exe -d Ubuntu -- bash -c SCRIPT)."""
    argv = calls[-1]["argv"]
    assert argv[:6] == ["wsl.exe", "-d", "Ubuntu", "--", "bash", "-c"]
    assert len(argv) == 7, "wsl.exe deve receber SÓ o script (posicionais são descartados por ele)"
    return argv[6]


def _decoded_inner(script):
    """Extrai o base64 do inner (`echo <b64> | base64 -d | bash -s`) e devolve o script decodificado."""
    m = re.search(r"echo ([A-Za-z0-9+/=]+) \| base64 -d", script)
    assert m, "inner base64 não encontrado no script"
    return base64.b64decode(m.group(1)).decode("utf-8")


def _call(argv_in, cwd=WIN_CWD, t=30.0, env=ENV, returncode=0, stdout="ok", stderr="", mnt=MNT):
    run, calls = _capture(returncode, stdout, stderr)
    r = wsl_sandboxed_run(argv_in, cwd, t, env, _run=run, _wslpath=lambda c: mnt)
    return r, calls


def test_isolation_capable_flag():
    # o portão do execution_ruler exige este atributo; sem ele a régua recusa (fail-closed).
    assert getattr(wsl_sandboxed_run, "isolation_capable", False) is True


def test_wsl_invocation_is_only_bash_c_script():
    _, calls = _call(["python", "-m", "pytest"])
    argv = calls[-1]["argv"]
    assert argv[0] == "wsl.exe" and argv[1:6] == ["-d", "Ubuntu", "--", "bash", "-c"]
    assert len(argv) == 7                                   # nenhum posicional (wsl.exe os descarta)
    assert calls[-1]["kw"].get("timeout") == 30.0 + 15      # guarda externa = timeout_s + folga


def test_security_flags_present_in_script():
    _, calls = _call(["true"])
    s = _script_of(calls)
    assert "unshare --net --mount --pid --fork" in s        # rede off + mount/pid ns
    assert "cp -a" in s and "/tmp/exec_ruler_" in s         # copia p/ ext4 (fora de /mnt)
    assert "env -i PATH=/usr/local/bin:/usr/bin:/bin" in s  # env LIMPO, PATH do Linux
    assert "trap " in s and "EXIT" in s                     # limpeza via trap (não `rc=$?`, que vem vazio)
    inner = _decoded_inner(s)
    assert "mount -t tmpfs none /mnt" in inner              # overmonta /mnt vazio (host FS escondido)


def test_no_command_substitution_anywhere():
    # gotcha do wsl.exe: `$(...)` volta VAZIO → o script NÃO pode conter nenhuma.
    _, calls = _call(["true"])
    assert "$(" not in _script_of(calls)


def test_root_copy_guard_present():
    _, calls = _call(["true"])
    # guarda-de-vida: só copia se mnt está sob /mnt/ (senão `cp -a '/.'` = raiz do WSL).
    assert re.search(r"case '?/mnt/[^ ']*'? in /mnt/\*\) ;; \*\) exit 3;; esac", _script_of(calls))


def test_windows_path_never_forwarded():
    _, calls = _call(["true"])
    s = _script_of(calls)
    assert r"C:\Windows\System32" not in s and r"C:\secret\bin" not in s


def test_argv_travels_in_inner_not_as_bare_command():
    argv_in = ["python", "-m", "pytest", "-q", "a b/test_x.py::test_y"]   # nome COM espaço
    _, calls = _call(argv_in)
    inner = _decoded_inner(_script_of(calls))
    # o argv aparece shlex-quoted no inner (nome com espaço fica entre aspas → não vira 2 args)
    assert "exec python -m pytest -q 'a b/test_x.py::test_y'" in inner


def test_env_overrides_lang_and_hashseed():
    env = dict(ENV, LANG="pt_BR.UTF-8", PYTHONHASHSEED="7")
    _, calls = _call(["true"], env=env)
    s = _script_of(calls)
    assert "LANG=pt_BR.UTF-8" in s and "PYTHONHASHSEED=7" in s


def test_missing_env_keys_use_defaults():
    _, calls = _call(["true"], env={})
    s = _script_of(calls)
    assert "LANG=C.UTF-8" in s and "PYTHONHASHSEED=0" in s and "PYTHONDONTWRITEBYTECODE=1" in s


def test_wslpath_failure_maps_to_spawn_error_without_running():
    run, calls = _capture()
    r = wsl_sandboxed_run(["true"], WIN_CWD, 5.0, ENV, _run=run, _wslpath=lambda c: None)
    assert r.spawn_error is True
    assert calls == []                                      # não roda o sandbox se o path não resolve


def test_rc_zero_maps_to_returncode_zero():
    r, _ = _call(["true"], returncode=0, stdout="passed")
    assert r.returncode == 0 and r.timed_out is False and r.spawn_error is False and r.stdout == "passed"


def test_rc_nonzero_maps_to_returncode():
    r, _ = _call(["false"], returncode=1, stderr="assert failed")
    assert r.returncode == 1 and r.timed_out is False and r.stderr == "assert failed"


def test_rc_124_maps_to_timed_out():
    r, _ = _call(["sleep", "999"], returncode=124)          # GNU timeout interno disparou
    assert r.timed_out is True


def test_outer_timeout_maps_to_timed_out():
    def run(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
    r = wsl_sandboxed_run(["sleep", "999"], WIN_CWD, 1.0, ENV, _run=run, _wslpath=lambda c: MNT)
    assert r.timed_out is True and r.spawn_error is False


def test_wsl_missing_maps_to_spawn_error():
    def run(argv, **kw):
        raise FileNotFoundError("wsl.exe")
    r = wsl_sandboxed_run(["true"], WIN_CWD, 5.0, ENV, _run=run, _wslpath=lambda c: MNT)
    assert r.spawn_error is True and "wsl.exe" in r.stderr


def test_never_raises_on_unexpected_error():
    def run(argv, **kw):
        raise ValueError("boom")
    r = wsl_sandboxed_run(["true"], WIN_CWD, 5.0, ENV, _run=run, _wslpath=lambda c: MNT)
    assert r.spawn_error is True and "boom" in r.stderr     # contrato: NUNCA levanta


def test_distro_override_via_env(monkeypatch):
    monkeypatch.setenv("SUPER_SQUAD_WSL_DISTRO", "Ubuntu-24.04")
    run, calls = _capture()
    wsl_sandboxed_run(["true"], WIN_CWD, 5.0, ENV, _run=run, _wslpath=lambda c: MNT)
    assert calls[-1]["argv"][2] == "Ubuntu-24.04"
