import json, pathlib, shutil, tempfile, unittest
from turnstile_cli import pass_cmd, rules, bug_cmd, state
from tests.test_pass import FakeIO, opts, run_capture, env, H, H2

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class EnvRuns(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch(); (self.d / "reports").mkdir()
        (self.d / "reports" / "ENV.md").write_text("ok"); (self.d / "reports" / "S.md").write_text("clean"); self.io = FakeIO()
        data = json.loads((self.d / "state.json").read_text())
        for pid in data["prs"]: data["prs"][pid]["state"] = "MERGED"
        data["stories"]["S1"]["state"] = "ENV_TESTING"; data["stories"]["S1"]["test_cases"] = ["TP-1", "TP-2", "TP-3", "TP-4", "TP-5"]
        data["stories"]["S1"]["evidence"] = {"deploy": {"build": "1", "head": H, "heads": {}}, "integration_review": {"report": "r", "head": H, "clean": True}}
        data["awaiting_human"] = [{"id": "ah-7", "owner": "lead", "type": "story_done", "story": "S1", "created_at": "x", "payload": None,
                                   "approved_at": "2026-10-13T10:00Z", "approved_via": "lead-terminal"}]
        (self.d / "state.json").write_text(state.dumps(data))
    def data(self): return json.loads((self.d / "state.json").read_text())
    def write(self, d): (self.d / "state.json").write_text(state.dumps(d))
    def bugs(self): return {b["id"]: b for b in self.data()["bugs"]}
    def run_env(self, failed=(), full=False, build="1", head=H, **kw):
        failed = list(failed)
        kw.setdefault("failed_cases", ",".join(failed) or None)
        o = opts(report="reports/ENV.md", figma_parity="pass", cases_pass=5 - len(failed), cases_fail=len(failed), full=full, build=build, head=head, **kw)
        return run_capture(self.d, "story", "S1", "ENV_TESTING", o, self.io)

    def test_reentry_needs_a_run_and_keeps_story_done(self):
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", opts(), self.io)
        self.assertEqual(rc, 2); self.assertIn("record a test run", out)
        rc, out = self.run_env(full=True); self.assertEqual(rc, 0, out)
        d = self.data(); run = d["stories"]["S1"]["evidence"]["env_runs"][0]
        self.assertEqual((run["full"], run["build"], run["head"], run["failed_cases"]), (True, "1", H, []))
        self.assertFalse(d["awaiting_human"][0].get("voided_at"))
        self.assertEqual(d["stories"]["S1"]["evidence"]["env_test"]["cases"], {"pass": 5, "fail": 0, "not_testable_here": 0})
        self.assertNotIn("bug_ids", json.dumps(d))

    def test_run_needs_build_and_head_bound_to_the_deploy(self):
        # 2026-10-14 finding 4: a run records {build, head}; a run on a head the state does not know is refused
        rc, out = self.run_env(build=None); self.assertEqual(rc, 2); self.assertIn("--build", out)
        rc, out = self.run_env(head=None); self.assertEqual(rc, 2); self.assertIn("--head", out)
        rc, out = self.run_env(head=H2); self.assertEqual(rc, 2); self.assertIn("evidence.deploy.head", out); self.assertIn("INTEGRATION_REVIEW --build", out)
        self.assertNotIn("env_runs", json.dumps(self.data()))

    def test_failed_cases_need_case_keyed_bugs_and_a_persisting_fail_reopens(self):
        # 2026-10-14 finding 5: key = story + case id; a fail with an open bug counts; a fail with a done bug reopens it (no duplicate)
        rc, out = self.run_env(["TP-1", "TP-2"], full=True)
        self.assertEqual(rc, 2); self.assertIn("TP-1", out); self.assertIn("TP-2", out); self.assertIn("--case", out)
        rc, out = self.run_env(["TP-1", "TP-2"], full=True, failed_cases=None)
        self.assertEqual(rc, 2); self.assertIn("--failed-cases", out)
        self.assertEqual(bug_cmd.add(self.d, "S1", "a", "tester", case="TP-1", io=self.io), 0)
        rc, out = self.run_env(["TP-1", "TP-2"], full=True); self.assertEqual(rc, 2); self.assertNotIn("TP-1", out.replace("TP-1,TP-2", "")); self.assertIn("TP-2", out)
        self.assertEqual(bug_cmd.add(self.d, "S1", "b", "tester", case="TP-2", io=self.io), 0)
        self.assertEqual(bug_cmd.add(self.d, "S1", "dup", "tester", case="TP-2", io=self.io), 2)  # no duplicate for an open case
        rc, out = self.run_env(["TP-1", "TP-2"], full=True); self.assertEqual(rc, 0, out)
        self.assertEqual([r["head"] for r in self.bugs()["b01"]["runs"]], [H])
        # the fix for TP-1 did not work: the open bug still counts, its runs grow, nothing new is required
        rc, out = self.run_env(["TP-1"]); self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.bugs()["b01"]["runs"]), 2); self.assertEqual(len(self.bugs()["b02"]["runs"]), 1)
        # b01 done, then TP-1 fails again: reopened, not duplicated
        self.assertEqual(bug_cmd.set_(self.d, "b01", state="done", io=self.io), 0); self.assertEqual(bug_cmd.set_(self.d, "b02", state="done", io=self.io), 0)
        rc, out = self.run_env(["TP-1"]); self.assertEqual(rc, 0, out)
        b = self.bugs(); self.assertEqual((b["b01"]["state"], len(b["b01"]["runs"]), b["b02"]["state"]), ("todo", 3, "done")); self.assertEqual(len(b), 2)
        self.assertIn("bug b01 reopened", (self.d / "ledger.md").read_text())
        self.assertEqual(bug_cmd.add(self.d, "S1", "dup", "tester", case="TP-1", io=self.io), 2)
        # a new case with no bug at all is still refused, and the count must match the list
        rc, out = self.run_env(["TP-1", "TP-3"]); self.assertEqual(rc, 2); self.assertIn("TP-3", out)
        o = opts(report="reports/ENV.md", figma_parity="pass", cases_pass=4, cases_fail=2, failed_cases="TP-1", build="1", head=H)
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", o, self.io); self.assertEqual(rc, 2); self.assertIn("--cases-fail", out)

    def test_done_needs_full_run_on_the_deploy_head(self):
        self.assertEqual(self.run_env(full=False)[0], 0)
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)
        self.assertEqual(rc, 2); self.assertIn("full", out)
        self.assertEqual(self.run_env(full=True)[0], 0)
        d = self.data(); d["stories"]["S1"]["evidence"]["env_test"]["head"] = H2; d["stories"]["S1"]["evidence"]["env_runs"][-1]["head"] = H2; self.write(d)
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)
        self.assertEqual(rc, 2); self.assertIn("env_test.head", out)
        d = self.data(); d["stories"]["S1"]["evidence"]["env_test"]["head"] = H; d["stories"]["S1"]["evidence"]["env_runs"][-1]["head"] = H; self.write(d)
        self.assertEqual(run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)[0], 0)

    def test_done_with_flags_records_a_full_run(self):
        o = opts(report="reports/ENV.md", figma_parity="pass", cases_pass=5, cases_fail=0, full=True, build="1", head=H, approved="ah-7")
        rc, out = run_capture(self.d, "story", "S1", "DONE", o, self.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.data()["stories"]["S1"]["evidence"]["env_runs"][-1]["full"], True)

    def test_integration_review_reentry_records_a_redeploy(self):
        # 2026-10-14 finding 3: fixes move the stack top; INTEGRATION_REVIEW re-enters itself with the new build/head
        d = self.data(); d["stories"]["S1"]["state"] = "INTEGRATION_REVIEW"; self.write(d)
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(), self.io)
        self.assertEqual(rc, 2); self.assertIn("--build", out); self.assertIn("--head", out)
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="2"), self.io); self.assertEqual(rc, 2)
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="2", head=H2), self.io); self.assertEqual(rc, 0, out)
        dp = self.data()["stories"]["S1"]["evidence"]["deploy"]; self.assertEqual((dp["build"], dp["head"]), ("2", H2)); self.assertTrue(dp["at"])
        self.assertEqual(dp["heads"], {})  # round 2: snapshot of every open PR head (all merged in this fixture)
        # the old review no longer matches the deploy: ENV_TESTING needs a review round on H2
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/S.md", head=H), self.io)
        self.assertEqual(rc, 2); self.assertIn("integration_review.head == evidence.deploy.head", out)
        self.assertEqual(run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/S.md", head=H2), self.io)[0], 0)
        self.assertEqual(self.run_env(head=H2, build="2", full=True)[0], 0)

    def test_rule_reads_env_test_when_no_runs(self):
        s = {"_id": "S1", "state": "ENV_TESTING", "evidence": {"env_test": {"report": "r", "cases": {"pass": 1, "fail": 0}, "figma_parity": "pass", "full": True}}}
        self.assertEqual(rules.last_env_run(s)["full"], True)

    def test_full_run_must_add_up_to_the_story_test_cases(self):
        # round 2 R2-10: --full is not self-declared; pass + fail + not_testable_here equals len(stories.<S>.test_cases)
        o = opts(report="reports/ENV.md", figma_parity="pass", cases_pass=3, cases_fail=0, full=True, build="1", head=H)
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", o, self.io); self.assertEqual(rc, 2); self.assertIn("5 test cases", out); self.assertIn("3", out)
        o = opts(report="reports/ENV.md", figma_parity="pass", cases_pass=3, cases_fail=0, cases_not_testable=2, full=True, build="1", head=H)
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", o, self.io); self.assertEqual(rc, 0, out)
        self.assertEqual(self.data()["stories"]["S1"]["evidence"]["env_test"]["cases"], {"pass": 3, "fail": 0, "not_testable_here": 2})
        o = opts(report="reports/ENV.md", figma_parity="pass", cases_pass=3, cases_fail=0, build="1", head=H)  # a partial run may be any size
        self.assertEqual(run_capture(self.d, "story", "S1", "ENV_TESTING", o, self.io)[0], 0)
        o = opts(report="reports/ENV.md", figma_parity="pass", cases_pass=6, cases_fail=0, full=True, build="1", head=H)
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", o, self.io); self.assertEqual(rc, 2); self.assertIn("5 test cases", out)
        d = self.data(); d["stories"]["S1"]["test_cases"] = []; self.write(d)
        o = opts(report="reports/ENV.md", figma_parity="pass", cases_pass=0, cases_fail=0, full=True, build="1", head=H)
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", o, self.io); self.assertEqual(rc, 2); self.assertIn("test_cases", out)
        # DONE re-checks the last full run against the case list (defence in depth: the list may have changed by a re-plan)
        d = self.data(); d["stories"]["S1"]["test_cases"] = ["TP-1", "TP-2", "TP-3", "TP-4", "TP-5"]; self.write(d)
        self.assertEqual(self.run_env(full=True)[0], 0)
        d = self.data(); d["stories"]["S1"]["test_cases"] = ["TP-1"]; self.write(d)
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io); self.assertEqual(rc, 2); self.assertIn("1 test case", out)

    def test_parity_not_testable_here_is_recorded_and_blocks_done(self):
        o = opts(report="reports/ENV.md", figma_parity="not_testable_here", cases_pass=0, cases_fail=0, cases_not_testable=5, full=True, build="1", head=H)
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", o, self.io); self.assertEqual(rc, 0, out)
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)
        self.assertEqual(rc, 2); self.assertIn("figma_parity == pass (has not_testable_here)", out)

    def test_integration_review_refuses_a_review_round(self):
        # round 2 R2-13: --report --build --head on INTEGRATION_REVIEW recorded a review round instead of the deploy
        d = self.data(); d["stories"]["S1"]["state"] = "INTEGRATION_REVIEW"; self.write(d)
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(report="reports/S.md", build="2", head=H2), self.io)
        self.assertEqual(rc, 2); self.assertIn("--report", out); self.assertIn("ENV_TESTING --report", out)
        self.assertEqual(self.data()["stories"]["S1"]["evidence"]["deploy"]["build"], "1")
        d = self.data(); d["stories"]["S1"]["state"] = "IN_PROGRESS"; self.write(d)
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(report="reports/S.md", build="2", head=H2), self.io)
        self.assertEqual(rc, 2); self.assertIn("--report", out)
