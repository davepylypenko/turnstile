import json, pathlib, shutil, tempfile, unittest
from turnstile_cli import pass_cmd, state

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"
H = "aaaaaaaa11111111"

class FakeIO:
    def __init__(self):
        self.commits = []; self.renders = 0
    def git_commit(self, delivery, message): self.commits.append(message)
    def renderer(self, data, delivery): self.renders += 1

def opts(**kw):
    o = pass_cmd.Options(); [setattr(o, k, v) for k, v in kw.items()]; return o

class PassCmd(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); self.io = FakeIO()
        (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok")

    def test_refuses_without_evidence_and_writes_nothing(self):
        before = (self.d / "state.json").read_text()
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "READY", opts(head=H), self.io)
        self.assertEqual(rc, 2)
        self.assertEqual((self.d / "state.json").read_text(), before)
        self.assertEqual(self.io.commits, [])

    def test_ready_records_evidence_ledger_board_commit_and_awaiting(self):
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "READY",
                          opts(head=H, ci="success", deep_review="reports/R.md", rounds=2, gate="pdf-review:pass:u"), self.io)
        self.assertEqual(rc, 0)
        data = json.loads((self.d / "state.json").read_text())
        pr = data["prs"]["jsfiller#1"]
        self.assertEqual(pr["state"], "READY")
        self.assertEqual(pr["evidence"]["gate"], {"name": "pdf-review", "head": H, "result": "pass", "run": "u"})
        self.assertEqual(pr["next_action"], "wait for the lead's word to send")
        self.assertEqual(data["awaiting_human"][0]["type"], "send")
        self.assertIn("READY", (self.d / "ledger.md").read_text())
        self.assertEqual(self.io.renders, 1)
        self.assertEqual(len(self.io.commits), 1)

    def test_head_change_voids_old_evidence(self):
        pass_cmd.run(self.d, "pr", "jsfiller#1", "READY",
                     opts(head=H, ci="success", deep_review="reports/R.md", rounds=1, gate="pdf-review:pass"), self.io)
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "AI_REVIEW", opts(head="eeeeeeee55555555", ci="success"), self.io)
        self.assertEqual(rc, 0)
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "READY", opts(head="eeeeeeee55555555"), self.io)
        self.assertEqual(rc, 2)  # deep_review and gate are for the old head

    def test_jira_instruction_printed_and_synced_flag(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pass_cmd.run(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertIn("JIRA: MYD-11 → In progress", buf.getvalue())
        data = json.loads((self.d / "state.json").read_text())
        self.assertFalse(data["prs"]["docs-platform#2"]["jira"]["synced"])
        rc = pass_cmd.jira_synced(self.d, "docs-platform#2", "In progress", self.io)
        self.assertEqual(rc, 0)
        data = json.loads((self.d / "state.json").read_text())
        self.assertEqual(data["prs"]["docs-platform#2"]["jira"], {"status": "In progress", "synced": True})

    def test_pass_refuses_stale_file(self):
        st = state.load(self.d / "state.json")
        (self.d / "state.json").write_text(state.dumps(st.data).replace('"IN_PROGRESS"', '"PLANNED"'))
        # simulate a concurrent edit between load and save inside run(): monkeypatch state.load to return the old object
        orig = state.load
        state.load = lambda p: st
        try:
            rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "AI_REVIEW", opts(head=H, ci="success"), self.io)
        finally:
            state.load = orig
        self.assertEqual(rc, 2)

    def test_story_transition(self):
        for pid, st_ in (("jsfiller#1", "MERGED"), ("docs-platform#2", "MERGED")):
            data = json.loads((self.d / "state.json").read_text()); data["prs"][pid]["state"] = st_
            (self.d / "state.json").write_text(state.dumps(data))
        rc = pass_cmd.run(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="173111"), self.io)
        self.assertEqual(rc, 0)
        data = json.loads((self.d / "state.json").read_text())
        self.assertEqual(data["stories"]["S1"]["state"], "INTEGRATION_REVIEW")
        self.assertEqual(data["stories"]["S1"]["evidence"]["deploy"]["build"], "173111")
        self.assertNotIn("_id", data["stories"]["S1"])

    def test_approve_sets_approved_at(self):
        pass_cmd.run(self.d, "pr", "jsfiller#1", "READY",
                     opts(head=H, ci="success", deep_review="reports/R.md", rounds=1, gate="pdf-review:pass"), self.io)
        data = json.loads((self.d / "state.json").read_text())
        ah = data["awaiting_human"][0]
        self.assertIsNone(ah["approved_at"])
        rc = pass_cmd.approve(self.d, ah["id"], self.io)
        self.assertEqual(rc, 0)
        data = json.loads((self.d / "state.json").read_text())
        self.assertTrue(data["awaiting_human"][0]["approved_at"])
        self.assertIn("approved " + ah["id"], (self.d / "ledger.md").read_text())
        self.assertEqual(len(self.io.commits), 2)
        self.assertEqual(pass_cmd.approve(self.d, "ah-999", self.io), 2)
