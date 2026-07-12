"""Testes herméticos do seam runtimes (Fase 2, construtores) — fail-closed. Zero rede, zero subprocess."""
import unittest
from types import SimpleNamespace

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

    def test_opencode_ready_but_no_subprocess_is_error(self):
        # habilitado + hardened + task válida, sem subprocess injetado → erro honesto (wiring §9 pendente)
        r = OpenCodeRuntime(enabled=True, hardening_ack=True).run(good_task())
        self.assertEqual(r.status, "error")
        self.assertIn("PENDENTE", r.error)

    def test_opencode_subprocess_but_no_command_builder_is_gated(self):
        # §9 não verificada: sem command_builder verificado, recusa (não adivinha flags do binário)
        r = OpenCodeRuntime(enabled=True, hardening_ack=True,
                            subprocess_run=lambda *a, **k: None).run(good_task())
        self.assertEqual(r.status, "error")
        self.assertIn("§9", r.error)

    def test_builder_result_defaults(self):
        r = b.BuilderResult("t", "ok")
        self.assertEqual(r.diff, "")
        self.assertEqual(r.cost_usd, 0.0)
        self.assertEqual(r.files_changed, ())


class TestOpenCodeWiredSequence(unittest.TestCase):
    """Sequência §3 fiada, exercitada 100% com fakes injetados (E2). Zero rede, zero subprocess/disk real."""

    def _fakes(self, *, diff="--- a\n+++ b\n+x", names="f.py\n", usage='{"usage":{"cost_usd":0.02,"steps":3}}',
               opencode_rc=0, opencode_stderr=""):
        calls = {"argv": [], "config": None, "spent": None}

        def subprocess_run(argv, cwd=None, capture_output=True, text=True, timeout=None, env=None):
            calls["argv"].append(argv)
            if argv[:1] == ["git"] and "--name-only" in argv:
                return SimpleNamespace(returncode=0, stdout=names, stderr="")
            if argv[:1] == ["git"] and "diff" in argv:
                return SimpleNamespace(returncode=0, stdout=diff, stderr="")
            # invocação do opencode (via command_builder)
            return SimpleNamespace(returncode=opencode_rc, stdout=usage, stderr=opencode_stderr)

        def command_builder(task, config_path, binary):
            return [binary, "run", "--config", config_path, task.instruction]

        def write_config_fn(path, content):
            calls["config"] = (path, content)

        def record_spend_fn(cost):
            calls["spent"] = cost

        return calls, dict(subprocess_run=subprocess_run, command_builder=command_builder,
                           write_config_fn=write_config_fn, record_spend_fn=record_spend_fn)

    def test_happy_path_produces_diff_and_records_spend(self):
        calls, fakes = self._fakes()
        events = []
        r = OpenCodeRuntime(enabled=True, hardening_ack=True, **fakes).run(
            good_task(), on_event=events.append)
        self.assertEqual(r.status, "ok")
        self.assertIn("+x", r.diff)
        self.assertEqual(r.files_changed, ("f.py",))
        self.assertAlmostEqual(r.cost_usd, 0.02)
        self.assertEqual(r.steps, 3)
        self.assertAlmostEqual(calls["spent"], 0.02)                 # ledger recebeu o gasto real
        self.assertTrue(any(e["event"] == "builder_start" for e in events))
        self.assertTrue(any(e["event"] == "builder_end" for e in events))

    def test_config_written_never_embeds_key(self):
        calls, fakes = self._fakes()
        OpenCodeRuntime(enabled=True, hardening_ack=True, **fakes).run(good_task())
        _, content = calls["config"]
        self.assertIn("OPENROUTER_API_KEY", content)   # referencia o env var
        self.assertNotIn("sk-or-v1-", content)         # nunca o valor literal

    def test_empty_diff_status(self):
        calls, fakes = self._fakes(diff="   \n", names="")
        r = OpenCodeRuntime(enabled=True, hardening_ack=True, **fakes).run(good_task())
        self.assertEqual(r.status, "empty_diff")

    def test_opencode_nonzero_is_error_and_redacted(self):
        calls, fakes = self._fakes(opencode_rc=1, opencode_stderr="boom key=sk-or-v1-" + "a" * 40)
        r = OpenCodeRuntime(enabled=True, hardening_ack=True, **fakes).run(good_task())
        self.assertEqual(r.status, "error")
        self.assertNotIn("sk-or-v1-", r.error)         # stderr redigido

    def test_global_budget_blocks_before_run(self):
        calls, fakes = self._fakes()
        r = OpenCodeRuntime(enabled=True, hardening_ack=True,
                            check_budget_fn=lambda: {"blocked": True, "spent": 99},
                            **fakes).run(good_task())
        self.assertEqual(r.status, "budget")
        self.assertEqual(calls["argv"], [])            # nem chegou a rodar o binário

    def test_timeout_surfaces_as_status(self):
        def sp(argv, **k):
            raise TimeoutError("wall-clock")
        r = OpenCodeRuntime(enabled=True, hardening_ack=True, subprocess_run=sp,
                            command_builder=lambda t, c, b: [b], write_config_fn=lambda p, s: None).run(
            good_task())
        self.assertEqual(r.status, "timeout")


if __name__ == "__main__":
    unittest.main()
