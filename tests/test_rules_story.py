import copy, json, pathlib, unittest
from turnstile_cli import rules

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())
H = "aaaaaaaa11111111"
START = {"id": "ah-1", "owner": "lead", "type": "start_story", "story": "S1", "approved_at": "2026-10-13T10:00Z"}
DONE = {"id": "ah-2", "owner": "lead", "type": "story_done", "story": "S1", "approved_at": "2026-10-13T10:00Z"}
CLEAN_ENV = {"report": "reports/ENV-S1.md", "cases": {"pass": 3, "fail": 0, "not_testable_here": 0}, "figma_parity": "pass", "full": True}

def story(state, **ev):
    s = copy.deepcopy(FIX["stories"]["S1"]); s["_id"] = "S1"; s["state"] = state; s["evidence"].update(ev); return s

def prs(*states):
    out = copy.deepcopy(FIX["prs"])
    for pid, st in zip(["jsfiller#1", "docs-platform#2"], states):
        out[pid]["state"] = st
    return out

def tested(state="ENV_TESTING", **over):
    s = story(state, deploy={"build": "173111", "head": H}, integration_review={"report": "r", "head": H, "rounds": 1, "clean": True},
              env_test=copy.deepcopy(CLEAN_ENV))
    s["evidence"].update(over)
    return s

