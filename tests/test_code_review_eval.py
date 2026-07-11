"""Testes herméticos do runner de medição code-reviewer + rulers de recall/over-flag.

Zero rede: o job-builder é trocado por um fake que devolve texto canônico, mas o `run_squad`
REAL executa os thunks (é puro). Valida agregação (detection_rate/over_flag_rate), o checkpoint
idempotente (resume não re-paga) e os dois rulers novos.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from super_squad import code_review_eval as cre
from super_squad.rulers import contains_any_ruler, contains_none_ruler, top_bug_clean_ruler
from super_squad.squad import Job

PERSONA = Path(__file__).resolve().parents[1] / "roles" / "vendor" / "code-reviewer.md"

CASES = {
    "role": "code-reviewer",
    "instruction": "Review this code.",
    "n_per_case": 3,
    "cases": [
        {"id": "buggy1", "kind": "buggy", "language": "python", "diff": "q = f\"...{x}...\"",
         "detect_any": ["sql injection", "parameterize"]},
        {"id": "clean1", "kind": "clean", "language": "python", "diff": "def f(): return 1",
         "forbid_any": ["sql injection", "command injection"]},
    ],
}


def _fake_job_factory(text_for):
    """Devolve um make_job fake: cada Job.run() entrega o texto que `text_for(slug, case_id)` der,
    com custo fixo — determinístico, sem rede."""
    def make_job(key, prompt, model, pin, pout, *, system=None, temperature=0.2,
                 timeout=120, api_key=None, max_tokens=None):
        case_id = key.split("::")[0]
        text = text_for(model, case_id)
        return Job(key=key, run=lambda: ({"model": model, "text": text}, 0.002), model=model)
    return make_job


class TestRulers(unittest.TestCase):
    def test_contains_any_hit_and_miss(self):
        r = contains_any_ruler(["sql injection", "parameterize"])
        self.assertTrue(r("This is a SQL Injection risk")["pass"])
        self.assertEqual(r("This is a SQL Injection risk")["label"], "HIT")
        self.assertFalse(r("looks fine to me")["pass"])

    def test_contains_none_clean_and_flagged(self):
        r = contains_none_ruler(["sql injection", "rce"])
        self.assertTrue(r("a pure stats helper")["pass"])
        self.assertEqual(r("a pure stats helper")["label"], "CLEAN")
        self.assertFalse(r("possible SQL injection here")["pass"])

    def test_accent_insensitive(self):
        # "injeção" normaliza p/ "injecao" — casa "injecao"
        r = contains_any_ruler(["injecao"])
        self.assertTrue(r("risco de injeção")["pass"])

    def test_top_bug_forbids_distinguishes_hallucination_from_thoroughness(self):
        from super_squad.rulers import top_bug_forbids_ruler
        r = top_bug_forbids_ruler(["timing attack", "non-constant"])
        # alucina a vuln FALSA específica -> over-flag
        self.assertFalse(r("TOP_BUG: vulnerable to a timing attack via string compare")["pass"])
        # levanta preocupação DIFERENTE e defensável -> NÃO é over-flag (minúcia, não alucinação)
        self.assertTrue(r("TOP_BUG: consider adding input validation on sig")["pass"])
        # diz que é seguro -> clean
        self.assertTrue(r("TOP_BUG: NONE")["pass"])

    def test_top_bug_clean_ruler(self):
        r = top_bug_clean_ruler()
        # a review CORRETA que NOMEIA o pitfall evitado NAO pode contar como over-flag (o bug antigo)
        praise = ("This correctly avoids the mutable default argument pitfall.\n"
                  "TOP_BUG: NONE, the code is correct.")
        self.assertTrue(r(praise)["pass"])
        # falso-positivo real: o veredito TOP_BUG acusa um bug em codigo limpo
        fp = "TOP_BUG: The function uses a mutable default argument that is shared."
        self.assertFalse(r(fp)["pass"])
        # sem linha TOP_BUG -> fail-closed
        self.assertFalse(r("some rambling with no verdict")["pass"])


class TestRunnerAggregation(unittest.TestCase):
    def _run(self, tmp, text_for, **kw):
        cases_path = Path(tmp) / "cases.json"
        cases_path.write_text(json.dumps(CASES, ensure_ascii=False), encoding="utf-8")
        out_path = Path(tmp) / "out.json"
        pool = [("prov/good", 0.2, 0.8), ("prov/bad", 0.2, 0.8)]
        with mock.patch.object(cre, "make_openrouter_text_job", _fake_job_factory(text_for)):
            return cre.run_code_review_eval(
                str(cases_path), str(PERSONA), pool, out_path=str(out_path),
                budget_usd=1.0, workers=2, **kw), out_path

    def test_detection_and_overflag_rates(self):
        # good: pega o bug (cita sql injection) e NÃO over-flag no limpo.
        # bad: MISS no bug (texto vazio de achado) e over-flag no limpo (grita sql injection).
        def text_for(slug, case_id):
            if slug == "prov/good":
                return ("Critical: SQL injection via f-string." if case_id == "buggy1"
                        else "Looks clean.\nTOP_BUG: NONE")
            return ("Nothing found." if case_id == "buggy1"
                    else "TOP_BUG: SQL injection everywhere!")
        with TemporaryDirectory() as tmp:
            summary, out_path = self._run(tmp, text_for)
            good = summary["by_slug"]["prov/good"]
            bad = summary["by_slug"]["prov/bad"]
            self.assertEqual(good["detection_rate"], 1.0)
            self.assertEqual(good["over_flag_rate"], 0.0)
            self.assertEqual(bad["detection_rate"], 0.0)
            self.assertEqual(bad["over_flag_rate"], 1.0)
            self.assertEqual(good["n_calls"], 6)  # 2 casos * 3 reps
            self.assertTrue(out_path.exists())

    def test_checkpoint_is_idempotent(self):
        calls = {"n": 0}
        def text_for(slug, case_id):
            calls["n"] += 1
            return "SQL injection found." if case_id == "buggy1" else "clean"
        with TemporaryDirectory() as tmp:
            summary1, out_path = self._run(tmp, text_for)
            after_first = calls["n"]
            # 2ª rodada idêntica: tudo já no checkpoint -> ZERO novas chamadas ao job factory.
            cases_path = Path(tmp) / "cases.json"
            pool = [("prov/good", 0.2, 0.8), ("prov/bad", 0.2, 0.8)]
            with mock.patch.object(cre, "make_openrouter_text_job", _fake_job_factory(text_for)):
                summary2 = cre.run_code_review_eval(
                    str(cases_path), str(PERSONA), pool, out_path=str(out_path),
                    budget_usd=1.0, workers=2)
            self.assertEqual(calls["n"], after_first, "resume não pode re-chamar jobs já feitos")
            self.assertEqual(summary2["by_slug"]["prov/good"]["n_calls"],
                             summary1["by_slug"]["prov/good"]["n_calls"])

    def test_empty_pool_raises(self):
        with TemporaryDirectory() as tmp:
            cases_path = Path(tmp) / "cases.json"
            cases_path.write_text(json.dumps(CASES), encoding="utf-8")
            with self.assertRaises(ValueError):
                cre.run_code_review_eval(str(cases_path), str(PERSONA), [],
                                         out_path=str(Path(tmp) / "o.json"))


if __name__ == "__main__":
    unittest.main()
