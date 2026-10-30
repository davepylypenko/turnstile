import contextlib, io, json, pathlib, shutil, tempfile, unittest
from turnstile_cli import pr_cmd, pass_cmd, state
from tests.test_pass import FakeIO, opts

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class PrAdd(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; (self.d / "briefs").mkdir(parents=True)
        shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch()
        self.io = FakeIO(heads={"jsfiller#7": "cccccccc33333333"}); self.io.facts["jsfiller#7"] = {"base": "epic_myd-1", "branch": "feature/MYD-11"}
        (self.d / "briefs" / "MYD-11.md").write_text("brief\n")
        self.approve_plan()
    def approve_plan(self):
        (self.d / "plan.md").write_text("# plan\n"); digest = state.digest("# plan\n")
        d = json.loads((self.d / "state.json").read_text()); d["epic"]["plan"] = {"path": "plan.md", "submitted_at": "x", "digest": digest}
        d["stories"]["S1"]["tickets"] = ["MYD-10", "MYD-11"]; d["stories"]["S1"]["branch"] = "epic_myd-1"
        d["awaiting_human"] = [{"id": "ah-1", "owner": "lead", "type": "plan", "payload": "plan.md", "digest": digest, "created_at": "x",
                                "approved_at": "2026-10-13T10:00Z", "approved_via": "lead-terminal"}]
        (self.d / "state.json").write_text(state.dumps(d))
    def add(self, pr="jsfiller#7", story="S1", ticket="MYD-11"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = pr_cmd.add(self.d, pr, story, ticket, io=self.io)
        return rc, buf.getvalue()
    def data(self): return json.loads((self.d / "state.json").read_text())

    def test_add_records_dev_from_github_facts_and_the_pass_to_ai_review_accepts_it(self):
        rc, out = self.add(); self.assertEqual(rc, 0, out)
        self.assertIn("JIRA: MYD-11 → In progress", out); self.assertIn("OK pr jsfiller#7 added (S1, MYD-11) DEV head cccccccc", out)
        pr = self.data()["prs"]["jsfiller#7"]
        self.assertEqual((pr["state"], pr["head"], pr["base"], pr["branch"], pr["story"], pr["ticket"]), ("DEV", "cccccccc33333333", "epic_myd-1", "feature/MYD-11", "S1", "MYD-11"))
        self.assertEqual(pr["jira"], {"status": "In progress", "synced": False}); self.assertEqual(self.io.commits[-1], "turnstile: pr jsfiller#7 added (S1, MYD-11) DEV head cccccccc")
        self.assertIn("pr jsfiller#7 added", (self.d / "ledger.md").read_text())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = pass_cmd.run(self.d, "pr", "jsfiller#7", "AI_REVIEW", opts(head="cccccccc33333333", ci="success"), io=self.io)
        self.assertEqual(rc, 0, buf.getvalue()); self.assertEqual(self.data()["prs"]["jsfiller#7"]["state"], "AI_REVIEW")
    def test_refusals_write_nothing(self):
        before = (self.d / "state.json").read_text()
        for kw, needle in [(dict(pr="jsfiller#7", story="S9"), "unknown story S9"), (dict(ticket="MYD-99"), "not in stories.S1.tickets"),
                           (dict(pr="nope#1"), "not configured"), (dict(pr="jsfiller#1"), "already recorded"), (dict(pr="bad"), "repo#123")]:
            rc, out = self.add(**kw); self.assertEqual(rc, 2, out); self.assertIn(needle, out)
        (self.d / "briefs" / "MYD-11.md").unlink(); rc, out = self.add(); self.assertEqual(rc, 2); self.assertIn("no brief briefs/MYD-11.md", out)
        (self.d / "briefs" / "MYD-11.md").write_text("brief\n")
        self.io.facts["jsfiller#7"]["base"] = "develop"; rc, out = self.add(); self.assertEqual(rc, 2); self.assertIn("based on develop, not on the story branch epic_myd-1", out)
        self.io.facts["jsfiller#7"]["base"] = "epic_myd-1"; self.io.facts["jsfiller#7"]["merged"] = True; rc, out = self.add(); self.assertIn("already merged", out)
        self.io.heads.pop("jsfiller#7"); self.io.facts["jsfiller#7"]["merged"] = False; rc, out = self.add(); self.assertEqual(rc, 2); self.assertIn("gh api failed", out)
        self.assertEqual((self.d / "state.json").read_text(), before); self.assertEqual(self.io.commits, [])
    def test_stacked_pr_may_base_on_another_open_pr_of_the_story(self):
        self.io.facts["jsfiller#7"]["base"] = "feature/MYD-10"
        rc, out = self.add(); self.assertEqual(rc, 0, out); self.assertEqual(self.data()["prs"]["jsfiller#7"]["base"], "feature/MYD-10")
    def test_unapproved_plan_refused(self):
        d = self.data(); d["awaiting_human"][0]["approved_at"] = None; (self.d / "state.json").write_text(state.dumps(d))
        rc, out = self.add(); self.assertEqual(rc, 2); self.assertIn("lead approval of plan.md", out)