class StoryRules(unittest.TestCase):
    def test_to_integration_review_needs_all_prs_ready_and_deploy_with_head(self):
        out = rules.check_story(story("IN_PROGRESS"), "INTEGRATION_REVIEW", prs("READY", "DEV"), FIX["stories"])
        self.assertTrue(any("docs-platform#2" in m for m in out))
        self.assertTrue(any("deploy.build" in m for m in out))
        out = rules.check_story(story("IN_PROGRESS", deploy={"build": "173111"}), "INTEGRATION_REVIEW", prs("READY", "MERGED"), FIX["stories"])
        self.assertTrue(any("deploy.head" in m for m in out), out)
        ok = rules.check_story(story("IN_PROGRESS", deploy={"build": "173111", "head": H}), "INTEGRATION_REVIEW",
                               prs("READY", "MERGED"), FIX["stories"])
        self.assertEqual(ok, [])

    def test_to_env_testing(self):
        out = rules.check_story(story("INTEGRATION_REVIEW"), "ENV_TESTING", prs("READY", "READY"), FIX["stories"])
        self.assertTrue(any("integration_review" in m for m in out))

    def test_to_env_testing_rechecks_prs_and_binds_review_head_to_deploy(self):
        s = story("INTEGRATION_REVIEW", deploy={"build": "1", "head": H}, integration_review={"report": "r", "head": H, "clean": True})
        self.assertEqual(rules.check_story(s, "ENV_TESTING", prs("READY", "MERGED"), FIX["stories"]), [])
        out = rules.check_story(s, "ENV_TESTING", prs("READY", "AI_REVIEW"), FIX["stories"])
        self.assertTrue(any("docs-platform#2" in m for m in out), out)
        s["evidence"]["integration_review"]["head"] = "ffffffff66666666"
        out = rules.check_story(s, "ENV_TESTING", prs("READY", "MERGED"), FIX["stories"])
        self.assertTrue(any("deploy.head" in m for m in out), out)

    def test_to_done_requires_clean_env_test(self):
        s = tested(env_test={"report": "r", "cases": {"pass": 3, "fail": 1}, "figma_parity": "fail"})
        out = rules.check_story(s, "DONE", prs("READY", "READY"), FIX["stories"], awaiting=[DONE])
        self.assertTrue(any("fail" in m for m in out))
        self.assertTrue(any("figma" in m for m in out))

    def test_to_done_happy_path(self):
        self.assertEqual(rules.check_story(tested(), "DONE", prs("READY", "MERGED"), FIX["stories"], bugs=[], awaiting=[DONE]), [])

    def test_to_done_needs_explicit_fail_count(self):
        s = tested(env_test={"report": "r", "cases": {"pass": 3}, "figma_parity": "pass"})
        out = rules.check_story(s, "DONE", prs("READY", "READY"), FIX["stories"], awaiting=[DONE])
        self.assertTrue(any("cases.fail" in m for m in out), out)

    def test_to_done_rechecks_prs_and_open_bugs(self):
        out = rules.check_story(tested(), "DONE", prs("READY", "DEV"), FIX["stories"], awaiting=[DONE])
        self.assertTrue(any("docs-platform#2" in m for m in out), out)
        bugs = [{"id": "b1", "story": "S1", "state": "todo"}, {"id": "b2", "story": "S2", "state": "todo"}, {"id": "b3", "story": "S1", "state": "done"}]
        out = rules.check_story(tested(), "DONE", prs("READY", "READY"), FIX["stories"], bugs=bugs, awaiting=[DONE])
        self.assertEqual([m for m in out if "bug" in m], ["MISSING bug b1 to be done (is todo)"])

    def test_to_done_needs_approved_story_done_entry(self):
        out = rules.check_story(tested(), "DONE", prs("READY", "READY"), FIX["stories"], awaiting=[])
        self.assertTrue(any("story_done" in m for m in out), out)
        out = rules.check_story(tested(), "DONE", prs("READY", "READY"), FIX["stories"], awaiting=[dict(DONE, approved_at=None)])
        self.assertTrue(any("story_done" in m for m in out), out)
        out = rules.check_story(tested(), "DONE", prs("READY", "READY"), FIX["stories"], awaiting=[dict(DONE, story="S2")])
        self.assertTrue(any("story_done" in m for m in out), out)

    def test_planned_needs_an_approved_start_story_entry_full_stop(self):
        # 2026-10-14 finding 2: no --reason bypass; the lead's start_story approval is the only way out of PLANNED
        s = story("PLANNED")
        self.assertTrue(any("start_story" in m for m in rules.check_story(s, "IN_PROGRESS", {}, FIX["stories"])))
        self.assertEqual(rules.check_story(s, "IN_PROGRESS", {}, FIX["stories"], awaiting=[START]), [])
        for reason in ("lead 2026-10-13: go", "per lead", "I felt like it"):
            out = rules.check_story(s, "IN_PROGRESS", {}, FIX["stories"], reason=reason)
            self.assertTrue(any("start_story" in m for m in out), (reason, out))
        out = rules.check_story(s, "IN_PROGRESS", {}, FIX["stories"], reason="lead: go", awaiting=[dict(START, approved_at=None)])
        self.assertTrue(any("approved_at" in m for m in out), out)
        self.assertFalse(hasattr(rules, "is_lead_override"))

    def test_planned_waits_for_after_without_any_override(self):
        stories = {"S0": {"state": "IN_PROGRESS"}, "S1": story("PLANNED")}
        s = story("PLANNED"); s["after"] = ["S0"]
        out = rules.check_story(s, "IN_PROGRESS", {}, stories, awaiting=[START])
        self.assertTrue(any("S0" in m and "DONE" in m for m in out), out)
        out = rules.check_story(s, "IN_PROGRESS", {}, stories, awaiting=[START], reason="lead: run in parallel")
        self.assertTrue(any("S0" in m for m in out), out)
        stories["S0"]["state"] = "DONE"
        self.assertEqual(rules.check_story(s, "IN_PROGRESS", {}, stories, awaiting=[START]), [])

    def test_parallel_start_only_through_parallel_with_in_the_plan(self):
        # an active story (IN_PROGRESS / INTEGRATION_REVIEW / ENV_TESTING) blocks a start unless the plan lists them as parallel
        for active in ("IN_PROGRESS", "INTEGRATION_REVIEW", "ENV_TESTING"):
            stories = {"S0": {"state": active, "parallel_with": []}, "S1": story("PLANNED")}
            s = story("PLANNED")
            out = rules.check_story(s, "IN_PROGRESS", {}, stories, awaiting=[START])
            self.assertTrue(any("S0" in m and "parallel_with" in m for m in out), (active, out))
            self.assertFalse(rules.startable(s, stories))
            s["parallel_with"] = ["S0"]
            self.assertEqual(rules.check_story(s, "IN_PROGRESS", {}, stories, awaiting=[START]), [])
            self.assertTrue(rules.startable(s, stories))
            s["parallel_with"] = []; stories["S0"]["parallel_with"] = ["S1"]  # either direction counts
            self.assertEqual(rules.check_story(s, "IN_PROGRESS", {}, stories, awaiting=[START]), [])
        stories = {"S0": {"state": "DONE", "parallel_with": []}, "S1": story("PLANNED")}
        self.assertEqual(rules.check_story(story("PLANNED"), "IN_PROGRESS", {}, stories, awaiting=[START]), [])  # DONE does not block
        self.assertTrue(rules.startable(story("PLANNED"), stories))

    def test_reopen_needs_reason(self):
        s = story("DONE")
        self.assertTrue(any("reopen" in m for m in rules.check_story(s, "IN_PROGRESS", {}, FIX["stories"])))
        self.assertEqual(rules.check_story(s, "IN_PROGRESS", {}, FIX["stories"], reason="bug b4 in prod"), [])
