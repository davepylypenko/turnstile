import json, pathlib, shutil, tempfile, unittest
from turnstile_cli import pass_cmd, rules, bug_cmd, state
from tests.test_pass import FakeIO, opts, run_capture, env, H

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class EnvRuns(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch(); (self.d / "reports").mkdir()
        (self.d / "reports" / "ENV.md").write_text("ok"); self.io = FakeIO()
        data = json.loads((self.d / "state.json").read_text())
        for pid in data["prs"]: data["prs"][pid]["state"] = "MERGED"
        data["stories"]["S1"]["state"] = "ENV_TESTING"
        data["stories"]["S1"]["evidence"] = {"deploy": {"build": "1", "head": H}, "integration_review": {"report": "r", "head": H, "clean": True}}
        data["awaiting_human"] = [{"id": "ah-7", "owner": "lead", "type": "story_done", "story": "S1", "created_at": "x", "payload": None,
                                   "approved_at": "2026-10-13T10:00Z", "approved_via": "lead-terminal"}]
        (self.d / "state.json").write_text(state.dumps(data))
    def data(self): return json.loads((self.d / "state.json").read_text())
    def run_env(self, fail, full=False, **kw):
        return run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/ENV.md", figma_parity="pass", cases_pass=5 - fail, cases_fail=fail, full=full, **kw), self.io)

    def test_reentry_needs_a_run_and_keeps_story_done(self):
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", opts(), self.io)
        self.assertEqual(rc, 2); self.assertIn("record a test run", out)
        rc, out = self.run_env(0, full=True); self.assertEqual(rc, 0, out)
        d = self.data(); self.assertEqual(len(d["stories"]["S1"]["evidence"]["env_runs"]), 1); self.assertTrue(d["stories"]["S1"]["evidence"]["env_runs"][0]["full"])
        self.assertFalse(d["awaiting_human"][0].get("voided_at"))
        self.assertEqual(d["stories"]["S1"]["evidence"]["env_test"]["cases"], {"pass": 5, "fail": 0})

    def test_failed_run_needs_bugs(self):
        rc, out = self.run_env(2, full=True)
        self.assertEqual(rc, 2); self.assertIn("every failed case became a bug: 2 fail(s)", out); self.assertNotIn("env_runs", json.dumps(self.data()))
        bug_cmd.add(self.d, "S1", "a", "tester", io=self.io)
        self.assertEqual(self.run_env(2, full=True)[0], 2)
        bug_cmd.add(self.d, "S1", "b", "tester", io=self.io)
        self.assertEqual(self.run_env(2, full=True)[0], 0)
        # the next failing run counts only bugs created after this run
        rc, out = self.run_env(1); self.assertEqual(rc, 2); self.assertIn("1 fail(s)", out)
        bug_cmd.add(self.d, "S1", "c", "tester", io=self.io)
        self.assertEqual(self.run_env(1)[0], 0)
        self.assertEqual(len(self.data()["stories"]["S1"]["evidence"]["env_runs"]), 2)

    def test_done_needs_full_run(self):
        self.assertEqual(self.run_env(0, full=False)[0], 0)
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)
        self.assertEqual(rc, 2); self.assertIn("full", out)
        self.assertEqual(self.run_env(0, full=True)[0], 0)
        self.assertEqual(run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)[0], 0)

    def test_done_with_flags_records_a_full_run(self):
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(report="reports/ENV.md", figma_parity="pass", cases_pass=3, cases_fail=0, full=True, approved="ah-7"), self.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.data()["stories"]["S1"]["evidence"]["env_runs"][-1]["full"], True)

    def test_rule_reads_env_test_when_no_runs(self):
        s = {"_id": "S1", "state": "ENV_TESTING", "evidence": {"env_test": {"report": "r", "cases": {"pass": 1, "fail": 0}, "figma_parity": "pass", "full": True}}}
        self.assertEqual(rules.last_env_run(s)["full"], True)
