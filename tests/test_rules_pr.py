import copy, json, pathlib, unittest
from turnstile_cli import rules

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())
H = "aaaaaaaa11111111"
H2 = "eeeeeeee55555555"

def pr_with(**ev):
    p = copy.deepcopy(FIX["prs"]["jsfiller#1"])
    p["_id"] = "jsfiller#1"
    p["evidence"].update(ev)
    return p

FULL = dict(
    ci={"head": H, "status": "success"},
    deep_review={"head": H, "report": "reports/R.md", "rounds": 2, "clean": True},
    gate={"name": "pdf-review", "head": H, "result": "pass", "run": "u"},
    head_verified={"head": H, "verified": True},
)
SEND = {"id": "ah-1", "owner": "lead", "type": "send", "pr": "jsfiller#1", "approved_at": "2026-10-13T10:00Z"}
REPLY = {"id": "ah-2", "owner": "lead", "type": "reply", "pr": "jsfiller#1", "approved_at": "2026-10-13T10:00Z"}

class Heads(unittest.TestCase):
    def test_same_head_prefix(self):
        self.assertTrue(rules.same_head("aaaaaaaa", "aaaaaaaa11111111"))
    def test_same_head_too_short(self):
        self.assertFalse(rules.same_head("aaaaaa", "aaaaaa11111111"))
    def test_different(self):
        self.assertFalse(rules.same_head("aaaaaaaa1", "aaaaaaaa2"))
    def test_same_head_uppercase(self):
        self.assertTrue(rules.same_head("AAAAAAAA1111", "aaaaaaaa11111111"))
    def test_valid_head(self):
        self.assertTrue(rules.valid_head("aaaaaaaa"))
        self.assertTrue(rules.valid_head("a" * 40))
        self.assertFalse(rules.valid_head("zzzzzzzz"))
        self.assertFalse(rules.valid_head("aaaaaaa"))
        self.assertFalse(rules.valid_head("a" * 41))

class ToReady(unittest.TestCase):
    repo = FIX["epic"]["repos"]["jsfiller"]
    def test_ok(self):
        self.assertEqual(rules.check_pr(pr_with(**FULL), "READY", self.repo, FIX["prs"]), [])
    def test_missing_gate(self):
        ev = dict(FULL); del ev["gate"]
        out = rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])
        self.assertTrue(any("gate" in m for m in out))
    def test_gate_fail_and_name_mismatch(self):
        ev = dict(FULL); ev["gate"] = dict(FULL["gate"], result="fail")
        self.assertTrue(any("gate.result" in m for m in rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])))
        ev["gate"] = dict(FULL["gate"], name="crit-review")
        self.assertTrue(any("gate.name" in m for m in rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])))
    def test_ci_failure_and_deep_review_not_clean(self):
        ev = dict(FULL); ev["ci"] = {"head": H, "status": "failure"}
        self.assertTrue(any("ci.status" in m for m in rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])))
        ev = dict(FULL); ev["deep_review"] = dict(FULL["deep_review"], clean=False)
        self.assertTrue(any("deep_review.clean" in m for m in rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])))
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
    def test_head_must_be_verified_against_github(self):
        ev = dict(FULL); del ev["head_verified"]
        out = rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])
        self.assertTrue(any("head_verified" in m for m in out), out)
        ev["head_verified"] = {"head": H, "verified": False}
        out = rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])
        self.assertTrue(any("head_verified" in m for m in out), out)
        ev["head_verified"] = {"head": H2, "verified": True}
        out = rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])
        self.assertTrue(any("head_verified" in m for m in out), out)

class ToAiReview(unittest.TestCase):
    repo = FIX["epic"]["repos"]["jsfiller"]
    def test_same_state_reentry_with_new_head(self):
        p = pr_with(ci={"head": H2, "status": "success"}); p["head"] = H2
        self.assertEqual(rules.check_pr(p, "AI_REVIEW", self.repo, FIX["prs"]), [])
    def test_not_from_on_human_review(self):
        p = pr_with(**FULL); p["state"] = "ON_HUMAN_REVIEW"
        self.assertTrue(any("allowed transition" in m for m in rules.check_pr(p, "AI_REVIEW", self.repo, FIX["prs"])))
    def test_to_dev_needs_reason(self):
        p = pr_with(**FULL)
        self.assertTrue(any("--reason" in m for m in rules.check_pr(p, "DEV", self.repo, FIX["prs"])))
        self.assertEqual(rules.check_pr(p, "DEV", self.repo, FIX["prs"], reason="scope changed"), [])

