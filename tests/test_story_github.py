import json, pathlib, shutil, tempfile, unittest
from turnstile_cli import pass_cmd, state
from tests.test_pass import FakeIO, opts, run_capture, H, H2

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"
B = "bbbbbbbb22222222"

class StoryPassesVerifyGitHub(unittest.TestCase):
    """Round 2 R2-7: a push without `pass pr` leaves state.json stale; every story gate asks GitHub for the head of every PR
    in deploy.heads and refuses when any differs."""
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch(); (self.d / "reports").mkdir()
        (self.d / "reports" / "ENV.md").write_text("ok"); (self.d / "reports" / "S.md").write_text("clean")
        self.io = FakeIO(heads={"jsfiller#1": H, "docs-platform#2": B})
        d = self.data()
        for pid in d["prs"]: d["prs"][pid]["state"] = "READY"
        d["prs"]["docs-platform#2"]["base"] = "feature/MYD-10"  # stacked on jsfiller#1: the top is docs-platform#2
        d["awaiting_human"] = [{"id": "ah-7", "owner": "lead", "type": "story_done", "story": "S1", "created_at": "x", "payload": None,
                                "approved_at": "2026-10-13T10:00Z", "approved_via": "lead-terminal"}]
        self.write(d)
    def data(self): return json.loads((self.d / "state.json").read_text())
    def write(self, d): (self.d / "state.json").write_text(state.dumps(d))
    def deploy(self): return self.data()["stories"]["S1"]["evidence"]["deploy"]
    def at(self, st, **ev):
        d = self.data(); d["stories"]["S1"]["state"] = st
        d["stories"]["S1"]["evidence"] = {"deploy": {"build": "1", "head": B, "heads": {"jsfiller#1": H, "docs-platform#2": B}},
                                          "integration_review": {"report": "r", "head": B, "clean": True}}
        d["stories"]["S1"]["evidence"].update(ev); self.write(d)
    def run_env(self, **kw):
        o = opts(report="reports/ENV.md", figma_parity="pass", cases_pass=1, cases_fail=0, full=True, build="1", head=B, **kw)
        return run_capture(self.d, "story", "S1", "ENV_TESTING", o, self.io)

    def test_deploy_record_refuses_a_state_head_github_no_longer_has(self):
        self.io.heads["jsfiller#1"] = H2
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="1", head=B), self.io)
        self.assertEqual(rc, 2); self.assertIn("jsfiller#1", out); self.assertIn(H2[:12], out); self.assertIn("AI_REVIEW --head", out)
        self.assertNotIn("deploy", json.dumps(self.data()["stories"]["S1"]["evidence"]))
        self.io.heads["jsfiller#1"] = H
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="1", head=B), self.io); self.assertEqual(rc, 0, out)
        dp = self.deploy(); self.assertEqual(dp["heads"], {"jsfiller#1": H, "docs-platform#2": B}); self.assertTrue(dp["head_verified"]["verified"])

    def test_env_testing_entry_and_run_refuse_a_drifted_head(self):
        self.at("INTEGRATION_REVIEW")
        self.io.heads["docs-platform#2"] = H2
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/S.md", head=B), self.io)
        self.assertEqual(rc, 2); self.assertIn("docs-platform#2", out); self.assertIn("GitHub", out)
        self.io.heads["docs-platform#2"] = B
        self.assertEqual(run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/S.md", head=B), self.io)[0], 0)
        self.io.heads["jsfiller#1"] = H2
        rc, out = self.run_env(); self.assertEqual(rc, 2); self.assertIn("jsfiller#1", out)
        self.assertNotIn("env_runs", json.dumps(self.data()))

    def test_offline_records_unverified_and_done_refuses_it(self):
        self.at("INTEGRATION_REVIEW")
        self.io.heads = {}  # gh unavailable
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/S.md", head=B), self.io)
        self.assertEqual(rc, 2); self.assertIn("unavailable", out); self.assertIn("--offline", out)
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/S.md", head=B, offline=True), self.io)
        self.assertEqual(rc, 0, out); self.assertIn("WARN --offline", out); self.assertEqual(self.deploy()["head_verified"], {"verified": False})
        rc, out = self.run_env(offline=True); self.assertEqual(rc, 0, out)
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7", offline=True), self.io)
        self.assertEqual(rc, 2); self.assertIn("--offline", out); self.assertEqual(self.data()["stories"]["S1"]["state"], "ENV_TESTING")
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)
        self.assertEqual(rc, 2); self.assertIn("unavailable", out)
        self.io.heads = {"jsfiller#1": H, "docs-platform#2": H2}
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)
        self.assertEqual(rc, 2); self.assertIn("docs-platform#2", out); self.assertIn(H2[:12], out)
        self.io.heads["docs-platform#2"] = B
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)
        self.assertEqual(rc, 0, out); self.assertTrue(self.deploy()["head_verified"]["verified"]); self.assertTrue(self.deploy()["head_verified"]["at"])

    def test_done_needs_a_heads_snapshot(self):
        # a deploy recorded before round 2 has no heads: DONE asks for a re-recorded deploy (migration step 6)
        self.at("ENV_TESTING"); d = self.data(); d["stories"]["S1"]["evidence"]["deploy"].pop("heads"); self.write(d)
        self.assertEqual(self.run_env()[0], 0)
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)
        self.assertEqual(rc, 2); self.assertIn("deploy.heads", out)

    def test_merged_prs_in_the_snapshot_are_still_verified(self):
        self.at("ENV_TESTING"); d = self.data(); d["prs"]["jsfiller#1"]["state"] = "MERGED"; self.write(d)
        self.io.heads["jsfiller#1"] = H2  # a merged PR cannot move, so a different head means the snapshot lies
        rc, out = self.run_env(); self.assertEqual(rc, 2); self.assertIn("jsfiller#1", out)

if __name__ == "__main__":
    unittest.main()
