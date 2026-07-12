"""Testes herméticos das primitivas de hardening A1–A5 (E1). Zero rede, zero I/O real.

Exercita o comportamento FAIL-CLOSED de cada guarda: redação de segredo (A2), allowlist de bash com
anti-encadeamento (A3), ciclo de worktree via subprocess_run fake (A1), teto mid-loop thread-safe (A5)
e o despacho de PermissionProfile (composição).
"""
import unittest
from types import SimpleNamespace

from super_squad.runtimes.base import PermissionProfile
from super_squad.runtimes import hardening as H


class TestRedactSecrets(unittest.TestCase):
    def test_redacts_common_secret_shapes(self):
        openrouter = "sk-or-v1-" + "a" * 40
        openai = "sk-" + "B" * 30
        text = (f"key={openrouter} and {openai}\n"
                f"Authorization: Bearer abcdef0123456789ABCDEF\n"
                f"aws AKIAABCDEFGHIJKLMNOP\n"
                f"  API_KEY = supersecretvalue\n")
        out = H.redact_secrets(text)
        for leaked in (openrouter, openai, "abcdef0123456789ABCDEF",
                       "AKIAABCDEFGHIJKLMNOP", "supersecretvalue"):
            self.assertNotIn(leaked, out)
        self.assertIn("[REDACTED]", out)

    def test_idempotent(self):
        once = H.redact_secrets("token=sk-or-v1-" + "z" * 40)
        twice = H.redact_secrets(once)
        self.assertEqual(once, twice)

    def test_non_str_and_bad_extra_pattern(self):
        self.assertEqual(H.redact_secrets(12345), "12345")           # não-str vira str, não levanta
        self.assertEqual(H.redact_secrets("hi", extra_patterns=("(",)), "hi")  # regex ruim é pulado


class TestBashAllowlist(unittest.TestCase):
    def test_empty_allowlist_blocks_all(self):
        self.assertFalse(H.is_bash_allowed("ls", ()))

    def test_first_token_must_be_listed(self):
        self.assertTrue(H.is_bash_allowed("git status", ("git", "ls")))
        self.assertFalse(H.is_bash_allowed("rm -rf /", ("git", "ls")))

    def test_shell_chaining_blocked_even_if_first_allowed(self):
        for evil in ("git status; rm -rf /", "git a && curl x", "git a | sh",
                     "git a > /etc/passwd", "git `whoami`", "git $(whoami)",
                     "git a\nrm -rf /"):
            self.assertFalse(H.is_bash_allowed(evil, ("git",)), evil)

    def test_broken_quotes_blocked(self):
        self.assertFalse(H.is_bash_allowed('git "unterminated', ("git",)))

    def test_assert_raises_and_redacts(self):
        with self.assertRaises(H.BashNotAllowed):
            H.assert_bash_allowed("curl http://x", ("git",))


class TestWorktreeManager(unittest.TestCase):
    def _fake_run(self, returncode=0, stderr=""):
        calls = []

        def run(args, capture_output=True, text=True, timeout=None):
            calls.append({"args": args, "capture_output": capture_output,
                          "text": text, "timeout": timeout})
            return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)
        return run, calls

    def test_add_remove_command_shape(self):
        run, calls = self._fake_run()
        wm = H.WorktreeManager(subprocess_run=run)
        wm.add("/repo", "/wt", "b1", timeout_s=30)
        wm.remove("/repo", "/wt")
        self.assertEqual(calls[0]["args"],
                         ["git", "-C", "/repo", "worktree", "add", "-b", "b1", "/wt"])
        self.assertTrue(calls[0]["capture_output"] and calls[0]["text"])  # captura stderr de verdade
        self.assertEqual(calls[1]["args"],
                         ["git", "-C", "/repo", "worktree", "remove", "--force", "/wt"])

    def test_nonzero_returncode_raises(self):
        run, _ = self._fake_run(returncode=1, stderr="fatal: exists")
        wm = H.WorktreeManager(subprocess_run=run)
        with self.assertRaises(H.WorktreeError):
            wm.add("/repo", "/wt", "b1")

    def test_session_always_removes(self):
        run, calls = self._fake_run()
        wm = H.WorktreeManager(subprocess_run=run)
        with self.assertRaises(ValueError):
            with wm.session("/repo", "/wt", "b1"):
                raise ValueError("corpo explodiu")
        # add + remove chamados mesmo com exceção no corpo (try/finally)
        verbs = [c["args"][4] for c in calls]  # 'add' / 'remove'
        self.assertEqual(verbs, ["add", "remove"])


class TestSpendGuard(unittest.TestCase):
    def test_accumulates_and_reports(self):
        g = H.SpendGuard(1.0)
        self.assertEqual(g.add(0.3), 0.3)
        self.assertEqual(g.add(0.2), 0.5)
        self.assertAlmostEqual(g.spent, 0.5)
        self.assertAlmostEqual(g.remaining, 0.5)

    def test_exceed_raises_but_counts_the_overflow(self):
        g = H.SpendGuard(0.5)
        g.add(0.4)
        with self.assertRaises(H.BudgetExceeded):
            g.add(0.2)  # 0.6 > 0.5
        self.assertAlmostEqual(g.spent, 0.6)   # o custo que estourou É contado
        self.assertEqual(g.remaining, 0.0)


class TestEnforcePermission(unittest.TestCase):
    def test_write_requires_configured_path(self):
        with self.assertRaises(H.PermissionDenied):
            H.enforce_permission(PermissionProfile(), action="write", target="/wt/f.py")

    def test_write_within_allowed_root_ok_escape_blocked(self):
        prof = PermissionProfile(write_paths=("/wt",))
        H.enforce_permission(prof, action="write", target="/wt/sub/f.py")   # ok
        with self.assertRaises(H.PermissionDenied):
            H.enforce_permission(prof, action="write", target="/wt/../etc/passwd")  # escape por ..
        with self.assertRaises(H.PermissionDenied):
            H.enforce_permission(prof, action="write", target="/wtsibling/f.py")    # prefixo espúrio

    def test_bash_delegates_to_allowlist(self):
        prof = PermissionProfile(bash_allowlist=("git",))
        H.enforce_permission(prof, action="bash", target="git status")
        with self.assertRaises(H.BashNotAllowed):
            H.enforce_permission(prof, action="bash", target="rm -rf /")

    def test_network_gated(self):
        with self.assertRaises(H.PermissionDenied):
            H.enforce_permission(PermissionProfile(), action="network", target="https://x")
        H.enforce_permission(PermissionProfile(network=True), action="network", target="https://x")

    def test_unknown_action_denied(self):
        with self.assertRaises(H.PermissionDenied):
            H.enforce_permission(PermissionProfile(), action="exec", target="x")


if __name__ == "__main__":
    unittest.main()
