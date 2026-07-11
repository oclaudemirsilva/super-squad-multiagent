"""Testes herméticos de super_squad.roles — ingestão de persona + job builder. Zero rede."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from super_squad import roles
from super_squad.squad import Job

PERSONA_ADVISORY = """---
name: security-auditor
description: "Use when auditing: security, compliance, risk."
tools: Read, Grep, Glob
model: inherit
---

You are a senior security auditor.
Focus on vulnerabilities and compliance.
"""

PERSONA_BUILDER = """---
name: backend-developer
description: Builds backend services
tools: Read, Write, Edit, Bash
model: sonnet
---

You are a backend developer who writes and runs code.
"""


class TestFrontmatter(unittest.TestCase):
    def test_split_with_frontmatter(self):
        front, body = roles.split_frontmatter(PERSONA_ADVISORY)
        self.assertEqual(front["name"], "security-auditor")
        self.assertEqual(front["tools"], "Read, Grep, Glob")
        self.assertTrue(body.startswith("You are a senior security auditor."))
        # aspas do description desfeitas, dois-pontos internos preservados
        self.assertEqual(front["description"], "Use when auditing: security, compliance, risk.")

    def test_no_frontmatter_returns_whole_body(self):
        front, body = roles.split_frontmatter("just a prompt, no dashes")
        self.assertEqual(front, {})
        self.assertEqual(body, "just a prompt, no dashes")

    def test_crlf_tolerated(self):
        front, _ = roles.split_frontmatter(PERSONA_ADVISORY.replace("\n", "\r\n"))
        self.assertEqual(front["name"], "security-auditor")


class TestClassify(unittest.TestCase):
    def test_advisory_is_single_shot(self):
        self.assertTrue(roles.classify_single_shot(("Read", "Grep", "Glob")))

    def test_builder_is_not_single_shot(self):
        self.assertFalse(roles.classify_single_shot(("Read", "Write", "Bash")))
        self.assertFalse(roles.classify_single_shot(("edit",)))  # case-insensitive

    def test_no_tools_defaults_single_shot(self):
        self.assertTrue(roles.classify_single_shot(()))


class TestParsePersona(unittest.TestCase):
    def test_advisory_spec(self):
        spec = roles.parse_persona(PERSONA_ADVISORY, source_path="x/security-auditor.md")
        self.assertEqual(spec.name, "security-auditor")
        self.assertEqual(spec.declared_tools, ("Read", "Grep", "Glob"))
        self.assertTrue(spec.single_shot)
        self.assertEqual(spec.model_hint, "inherit")
        self.assertIn("senior security auditor", spec.system_prompt)

    def test_builder_spec(self):
        spec = roles.parse_persona(PERSONA_BUILDER)
        self.assertFalse(spec.single_shot)
        self.assertEqual(spec.model_hint, "sonnet")

    def test_name_falls_back_to_filename(self):
        spec = roles.parse_persona("no frontmatter here", source_path="dir/my-role.md")
        self.assertEqual(spec.name, "my-role")


class TestLoad(unittest.TestCase):
    def test_load_dir(self):
        with TemporaryDirectory() as d:
            (Path(d) / "security-auditor.md").write_text(PERSONA_ADVISORY, encoding="utf-8")
            (Path(d) / "backend-developer.md").write_text(PERSONA_BUILDER, encoding="utf-8")
            catalog = roles.load_roles_dir(d)
            self.assertEqual(set(catalog), {"security-auditor", "backend-developer"})
            self.assertTrue(catalog["security-auditor"].single_shot)


class TestMakeRoleJob(unittest.TestCase):
    def test_single_shot_builds_job_and_runs_mocked(self):
        spec = roles.parse_persona(PERSONA_ADVISORY)
        job = roles.make_role_job(
            "job1", spec, "Audit this login form for SQLi.",
            "provider/model-x", 0.1, 0.4, api_key="k",
        )
        self.assertIsInstance(job, Job)
        fake = {
            "choices": [{"message": {"content": "VERDICT: 1 high finding"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        with mock.patch("super_squad.openrouter.openrouter_messages_raw", return_value=fake) as m:
            result, cost = job.run()
        self.assertEqual(result["text"], "VERDICT: 1 high finding")
        self.assertGreaterEqual(cost, 0.0)
        # o system prompt do papel foi passado como system=
        _, kwargs = m.call_args
        self.assertIn("senior security auditor", kwargs["system"])

    def test_builder_role_refuses_motor_shortcut(self):
        spec = roles.parse_persona(PERSONA_BUILDER)
        with self.assertRaises(ValueError):
            roles.make_role_job("j", spec, "input", "m", 0.1, 0.4)


if __name__ == "__main__":
    unittest.main()
