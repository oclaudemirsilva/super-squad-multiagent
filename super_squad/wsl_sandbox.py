"""wsl_sandbox.py — o `run_fn` OS-sandboxed REAL que destrava o `execution_ruler` (hoje fail-closed).

Executa um argv CONFIÁVEL (o teste do gold) num workspace que JÁ recebeu o patch NÃO-confiável do modelo,
dentro de um isolamento honesto sobre WSL2:

  • REDE  → BLOQUEADA (`unshare --net`): sem egress (exfiltrar segredo, baixar payload). Só `lo` (localhost).
  • FS DO HOST → ESCONDIDO: a árvore é COPIADA pro ext4 do WSL (fora de /mnt) e, num mount namespace privado
    (`unshare --mount`), o `/mnt` (onde o C: do Windows aparece) é desmontado ANTES de rodar → o código-com-
    patch não enxerga/lê o disco do host.
  • PID → isolado (`--pid --fork --mount-proc`): não vê/sinaliza processos do host WSL.
  • EFÊMERO → o dir de trabalho é apagado sempre (o patch não persiste entre casos).

⚠ HONESTO (não maquiado): o KERNEL é COMPARTILHADO com a VM leve do WSL2. Isto é uma CERCA forte de
corretude+contenção (mata rede/FS-do-host/persistência/roubo de env), NÃO um limite anti-inquilino-hostil
(exploit de kernel/escape de namespace está FORA do modelo de ameaça). Para adversário real: nsjail/gVisor/
microVM descartável por caso — a costura `run_fn` permite trocar sem tocar a régua.

GOTCHAS de wsl.exe (medidos 2026-07-12, o design DEPENDE deles):
  1. `$(...)` (command substitution) E `$?` voltam VAZIOS via `wsl.exe -- bash -c` (a expansão é mangled).
     → NÃO se usa NENHUM dos dois: o `mnt` (wslpath) é resolvido numa chamada Python SEPARADA, o tmp-dir é
     gerado em Python (uuid), a limpeza usa `trap … EXIT`, e o comando isolado é a ÚLTIMA linha (o exit
     propaga direto — wsl.exe propaga exit code, ISSO funciona). ⚠ Se usasse `rc=$?; exit $rc`, TODA falha
     viraria exit 0 = pass silencioso (bug de instrumento que o oráculo red→green pegou).
  2. Argumentos posicionais depois de `bash -c SCRIPT` são DESCARTADOS pelo wsl.exe → tudo vai EMBUTIDO no
     SCRIPT (valores confiáveis via shlex.quote; o argv confiável idem). O código não-confiável do patch já
     é DADO em arquivo, nunca vira comando.
  3. `wslpath` DIRETO (`wsl.exe -- wslpath`) falha com backslashes; via `bash -c "wslpath -a '<path>'"` ok.
  4. Os drives do host montam em `/mnt/c`, `/mnt/d`… (9p) com montagens wslg aninhadas — `umount -l` de
     cada `/mnt/*` NÃO esconde (ressurgem VISÍVEIS). Esconder o host = OVERMONTAR `/mnt` com um tmpfs vazio.
  GUARDA-DE-VIDA: se `mnt` não começar com `/mnt/`, ABORTA (Python E bash) — senão `cp -a '/.'` copiaria a
  RAIZ inteira do WSL (bug real observado quando o mnt vem vazio).

Pré-requisitos (verificados 2026-07-12): distro WSL2 "Ubuntu" como root (uid 0 → unshare/umount sem sudo),
com `python`, `python -m pytest`, `unshare`/`timeout` (util-linux/coreutils).

SOLID/DIP: `_run` (subprocess.run) e `_wslpath` são injetáveis → testes 100% herméticos (zero WSL real).
"""
from __future__ import annotations

import base64
import os
import shlex
import subprocess
import uuid
from typing import Callable, Optional

WSL_EXE = "wsl.exe"


def _distro() -> str:
    return os.environ.get("SUPER_SQUAD_WSL_DISTRO", "Ubuntu")


