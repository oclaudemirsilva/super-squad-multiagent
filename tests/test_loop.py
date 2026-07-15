"""Testes herméticos do orquestrador de loop (`super_squad.loop`). Zero rede/WSL: injetamos
`write_fn`/`debug_fn` fakes e um `run_fn` fake `isolation_capable` que decide pass/fail lendo os
arquivos aplicados. Exercita o applier REAL + a régua REAL + as 4 paradas."""
from __future__ import annotations

import unittest

from super_squad.execution_ruler import RunResult
from super_squad.loop import (
    LoopTask, orchestrate, compose_writer_input, task_from_gold,
)


# ── fakes ────────────────────────────────────────────────────────────────────────

def _fake_run_fn_factory(pass_if_contains: bytes, target: str):
    """run_fn fake, isolation_capable: rc=0 (teste passa) sse o arquivo `target` no workspace contém
    `pass_if_contains`; senão rc=1. Simula 'rodar o teste' sem subprocess — lê o disco do workspace."""
    import os

    def run_fn(argv, cwd, timeout_s, env):
        try:
            data = open(os.path.join(cwd, target), "rb").read()
        except OSError:
            return RunResult(returncode=1, stderr="target ausente")
        ok = pass_if_contains in data
        # stderr inclui o conteúdo aplicado → falhas de patches distintos têm assinatura distinta (realista)
        return RunResult(returncode=0 if ok else 1,
                         stdout="ok" if ok else "",
                         stderr="" if ok else f"assert falhou; arquivo:\n{data.decode('utf-8','replace')}")
    run_fn.isolation_capable = True
    return run_fn


def _writer(*texts):
    """write_fn fake: devolve os candidatos `texts` (na ordem = titular primeiro), custo fixo por chamada.
    Se chamado mais vezes que len(texts), repete o último (simula modelo travado)."""
    calls = {"n": 0}

    def write_fn(task_input):
        i = min(calls["n"], len(texts) - 1)
        calls["n"] += 1
        t = texts[i]
        results = [{"model": "fake-writer", "ok": bool(t), "text": t, "cost_usd": 0.01}]
        return {"results": results, "spent_usd": 0.01}
    write_fn.calls = calls
    return write_fn


def _writer_panel(rounds):
    """write_fn fake multi-candidato: `rounds` = lista por-iteração de listas de textos (candidatos)."""
    calls = {"n": 0}

    def write_fn(task_input):
        i = min(calls["n"], len(rounds) - 1)
        calls["n"] += 1
        cands = rounds[i]
        results = [{"model": f"m{j}", "ok": bool(t), "text": t, "cost_usd": 0.005} for j, t in enumerate(cands)]
        return {"results": results, "spent_usd": 0.005 * len(cands)}
    return write_fn


DIFF_PASS = "--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 2\n"
DIFF_WRONG = "--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 9\n"
DIFF_WRONG8 = "--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 8\n"
DIFF_WRONG7 = "--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 7\n"
DIFF_NOAPPLY = "--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-NOTHERE\n+return 2\n"


def _task():
    return LoopTask(
        spec="f() deve retornar 2",
        base_files={"m.py": b"def f():\n    return 1\n"},
        test_cmd=["pytest", "-q"],
        test_files={"test_m.py": b"from m import f\n\ndef test_f():\n    assert f() == 2\n"},
        patch_target="m.py",
        timeout_s=5,
    )


