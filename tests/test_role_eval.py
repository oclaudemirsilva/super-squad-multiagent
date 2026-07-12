"""Testes herméticos de super_squad.role_eval — runner role-agnóstico. Zero rede.

Injeta run_squad/make_job/load_role fakes; usa tmp dir para o checkpoint real (IO de arquivo é ok,
rede não). Cobre: régua vinda do gold (`ruler` spec), fallback code-review, validação fail-closed,
agregação pass_rate/per_case, idempotência do checkpoint.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from super_squad import role_eval as re


def fake_load_role(path):
    return SimpleNamespace(name="p", system_prompt="SYS")


def fake_make_job(key, prompt, slug, pin, pout, **kw):
    return {"key": key, "prompt": prompt, "slug": slug}


def make_fake_run_squad(answer_for):
    """answer_for(case_id) -> texto da resposta. Ecoa como resultado ok."""
    def run(jobs, workers=6, budget_usd=0.0):
        results = []
        for j in jobs:
            cid = j["key"].split("::")[0]
            results.append(SimpleNamespace(
                key=j["key"], model=j["slug"], ok=True, cost_usd=0.0001, latency_ms=100,
                value={"text": answer_for(cid)}))
        return SimpleNamespace(results=results, total_cost_usd=0.001 * len(jobs), budget_hit=False)
    return run


GOLD_GENERIC = {
    "instruction": "Judge.",
    "n_per_case": 2,
    "cases": [
        {"id": "c-hit", "input": "x", "ruler": "contains_any:approved,ok"},
        {"id": "c-miss", "input": "y", "ruler": "contains_any:approved,ok"},
    ],
}
POOL = [("vendor/model-a", 0.1, 0.2)]
COMMON = dict(load_role_fn=fake_load_role, make_job_fn=fake_make_job)


class TestRoleEval(unittest.TestCase):
    def test_ruler_from_gold_scores(self):
        # c-hit responde "approved" (passa), c-miss responde "rejected" (falha)
        run = make_fake_run_squad(lambda cid: "approved" if cid == "c-hit" else "rejected")
        with TemporaryDirectory() as d:
            out = str(Path(d) / "o.json")
            s = re.run_role_eval(self._write(d, GOLD_GENERIC), None, POOL, out_path=out,
                                 api_key="k", run_squad_fn=run, **COMMON)
            slug = "vendor/model-a"
            self.assertEqual(s["by_slug"][slug]["per_case"]["c-hit"], 1.0)
            self.assertEqual(s["by_slug"][slug]["per_case"]["c-miss"], 0.0)
            self.assertAlmostEqual(s["by_slug"][slug]["pass_rate"], 0.5)

    def test_code_review_convention_fallback(self):
        gold = {"instruction": "Review.", "n_per_case": 1, "cases": [
            {"id": "b1", "kind": "buggy", "diff": "x", "language": "py", "detect_any": ["sqli"]},
            {"id": "cl1", "kind": "clean", "diff": "y", "language": "py", "forbid_any": ["sqli"]},
        ]}
        run = make_fake_run_squad(lambda cid: "found sqli\nTOP_BUG: NONE" if cid == "b1"
                                  else "looks fine\nTOP_BUG: NONE")
        with TemporaryDirectory() as d:
            out = str(Path(d) / "o.json")
            s = re.run_role_eval(self._write(d, gold), None, POOL, out_path=out, api_key="k",
                                 run_squad_fn=run, **COMMON)
            slug = "vendor/model-a"
            self.assertEqual(s["by_slug"][slug]["per_case"]["b1"], 1.0)   # detectou sqli
            self.assertEqual(s["by_slug"][slug]["per_case"]["cl1"], 1.0)  # TOP_BUG NONE = limpo

    def test_fail_closed_without_ruler(self):
        gold = {"instruction": "x", "n_per_case": 1, "cases": [{"id": "nope", "input": "z"}]}
        run = make_fake_run_squad(lambda cid: "whatever")
        with TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                re.run_role_eval(self._write(d, gold), None, POOL,
                                 out_path=str(Path(d) / "o.json"), api_key="k",
                                 run_squad_fn=run, **COMMON)

    def test_checkpoint_idempotent(self):
        run = make_fake_run_squad(lambda cid: "approved")
        with TemporaryDirectory() as d:
            gp = self._write(d, GOLD_GENERIC)
            out = str(Path(d) / "o.json")
            re.run_role_eval(gp, None, POOL, out_path=out, api_key="k", run_squad_fn=run, **COMMON)
            n1 = sum(1 for _ in open(f"{out}.ckpt.jsonl", encoding="utf-8"))
            # 2ª rodada: tudo já no checkpoint -> nenhum job novo, mesmas linhas
            calls = {"n": 0}

            def run2(jobs, workers=6, budget_usd=0.0):
                calls["n"] = len(jobs)
                return SimpleNamespace(results=[], total_cost_usd=0.0, budget_hit=False)
            re.run_role_eval(gp, None, POOL, out_path=out, api_key="k", run_squad_fn=run2, **COMMON)
            n2 = sum(1 for _ in open(f"{out}.ckpt.jsonl", encoding="utf-8"))
            self.assertEqual(calls["n"], 0)   # nada re-rodado
            self.assertEqual(n1, n2)          # checkpoint não duplicou

    def test_empty_pool_raises(self):
        with TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                re.run_role_eval(self._write(d, GOLD_GENERIC), None, [],
                                 out_path=str(Path(d) / "o.json"), api_key="k",
                                 run_squad_fn=make_fake_run_squad(lambda c: "x"), **COMMON)

    def test_render_markdown(self):
        run = make_fake_run_squad(lambda cid: "approved")
        with TemporaryDirectory() as d:
            s = re.run_role_eval(self._write(d, GOLD_GENERIC), None, POOL,
                                 out_path=str(Path(d) / "o.json"), api_key="k",
                                 run_squad_fn=run, **COMMON)
            md = re.render_markdown(s)
            self.assertIn("Pass Rate", md)
            self.assertIn("vendor/model-a", md)

    @staticmethod
    def _write(d, gold):
        p = Path(d) / "gold.json"
        p.write_text(json.dumps(gold), encoding="utf-8")
        return str(p)


if __name__ == "__main__":
    unittest.main()
