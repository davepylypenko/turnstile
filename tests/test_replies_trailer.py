import copy, json, pathlib, shutil, tempfile, unittest
from turnstile_cli import github, pass_cmd, state
from tests.test_pass import FakeIO, opts, run_capture, env, H, LINK, READY_OPTS

D = pathlib.Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((D / "gh_pr_13222.json").read_text())
SINCE = "2026-10-13T10:00Z"
def thread(tid, opened, replies=(), human_login="lMakDen"):
    return {"id": tid, "resolved": False, "human": True, "opened_at": opened, "replies": [{"login": l, "at": a} for l, a in replies]}

class Parse(unittest.TestCase):
    def test_threads_trailer_body(self):
        f = github.parse("jsfiller#1", PAYLOAD)
        self.assertEqual(len(f.threads), 4); self.assertEqual(f.threads[0]["id"], "PRRT_1"); self.assertTrue(f.threads[0]["human"]); self.assertFalse(f.threads[1]["human"])
        self.assertEqual(f.threads[0]["opened_at"], "2026-10-12T09:00:00Z"); self.assertEqual(f.threads[0]["replies"], [])
        self.assertEqual(f.trailered, []); self.assertFalse(f.body_footer)
        p = copy.deepcopy(PAYLOAD); p["allCommits"]["nodes"][0]["commit"]["message"] = "x\n\nCo-Authored-By: a"; p["body"] += "\n\n🤖 Generated with [Claude Code](https://x)"
        f = github.parse("jsfiller#1", p); self.assertEqual(len(f.trailered), 1); self.assertTrue(f.body_footer)
    def test_ts(self):
        self.assertLess(github.ts("2026-10-13T10:00Z"), github.ts("2026-10-13T10:00:30Z")); self.assertIsNone(github.ts("nope"))

class Rework(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(D / "state_min.json", self.d / "state.json"); (self.d / ".state.lock").touch()
        (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok")
        self.io = FakeIO(heads={"jsfiller#1": H})
        # a PR on human review that went to REWORK at SINCE with one human thread opened before it
        data = json.loads((self.d / "state.json").read_text()); pr = data["prs"]["jsfiller#1"]
        pr["state"] = "REWORK"; pr["rework_since"] = {"head": H, "at": SINCE, "reason": "human thread PRRT_1"}
        pr["evidence"].update({"head_verified": {"head": H, "verified": True}, "deep_review": {"head": H, "report": "reports/R.md", "rounds": 1, "clean": True},
                               "gate": {"name": "pdf-review", "head": H, "result": "pass"}, "human": {"head": H, "sent_head": H, "slack_permalink": LINK, "approved": "ah-1", "open_threads": 1, "approvals": []}})
        data["stories"]["S1"]["state"] = "DONE"
        data["awaiting_human"] = [{"id": "ah-2", "owner": "lead", "type": "reply", "pr": "jsfiller#1", "head": H, "created_at": SINCE, "payload": None,
                                   "approved_at": "2026-10-13T10:30Z", "approved_via": "lead-terminal", "used_at": "2026-10-13T10:40Z", "message_ts": "1.2"}]
        (self.d / "state.json").write_text(state.dumps(data))
    def go(self):
        return run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(head=H, ci="success", gate="pdf-review:pass", slack=LINK, approved="ah-2"), self.io)
    def test_rework_needs_lead_replies(self):
        self.io.facts["jsfiller#1"] = {"threads": [thread("PRRT_1", "2026-10-13T09:00:00Z")]}
        rc, out = self.go(); self.assertEqual(rc, 2); self.assertIn("reply by the lead (leadlogin)", out); self.assertIn("PRRT_1", out)
        self.io.facts["jsfiller#1"] = {"threads": [thread("PRRT_1", "2026-10-13T09:00:00Z", [("someoneelse", "2026-10-13T11:00:00Z")])]}
        self.assertEqual(self.go()[0], 2)
        self.io.facts["jsfiller#1"] = {"threads": [thread("PRRT_1", "2026-10-13T09:00:00Z", [("leadlogin", "2026-10-13T09:30:00Z")])]}
        self.assertEqual(self.go()[0], 2)  # the lead's reply predates the rework
        self.io.facts["jsfiller#1"] = {"threads": [thread("PRRT_1", "2026-10-13T09:00:00Z", [("leadlogin", "2026-10-13T11:00:00Z")]),
                                                   thread("PRRT_9", "2026-10-13T12:00:00Z")]}  # opened after the rework: not required
        rc, out = self.go(); self.assertEqual(rc, 0, out)
    def test_lead_login_required_when_threads_exist(self):
        data = json.loads((self.d / "state.json").read_text()); data["epic"]["roles"]["lead_github"] = None; (self.d / "state.json").write_text(state.dumps(data))
        self.io.facts["jsfiller#1"] = {"threads": [thread("PRRT_1", "2026-10-13T09:00:00Z")]}
        rc, out = self.go(); self.assertEqual(rc, 2); self.assertIn("lead_github", out)
    def test_bot_threads_ignored(self):
        t = thread("PRRT_2", "2026-10-13T09:00:00Z"); t["human"] = False
        self.io.facts["jsfiller#1"] = {"threads": [t]}
        self.assertEqual(self.go()[0], 0)

class Trailer(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(D / "state_min.json", self.d / "state.json"); (self.d / ".state.lock").touch()
        (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok"); self.io = FakeIO(heads={"jsfiller#1": H})
    def test_trailer_and_footer_refused(self):
        self.io.facts["jsfiller#1"] = {"trailered": ["abc12345"]}
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("Co-Authored-By", out); self.assertIn("abc12345", out)
        self.io.facts["jsfiller#1"] = {"body_footer": True}
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("generated-with footer", out)
