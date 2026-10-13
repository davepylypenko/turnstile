import copy, json, pathlib, unittest
from turnstile_cli import rules

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())

def story(state, **ev):
    s = copy.deepcopy(FIX["stories"]["S1"]); s["_id"] = "S1"; s["state"] = state; s["evidence"].update(ev); return s

def prs(*states):
    out = copy.deepcopy(FIX["prs"])
    for pid, st in zip(["jsfiller#1", "docs-platform#2"], states):
        out[pid]["state"] = st
    return out

class StoryRules(unittest.TestCase):
    def test_to_integration_review_needs_all_prs_ready_and_deploy(self):
        out = rules.check_story(story("IN_PROGRESS"), "INTEGRATION_REVIEW", prs("READY", "DEV"), FIX["stories"])
        self.assertTrue(any("docs-platform#2" in m for m in out))
        self.assertTrue(any("deploy" in m for m in out))
        ok = rules.check_story(story("IN_PROGRESS", deploy={"build": "173111"}), "INTEGRATION_REVIEW",
                               prs("READY", "MERGED"), FIX["stories"])
        self.assertEqual(ok, [])
    def test_to_env_testing(self):
        out = rules.check_story(story("INTEGRATION_REVIEW"), "ENV_TESTING", prs("READY", "READY"), FIX["stories"])
        self.assertTrue(any("integration_review" in m for m in out))
    def test_to_done_requires_clean_env_test(self):
        s = story("ENV_TESTING", env_test={"report": "r", "cases": {"pass": 3, "fail": 1}, "figma_parity": "fail"})
        out = rules.check_story(s, "DONE", prs("READY", "READY"), FIX["stories"])
        self.assertTrue(any("fail" in m for m in out))
        self.assertTrue(any("figma" in m for m in out))
    def test_planned_waits_for_after_unless_reason(self):
        stories = {"S0": {"state": "IN_PROGRESS"}, "S1": story("PLANNED")}
        s = story("PLANNED"); s["after"] = ["S0"]
        self.assertTrue(rules.check_story(s, "IN_PROGRESS", {}, stories))
        self.assertEqual(rules.check_story(s, "IN_PROGRESS", {}, stories, reason="lead: run in parallel"), [])
