import copy, json, pathlib, unittest
from turnstile_cli import rules

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())
H = "aaaaaaaa11111111"
H_TOP = "bbbbbbbb22222222"  # docs-platform#2's head: the stack top once it is based on jsfiller#1 (finding 4: the deploy must be the top)

def story(head=H, **over):
    s = copy.deepcopy(FIX["stories"]["S1"]); s["_id"] = "S1"; s["state"] = "IN_PROGRESS"
    s["evidence"] = {"deploy": {"build": "1", "head": head}}; s.update(over); return s

def prs(**over):
    out = copy.deepcopy(FIX["prs"])
    for pid in out: out[pid]["state"] = "READY"
    for pid, fields in over.items(): out[pid].update(fields)
    return out

class StoryBranch(unittest.TestCase):
    def check(self, s, p):
        return rules.check_story(s, "INTEGRATION_REVIEW", p, FIX["stories"])
    def test_prs_on_the_story_branch_pass(self):
        self.assertEqual(self.check(story(), prs()), [])
    def test_stacked_pr_passes(self):
        self.assertEqual(self.check(story(head=H_TOP), prs(**{"docs-platform#2": {"base": "feature/MYD-10"}})), [])
        self.assertTrue(any("stack top" in m for m in self.check(story(), prs(**{"docs-platform#2": {"base": "feature/MYD-10"}}))))
    def test_pr_based_elsewhere_is_refused_unless_merged(self):
        out = self.check(story(head=H_TOP, branch="story/s1"), prs(**{"jsfiller#1": {"base": "epic_myd-1"}, "docs-platform#2": {"base": "feature/MYD-10"}}))
        self.assertEqual([m for m in out if "jsfiller#1" in m], ["MISSING PR jsfiller#1 based on the story branch story/s1 or on another PR of the story (base is epic_myd-1)"])
        self.assertEqual([m for m in out if "docs-platform#2" in m], [])
        self.assertEqual(self.check(story(head=H_TOP, branch="story/s1"), prs(**{"jsfiller#1": {"base": "epic_myd-1", "state": "MERGED"}, "docs-platform#2": {"base": "feature/MYD-10"}})), [])
    def test_two_prs_on_the_epic_branch_do_not_vouch_for_each_other(self):
        out = self.check(story(branch="story/s1"), prs(**{"jsfiller#1": {"base": "epic_myd-1"}, "docs-platform#2": {"base": "epic_myd-1"}}))
        self.assertEqual(len([m for m in out if "based on the story branch" in m]), 2)
    def test_missing_story_branch_fails_closed(self):
        s = story(); del s["branch"]
        self.assertTrue(any("stories.S1.branch" in m for m in self.check(s, prs())))
