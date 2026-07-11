"""Testes herméticos de run_role — a porta da frente do subagent. Zero rede (deps injetadas)."""
import unittest
from pathlib import Path

from super_squad.run_role import run_role
from super_squad.squad import Job, run_squad

PERSONA = Path(__file__).resolve().parents[1] / "roles" / "vendor" / "code-reviewer.md"


def _fake_make_job(text_by_slug):
    """make_job fake: cada Job.run() devolve o texto de `text_by_slug[slug]`, custo fixo."""
    def make_job(key, prompt, model, pin, pout, *, system=None, temperature=0.2,
                 timeout=120, api_key=None, max_tokens=None):
        return Job(key=key, run=lambda: ({"model": model, "text": text_by_slug[model]}, 0.001),
                   model=model)
    return make_job


class TestRunRole(unittest.TestCase):
    def test_empty_roster_raises_with_guidance(self):
        with self.assertRaises(RuntimeError) as cm:
            run_role("code-reviewer", "x", roster=[], load_role_fn=lambda p: _spec(),
                     run_squad_fn=run_squad, make_job_fn=_fake_make_job({}))
        self.assertIn("AI_SQUAD_ROSTER_CODE_REVIEWER", str(cm.exception))

    def test_titular_only_by_default(self):
        roster = [("prov/titular", 0.2, 0.8), ("prov/alt", 0.2, 0.8)]
        out = run_role("code-reviewer", "review this", roster=roster,
                       load_role_fn=lambda p: _spec(),
                       run_squad_fn=run_squad,
                       make_job_fn=_fake_make_job({"prov/titular": "TITULAR verdict",
                                                   "prov/alt": "ALT verdict"}))
        self.assertEqual(out["model"], "prov/titular")
        self.assertEqual(out["text"], "TITULAR verdict")
        self.assertEqual(len(out["results"]), 1)  # só o titular

    def test_panel_runs_whole_roster(self):
        roster = [("prov/titular", 0.2, 0.8), ("prov/alt", 0.2, 0.8)]
        out = run_role("code-reviewer", "review this", roster=roster, panel=True,
                       load_role_fn=lambda p: _spec(),
                       run_squad_fn=run_squad,
                       make_job_fn=_fake_make_job({"prov/titular": "A", "prov/alt": "B"}))
        models = sorted(r["model"] for r in out["results"])
        self.assertEqual(models, ["prov/alt", "prov/titular"])
        self.assertAlmostEqual(out["spent_usd"], 0.002, places=6)

    def test_uses_real_persona_system_prompt(self):
        # o system prompt REAL da persona deve chegar no make_job (via load_role real)
        captured = {}
        def make_job(key, prompt, model, pin, pout, *, system=None, **kw):
            captured["system"] = system
            return Job(key=key, run=lambda: ({"model": model, "text": "ok"}, 0.0), model=model)
        run_role("code-reviewer", "x", roster=[("m", 0.1, 0.1)],
                 run_squad_fn=run_squad, make_job_fn=make_job)  # load_role real (le o arquivo)
        self.assertIn("code review", captured["system"].lower())


def _spec():
    from super_squad.roles import RoleSpec
    return RoleSpec(name="code-reviewer", description="", system_prompt="You review code.",
                    declared_tools=(), model_hint="inherit", single_shot=True)


if __name__ == "__main__":
    unittest.main()
