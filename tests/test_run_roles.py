"""Testes herméticos de super_squad.run_roles — porta paralela de N papéis. Zero rede.

Injeta run_squad/make_job/load_role/roster fakes → exercita o roteamento paralelo e o fail-soft
por-tarefa sem tocar OpenRouter (nenhum dólar gasto — a medição real é gradual, sob necessidade).
"""
import unittest
from types import SimpleNamespace

from super_squad import run_roles as rr


def fake_load_role(path):
    name = str(path).replace("\\", "/").split("/")[-1].replace(".md", "")
    return SimpleNamespace(name=name, system_prompt=f"SYS[{name}]")


def make_fake_roster(mapping):
    def roster(role):
        return mapping.get(role, [])
    return roster


def fake_make_job(key, task_input, slug, pin, pout, **kw):
    # devolve um "job" inspecionável (o fake run_squad só ecoa)
    return {"key": key, "slug": slug, "input": task_input, "system": kw.get("system")}


def make_fake_run_squad(spent=0.001):
    def run(jobs, workers=1, budget_usd=0.0):
        results = [SimpleNamespace(key=j["key"], model=j["slug"], ok=True,
                                   cost_usd=0.0001, error=None,
                                   value={"text": f"veredito[{j['slug']}] sobre {j['input']}"})
                   for j in jobs]
        return SimpleNamespace(results=results, total_cost_usd=spent, budget_hit=False)
    return run


ROSTER = {  # slugs fictícios — o roster real é privado (D1); o teste só exercita o roteamento
    "code-reviewer": [("vendor/model-a", 0.09, 0.10), ("vendor/model-b", 0.21, 0.32)],
    "security-auditor": [("vendor/model-a", 0.09, 0.10)],
}
COMMON = dict(load_role_fn=fake_load_role, make_job_fn=fake_make_job,
              roster_fn=make_fake_roster(ROSTER), run_squad_fn=make_fake_run_squad())


