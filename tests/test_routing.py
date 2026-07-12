"""Testes herméticos de super_squad.routing — seam RoutingProvider (scaffold). Zero rede."""
import unittest

from super_squad import routing as rt


def roster_fn(role):
    return {"code-reviewer": [("vendor/model-a", 0.1, 0.2)]}.get(role, [])


class FakeBooster:
    def __init__(self, avail, handles):
        self._a, self._h = avail, set(handles)

    def available(self):
        return self._a

    def can_handle(self, intent):
        return intent in self._h


class TestRouting(unittest.TestCase):
    def test_trivial_intent_with_booster_goes_free(self):
        p = rt.MeasuredRoutingProvider(roster_fn=roster_fn,
                                       booster=FakeBooster(True, ["remove-console"]))
        r = p.route(rt.Task(role="code-reviewer", intent="remove-console"))
        self.assertEqual(r.tier, "booster")
        self.assertEqual(r.est_cost_usd, 0.0)
        self.assertEqual(r.handler, "remove-console")

    def test_trivial_intent_without_booster_falls_to_model(self):
        p = rt.MeasuredRoutingProvider(roster_fn=roster_fn, booster=rt.NullBoosterAdapter())
        r = p.route(rt.Task(role="code-reviewer", intent="remove-console"))
        self.assertEqual(r.tier, "model")
        self.assertEqual(r.handler, "vendor/model-a")

    def test_nontrivial_intent_goes_to_measured_titular(self):
        p = rt.MeasuredRoutingProvider(roster_fn=roster_fn,
                                       booster=FakeBooster(True, ["remove-console"]))
        r = p.route(rt.Task(role="code-reviewer", intent="deep-refactor"))
        self.assertEqual(r.tier, "model")
        self.assertEqual(r.handler, "vendor/model-a")

    def test_no_intent_goes_to_model(self):
        p = rt.MeasuredRoutingProvider(roster_fn=roster_fn, booster=rt.NullBoosterAdapter())
        r = p.route(rt.Task(role="code-reviewer"))
        self.assertEqual(r.tier, "model")
        self.assertEqual(r.handler, "vendor/model-a")

    def test_empty_roster_returns_explicit_error_route(self):
        p = rt.MeasuredRoutingProvider(roster_fn=roster_fn, booster=rt.NullBoosterAdapter())
        r = p.route(rt.Task(role="ghost-role"))
        self.assertEqual(r.handler, "")
        self.assertIn("VAZIO", r.rationale)

    def test_default_booster_is_null(self):
        # sem injetar booster → NullBoosterAdapter → tudo cai pro modelo (fallback gracioso)
        p = rt.MeasuredRoutingProvider(roster_fn=roster_fn)
        r = p.route(rt.Task(role="code-reviewer", intent="add-types"))
        self.assertEqual(r.tier, "model")

    def test_rationale_is_present(self):
        p = rt.MeasuredRoutingProvider(roster_fn=roster_fn, booster=rt.NullBoosterAdapter())
        self.assertTrue(p.route(rt.Task(role="code-reviewer")).rationale)


if __name__ == "__main__":
    unittest.main()
