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

class TrunkMode(unittest.TestCase):
    def test_mode_defaults_from_the_epic_and_control_cases_parse(self):
        s = plan_cmd.stories_from_plan(PLAN)
        self.assertEqual((s["S1"]["mode"], s["S2"]["mode"], s["S1"]["control_cases"]), ("stack", "stack", []))
        s = plan_cmd.stories_from_plan(PLAN, "trunk"); self.assertEqual((s["S1"]["mode"], s["S2"]["mode"]), ("trunk", "trunk"))
        text = PLAN.replace('"test_cases": ["TP-1"]', '"test_cases": ["TP-1"], "mode": "stack", "control_cases": ["CC-1", "CC-2"]')
        s = plan_cmd.stories_from_plan(text, "trunk"); self.assertEqual((s["S1"]["mode"], s["S1"]["control_cases"], s["S2"]["mode"]), ("stack", ["CC-1", "CC-2"], "trunk"))
        for bad, default in [(PLAN.replace('"test_cases": ["TP-1"]', '"test_cases": ["TP-1"], "mode": "branchy"'), "stack"), (PLAN, "x"),
                             (PLAN.replace('"test_cases": ["TP-1"]', '"test_cases": ["TP-1"], "control_cases": "CC-1"'), "stack")]:
            with self.assertRaises(TurnstileError): plan_cmd.stories_from_plan(bad, default)
    def test_plan_submitted_uses_epic_story_mode(self):
        d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; d.mkdir(); shutil.copy(FIX, d / "state.json"); (d / ".state.lock").touch()
        data = json.loads((d / "state.json").read_text()); data["epic"]["story_mode"] = "trunk"; data["stories"]["S1"]["state"] = "PLANNED"; (d / "state.json").write_text(state.dumps(data))
        (d / "plan.md").write_text(PLAN)
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(plan_cmd.run(d, io=FakeIO()), 0)
        st = json.loads((d / "state.json").read_text())["stories"]; self.assertEqual((st["S1"]["mode"], st["S2"]["mode"], st["S2"]["control_cases"]), ("trunk", "trunk", []))

class StartedStoryMode(unittest.TestCase):
    def test_replan_cannot_flip_mode_or_human_review_of_a_started_story(self):
        # review P2-3: like the branch, the mode decides the running rules; human_review may only be set where it was unset (the migration path)
        existing = {"S1": {"state": "IN_PROGRESS", "branch": "epic_myd-1", "mode": "stack", "evidence": {}}}
        planned = plan_cmd.stories_from_plan(PLAN, "trunk"); planned["S1"]["mode"] = "trunk"
        with self.assertRaises(TurnstileError) as cm: plan_cmd.merge_stories(existing, planned)
        self.assertIn("its mode cannot change from 'stack' to 'trunk'", str(cm.exception))
        legacy = {"S1": {"state": "IN_PROGRESS", "branch": "epic_myd-1", "evidence": {}}}
        merged, _ = plan_cmd.merge_stories(legacy, plan_cmd.stories_from_plan(PLAN)); self.assertEqual((merged["S1"]["mode"], merged["S1"]["human_review"]), ("stack", "per_pr"))
        with self.assertRaises(TurnstileError): plan_cmd.merge_stories(legacy, planned)
        started = {"S1": {"state": "ENV_TESTING", "branch": "epic_myd-1", "human_review": "per_pr", "evidence": {}}}
        with self.assertRaises(TurnstileError) as cm: plan_cmd.merge_stories(started, plan_cmd.stories_from_plan(PLAN.replace(', "human_review": "per_pr"', "")))
        self.assertIn("human_review cannot change from 'per_pr' to None", str(cm.exception))
        planned_only = {"S1": {"state": "PLANNED", "branch": "epic_myd-1", "mode": "stack", "evidence": {}}}
        self.assertEqual(plan_cmd.merge_stories(planned_only, planned)[0]["S1"]["mode"], "trunk")
    def test_trunk_story_under_a_flag_needs_control_cases(self):
        self.assertEqual(plan_cmd.stories_from_plan(PLAN, "trunk")["S1"]["control_cases"], [])
        with self.assertRaises(TurnstileError) as cm: plan_cmd.stories_from_plan(PLAN, "trunk", "pwr-x")
        self.assertIn("S1.control_cases is empty", str(cm.exception))
        text = PLAN.replace('"test_cases": ["TP-1"]', '"test_cases": ["TP-1"], "control_cases": ["CC-1"]').replace('"after": ["S1"]', '"after": ["S1"], "control_cases": ["CC-2"]')
        self.assertEqual(plan_cmd.stories_from_plan(text, "trunk", "pwr-x")["S2"]["control_cases"], ["CC-2"])
        self.assertEqual(plan_cmd.stories_from_plan(PLAN.replace('"after": ["S1"]', '"after": ["S1"], "mode": "stack"'), "stack", "pwr-x")["S2"]["mode"], "stack")

