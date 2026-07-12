"""Testes HERMÉTICOS do harvest_validate (zero WSL/git real): injetam `run_fn`/`make_workspace`/`harvest_fn`.
Travam a LÓGICA que decide se um caso colhido é gold red→green válido — o ponto onde um falso-positivo
contaminaria o gold do code-writer.
"""
from __future__ import annotations

from super_squad.execution_ruler import RunResult
from super_squad.harvest_validate import harvest_and_validate, validate_red_green

_BUGGY = {"m.py": b"buggy"}
_FIXED = {"m.py": b"fixed"}
_TEST = {"test_m.py": b"test"}
_CMD = ["python", "-m", "pytest", "-q", "test_m.py"]


def _seq(*results):
    """run_fn fake: devolve os RunResult na ORDEM chamada (validate roda red, depois green)."""
    it = iter(results)

    def run(argv, cwd, t, env):
        return next(it)

    return run


def _validate(*results):
    return validate_red_green(_BUGGY, _FIXED, _TEST, _CMD,
                              run_fn=_seq(*results), make_workspace=lambda f: "ws", env_builder=dict)


def test_valid_when_red_fails_and_green_passes():
    v = _validate(RunResult(returncode=1), RunResult(returncode=0))
    assert v["valid"] is True and v["reason"] == "ok"
    assert v["red_fail"] is True and v["green_pass"] is True


def test_invalid_when_baseline_does_not_fail():
    # o teste passa JÁ no código-com-bug → não pega o bug daquele estado → inútil como gold.
    v = _validate(RunResult(returncode=0), RunResult(returncode=0))
    assert v["valid"] is False and v["reason"] == "baseline_nao_falhou"


def test_invalid_when_fix_does_not_pass():
    v = _validate(RunResult(returncode=1), RunResult(returncode=1))
    assert v["valid"] is False and v["reason"] == "fix_nao_passou"


def test_red_timeout_is_not_a_clean_fail():
    # timeout no baseline NÃO conta como 'red' honesto (pode ser lentidão, não o bug).
    v = _validate(RunResult(timed_out=True), RunResult(returncode=0))
    assert v["valid"] is False and v["red_fail"] is False


def test_red_spawn_error_is_not_a_clean_fail():
    v = _validate(RunResult(spawn_error=True, stderr="x"), RunResult(returncode=0))
    assert v["valid"] is False and v["red_fail"] is False


def test_green_spawn_error_is_not_a_pass():
    v = _validate(RunResult(returncode=1), RunResult(spawn_error=True))
    assert v["valid"] is False and v["green_pass"] is False


def test_validate_never_raises_on_run_fn_error():
    def boom(argv, cwd, t, env):
        raise RuntimeError("kaboom")
    v = validate_red_green(_BUGGY, _FIXED, _TEST, _CMD,
                           run_fn=boom, make_workspace=lambda f: "ws", env_builder=dict)
    assert v["valid"] is False  # erro vira spawn_error → não-válido, sem levantar


# ── driver harvest_and_validate (harvest_fn + fetch_fixed + run_fn injetados) ──

def _fake_case(cid="repo@abc123"):
    return {
        "case_id": cid, "role": "debugger", "ruler": "execution",
        "buggy_files": dict(_BUGGY), "test_files": dict(_TEST), "test_cmd": list(_CMD),
        "provenance": {"sha": "abc123def4", "parent": "0000fed321", "repo": "repo"},
    }


def test_harvest_and_validate_keeps_only_valid():
    cases = [_fake_case("repo@aaa"), _fake_case("repo@bbb")]
    # aaa: red falha, green passa (válido) ; bbb: baseline não falha (descarta)
    results = iter([RunResult(returncode=1), RunResult(returncode=0),   # aaa
                    RunResult(returncode=0), RunResult(returncode=0)])   # bbb

    def run_fn(argv, cwd, t, env):
        return next(results)

    validated, report = harvest_and_validate(
        "x/repo",
        harvest_fn=lambda rg, **kw: (cases, []),
        run_git=lambda args: None,
        fetch_tree=lambda ref: dict(_FIXED),   # árvore completa (mesma p/ pai e fix no teste)
        run_fn=run_fn,
    )
    assert [c["case_id"] for c in validated] == ["repo@aaa"]
    assert validated[0]["expect_baseline_fail"] is True
    assert {r["case_id"]: r["reason"] for r in report} == {
        "repo@aaa": "ok", "repo@bbb": "baseline_nao_falhou"}


def test_harvest_and_validate_skips_when_no_tree():
    validated, report = harvest_and_validate(
        "x/repo",
        harvest_fn=lambda rg, **kw: ([_fake_case()], []),
        run_git=lambda args: None,
        fetch_tree=lambda ref: {},   # árvore vazia (git archive falhou)
        run_fn=lambda *a: RunResult(returncode=0),
    )
    assert validated == []
    assert report[0]["reason"] == "sem_arvore"
