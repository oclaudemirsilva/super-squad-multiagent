"""Testes herméticos de super_squad.skills — ingestão de skill + composição com persona (D10). Zero rede."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from super_squad import skills as sk


SKILL_CONSULTIVA = """---
name: root-cause-playbook
description: "Procedimento p/ isolar causa-raiz."
allowed-tools: Read, Grep
---

1. Reproduza o sintoma.
2. Bissecção de hipóteses.
3. Reduza ao menor caso.
"""

SKILL_SCRIPT_TOOL = """---
name: autofix
description: "Roda um fixer."
allowed-tools: Read, Bash
---

Aplique a correção.
"""

SKILL_SCRIPT_BODY = """---
name: gen-report
description: "Gera relatório."
allowed-tools: Read
---

Rode `python scripts/report.py` e resuma a saída.
"""


class TestSkills(unittest.TestCase):
    def test_parse_consultative(self):
        s = sk.parse_skill(SKILL_CONSULTIVA)
        self.assertEqual(s.name, "root-cause-playbook")
        self.assertIn("Bissecção", s.procedure)
        self.assertEqual(s.allowed_tools, ("Read", "Grep"))
        self.assertFalse(s.requires_script)

    def test_requires_script_via_builder_tool(self):
        self.assertTrue(sk.parse_skill(SKILL_SCRIPT_TOOL).requires_script)  # Bash

    def test_requires_script_via_body_reference(self):
        self.assertTrue(sk.parse_skill(SKILL_SCRIPT_BODY).requires_script)  # 'python scripts/report.py'

    def test_compose_consultative_ok(self):
        s = sk.parse_skill(SKILL_CONSULTIVA)
        out = sk.compose_system("You are a debugger.", s)
        self.assertIn("You are a debugger.", out)
        self.assertIn("root-cause-playbook", out)
        self.assertIn("Bissecção", out)

    def test_compose_script_gated(self):
        s = sk.parse_skill(SKILL_SCRIPT_TOOL)
        with self.assertRaises(sk.SkillGateError):
            sk.compose_system("SYS", s)
        # com allow_script explícito, compõe (ciente do risco)
        self.assertIn("autofix", sk.compose_system("SYS", s, allow_script=True))

    def test_name_falls_back_to_basename(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "my-skill.md"
            p.write_text("no frontmatter here\njust body", encoding="utf-8")
            self.assertEqual(sk.load_skill(p).name, "my-skill")

    def test_load_skills_dir(self):
        with TemporaryDirectory() as d:
            (Path(d) / "a.md").write_text(SKILL_CONSULTIVA, encoding="utf-8")
            (Path(d) / "b.md").write_text(SKILL_SCRIPT_TOOL, encoding="utf-8")
            loaded = sk.load_skills_dir(d)
            self.assertEqual(set(loaded), {"root-cause-playbook", "autofix"})

    # --- D2: proveniência de licença por-skill (checagem humana, fail-closed) ---
    def test_license_parsed_and_cleared(self):
        text = SKILL_CONSULTIVA.replace("allowed-tools: Read, Grep",
                                        "allowed-tools: Read, Grep\nlicense: MIT\nsource: própria")
        s = sk.parse_skill(text)
        self.assertEqual(s.license, "MIT")
        self.assertEqual(s.source, "própria")
        self.assertTrue(s.license_cleared)

    def test_missing_or_draft_license_not_cleared(self):
        self.assertIsNone(sk.parse_skill(SKILL_CONSULTIVA).license)      # ausente
        self.assertFalse(sk.parse_skill(SKILL_CONSULTIVA).license_cleared)  # fail-closed
        draft = SKILL_CONSULTIVA.replace("allowed-tools: Read, Grep",
                                         "allowed-tools: Read, Grep\nlicense: DRAFT")
        self.assertFalse(sk.parse_skill(draft).license_cleared)         # provisória = não liberada

    def test_ingested_repo_skill_is_cleared(self):
        # a skill real ingerida (D2) carrega licença explícita e passa o gate de proveniência
        repo_skill = Path(__file__).resolve().parents[1] / "roles" / "skills" / "test-design-boundaries.md"
        s = sk.load_skill(repo_skill)
        self.assertEqual(s.license, "MIT")
        self.assertTrue(s.license_cleared)
        self.assertFalse(s.requires_script)   # consultiva, não executa código


if __name__ == "__main__":
    unittest.main()