class TestRunRoles(unittest.TestCase):
    def test_parallel_two_roles_one_fanout(self):
        out = rr.run_roles([{"role": "code-reviewer", "input": "diffA"},
                            {"role": "security-auditor", "input": "diffB"}], **COMMON)
        self.assertEqual(len(out["tasks"]), 2)
        self.assertEqual(out["tasks"][0]["role"], "code-reviewer")
        # titular por default = 1 resultado por papel
        self.assertEqual(len(out["tasks"][0]["results"]), 1)
        self.assertTrue(out["tasks"][0]["results"][0]["ok"])
        self.assertIn("diffA", out["tasks"][0]["results"][0]["text"])
        self.assertIn("diffB", out["tasks"][1]["results"][0]["text"])

    def test_accepts_tuple_form(self):
        out = rr.run_roles([("code-reviewer", "x")], **COMMON)
        self.assertEqual(out["tasks"][0]["role"], "code-reviewer")

    def test_panel_runs_full_roster(self):
        out = rr.run_roles([{"role": "code-reviewer", "input": "x", "panel": True}], **COMMON)
        self.assertEqual(len(out["tasks"][0]["results"]), 2)  # titular + alternado

    def test_empty_roster_is_fail_soft_per_task(self):
        # 'debugger' sem roster → erro NAQUELA tarefa, as outras seguem
        out = rr.run_roles([{"role": "debugger", "input": "x"},
                            {"role": "code-reviewer", "input": "y"}], **COMMON)
        self.assertIsNotNone(out["tasks"][0]["error"])
        self.assertEqual(out["tasks"][0]["results"], [])
        self.assertIsNone(out["tasks"][1]["error"])
        self.assertTrue(out["tasks"][1]["results"][0]["ok"])

    def test_instruction_prefixes_input(self):
        seen = {}

        def spy_make_job(key, prompt, slug, pin, pout, **kw):
            seen[key.split("::")[1]] = prompt
            return {"key": key, "slug": slug, "input": prompt, "system": kw.get("system")}

        common = dict(COMMON)
        common["make_job_fn"] = spy_make_job
        rr.run_roles([{"role": "code-reviewer", "input": "the code",
                       "instruction": "Do X. End with VERDICT:"}], **common)
        self.assertTrue(seen["code-reviewer"].startswith("Do X. End with VERDICT:"))
        self.assertIn("the code", seen["code-reviewer"])

    def test_no_instruction_leaves_input_raw(self):
        seen = {}

        def spy_make_job(key, prompt, slug, pin, pout, **kw):
            seen[key.split("::")[1]] = prompt
            return {"key": key, "slug": slug, "input": prompt, "system": kw.get("system")}

        common = dict(COMMON)
        common["make_job_fn"] = spy_make_job
        rr.run_roles([{"role": "code-reviewer", "input": "raw only"}], **common)
        self.assertEqual(seen["code-reviewer"], "raw only")

    def test_label_override(self):
        out = rr.run_roles([{"role": "code-reviewer", "input": "x", "label": "PR-42"}], **COMMON)
        self.assertEqual(out["tasks"][0]["label"], "PR-42")

    def test_spent_aggregated(self):
        out = rr.run_roles([("code-reviewer", "x"), ("security-auditor", "y")], **COMMON)
        self.assertGreater(out["spent_usd"], 0)

    def test_skill_composed_into_system(self):
        from types import SimpleNamespace
        seen = {}

        def spy_make_job(key, prompt, slug, pin, pout, **kw):
            seen[key.split("::")[1]] = kw.get("system")
            return {"key": key, "slug": slug, "input": prompt}

        def fake_load_skill(path):
            return SimpleNamespace(name="pb", procedure="STEP1; STEP2", requires_script=False)

        def fake_compose(system, skill):
            return f"{system}\n\n## Skill {skill.name}\n{skill.procedure}"

        common = dict(COMMON)
        common.update(make_job_fn=spy_make_job, load_skill_fn=fake_load_skill, compose_fn=fake_compose)
        out = rr.run_roles([{"role": "code-reviewer", "input": "x", "skill": "pb"}], **common)
        self.assertEqual(out["tasks"][0]["skill"], "pb")
        self.assertIn("STEP1; STEP2", seen["code-reviewer"])          # playbook composto
        self.assertIn("SYS[code-reviewer]", seen["code-reviewer"])    # persona preservada

    def test_skill_gate_fail_soft_per_task(self):
        from super_squad.skills import SkillGateError
        from types import SimpleNamespace

        def gated_compose(system, skill):
            raise SkillGateError("skill executa código (Fase 2)")

        common = dict(COMMON)
        common.update(load_skill_fn=lambda p: SimpleNamespace(name="x", requires_script=True),
                      compose_fn=gated_compose)
        out = rr.run_roles([{"role": "code-reviewer", "input": "x", "skill": "x"},
                            {"role": "security-auditor", "input": "y"}], **common)
        self.assertIsNotNone(out["tasks"][0]["error"])   # skill-gated → tarefa erra
        self.assertIn("Fase 2", out["tasks"][0]["error"])
        self.assertIsNone(out["tasks"][1]["error"])      # a outra segue (fail-soft)

    def test_no_skill_uses_persona_system(self):
        seen = {}

        def spy_make_job(key, prompt, slug, pin, pout, **kw):
            seen[key.split("::")[1]] = kw.get("system")
            return {"key": key, "slug": slug, "input": prompt}

        common = dict(COMMON)
        common["make_job_fn"] = spy_make_job
        rr.run_roles([{"role": "code-reviewer", "input": "x"}], **common)
        self.assertEqual(seen["code-reviewer"], "SYS[code-reviewer]")  # sem skill = system puro

    def test_no_jobs_no_crash(self):
        # só papéis quebrados → nenhum job, sem run_squad, sem crash
        out = rr.run_roles([{"role": "ghost", "input": "x"}], **COMMON)
        self.assertIsNotNone(out["tasks"][0]["error"])
        self.assertEqual(out["spent_usd"], 0.0)


if __name__ == "__main__":
    unittest.main()
