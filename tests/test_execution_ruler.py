"""Testes herméticos do execution_ruler — régua objetiva de papel ativo. Zero subprocess/rede/disk real.

Injeta apply_fn/run_fn/make_workspace/env_builder/redact → exercita todo o control-flow e os invariantes
de SEGURANÇA (fail-closed de isolamento, oráculo re-materializado, nunca-levanta) sem executar nada.
"""
import unittest

from super_squad.execution_ruler import (
    execution_ruler, ApplyResult, RunResult, _default_apply, _is_contained,
)


def iso_run(fn):
    """Marca um fake run_fn como isolation_capable (senão o portão fail-closed recusa)."""
    fn.isolation_capable = True
    return fn


BUGGY = {"m.py": b"def f():\n    return 0\n"}


def _ruler(**over):
    """execution_ruler com fakes seguros por default (apply ok, run rc=0, ws capturado)."""
    seen = over.pop("_seen", {})

    def default_apply(text, base, *, patch_target=None):
        return ApplyResult(ok=True, files={**base, "m.py": b"fixed"}, touched=("m.py",))

    def default_run(argv, cwd, timeout_s, env):
        seen.setdefault("runs", []).append(list(argv))
        return RunResult(returncode=0, stdout="ok")

    def default_ws(tree):
        seen["tree"] = tree
        return None  # path None → rmtree(ignore_errors) é no-op; hermético

    kw = dict(apply_fn=default_apply, run_fn=iso_run(default_run),
              make_workspace=default_ws, env_builder=lambda: {"PATH": "/x"},
              redact=lambda s: s.replace("SECRET", "[R]"))
    kw.update(over)
    return execution_ruler(BUGGY, ["pytest", "t.py::test_f"], **kw), seen