class Merge(unittest.TestCase):
    def test_keeps_state_of_existing_and_plans_new(self):
        existing = json.loads(FIX.read_text())["stories"]
        merged, warns = plan_cmd.merge_stories(existing, plan_cmd.stories_from_plan(PLAN))
        self.assertEqual((merged["S1"]["state"], merged["S1"]["figma"]), ("IN_PROGRESS", ["F:1-2"]))
        self.assertEqual((merged["S2"]["state"], merged["S2"]["evidence"], merged["S2"]["next_action"]), ("PLANNED", {}, ""))
        self.assertEqual(warns, [])
    def test_drop_only_planned(self):
        self.assertNotIn("S1", plan_cmd.merge_stories({"S1": {"state": "PLANNED"}}, {})[0])
        with self.assertRaises(TurnstileError):
            plan_cmd.merge_stories({"S1": {"state": "PLANNED"}, "S2": {"state": "IN_PROGRESS"}}, {})
    def test_started_story_keeps_its_branch_and_warns_on_tickets_or_repos(self):
        # 2026-10-14 minor 9: a re-plan cannot retarget a started story's branch; ticket/repo changes are printed as WARN
        existing = json.loads(FIX.read_text())["stories"]
        planned = plan_cmd.stories_from_plan(PLAN.replace('"branch": "epic_myd-1"', '"branch": "story/s1-new"'))
        with self.assertRaises(TurnstileError) as cm:
            plan_cmd.merge_stories(existing, planned)
        self.assertIn("branch", str(cm.exception)); self.assertIn("S1", str(cm.exception))
        planned = plan_cmd.stories_from_plan(PLAN.replace('"tickets": ["MYD-10", "MYD-11"]', '"tickets": ["MYD-10"]').replace('"repos": ["jsfiller"], "branch": "epic_myd-1"', '"repos": ["jsfiller", "locales"], "branch": "epic_myd-1"'))
        merged, warns = plan_cmd.merge_stories(existing, planned)
        self.assertEqual(merged["S1"]["tickets"], ["MYD-10"]); self.assertEqual(len(warns), 2); self.assertTrue(all(w.startswith("WARN S1") for w in warns), warns)
        planned = plan_cmd.stories_from_plan(PLAN.replace('"branch": "story/s2"', '"branch": "story/s2-moved"'))
        merged, warns = plan_cmd.merge_stories(existing, planned)  # S2 is new / PLANNED: anything goes
        self.assertEqual(merged["S2"]["branch"], "story/s2-moved")

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
        self.assertRegex(d["stories"]["S2"]["state_since"], r"^\d{4}-\d\d-\d\dT\d\d:\d\dZ$"); self.assertNotIn("state_since", d["stories"]["S1"])
        e = self.plan_entry(); self.assertEqual((e["id"], e["type"], e["payload"], e["approved_at"]), ("ah-1", "plan", "plan.md", None))
        self.assertEqual(len(self.io.commits), 1); self.assertEqual(self.io.renders, 1); self.assertIn("plan submitted", (self.d / "ledger.md").read_text())
    def test_resubmit_voids_previous_entry(self):
        self.submit(); self.approve("ah-1"); (self.d / "plan.md").write_text(PLAN + "\nmore\n"); self.submit()
        entries = [a for a in self.data()["awaiting_human"] if a["type"] == "plan"]
        self.assertEqual(len(entries), 2); self.assertTrue(entries[0]["voided_at"]); self.assertIsNone(entries[1]["approved_at"])
        self.assertEqual(entries[1]["digest"], state.digest(PLAN + "\nmore\n"))
    def test_resubmit_prints_warnings_for_a_started_story(self):
        self.submit()
        (self.d / "plan.md").write_text(PLAN.replace('"tickets": ["MYD-10", "MYD-11"]', '"tickets": ["MYD-10"]'))
        rc, out = self.submit(); self.assertEqual(rc, 0); self.assertIn("WARN S1", out); self.assertIn("WARN S1", (self.d / "ledger.md").read_text())
        (self.d / "plan.md").write_text(PLAN.replace('"branch": "epic_myd-1"', '"branch": "elsewhere"'))
        rc, out = self.submit(); self.assertEqual(rc, 2); self.assertIn("branch", out)
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
        d["awaiting_human"][0]["digest"] = "another-plan"  # 2026-10-14 minor 8: the approved entry is for this plan digest
        self.assertIn("approved for another version", rules.plan_approval_missing(d, state.digest(PLAN)))
        d["awaiting_human"][0]["digest"] = state.digest(PLAN)
        self.assertIsNone(rules.plan_approval_missing(d, state.digest(PLAN)))
    def test_approve_and_status_name_the_plan_entry(self):
        # 2026-10-14 nit 16: no more "plan None"
        self.submit()
        buf = io.StringIO()
        with env(TURNSTILE_LEAD="1"), contextlib.redirect_stdout(buf):
            pass_cmd.approve(self.d, "ah-1", self.io)
        self.assertIn("(plan plan.md by lead)", buf.getvalue()); self.assertNotIn("None", buf.getvalue())
        self.assertIn("approved ah-1 (plan plan.md by lead) approved_via: lead-terminal", (self.d / "ledger.md").read_text())
