"""Testes herméticos do git_harvester — colhe golds do histórico. Zero git real (run_git injetado)."""
import unittest

from super_squad.git_harvester import harvest_with_report, GitResult, _is_fix_message


FS = "\x00"
RS = "\x1e"


def rec(sha, parents, subject, body="", author="dev", atime="2026-01-01T00:00:00"):
    return FS.join([sha, parents, author, atime, subject, body]) + RS


def make_git(log_records, *, name_status=None, tdiffs=None, shows=None):
    name_status = name_status or {}
    tdiffs = tdiffs or {}
    shows = shows or {}

    def run(args):
        if args[0] == "log":
            return GitResult(0, "".join(log_records), "")
        if args[0] == "diff" and "--name-status" in args:
            return GitResult(0, name_status.get((args[-2], args[-1]), ""), "")
        if args[0] == "diff":                      # diff parent sha -- path
            return GitResult(0, tdiffs.get((args[1], args[2], args[-1]), ""), "")
        if args[0] == "show":
            ref = args[1]
            return GitResult(0 if ref in shows else 1, shows.get(ref, ""), "")
        return GitResult(1, "", "")
    return run


HAPPY = make_git(
    [rec("a" * 40, "p" * 40, "fix: divide by zero", "closes #7")],
    name_status={("p" * 40, "a" * 40): "M\tm.py\nA\ttests/test_m.py"},
    tdiffs={("p" * 40, "a" * 40, "tests/test_m.py"): "@@ -0,0 +1 @@\n+def test_zero():\n+    assert True\n"},
    shows={f"{'p'*40}:m.py": "def f():\n    return 1/0\n",
           f"{'a'*40}:tests/test_m.py": "def test_zero():\n    assert True\n"},
)


class TestGitHarvester(unittest.TestCase):
    def test_happy_path(self):
        cases, diags = harvest_with_report(HAPPY, repo_name="proj")
        self.assertEqual(len(cases), 1)
        c = cases[0]
        self.assertEqual(c["case_id"], "proj@aaaaaaaaaa")
        self.assertEqual(c["ruler"], "execution")
        self.assertEqual(c["buggy_files"], {"m.py": b"def f():\n    return 1/0\n"})
        self.assertIn("tests/test_m.py", c["test_files"])
        self.assertEqual(c["test_cmd"], ["python", "-m", "pytest", "-q", "tests/test_m.py::test_zero"])
        self.assertEqual(c["issue_ref"], "#7")
        self.assertEqual(sorted(c["provenance"]["detected_by"]), ["keyword", "structural"])
        self.assertEqual(c["origin"], "human_commit")
        self.assertEqual(c["gold_origin"], "git-history")

    def test_reference_patch_not_fed_to_model(self):
        c = harvest_with_report(HAPPY)[0][0]
        # o fix humano é só metadado (ref), NUNCA nos campos que o modelo vê
        self.assertNotIn("reference_patch", c)      # sem o diff em si
        self.assertIn("reference_patch_ref", c)     # só o ponteiro parent..sha
        self.assertNotIn("1/0", str(c["test_files"]))  # o oráculo é o teste, não o fix

    def test_keyword_denylist(self):
        self.assertFalse(_is_fix_message("add fixture for parser", ""))
        self.assertFalse(_is_fix_message("update prefix handling", ""))
        self.assertTrue(_is_fix_message("fix: null deref", ""))
        self.assertFalse(_is_fix_message("Revert \"fix: x\"", ""))

    def test_merge_and_root_skipped(self):
        git = make_git([rec("m" * 40, f"{'p'*40} {'q'*40}", "fix: merge"),
                        rec("r" * 40, "", "fix: root")])
        cases, diags = harvest_with_report(git)
        self.assertEqual(cases, [])
        reasons = {d["reason"] for d in diags}
        self.assertIn("merge", reasons)
        self.assertIn("root", reasons)

    def test_keyword_only_no_test_dropped(self):
        git = make_git([rec("a" * 40, "p" * 40, "fix: bug")],
                       name_status={("p" * 40, "a" * 40): "M\tm.py"})  # sem teste tocado
        cases, diags = harvest_with_report(git)
        self.assertEqual(cases, [])
        self.assertIn("no_oracle", {d["reason"] for d in diags})

    def test_no_runner_for_unknown_ext(self):
        git = make_git([rec("a" * 40, "p" * 40, "fix: bug")],
                       name_status={("p" * 40, "a" * 40): "M\tm.rb\nA\tspec/m_spec.rb"},
                       shows={f"{'p'*40}:m.rb": "code"})
        # .rb não está no runner_map e sem default_test_cmd → skip no_runner
        cases, diags = harvest_with_report(git)
        self.assertEqual(cases, [])
        self.assertIn("no_runner", {d["reason"] for d in diags})

    def test_default_test_cmd_override(self):
        git = make_git([rec("a" * 40, "p" * 40, "fix: bug")],
                       name_status={("p" * 40, "a" * 40): "M\tm.rb\nA\tspec/m_spec.rb"},
                       tdiffs={("p" * 40, "a" * 40, "spec/m_spec.rb"): "+it('works')\n"},
                       shows={f"{'p'*40}:m.rb": "code", f"{'a'*40}:spec/m_spec.rb": "spec"})
        cases, _ = harvest_with_report(git, default_test_cmd=["rspec", "spec/m_spec.rb"])
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["test_cmd"], ["rspec", "spec/m_spec.rb"])

    def test_never_raises_on_git_failure(self):
        # rev-list falha → lista vazia + diagnóstico, sem crash
        def failing(args):
            return GitResult(128, "", "fatal: not a git repository")
        cases, diags = harvest_with_report(failing)
        self.assertEqual(cases, [])
        self.assertIn("rev_list_failed", diags[0]["reason"])

    def test_nul_delimited_message_with_newlines(self):
        # corpo com quebras de linha e pipes não corrompe o parse (-z-style FS/RS)
        git = make_git(
            [rec("a" * 40, "p" * 40, "fix: x", "line1\nline2 | piped\nline3")],
            name_status={("p" * 40, "a" * 40): "M\tm.py\nA\ttest_m.py"},
            tdiffs={("p" * 40, "a" * 40, "test_m.py"): "+def test_x():\n"},
            shows={f"{'p'*40}:m.py": "code", f"{'a'*40}:test_m.py": "t"})
        cases, _ = harvest_with_report(git)
        self.assertEqual(len(cases), 1)
        self.assertIn("line2 | piped", cases[0]["spec"])

    def test_determinism_ordered_by_time(self):
        git = make_git([
            rec("b" * 40, "p" * 40, "fix: later", author="d", atime="2026-02-01T00:00:00"),
            rec("a" * 40, "q" * 40, "fix: earlier", author="d", atime="2026-01-01T00:00:00"),
        ], name_status={("p" * 40, "b" * 40): "M\tx.py\nA\ttest_x.py",
                        ("q" * 40, "a" * 40): "M\ty.py\nA\ttest_y.py"},
           tdiffs={("p" * 40, "b" * 40, "test_x.py"): "+def test_x():\n",
                   ("q" * 40, "a" * 40, "test_y.py"): "+def test_y():\n"},
           shows={f"{'p'*40}:x.py": "x", f"{'b'*40}:test_x.py": "tx",
                  f"{'q'*40}:y.py": "y", f"{'a'*40}:test_y.py": "ty"})
        cases, _ = harvest_with_report(git)
        self.assertEqual([c["provenance"]["author_time"] for c in cases],
                         ["2026-01-01T00:00:00", "2026-02-01T00:00:00"])


if __name__ == "__main__":
    unittest.main()