class TestLoop(unittest.TestCase):
    def setUp(self):
        # o teste "passa" (nosso run_fn fake) sse m.py contém 'return 2'
        self.run_fn = _fake_run_fn_factory(b"return 2", "m.py")

    def test_solves_first_iter(self):
        r = orchestrate(_task(), budget_usd=1.0, write_fn=_writer(DIFF_PASS), run_fn=self.run_fn)
        self.assertTrue(r.ok)
        self.assertEqual(r.reason, "solved")
        self.assertEqual(r.iters, 1)
        self.assertEqual(r.patch, DIFF_PASS)
        self.assertAlmostEqual(r.spent_usd, 0.01, places=6)

    def test_solves_second_iter_after_wrong_first(self):
        # 1ª tentativa aplica mas falha o teste; 2ª passa. Fecha em 2 iters.
        r = orchestrate(_task(), budget_usd=1.0, write_fn=_writer(DIFF_WRONG, DIFF_PASS), run_fn=self.run_fn)
        self.assertTrue(r.ok)
        self.assertEqual(r.iters, 2)
        self.assertEqual(r.history[0].label, "test_fail")
        self.assertFalse(r.history[0].passed)

    def test_debugger_feedback_flows_into_next_writer_input(self):
        seen = {}

        def dbg(task_input):
            return {"text": "DICA: retorne 2, não 9", "spent_usd": 0.002}

        # captura o input do writer na 2ª chamada p/ conferir que o diagnóstico entrou
        base_writer = _writer(DIFF_WRONG, DIFF_PASS)
        inputs = []

        def spy_writer(task_input):
            inputs.append(task_input)
            return base_writer(task_input)

        r = orchestrate(_task(), budget_usd=1.0, write_fn=spy_writer, debug_fn=dbg, run_fn=self.run_fn)
        self.assertTrue(r.ok)
        self.assertIn("DICA: retorne 2", inputs[1])          # diagnóstico realimentado
        self.assertIn("PREVIOUS ATTEMPT FAILED", inputs[1])
        self.assertGreater(r.history[0].cost_usd, 0)

    def test_stops_on_budget_before_paying(self):
        # teto é checado ANTES de cada chamada paga: iter1 roda (spent=0 no topo, gasta 0.01); no topo da
        # iter2 spent(0.01) >= budget(0.008) ⇒ barra ANTES de gastar de novo (precedência sobre 'stuck').
        r = orchestrate(_task(), budget_usd=0.008, write_fn=_writer(DIFF_WRONG, DIFF_WRONG, DIFF_WRONG),
                        run_fn=self.run_fn, max_iters=5)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "budget")
        self.assertEqual(r.iters, 1)
        self.assertLessEqual(r.spent_usd, 0.011)            # não estourou o orçamento além de 1 tiro

    def test_stops_on_max_iters(self):
        # falhas DISTINTAS (9,8) → não dispara 'stuck'; esgota as 2 iterações.
        r = orchestrate(_task(), budget_usd=10.0, max_iters=2,
                        write_fn=_writer(DIFF_WRONG, DIFF_WRONG8), run_fn=self.run_fn)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "max_iters")
        self.assertEqual(r.iters, 2)
        self.assertEqual(r.patch, DIFF_WRONG8)              # melhor (última) tentativa que ao menos aplicou

    def test_stuck_on_repeated_apply_failure(self):
        # nenhum candidato aplica, 2× seguidas com a mesma assinatura ⇒ 'stuck'
        r = orchestrate(_task(), budget_usd=10.0, max_iters=5,
                        write_fn=_writer(DIFF_NOAPPLY, DIFF_NOAPPLY), run_fn=self.run_fn)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "stuck")
        self.assertEqual(r.history[0].label, "apply_failed")

    def test_no_writer_output(self):
        r = orchestrate(_task(), budget_usd=10.0, max_iters=2, write_fn=_writer("", ""), run_fn=self.run_fn)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "stuck")                 # mesmo 'no_writer_output' 2× ⇒ travou
        self.assertEqual(r.history[0].label, "no_writer_output")

    def test_panel_picks_first_that_applies(self):
        # candidato 0 não aplica; candidato 1 aplica e passa → escolhe o 1
        r = orchestrate(_task(), budget_usd=1.0, run_fn=self.run_fn,
                        write_fn=_writer_panel([[DIFF_NOAPPLY, DIFF_PASS]]))
        self.assertTrue(r.ok)
        self.assertEqual(r.history[0].model, "m1")

    def test_tolerant_apply_end_to_end(self):
        # diff com trailing whitespace no contexto — o applier tolerante deve colar e o teste passar
        diff = "--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,2 @@\n def f():   \n-    return 1\n+    return 2\n"
        r = orchestrate(_task(), budget_usd=1.0, write_fn=_writer(diff), run_fn=self.run_fn)
        self.assertTrue(r.ok)

    def test_budget_must_be_positive(self):
        with self.assertRaises(ValueError):
            orchestrate(_task(), budget_usd=0, write_fn=_writer(DIFF_PASS), run_fn=self.run_fn)

    def test_isolation_required_without_capable_run_fn(self):
        # run_fn NÃO isolation_capable → a régua recusa executar (fail-closed) → nunca dá 'solved'
        def bare_run_fn(argv, cwd, timeout_s, env):
            return RunResult(returncode=0)
        r = orchestrate(_task(), budget_usd=1.0, max_iters=1, write_fn=_writer(DIFF_PASS), run_fn=bare_run_fn)
        self.assertFalse(r.ok)
        self.assertEqual(r.history[0].label, "isolation_required")


class TestComposeAndGold(unittest.TestCase):
    def test_writer_input_has_spec_and_target_only(self):
        task = LoopTask(spec="S", base_files={"a.py": b"x", "b.py": b"y"}, test_cmd=["pytest"],
                        test_files={"t.py": b"T"}, patch_target="a.py")
        s = compose_writer_input(task, [])
        self.assertIn("## a.py", s)
        self.assertNotIn("## b.py", s)                       # só o alvo, não a árvore toda
        self.assertIn("S", s)

    def test_task_from_gold(self):
        import base64
        gold = {"spec": "S", "test_cmd": ["pytest", "-q"],
                "buggy_files": {"m.py": base64.b64encode(b"buggy").decode()},
                "test_files": {"t.py": base64.b64encode(b"test").decode()}}
        task = task_from_gold(gold, {"pkg/__init__.py": b""})
        self.assertEqual(task.patch_target, "m.py")           # 1 buggy file → habilita whole-file
        self.assertIn("pkg/__init__.py", task.base_files)     # árvore-do-pai entra na base
        self.assertEqual(task.base_files["m.py"], b"buggy")


if __name__ == "__main__":
    unittest.main()