class TestExecutionRuler(unittest.TestCase):
    def test_isolation_fail_closed_by_default(self):
        # sem run_fn isolado e sem allow_unsandboxed → RECUSA, não executa
        ran = {"n": 0}

        def spy(argv, cwd, t, env):
            ran["n"] += 1
            return RunResult(0)
        r = execution_ruler(BUGGY, ["pytest"], run_fn=spy)  # spy não é isolation_capable
        out = r("some patch")
        self.assertFalse(out["pass"])
        self.assertEqual(out["label"], "isolation_required")
        self.assertEqual(ran["n"], 0)  # NADA executado

    def test_allow_unsandboxed_override_runs(self):
        def spy(argv, cwd, t, env):
            return RunResult(0)
        r = execution_ruler(BUGGY, ["pytest"], run_fn=spy, allow_unsandboxed=True,
                            apply_fn=lambda text, b, patch_target=None: ApplyResult(True, files=b, touched=()),
                            make_workspace=lambda tree: None)
        self.assertTrue(r("patch")["pass"])

    def test_happy_path(self):
        r, seen = _ruler()
        out = r("--- a/m.py\n+++ b/m.py")
        self.assertTrue(out["pass"])
        self.assertEqual(out["label"], "pass")
        self.assertEqual(out["returncode"], 0)

    def test_test_fail(self):
        r, _ = _ruler(run_fn=iso_run(lambda a, c, t, e: RunResult(returncode=1)))
        out = r("patch")
        self.assertFalse(out["pass"])
        self.assertEqual(out["label"], "test_fail")

    def test_apply_failed_never_runs(self):
        ran = {"n": 0}

        def norun(a, c, t, e):
            ran["n"] += 1
            return RunResult(0)
        r, _ = _ruler(apply_fn=lambda text, b, patch_target=None: ApplyResult(False, reason="hunk_not_found"),
                      run_fn=iso_run(norun))
        out = r("bad patch")
        self.assertFalse(out["pass"])
        self.assertEqual(out["label"], "apply_failed")
        self.assertEqual(ran["n"], 0)  # patch inaplicável NÃO executa

    def test_unsafe_path(self):
        r, _ = _ruler(apply_fn=lambda text, b, patch_target=None: ApplyResult(False, reason="x", unsafe=True))
        self.assertEqual(r("patch")["label"], "unsafe_path")

    def test_oracle_rematerialized_over_patch(self):
        # o patch alega ter tocado o próprio teste → marca patched_oracle E sobrescreve com o confiável
        seen = {}

        def apply(text, b, patch_target=None):
            return ApplyResult(True, files={"t.py": b"MALICIOUS", "m.py": b"x"}, touched=("t.py", "m.py"))

        def ws(tree):
            seen["tree"] = tree
            return None
        r = execution_ruler(BUGGY, ["pytest"], test_files={"t.py": b"TRUSTED"}, allow_unsandboxed=True,
                            apply_fn=apply, run_fn=lambda a, c, t, e: RunResult(0), make_workspace=ws)
        out = r("patch touching t.py")
        self.assertEqual(seen["tree"]["t.py"], b"TRUSTED")   # oráculo confiável venceu o do patch
        self.assertEqual(out["label"], "patched_oracle_pass")

    def test_collection_hook_planted_by_patch_removed(self):
        seen = {}

        def apply(text, b, patch_target=None):
            return ApplyResult(True, files={"conftest.py": b"import os", "m.py": b"x"}, touched=("conftest.py",))
        r = execution_ruler(BUGGY, ["pytest"], test_files={}, allow_unsandboxed=True, apply_fn=apply,
                            run_fn=lambda a, c, t, e: RunResult(0),
                            make_workspace=lambda tree: seen.setdefault("tree", tree) and None or None)
        r("patch that plants conftest")
        self.assertNotIn("conftest.py", seen["tree"])  # hook plantado foi removido

    def test_setup_failed_skips_test(self):
        calls = []

        def run(argv, c, t, e):
            calls.append(argv[0])
            return RunResult(returncode=2 if argv[0] == "build" else 0)
        r, _ = _ruler(setup_cmd=["build"], run_fn=iso_run(run))
        out = r("patch")
        self.assertEqual(out["label"], "setup_failed")
        self.assertEqual(calls, ["build"])  # o teste NÃO roda

    def test_setup_timeout(self):
        r, _ = _ruler(setup_cmd=["build"],
                      run_fn=iso_run(lambda a, c, t, e: RunResult(timed_out=True)))
        self.assertEqual(r("p")["label"], "setup_timeout")

    def test_test_timeout(self):
        r, _ = _ruler(run_fn=iso_run(lambda a, c, t, e: RunResult(timed_out=True)))
        out = r("p")
        self.assertEqual(out["label"], "test_timeout")
        self.assertIsNone(out["returncode"])

    def test_run_error_spawn(self):
        r, _ = _ruler(run_fn=iso_run(lambda a, c, t, e: RunResult(spawn_error=True)))
        self.assertEqual(r("p")["label"], "run_error")

    def test_ruler_never_raises(self):
        def boom(text, b, patch_target=None):
            raise RuntimeError("boom SECRET")
        r, _ = _ruler(apply_fn=boom)
        out = r("p")  # não deve levantar
        self.assertFalse(out["pass"])
        self.assertEqual(out["label"], "ruler_error")
        self.assertNotIn("SECRET", out["detail"])  # redigido

    def test_expect_substring(self):
        r_hit, _ = _ruler(expect="exit0+substring:PASSED",
                          run_fn=iso_run(lambda a, c, t, e: RunResult(0, stdout="all PASSED")))
        r_miss, _ = _ruler(expect="exit0+substring:PASSED",
                           run_fn=iso_run(lambda a, c, t, e: RunResult(0, stdout="nope")))
        self.assertTrue(r_hit("p")["pass"])
        self.assertFalse(r_miss("p")["pass"])   # rc0 mas sem a substring confiável → falha

    def test_argv_never_contains_patch_text(self):
        seen = {}
        r, s = _ruler(run_fn=iso_run(lambda a, c, t, e: seen.setdefault("argv", list(a)) and RunResult(0) or RunResult(0)))
        r("; rm -rf / #malicious")
        self.assertEqual(seen["argv"], ["pytest", "t.py::test_f"])  # patch nunca vira argv

    def test_unsafe_buggy_file_key(self):
        def ws(tree):
            raise ValueError("unsafe_path:../escape")
        r = execution_ruler({"../escape": b"x"}, ["pytest"], allow_unsandboxed=True,
                            apply_fn=lambda text, b, patch_target=None: ApplyResult(True, files=b, touched=()),
                            make_workspace=ws)
        out = r("p")
        self.assertFalse(out["pass"])
        self.assertEqual(out["label"], "ruler_error")  # exceção do ws vira veredito, não crash


class TestDefaultApply(unittest.TestCase):
    def test_content_search_ignores_stale_offsets(self):
        base = {"m.py": b"a\nb\nc\nd\n"}
        # offset mentiroso (@@ -99), mas contexto/removida casam por conteúdo
        diff = "--- a/m.py\n+++ b/m.py\n@@ -99,2 +99,2 @@\n b\n-c\n+C\n"
        res = _default_apply(diff, base)
        self.assertTrue(res.ok)
        self.assertEqual(res.files["m.py"], b"a\nb\nC\nd\n")

    def test_whole_or_nothing_on_missing_context(self):
        base = {"m.py": b"a\nb\n"}
        diff = "--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-NOTHERE\n+x\n"
        res = _default_apply(diff, base)
        self.assertFalse(res.ok)  # bloco não encontrado byte-exato → falha

    def test_unsafe_diff_path(self):
        res = _default_apply("--- a\n+++ b/../../etc/x\n@@ -1 +1 @@\n a\n", {})
        self.assertTrue(res.unsafe)

    def test_empty_patch(self):
        self.assertFalse(_default_apply("", {}).ok)

    def test_is_contained(self):
        self.assertTrue(_is_contained("a/b.py"))
        self.assertFalse(_is_contained("../x"))
        self.assertFalse(_is_contained("/abs"))
        self.assertFalse(_is_contained("a\x00b"))


if __name__ == "__main__":
    unittest.main()
