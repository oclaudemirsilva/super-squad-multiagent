"""Testes herméticos de super_squad.gold_preflight — veta caso-limpo suspeito. Zero rede.

Injeta um `batch_run_fn` fake que devolve reviews canônicas por (case, model), então exercita
o gate sem tocar OpenRouter. Cobre: caso limpo de verdade passa; caso com bug real (consenso do
juiz sinaliza) vira suspeito e BLOQUEIA; motivos são reportados; inconclusivo (sem amostra) =
suspeito (fail-closed); limiar configurável.
"""
import unittest

from super_squad import gold_preflight as gp


# gold minimal: 1 caso limpo de verdade + 1 "limpo" que na real tem bug (symlink), + 1 buggy ignorado.
CASES = {
    "instruction": "Review. End with 'TOP_BUG: <...or NONE>'.",
    "n_per_case": 5,
    "cases": [
        {"id": "clean-real", "kind": "clean", "language": "python",
         "diff": "def f(x=None):\n    x = x or []\n    return x", "forbid_any": ["mutable default"]},
        {"id": "clean-fake", "kind": "clean", "language": "python",
         "diff": "def read(name):\n    return open(basename(name)).read()", "forbid_any": ["path traversal"]},
        {"id": "buggy-ignored", "kind": "buggy", "language": "python",
         "diff": "x == secret", "detect_any": ["timing"]},
    ],
}


# frase PROIBIDA por caso (o gate usa forbids_ruler: sinalizar = NOMEAR essa frase no TOP_BUG).
_FORBID = {c["id"]: (c["forbid_any"][0] if c.get("forbid_any") else "") for c in CASES["cases"]}


def make_fake_run(flag_map):
    """flag_map: {case_id: fração_de_reps_que_sinalizam}. Devolve batch_run_fn hermético.
    Ao sinalizar, emite a vuln PROIBIDA do caso no TOP_BUG (ex.: 'path traversal' via symlink)."""
    def fake(specs, **kw):
        out = {}
        for (key, system, prompt, model) in specs:
            case_id, _model, rep = key.split("::")
            frac = flag_map.get(case_id, 0.0)
            # sinaliza os primeiros round(frac*n) reps deste (case,model)
            flag = int(rep) < round(frac * CASES["n_per_case"])
            out[key] = (f"TOP_BUG: Real {_FORBID.get(case_id, 'bug')} via symlink escape here"
                        if flag else "Looks correct.\nTOP_BUG: NONE")
        return out
    return fake


class TestGoldPreflight(unittest.TestCase):
    def test_true_clean_case_passes(self):
        run = make_fake_run({"clean-real": 0.0, "clean-fake": 0.0})
        rep = gp.validate_clean_cases(CASES, "sys", ["judge-a"], n=5, batch_run_fn=run)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["suspects"], [])

    def test_hidden_bug_case_is_suspect(self):
        # clean-fake sinalizado 80% (consenso) -> suspeito; clean-real limpo.
        run = make_fake_run({"clean-real": 0.0, "clean-fake": 0.8})
        rep = gp.validate_clean_cases(CASES, "sys", ["judge-a"], n=5, batch_run_fn=run)
        self.assertFalse(rep["ok"])
        ids = [s["case_id"] for s in rep["suspects"]]
        self.assertIn("clean-fake", ids)
        self.assertNotIn("clean-real", ids)

    def test_suspect_reports_reasons(self):
        run = make_fake_run({"clean-fake": 1.0})
        rep = gp.validate_clean_cases(CASES, "sys", ["judge-a"], n=5, batch_run_fn=run)
        suspect = next(s for s in rep["suspects"] if s["case_id"] == "clean-fake")
        self.assertGreaterEqual(len(suspect["reasons"]), 1)
        self.assertIn("symlink", suspect["reasons"][0].lower())

    def test_assert_raises_on_suspect(self):
        run = make_fake_run({"clean-fake": 0.6})
        with self.assertRaises(gp.GoldPreflightError):
            gp.assert_clean_cases_valid(CASES, "sys", ["judge-a"], n=5, batch_run_fn=run)

    def test_assert_returns_report_on_clean(self):
        run = make_fake_run({})  # nada sinaliza
        rep = gp.assert_clean_cases_valid(CASES, "sys", ["judge-a"], n=5, batch_run_fn=run)
        self.assertTrue(rep["ok"])

    def test_threshold_is_configurable(self):
        # 40% sinalização: suspeito no default (0.40) mas OK com limiar 0.5.
        run = make_fake_run({"clean-fake": 0.4})
        strict = gp.validate_clean_cases(CASES, "sys", ["j"], n=5, batch_run_fn=run)
        self.assertFalse(strict["ok"])
        lax = gp.validate_clean_cases(CASES, "sys", ["j"], n=5, suspect_threshold=0.5, batch_run_fn=run)
        self.assertTrue(lax["ok"])

    def test_no_samples_is_fail_closed(self):
        # run_fn devolve vazio (todos os juízes morreram) -> n_samples=0 -> suspeito.
        rep = gp.validate_clean_cases(CASES, "sys", ["j"], n=5, batch_run_fn=lambda specs, **kw: {})
        self.assertFalse(rep["ok"])
        for s in rep["suspects"]:
            self.assertEqual(s["n_samples"], 0)

    def test_only_clean_cases_are_probed(self):
        # o caso buggy NÃO deve virar spec (só clean são vetados aqui).
        seen = {}

        def spy(specs, **kw):
            for (key, *_rest) in specs:
                seen[key.split("::")[0]] = True
            return {k[0]: "TOP_BUG: NONE" for k in specs}

        gp.clean_case_flag_rates(CASES, "sys", ["j"], n=2, batch_run_fn=spy)
        self.assertIn("clean-real", seen)
        self.assertIn("clean-fake", seen)
        self.assertNotIn("buggy-ignored", seen)


if __name__ == "__main__":
    unittest.main()
