import copy, json, pathlib, unittest
from turnstile_cli import rules

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())
H = "aaaaaaaa11111111"

def pr_with(**ev):
    p = copy.deepcopy(FIX["prs"]["jsfiller#1"])
    p["evidence"].update(ev)
    return p

FULL = dict(
    ci={"head": H, "status": "success"},
    deep_review={"head": H, "report": "reports/R.md", "rounds": 2, "clean": True},
    gate={"name": "pdf-review", "head": H, "result": "pass", "run": "u"},
)

class Heads(unittest.TestCase):
    def test_same_head_prefix(self):
        self.assertTrue(rules.same_head("aaaaaaaa", "aaaaaaaa11111111"))
    def test_same_head_too_short(self):
        self.assertFalse(rules.same_head("aaaaaa", "aaaaaa11111111"))
    def test_different(self):
        self.assertFalse(rules.same_head("aaaaaaaa1", "aaaaaaaa2"))

class ToReady(unittest.TestCase):
    repo = FIX["epic"]["repos"]["jsfiller"]
    def test_ok(self):
        self.assertEqual(rules.check_pr(pr_with(**FULL), "READY", self.repo, FIX["prs"]), [])
    def test_missing_gate(self):
        ev = dict(FULL); del ev["gate"]
        out = rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])
        self.assertTrue(any("gate" in m for m in out))
    def test_stale_deep_review_head(self):
        ev = dict(FULL); ev["deep_review"] = dict(FULL["deep_review"], head="cccccccc33333333")
        out = rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])
        self.assertTrue(any("deep_review" in m and "head" in m for m in out))
    def test_copilot_required_only_when_enabled(self):
        repo_cp = dict(self.repo, copilot=True)
        self.assertTrue(any("copilot" in m for m in rules.check_pr(pr_with(**FULL), "READY", repo_cp, FIX["prs"])))
        ok = rules.check_pr(pr_with(copilot={"head": H, "open_threads": 0}, **FULL), "READY", repo_cp, FIX["prs"])
        self.assertEqual(ok, [])
    def test_wrong_source_state(self):
        p = pr_with(**FULL); p["state"] = "DEV"
        self.assertTrue(any("from DEV" in m for m in rules.check_pr(p, "READY", self.repo, FIX["prs"])))

class ToHuman(unittest.TestCase):
    repo = FIX["epic"]["repos"]["jsfiller"]
    def ready(self):
        p = pr_with(**FULL); p["state"] = "READY"; return p
    def test_needs_permalink_and_approval(self):
        out = rules.check_pr(self.ready(), "ON_HUMAN_REVIEW", self.repo, FIX["prs"])
        self.assertTrue(any("slack_permalink" in m for m in out))
        self.assertTrue(any("approved" in m for m in out))
    def test_blocked_by_unmerged(self):
        p = self.ready(); p["blocked_by"] = "docs-platform#2"
        p["evidence"]["human"] = {"head": H, "slack_permalink": "u", "sent_head": H, "approved": "ah-1"}
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", self.repo, FIX["prs"])
        self.assertTrue(any("blocked_by" in m for m in out))
    def test_push_after_send_voids(self):
        p = self.ready(); p["state"] = "ON_HUMAN_REVIEW"; p["head"] = "dddddddd44444444"
        p["evidence"]["human"] = {"head": H, "slack_permalink": "u", "sent_head": H, "approved": "ah-1"}
        out = rules.check_pr(p, "APPROVED", self.repo, FIX["prs"])
        self.assertTrue(any("sent_head" in m for m in out))
        self.assertEqual(rules.check_pr(p, "REWORK", self.repo, FIX["prs"], reason="push after send"), [])

class NextAction(unittest.TestCase):
    def test_strings(self):
        repo = FIX["epic"]["repos"]["jsfiller"]
        p = pr_with(); self.assertIn("deep review", rules.next_action_pr(p, repo))
        p = pr_with(**FULL); p["state"] = "READY"; self.assertIn("lead", rules.next_action_pr(p, repo))
