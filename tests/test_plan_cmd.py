import contextlib, io, json, pathlib, shutil, tempfile, unittest
from turnstile_cli import plan_cmd, pass_cmd, rules, state
from turnstile_cli.errors import TurnstileError
from tests.test_pass import FakeIO, opts, env

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"
PLAN = """# plan

```json turnstile-stories
{
  "S1": {"title": "Header", "tickets": ["MYD-10", "MYD-11"], "repos": ["jsfiller"], "branch": "epic_myd-1", "after": [], "parallel_with": [],
         "test_cases": ["TP-1"], "figma": ["F:1-2"], "env_slot": {"variant": "v1"}, "human_review_units": [], "human_review": "per_pr"},
  "S2": {"title": "Results", "tickets": ["MYD-12"], "repos": ["front-link2fill-app"], "branch": "story/s2", "after": ["S1"]}
}
```
"""

class Parse(unittest.TestCase):
    def test_parses_block_and_defaults(self):
        s = plan_cmd.stories_from_plan(PLAN)
        self.assertEqual(sorted(s), ["S1", "S2"]); self.assertEqual(s["S1"]["human_review"], "per_pr")
        self.assertEqual((s["S2"]["parallel_with"], s["S2"]["test_cases"], s["S2"]["env_slot"], s["S2"]["human_review_units"]), ([], [], {}, []))
    def test_rejects(self):
        for bad in ["# no block", PLAN.replace('"S2"', '"X2"'), PLAN.replace('"title": "Results", ', ""),
                    PLAN.replace('"branch": "story/s2", ', ""), PLAN.replace('"after": ["S1"]', '"after": ["S9"]'), PLAN.replace("}\n}\n```", "}\n```")]:
            with self.assertRaises(TurnstileError, msg=bad[:40]):
                plan_cmd.stories_from_plan(bad)

class Merge(unittest.TestCase):
    def test_keeps_state_of_existing_and_plans_new(self):
        existing = json.loads(FIX.read_text())["stories"]
        merged = plan_cmd.merge_stories(existing, plan_cmd.stories_from_plan(PLAN))
        self.assertEqual((merged["S1"]["state"], merged["S1"]["figma"]), ("IN_PROGRESS", ["F:1-2"]))
        self.assertEqual((merged["S2"]["state"], merged["S2"]["evidence"], merged["S2"]["next_action"]), ("PLANNED", {}, ""))
    def test_drop_only_planned(self):
        self.assertNotIn("S1", plan_cmd.merge_stories({"S1": {"state": "PLANNED"}}, {}))
        with self.assertRaises(TurnstileError):
            plan_cmd.merge_stories({"S1": {"state": "PLANNED"}, "S2": {"state": "IN_PROGRESS"}}, {})

class Run(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / "plan.md").write_text(PLAN); (self.d / ".state.lock").touch()
        self.io = FakeIO(heads={"jsfiller#1": "aaaaaaaa11111111"})
    def submit(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = plan_cmd.run(self.d, self.io)
        return rc, buf.getvalue()
    def data(self): return json.loads((self.d / "state.json").read_text())
    def write(self, d): (self.d / "state.json").write_text(state.dumps(d))
    def approve(self, ah):
        with env(TURNSTILE_LEAD="1"):
            self.assertEqual(pass_cmd.approve(self.d, ah, self.io), 0)
    def plan_entry(self):
        return rules.latest_entry(self.data()["awaiting_human"], "plan", "payload", "plan.md")

    def test_submit_records_stories_digest_and_awaiting(self):
        rc, out = self.submit()
        self.assertEqual(rc, 0); self.assertIn("TURNSTILE_LEAD=1 turnstile approve ah-1", out); self.assertIn("OK plan submitted", out)
        d = self.data()
        self.assertEqual(d["stories"]["S2"]["state"], "PLANNED"); self.assertEqual(d["epic"]["plan"]["digest"], state.digest(PLAN))
        e = self.plan_entry(); self.assertEqual((e["id"], e["type"], e["payload"], e["approved_at"]), ("ah-1", "plan", "plan.md", None))
        self.assertEqual(len(self.io.commits), 1); self.assertEqual(self.io.renders, 1); self.assertIn("plan submitted", (self.d / "ledger.md").read_text())
    def test_resubmit_voids_previous_entry(self):
        self.submit(); self.approve("ah-1"); (self.d / "plan.md").write_text(PLAN + "\nmore\n"); self.submit()
        entries = [a for a in self.data()["awaiting_human"] if a["type"] == "plan"]
        self.assertEqual(len(entries), 2); self.assertTrue(entries[0]["voided_at"]); self.assertIsNone(entries[1]["approved_at"])
    def test_story_start_needs_plan_approval_even_with_lead_reason(self):
        d = self.data(); d["stories"]["S1"]["state"] = "DONE"; self.write(d)  # S2 is after S1: plan-submitted opens its start_story entry
        self.submit()
        start = rules.latest_entry(self.data()["awaiting_human"], "start_story", "story", "S2"); self.assertIsNotNone(start)
        self.approve(start["id"])
        self.assertEqual(pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(), self.io), 2)
        self.assertEqual(pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(reason="lead 2026-10-13: go"), self.io), 2)
        self.approve("ah-1")
        self.assertEqual(pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(), self.io), 0)
    def test_edited_plan_voids_approval(self):
        self.submit(); self.approve("ah-1")
        d = self.data(); d["stories"]["S1"]["state"] = "DONE"; self.write(d)
        (self.d / "plan.md").write_text(PLAN + "\nedited after approval\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(reason="lead: go"), self.io)
        self.assertEqual(rc, 2); self.assertIn("plan.md changed", buf.getvalue())
    def test_messages(self):
        d = json.loads(FIX.read_text())
        self.assertIn("plan-submitted", rules.plan_approval_missing(d, state.digest(PLAN)))
        d["epic"]["plan"] = {"path": "plan.md", "submitted_at": "x", "digest": state.digest(PLAN)}
        d["awaiting_human"] = [{"id": "ah-1", "type": "plan", "payload": "plan.md", "approved_at": None}]
        self.assertIn("approve ah-1", rules.plan_approval_missing(d, state.digest(PLAN)))
        d["awaiting_human"][0]["approved_at"] = "x"
        self.assertIsNone(rules.plan_approval_missing(d, state.digest(PLAN)))
