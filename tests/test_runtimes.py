"""Testes herméticos do seam runtimes (Fase 2, construtores) — fail-closed. Zero rede, zero subprocess."""
import unittest

from super_squad.runtimes import base as b
from super_squad.runtimes.opencode import OpenCodeRuntime


def good_task(**over):
    d = dict(task_id="t1", role="backend-builder", system_prompt="SYS", instruction="do X",
             model_slug="vendor/m", workspace="/tmp/wt", max_steps=8, timeout_s=120)
    d.update(over)
    return b.BuilderTask(**d)


class TestRuntimeSeam(unittest.TestCase):
    def test_permission_defaults_are_conservative(self):
        p = b.PermissionProfile()
        self.assertEqual(p.write_paths, ())
        self.assertEqual(p.bash_allowlist, ())
        self.assertFalse(p.network)

    def test_null_runtime_refuses(self):
        with self.assertRaises(b.BuilderGateError):
            b.NullBuilderRuntime().run(good_task())

    def test_preconditions_pass_when_all_present(self):
        b.assert_builder_preconditions(good_task(), hardening_ack=True)  # não levanta

    def test_preconditions_block_without_worktree(self):
        with self.assertRaises(b.BuilderGateError) as cm:
            b.assert_builder_preconditions(good_task(workspace=""), hardening_ack=True)
        self.assertIn("worktree", str(cm.exception))

    def test_preconditions_block_without_caps(self):
        with self.assertRaises(b.BuilderGateError):
            b.assert_builder_preconditions(good_task(max_steps=0), hardening_ack=True)
        with self.assertRaises(b.BuilderGateError):
            b.assert_builder_preconditions(good_task(timeout_s=0), hardening_ack=True)

    def test_preconditions_block_without_hardening_ack(self):
        with self.assertRaises(b.BuilderGateError) as cm:
            b.assert_builder_preconditions(good_task(), hardening_ack=False)
        self.assertIn("hardening", str(cm.exception))

    def test_opencode_disabled_by_default_is_blocked(self):
        r = OpenCodeRuntime().run(good_task())
        self.assertEqual(r.status, "blocked")
        self.assertIn("DESABILITADO", r.error)

    def test_opencode_enabled_but_preconditions_fail_is_blocked(self):
        r = OpenCodeRuntime(enabled=True, hardening_ack=True).run(good_task(workspace=""))
        self.assertEqual(r.status, "blocked")
        self.assertIn("worktree", r.error)

    def test_opencode_enabled_no_hardening_ack_is_blocked(self):
        r = OpenCodeRuntime(enabled=True, hardening_ack=False).run(good_task())
        self.assertEqual(r.status, "blocked")
        self.assertIn("hardening", r.error)

    def test_opencode_ready_but_wiring_pending_is_error(self):
        # habilitado + hardened + task válida, sem subprocess injetado → erro honesto (wiring §9 pendente)
        r = OpenCodeRuntime(enabled=True, hardening_ack=True).run(good_task())
        self.assertEqual(r.status, "error")
        self.assertIn("PENDENTE", r.error)

    def test_opencode_real_path_not_implemented_yet(self):
        # com subprocess injetado, o caminho real ainda é NotImplementedError (scaffold honesto)
        with self.assertRaises(NotImplementedError):
            OpenCodeRuntime(enabled=True, hardening_ack=True,
                            subprocess_run=lambda *a, **k: None).run(good_task())

    def test_builder_result_defaults(self):
        r = b.BuilderResult("t", "ok")
        self.assertEqual(r.diff, "")
        self.assertEqual(r.cost_usd, 0.0)
        self.assertEqual(r.files_changed, ())


if __name__ == "__main__":
    unittest.main()