def _default_wslpath(cwd: str, distro: str, run: Callable) -> "Optional[str]":
    """Resolve o path Windows→/mnt via `bash -c "wslpath -a '<cwd>'"` (o direto falha com backslashes).
    Devolve o /mnt/... só se for válido (começa com /mnt/), senão None (o chamador vira spawn_error)."""
    try:
        p = run([WSL_EXE, "-d", distro, "--", "bash", "-c", f"wslpath -a {shlex.quote(cwd)}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception:  # noqa: BLE001 — falha de spawn/timeout vira None (spawn_error no chamador)
        return None
    mnt = (p.stdout or "").strip()
    return mnt if p.returncode == 0 and mnt.startswith("/mnt/") else None


def _build_script(mnt: str, wsl_tmp: str, argv: "list[str]", timeout_s: float,
                  lang: str, hashseed: str, dontwrite: str) -> str:
    """Monta o SCRIPT bash SEM nenhum `$(...)` NEM `$?` — AMBOS voltam VAZIOS via `wsl.exe -- bash -c`
    (gotcha medido). Consequências no design: (1) a limpeza usa `trap ... EXIT` (não `rc=$?; exit $rc`,
    que exitaria 0 e mascararia TODA falha como pass); (2) o comando isolado é a ÚLTIMA linha, então seu
    exit propaga DIRETO (wsl.exe propaga exit code — isso funciona). Valores confiáveis via shlex.quote;
    o inner (umount+cd+exec) viaja em base64 (roda num bash-neto, imune ao gotcha)."""
    inner = (
        # ESCONDE o disco do host: overmonta /mnt com um tmpfs VAZIO. (umount -l dos /mnt/* NÃO basta — as
        # montagens 9p/wslg aninhadas ressurgem VISÍVEIS; o tmpfs mascara TUDO de uma vez. Medido 07-12.)
        "mount -t tmpfs none /mnt 2>/dev/null || true\n"
        "ip link set lo up 2>/dev/null || true\n"        # localhost sobe; egress externo continua morto
        f"cd {shlex.quote(wsl_tmp)} || exit 125\n"
        "exec " + " ".join(shlex.quote(a) for a in argv) + "\n"
    )
    b64 = base64.b64encode(inner.encode("utf-8")).decode("ascii")
    inner_cmd = f"echo {b64} | base64 -d | bash -s"
    return (
        "set -e\n"
        # GUARDA-DE-VIDA: mnt tem que estar sob /mnt/ senão `cp -a '/.'` copiaria a raiz do WSL.
        f"case {shlex.quote(mnt)} in /mnt/*) ;; *) exit 3;; esac\n"
        f"mkdir -p {shlex.quote(wsl_tmp)}\n"
        # trap = limpeza que PRESERVA o exit code do último comando (sem tocar em $?, que vem vazio).
        f"trap {shlex.quote('rm -rf ' + shlex.quote(wsl_tmp))} EXIT\n"
        f"cp -a {shlex.quote(mnt + '/.')} {shlex.quote(wsl_tmp + '/')}\n"
        # ÚLTIMA linha: o exit do sandbox vira o exit do script (set -e propaga; 124 = timeout).
        f"timeout --kill-after=5 {shlex.quote(f'{timeout_s:g}')} "
        "unshare --net --mount --pid --fork --mount-proc "
        "env -i PATH=/usr/local/bin:/usr/bin:/bin "
        f"LANG={shlex.quote(lang)} PYTHONHASHSEED={shlex.quote(hashseed)} "
        f"PYTHONDONTWRITEBYTECODE={shlex.quote(dontwrite)} "
        f"bash -c {shlex.quote(inner_cmd)}\n"
    )


def wsl_sandboxed_run(
    argv: "list[str]",
    cwd: str,
    timeout_s: float,
    env: "dict[str, str]",
    *,
    _run: "Optional[Callable]" = None,
    _wslpath: "Optional[Callable]" = None,
):
    """Contrato `run_fn` do execution_ruler: (argv, cwd, timeout_s, env) -> RunResult. NUNCA levanta.
    `cwd` é um path do HOST Windows (o workspace); a árvore é copiada p/ o ext4 do WSL e rodada isolada.
    O PATH do Windows em `env` é DESCARTADO (inútil no Linux); LANG/PYTHONHASHSEED/PYTHONDONTWRITEBYTECODE
    são preservados."""
    from super_squad.execution_ruler import RunResult  # local: evita ciclo de import

    run = _run or subprocess.run
    distro = _distro()
    wslpath = _wslpath or (lambda c: _default_wslpath(c, distro, run))
    try:
        mnt = wslpath(cwd)
        if not mnt:
            return RunResult(spawn_error=True, stderr="wslpath falhou ou mnt fora de /mnt/")
        wsl_tmp = "/tmp/exec_ruler_" + uuid.uuid4().hex
        script = _build_script(
            mnt, wsl_tmp, list(argv), timeout_s,
            env.get("LANG", "C.UTF-8"),
            env.get("PYTHONHASHSEED", "0"),
            env.get("PYTHONDONTWRITEBYTECODE", "1"),
        )
        p = run([WSL_EXE, "-d", distro, "--", "bash", "-c", script],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout_s + 15)
    except subprocess.TimeoutExpired:                 # guarda externa (o `timeout` interno travou)
        return RunResult(timed_out=True)
    except (FileNotFoundError, OSError) as e:         # wsl.exe ausente / falha de spawn
        return RunResult(spawn_error=True, stderr=repr(e))
    except Exception as e:                            # noqa: BLE001 — contrato: NUNCA levanta pro chamador
        return RunResult(spawn_error=True, stderr=repr(e))
    if p.returncode == 124:                           # GNU timeout interno disparou
        return RunResult(timed_out=True, stdout=p.stdout or "", stderr=p.stderr or "")
    return RunResult(returncode=p.returncode, stdout=p.stdout or "", stderr=p.stderr or "")


# marca de capacidade que o portão de isolamento do execution_ruler exige (fail-closed sem ela).
wsl_sandboxed_run.isolation_capable = True