class ToHuman(unittest.TestCase):
    repo = FIX["epic"]["repos"]["jsfiller"]
    def ready(self):
        p = pr_with(**FULL); p["state"] = "READY"; return p
    def human(self, approved="ah-1"):
        return {"head": H, "slack_permalink": "https://x", "sent_head": H, "approved": approved, "open_threads": 0, "approvals": []}
    def test_needs_permalink_and_approval(self):
        out = rules.check_pr(self.ready(), "ON_HUMAN_REVIEW", self.repo, FIX["prs"], awaiting=[SEND])
        self.assertTrue(any("slack_permalink" in m for m in out))
        self.assertTrue(any("approved" in m for m in out))
    def test_approved_entry_must_exist_match_and_be_approved(self):
        p = self.ready(); p["evidence"]["human"] = self.human("ah-NOPE")
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", self.repo, FIX["prs"], awaiting=[SEND])
        self.assertTrue(any("ah-NOPE" in m for m in out), out)
        p["evidence"]["human"] = self.human("ah-1")
        self.assertEqual(rules.check_pr(p, "ON_HUMAN_REVIEW", self.repo, FIX["prs"], awaiting=[SEND]), [])
        unapproved = dict(SEND, approved_at=None)
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", self.repo, FIX["prs"], awaiting=[unapproved])
        self.assertTrue(any("approved_at" in m for m in out), out)
        other_pr = dict(SEND, pr="docs-platform#2")
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", self.repo, FIX["prs"], awaiting=[other_pr])
        self.assertTrue(any("ah-1" in m for m in out), out)
        wrong_type = dict(SEND, type="merge")
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", self.repo, FIX["prs"], awaiting=[wrong_type])
        self.assertTrue(any("type send" in m for m in out), out)
        consumed = dict(SEND, consumed_at="x")
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", self.repo, FIX["prs"], awaiting=[consumed])
        self.assertTrue(any("consumed" in m for m in out), out)
        voided = dict(SEND, voided_at="x")
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", self.repo, FIX["prs"], awaiting=[voided])
        self.assertTrue(any("voided" in m for m in out), out)
    def test_blocked_by_unmerged(self):
        p = self.ready(); p["blocked_by"] = "docs-platform#2"; p["evidence"]["human"] = self.human()
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", self.repo, FIX["prs"], awaiting=[SEND])
        self.assertTrue(any("blocked_by" in m for m in out))
    def test_push_after_send_voids(self):
        p = self.ready(); p["state"] = "ON_HUMAN_REVIEW"; p["head"] = "dddddddd44444444"; p["evidence"]["human"] = self.human()
        out = rules.check_pr(p, "APPROVED", self.repo, FIX["prs"])
        self.assertTrue(any("sent_head" in m for m in out))
        self.assertEqual(rules.check_pr(p, "REWORK", self.repo, FIX["prs"], reason="push after send"), [])
        self.assertTrue(any("--reason" in m for m in rules.check_pr(p, "REWORK", self.repo, FIX["prs"])))
    def test_rework_back_needs_gate_copilot_reply_but_no_new_deep_review(self):
        repo_cp = dict(self.repo, copilot=True)
        p = self.ready(); p["state"] = "REWORK"; p["head"] = H2
        p["rework_since"] = {"head": H, "at": "2026-10-13T10:00Z", "reason": "human thread"}
        p["evidence"].update(ci={"head": H2, "status": "success"}, gate={"name": "pdf-review", "head": H2, "result": "pass"},
                             copilot={"head": H2, "open_threads": 0}, head_verified={"head": H2, "verified": True},
                             human={"head": H2, "slack_permalink": "https://x", "sent_head": H2, "approved": "ah-2"})
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", repo_cp, FIX["prs"], awaiting=[REPLY])
        self.assertEqual(out, [])  # deep_review is still for H, not required after human review
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", repo_cp, FIX["prs"], awaiting=[dict(SEND, id="ah-2")])
        self.assertTrue(any("type reply" in m for m in out), out)
        p["evidence"]["gate"]["head"] = H
        self.assertTrue(any("gate" in m for m in rules.check_pr(p, "ON_HUMAN_REVIEW", repo_cp, FIX["prs"], awaiting=[REPLY])))
    def test_without_rework_marker_deep_review_is_required(self):
        p = self.ready(); p["state"] = "REWORK"; p["head"] = H2
        p["evidence"].update(ci={"head": H2, "status": "success"}, gate={"name": "pdf-review", "head": H2, "result": "pass"},
                             head_verified={"head": H2, "verified": True},
                             human={"head": H2, "slack_permalink": "https://x", "sent_head": H2, "approved": "ah-2"})
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", self.repo, FIX["prs"], awaiting=[REPLY])
        self.assertTrue(any("deep_review" in m for m in out), out)

class ToApprovedAndMerged(unittest.TestCase):
    repo = FIX["epic"]["repos"]["jsfiller"]
    def sent(self):
        p = pr_with(**FULL); p["state"] = "ON_HUMAN_REVIEW"
        p["evidence"]["human"] = {"head": H, "slack_permalink": "https://x", "sent_head": H, "approved": "ah-1", "open_threads": 0, "approvals": ["isachivka"]}
        return p
    def test_approved_ok(self):
        self.assertEqual(rules.check_pr(self.sent(), "APPROVED", self.repo, FIX["prs"]), [])
    def test_approved_needs_approvals_and_no_threads(self):
        p = self.sent(); p["evidence"]["human"]["approvals"] = []
        self.assertTrue(any("approvals" in m for m in rules.check_pr(p, "APPROVED", self.repo, FIX["prs"])))
        p = self.sent(); p["evidence"]["human"]["open_threads"] = 2
        self.assertTrue(any("open_threads" in m for m in rules.check_pr(p, "APPROVED", self.repo, FIX["prs"])))
    def test_merged_only_from_approved_with_sha(self):
        p = self.sent()
        self.assertTrue(any("allowed transition" in m for m in rules.check_pr(p, "MERGED", self.repo, FIX["prs"])))
        p["state"] = "APPROVED"
        self.assertTrue(any("merged_sha" in m for m in rules.check_pr(p, "MERGED", self.repo, FIX["prs"])))
        p["merged_sha"] = "abcabcabcabcabca"
        self.assertEqual(rules.check_pr(p, "MERGED", self.repo, FIX["prs"]), [])

class NextAction(unittest.TestCase):
    def test_strings(self):
        repo = FIX["epic"]["repos"]["jsfiller"]
        p = pr_with(); self.assertIn("deep review", rules.next_action_pr(p, repo))
        p = pr_with(**FULL); p["state"] = "READY"; self.assertIn("lead", rules.next_action_pr(p, repo))
