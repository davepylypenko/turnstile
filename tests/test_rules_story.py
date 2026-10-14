import copy, json, pathlib, unittest
from turnstile_cli import rules

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())
H = "aaaaaaaa11111111"
START = {"id": "ah-1", "owner": "lead", "type": "start_story", "story": "S1", "approved_at": "2026-10-13T10:00Z"}
DONE = {"id": "ah-2", "owner": "lead", "type": "story_done", "story": "S1", "approved_at": "2026-10-13T10:00Z"}
CLEAN_ENV = {"report": "reports/ENV-S1.md", "cases": {"pass": 3, "fail": 0, "not_testable_here": 0}, "figma_parity": "pass", "full": True,
             "build": "173111", "head": H, "failed_cases": []}

def story(state, **ev):
    s = copy.deepcopy(FIX["stories"]["S1"]); s["_id"] = "S1"; s["state"] = state; s["evidence"].update(ev); return s

def prs(*states):
    out = copy.deepcopy(FIX["prs"])
    for pid, st in zip(["jsfiller#1", "docs-platform#2"], states):
        out[pid]["state"] = st
    return out

def tested(state="ENV_TESTING", **over):
    s = story(state, deploy={"build": "173111", "head": H, "heads": {"jsfiller#1": H, "docs-platform#2": "bbbbbbbb22222222"}, "head_verified": {"verified": True}}, integration_review={"report": "r", "head": H, "rounds": 1, "clean": True},
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

    def test_deploy_head_must_be_the_current_stack_top(self):
        # 2026-10-14 finding 4: the stack top is the head of the story's open PR that no other PR of the story is based on
        ps = prs("READY", "READY"); ps["docs-platform#2"]["base"] = "feature/MYD-10"; ps["docs-platform#2"]["head"] = "cccccccc33333333"
        self.assertEqual(rules.stack_tops("S1", ps), [("docs-platform#2", "cccccccc33333333")])
        s = story("IN_PROGRESS", deploy={"build": "1", "head": H})
        out = rules.check_story(s, "INTEGRATION_REVIEW", ps, FIX["stories"])
        self.assertTrue(any("stack top" in m and "docs-platform#2" in m for m in out), out)
        s["evidence"]["deploy"]["head"] = "cccccccc33333333"
        self.assertEqual(rules.check_story(s, "INTEGRATION_REVIEW", ps, FIX["stories"]), [])
        ps["docs-platform#2"]["state"] = "MERGED"  # merged PRs drop out of the stack; nothing left to compare → no check
        self.assertEqual(rules.stack_tops("S1", ps), [("jsfiller#1", H)])
        ps["jsfiller#1"]["state"] = "MERGED"; self.assertEqual(rules.stack_tops("S1", ps), [])
        self.assertEqual(rules.check_story(s, "INTEGRATION_REVIEW", ps, FIX["stories"]), [])
        # a multi-repo story has one top per repo: the deploy head may be any of them
        ps = prs("READY", "READY"); self.assertEqual(len(rules.stack_tops("S1", ps)), 2)
        s = tested(); s["evidence"]["deploy"]["head"] = "bbbbbbbb22222222"; s["evidence"]["integration_review"]["head"] = "bbbbbbbb22222222"
        s["evidence"]["env_test"].update(head="bbbbbbbb22222222", build="173111")
        self.assertEqual(rules.check_story(s, "DONE", ps, FIX["stories"], bugs=[], awaiting=[DONE]), [])
        s["evidence"]["env_test"]["head"] = H
        out = rules.check_story(s, "DONE", ps, FIX["stories"], bugs=[], awaiting=[DONE])
        self.assertTrue(any("env_test.head" in m for m in out), out)

    def test_integration_review_reenters_itself(self):
        s = story("INTEGRATION_REVIEW", deploy={"build": "2", "head": H})
        self.assertEqual(rules.check_story(s, "INTEGRATION_REVIEW", prs("READY", "MERGED"), FIX["stories"]), [])

    def test_reopen_needs_reason(self):
        s = story("DONE")
        self.assertTrue(any("reopen" in m for m in rules.check_story(s, "IN_PROGRESS", {}, FIX["stories"])))
        self.assertEqual(rules.check_story(s, "IN_PROGRESS", {}, FIX["stories"], reason="bug b4 in prod"), [])


class DeployHeadsSnapshot(unittest.TestCase):
    """Round 2: deploy.heads snapshots every open PR of the story at the deploy (all repos); a later change voids it."""
    def setUp(self):
        import copy, json, pathlib
        d = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())
        self.prs = d["prs"]
        for p in self.prs.values(): p["state"] = "READY"
        self.s = copy.deepcopy(d["stories"]["S1"]); self.s["_id"] = "S1"; self.s["state"] = "INTEGRATION_REVIEW"
        A, B = self.prs["jsfiller#1"]["head"], self.prs["docs-platform#2"]["head"]
        self.s["evidence"] = {"deploy": {"build": "1", "head": A, "heads": {"jsfiller#1": A, "docs-platform#2": B}},
                              "integration_review": {"report": "r", "head": A, "clean": True}}

    def test_other_repo_change_after_deploy_is_caught(self):
        self.assertEqual(rules.check_story(self.s, "ENV_TESTING", self.prs, {"S1": self.s}), [])
        self.prs["docs-platform#2"]["head"] = "cccccccc33333333"
        out = rules.check_story(self.s, "ENV_TESTING", self.prs, {"S1": self.s})
        self.assertTrue(any("docs-platform#2" in m and "deploy.heads" in m for m in out), out)

    def test_send_of_a_done_story_after_a_push_is_refused(self):
        self.s["state"] = "DONE"; pr = dict(self.prs["jsfiller#1"], state="READY")
        out = []; rules._story_gates_passed(pr, {"S1": self.s}, out, self.prs); self.assertEqual(out, [])
        self.prs["jsfiller#1"]["head"] = "dddddddd44444444"
        out = []; rules._story_gates_passed(pr, {"S1": self.s}, out, self.prs); self.assertTrue(out)

    def test_to_done_needs_a_heads_snapshot_verified_on_github(self):
        # round 2 R2-7: DONE trusts deploy.heads only after an online story pass confirmed every head on GitHub
        s = tested(); s["evidence"]["deploy"].pop("heads")
        out = rules.check_story(s, "DONE", prs("READY", "MERGED"), FIX["stories"], bugs=[], awaiting=[DONE])
        self.assertTrue(any("deploy.heads" in m for m in out), out)
        s = tested(); s["evidence"]["deploy"]["head_verified"] = {"verified": False}
        out = rules.check_story(s, "DONE", prs("READY", "MERGED"), FIX["stories"], bugs=[], awaiting=[DONE])
        self.assertTrue(any("head_verified" in m and "offline" in m for m in out), out)
        s = tested(); s["evidence"]["deploy"].pop("head_verified")
        self.assertTrue(any("head_verified" in m for m in rules.check_story(s, "DONE", prs("READY", "MERGED"), FIX["stories"], bugs=[], awaiting=[DONE])))
