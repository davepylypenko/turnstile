import contextlib, io as _io, json, os, pathlib, shutil, tempfile, unittest
from turnstile_cli import pass_cmd, state
from turnstile_cli.errors import TurnstileError
from turnstile_cli.github import PrFacts

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"
H = "aaaaaaaa11111111"
H2 = "eeeeeeee55555555"
LINK = "https://pdffiller.slack.com/archives/C1/p1760000000123456"

class FakeIO:
    """GitHub facts per PR: `heads` gives the head, `facts` per-PR overrides of the canned green PrFacts."""
    def __init__(self, heads=None):
        self.commits = []; self.renders = 0; self.heads = heads or {}; self.facts = {}; self.fail_commit = False; self.fail_render = False
    def git_commit(self, delivery, message):
        if self.fail_commit:
            raise RuntimeError("gpg: signing failed")
        self.commits.append(message)
    def render_board(self, data):
        if self.fail_render:
            raise RuntimeError("template missing")
        self.renders += 1; return "<html>%s</html>" % len(self.commits)
    def github_facts(self, pr_id, org):
        h = self.heads.get(pr_id)
        if h is None:
            raise TurnstileError("gh api failed for %s: offline" % pr_id)
        f = PrFacts(id=pr_id, head=h, merged=False, merged_sha=None, draft=True, ci="success", checks={"pdf-review": "success"},
                    approvals=["isachivka"], human_threads_open=0)
        for k, v in self.facts.get(pr_id, {}).items():
            setattr(f, k, v)
        return f

def opts(**kw):
    o = pass_cmd.Options(); [setattr(o, k, v) for k, v in kw.items()]; return o

def run_capture(*a, **kw):
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = pass_cmd.run(*a, **kw)
    return rc, buf.getvalue()

READY_OPTS = dict(head=H, ci="success", deep_review="reports/R.md", rounds=2, gate="pdf-review:pass:https://r/1")

class PassCmd(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json")
        self.io = FakeIO(heads={"jsfiller#1": H, "docs-platform#2": "bbbbbbbb22222222"})
        (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok")

    def data(self):
        return json.loads((self.d / "state.json").read_text())

    def write(self, data):
        (self.d / "state.json").write_text(state.dumps(data))

    def to_ready(self, pid="jsfiller#1"):
        rc = pass_cmd.run(self.d, "pr", pid, "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 0)

    def story(self, **fields):
        data = self.data(); data["stories"]["S1"].update(fields); self.write(data)

    def sent(self, ah):
        """What the Slack PostToolUse hook records after a real send."""
        data = self.data()
        e = next(a for a in data["awaiting_human"] if a["id"] == ah); e["used_at"] = "2026-10-13T10:05Z"; e["message_ts"] = "1.2"
        self.write(data)

    def to_human(self):
        self.to_ready()
        self.story(state="DONE")
        ah = self.data()["awaiting_human"][0]["id"]
        with env(TURNSTILE_LEAD="1"):
            self.assertEqual(pass_cmd.approve(self.d, ah, self.io), 0)
        self.sent(ah)
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(head=H, slack=LINK, reviewers="isachivka", approved=ah), self.io)
        self.assertEqual(rc, 0)
        return ah

    def test_refuses_without_evidence_and_writes_nothing(self):
        before = (self.d / "state.json").read_text()
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "READY", opts(head=H), self.io)
        self.assertEqual(rc, 2)
        self.assertEqual((self.d / "state.json").read_text(), before)
        self.assertEqual(self.io.commits, [])
        self.assertFalse((self.d / "ledger.md").exists()); self.assertFalse((self.d / "board.html").exists())

    def test_ready_records_evidence_ledger_board_commit_and_awaiting(self):
        self.to_ready()
        data = self.data(); pr = data["prs"]["jsfiller#1"]
        self.assertEqual(pr["state"], "READY")
        self.assertEqual(pr["evidence"]["gate"], {"name": "pdf-review", "head": H, "result": "pass", "run": "https://r/1"})
        self.assertEqual(pr["evidence"]["head_verified"]["verified"], True)
        self.assertEqual(pr["evidence"]["head_verified"]["head"], H)
        self.assertEqual(pr["next_action"], "wait for the lead's word to send")
        ah = data["awaiting_human"][0]
        self.assertEqual((ah["type"], ah["pr"], ah["head"], ah["approved_at"]), ("send", "jsfiller#1", H, None))
        self.assertIn("READY", (self.d / "ledger.md").read_text())
        self.assertEqual((self.d / "board.html").read_text(), "<html>0</html>")
        self.assertEqual(self.io.renders, 1)
        self.assertEqual(len(self.io.commits), 1)
        self.assertTrue((self.d / ".gitattributes").read_text().startswith("ledger.md merge=union"))
        self.assertEqual((self.d / ".gitignore").read_text().splitlines(), [".*.tmp"])
        self.assertTrue((self.d / ".state.lock").exists())  # tracked, empty; init creates it, pass repairs it

    def test_ready_can_declare_companion_prs_on_the_send_entry(self):
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "READY", opts(companions="locales#5,locales#6", **READY_OPTS), self.io)
        self.assertEqual(rc, 0)
        self.assertEqual(self.data()["awaiting_human"][0]["companions"], ["locales#5", "locales#6"])

    def test_head_change_voids_old_evidence_and_open_send(self):
        self.to_ready()
        self.io.heads["jsfiller#1"] = H2
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "AI_REVIEW", opts(head=H2, ci="success"), self.io)
        self.assertEqual(rc, 0)
        self.assertTrue(self.data()["awaiting_human"][0]["voided_at"])
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "READY", opts(head=H2), self.io)
        self.assertEqual(rc, 2)  # deep_review and gate are for the old head

    def test_same_state_reentry_after_push(self):
        self.io.heads["jsfiller#1"] = H2
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "AI_REVIEW", opts(head=H2, ci="success"), self.io)
        self.assertEqual(rc, 0)
        self.assertEqual(self.data()["prs"]["jsfiller#1"]["head"], H2)

    def test_head_is_stored_lowercase_and_validated(self):
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "READY", opts(**dict(READY_OPTS, head=H.upper())), self.io)
        self.assertEqual(rc, 0)
        data = self.data()
        self.assertEqual(data["prs"]["jsfiller#1"]["head"], H)
        self.assertEqual(data["prs"]["jsfiller#1"]["evidence"]["gate"]["head"], H)
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="zzzzzzzz", ci="success"), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING --head", out)

    def test_head_is_verified_against_github(self):
        self.io.heads["jsfiller#1"] = H2
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING head %s on GitHub" % H, out); self.assertIn(H2, out)
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "AI_REVIEW", opts(ci="success"), self.io)
        self.assertEqual(rc, 2); self.assertIn("GitHub", out)  # stored head is stale, no --head given
        del self.io.heads["jsfiller#1"]
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING GitHub head for jsfiller#1", out); self.assertIn("--offline", out)
        self.assertEqual(self.io.commits, [])

    def test_offline_warns_and_blocks_ready_but_not_ai_review(self):
        del self.io.heads["jsfiller#1"]
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(offline=True, **READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("WARN", out); self.assertIn("head_verified", out)
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "AI_REVIEW", opts(offline=True, head=H2, ci="success"), self.io)
        self.assertEqual(rc, 0); self.assertIn("WARN", out)
        pr = self.data()["prs"]["jsfiller#1"]
        self.assertEqual(pr["evidence"]["head_verified"], {"head": H2, "verified": False})
        self.assertIn("offline", (self.d / "ledger.md").read_text())

    def test_jira_instruction_printed_after_commit_and_synced_flag(self):
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 0)
        lines = out.strip().splitlines()
        self.assertIn("JIRA: MYD-11 → In progress", lines)
        self.assertTrue(lines[-1].startswith("OK "))
        self.assertFalse(self.data()["prs"]["docs-platform#2"]["jira"]["synced"])
        rc = pass_cmd.jira_synced(self.d, "docs-platform#2", "On Review", self.io)
        self.assertEqual(rc, 2)  # AI_REVIEW maps to In progress, not On Review
        rc = pass_cmd.jira_synced(self.d, "docs-platform#2", "In progress", self.io)
        self.assertEqual(rc, 0)
        self.assertEqual(self.data()["prs"]["docs-platform#2"]["jira"], {"status": "In progress", "synced": True})

    def test_jira_not_printed_when_commit_fails(self):
        self.io.fail_commit = True
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 2); self.assertNotIn("JIRA:", out); self.assertIn("MISSING git commit failed", out)

    def test_commit_failure_restores_state_ledger_and_board(self):
        self.to_ready()
        before = {n: (self.d / n).read_text() for n in ("state.json", "ledger.md", "board.html")}
        self.io.fail_commit = True
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING git commit failed: gpg: signing failed", out)
        for n, text in before.items():
            self.assertEqual((self.d / n).read_text(), text, n)
        self.assertEqual(len(self.io.commits), 1)

    def test_commit_failure_on_first_pass_removes_created_files(self):
        self.io.fail_commit = True
        rc = pass_cmd.run(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 2)
        self.assertFalse((self.d / "ledger.md").exists()); self.assertFalse((self.d / "board.html").exists())
        self.assertEqual(self.data()["prs"]["docs-platform#2"]["state"], "DEV")

    def test_render_failure_writes_nothing(self):
        self.io.fail_render = True
        before = (self.d / "state.json").read_text()
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING board render failed", out)
        self.assertEqual((self.d / "state.json").read_text(), before); self.assertFalse((self.d / "ledger.md").exists())

    def test_pass_refuses_stale_file(self):
        st = state.load(self.d / "state.json")
        (self.d / "state.json").write_text(state.dumps(st.data).replace('"IN_PROGRESS"', '"PLANNED"'))
        orig = state.load
        state.load = lambda p: st
        try:
            rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "AI_REVIEW", opts(head=H, ci="success"), self.io)
        finally:
            state.load = orig
        self.assertEqual(rc, 2)

    def test_report_files_must_exist(self):
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**dict(READY_OPTS, deep_review="reports/NOPE.md")), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING report file reports/NOPE.md", out)

    def test_approve_needs_lead_env_and_sets_approved_at(self):
        self.to_ready()
        ah = self.data()["awaiting_human"][0]
        self.assertIsNone(ah["approved_at"])
        with env(TURNSTILE_LEAD=None):
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(pass_cmd.approve(self.d, ah["id"], self.io), 2)
            self.assertIn("TURNSTILE_LEAD=1", buf.getvalue())
        self.assertIsNone(self.data()["awaiting_human"][0]["approved_at"])
        with env(TURNSTILE_LEAD="1"):
            self.assertEqual(pass_cmd.approve(self.d, ah["id"], self.io), 0)
            self.assertEqual(pass_cmd.approve(self.d, "ah-999", self.io), 2)
        entry = self.data()["awaiting_human"][0]
        self.assertTrue(entry["approved_at"]); self.assertEqual(entry["approved_via"], "lead-terminal")
        line = next(l for l in (self.d / "ledger.md").read_text().splitlines() if "approved " + ah["id"] in l)
        self.assertIn("approved_via: lead-terminal", line)
        self.assertEqual(len(self.io.commits), 2)

    def test_on_human_review_requires_a_lead_approved_entry_and_consumes_it(self):
        self.to_ready(); self.story(state="DONE")
        ah = self.data()["awaiting_human"][0]["id"]
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(head=H, slack=LINK, approved="ah-NOPE"), self.io)
        self.assertEqual(rc, 2); self.assertIn("ah-NOPE", out)
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(head=H, slack=LINK, approved=ah), self.io)
        self.assertEqual(rc, 2); self.assertIn("approved_at", out)
        self.assertIsNone(self.data()["awaiting_human"][0]["approved_at"])  # pass never approves
        with env(TURNSTILE_LEAD="1"):
            pass_cmd.approve(self.d, ah, self.io)
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(head=H, slack=LINK, reviewers="isachivka", approved=ah), self.io)
        self.assertEqual(rc, 2); self.assertIn("used_at", out)  # approved but no message went through the guard
        self.sent(ah)
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(head=H, slack=LINK, reviewers="isachivka", approved=ah), self.io)
        self.assertEqual(rc, 0)
        data = self.data()
        self.assertTrue(data["awaiting_human"][0]["consumed_at"])
        self.assertEqual(data["prs"]["jsfiller#1"]["evidence"]["human"]["sent_head"], H)
        self.assertEqual(data["prs"]["jsfiller#1"]["jira"], {"status": "On Review", "synced": False})

    def test_on_human_review_requires_the_story_done_or_per_pr(self):
        self.to_ready()
        ah = self.data()["awaiting_human"][0]["id"]
        with env(TURNSTILE_LEAD="1"):
            pass_cmd.approve(self.d, ah, self.io)
        self.sent(ah)
        send = opts(head=H, slack=LINK, reviewers="isachivka", approved=ah)
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", send, self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING story S1 to be DONE (is IN_PROGRESS)", out)
        self.assertEqual(self.data()["prs"]["jsfiller#1"]["state"], "READY")
        self.story(human_review="per_pr")
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", send, self.io)
        self.assertEqual(rc, 0, out)

    def test_rework_marks_pr_voids_nothing_and_opens_reply_entry(self):
        self.to_human()
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "REWORK", opts(reason="human thread r1"), self.io)
        self.assertEqual(rc, 0)
        data = self.data(); pr = data["prs"]["jsfiller#1"]
        self.assertEqual(pr["rework_since"]["head"], H); self.assertEqual(pr["rework_since"]["reason"], "human thread r1")
        reply = [a for a in data["awaiting_human"] if a["type"] == "reply"]
        self.assertEqual(len(reply), 1); self.assertEqual(reply[0]["pr"], "jsfiller#1"); self.assertIsNone(reply[0]["approved_at"])
        # back to humans: new head, gate on it, approved reply, no new deep review
        self.io.heads["jsfiller#1"] = H2
        with env(TURNSTILE_LEAD="1"):
            pass_cmd.approve(self.d, reply[0]["id"], self.io)
        self.sent(reply[0]["id"])
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW",
                              opts(head=H2, ci="success", gate="pdf-review:pass", slack=LINK + "?thread_ts=2", approved=reply[0]["id"]), self.io)
        self.assertEqual(rc, 0, out)
        pr = self.data()["prs"]["jsfiller#1"]
        self.assertEqual(pr["evidence"]["human"]["sent_head"], H2)
        self.assertEqual(pr["evidence"]["deep_review"]["head"], H)

    def test_approved_opens_merge_entry_and_merged_logs_unblocked(self):
        self.to_human()
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "APPROVED", opts(approvals="isachivka", open_threads=0), self.io)
        self.assertEqual(rc, 0)
        self.assertEqual([a["type"] for a in self.data()["awaiting_human"]], ["send", "merge"])
        self.io.facts["jsfiller#1"] = {"merged": True, "merged_sha": "abcabcabcabcabca"}
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "MERGED", opts(merged_sha="abcabcabcabcabca"), self.io)
        self.assertEqual(rc, 0)
        self.assertIn("unblocked for sending by jsfiller#1: docs-platform#2", (self.d / "ledger.md").read_text())
        self.assertEqual(self.data()["prs"]["jsfiller#1"]["jira"]["status"], "On Hold")
        self.assertNotIn("re-evaluate the story DoD", (self.d / "ledger.md").read_text())  # docs-platform#2 is still DEV

    def test_merged_last_pr_of_a_story_notes_the_story_dod(self):
        data = self.data(); data["prs"]["docs-platform#2"]["state"] = "MERGED"; self.write(data)
        self.to_human()
        pass_cmd.run(self.d, "pr", "jsfiller#1", "APPROVED", opts(approvals="isachivka", open_threads=0), self.io)
        self.io.facts["jsfiller#1"] = {"merged": True, "merged_sha": "abcabcabcabcabca"}
        self.assertEqual(pass_cmd.run(self.d, "pr", "jsfiller#1", "MERGED", opts(merged_sha="abcabcabcabcabca"), self.io), 0)
        self.assertIn("story S1: every PR merged (docs-platform#2, jsfiller#1); re-evaluate the story DoD", (self.d / "ledger.md").read_text())

    def test_story_transition_records_deploy_and_opens_story_done_entry(self):
        data = self.data()
        for pid in ("jsfiller#1", "docs-platform#2"):
            data["prs"][pid]["state"] = "MERGED"
        self.write(data)
        rc = pass_cmd.run(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="173111", head=H), self.io)
        self.assertEqual(rc, 0)
        data = self.data()
        self.assertEqual(data["stories"]["S1"]["state"], "INTEGRATION_REVIEW")
        self.assertEqual(data["stories"]["S1"]["evidence"]["deploy"]["build"], "173111")
        self.assertEqual(data["stories"]["S1"]["evidence"]["deploy"]["head"], H)
        self.assertNotIn("_id", data["stories"]["S1"])
        (self.d / "reports" / "S.md").write_text("clean")
        rc = pass_cmd.run(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/S.md", head=H, rounds=2), self.io)
        self.assertEqual(rc, 0)
        data = self.data()
        self.assertEqual(data["stories"]["S1"]["evidence"]["integration_review"]["head"], H)
        self.assertEqual([a["type"] for a in data["awaiting_human"]], ["story_done"])
        self.assertEqual(data["awaiting_human"][0]["story"], "S1")

    def test_story_done_needs_both_case_counts_and_lead_word(self):
        data = self.data()
        for pid in ("jsfiller#1", "docs-platform#2"):
            data["prs"][pid]["state"] = "MERGED"
        data["stories"]["S1"]["state"] = "ENV_TESTING"
        data["stories"]["S1"]["evidence"] = {"deploy": {"build": "1", "head": H}, "integration_review": {"report": "r", "head": H, "clean": True}}
        data["awaiting_human"] = [{"id": "ah-7", "owner": "lead", "type": "story_done", "story": "S1", "created_at": "x", "payload": None, "approved_at": None}]
        self.write(data)
        (self.d / "reports" / "ENV.md").write_text("ok")
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(report="reports/ENV.md", figma_parity="pass", approved="ah-7"), self.io)
        self.assertEqual(rc, 2); self.assertIn("--cases-pass and --cases-fail", out)
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(report="reports/ENV.md", figma_parity="pass", cases_pass=3, cases_fail=0, approved="ah-7"), self.io)
        self.assertEqual(rc, 2); self.assertIn("story_done", out)
        with env(TURNSTILE_LEAD="1"):
            pass_cmd.approve(self.d, "ah-7", self.io)
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(report="reports/ENV.md", figma_parity="pass", cases_pass=3, cases_fail=0, approved="ah-7"), self.io)
        self.assertEqual(rc, 0, out)
        data = self.data()
        self.assertEqual(data["stories"]["S1"]["evidence"]["env_test"]["cases"], {"pass": 3, "fail": 0})
        self.assertTrue(data["awaiting_human"][0]["consumed_at"])

    def test_reopen_voids_the_open_story_done_and_done_uses_the_newest_entry(self):
        # R2-6: a story_done approval is for one test run; leaving ENV_TESTING backwards voids it, a later run opens a new one
        data = self.data()
        for pid in ("jsfiller#1", "docs-platform#2"):
            data["prs"][pid]["state"] = "MERGED"
        data["stories"]["S1"]["state"] = "ENV_TESTING"
        data["stories"]["S1"]["evidence"] = {"deploy": {"build": "1", "head": H}, "integration_review": {"report": "r", "head": H, "clean": True}}
        data["awaiting_human"] = [{"id": "ah-7", "owner": "lead", "type": "story_done", "story": "S1", "created_at": "x", "payload": None,
                                   "approved_at": "2026-10-13T10:00Z", "approved_via": "lead-terminal"}]
        self.write(data)
        (self.d / "reports" / "ENV.md").write_text("ok"); (self.d / "reports" / "S.md").write_text("clean")
        done = opts(report="reports/ENV.md", figma_parity="pass", cases_pass=3, cases_fail=0)
        rc = pass_cmd.run(self.d, "story", "S1", "IN_PROGRESS", opts(reason="bug b4 found by the lead"), self.io)
        self.assertEqual(rc, 0)
        self.assertTrue(self.data()["awaiting_human"][0]["voided_at"])
        self.assertIn("voided ah-7 (story_done for S1: story left ENV_TESTING)", (self.d / "ledger.md").read_text())
        self.assertEqual(pass_cmd.run(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="2", head=H), self.io), 0)
        self.assertEqual(pass_cmd.run(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/S.md", head=H), self.io), 0)
        ids = [(a["id"], a["type"], a.get("voided_at") is not None) for a in self.data()["awaiting_human"]]
        self.assertEqual(ids, [("ah-7", "story_done", True), ("ah-8", "story_done", False)])
        rc, out = run_capture(self.d, "story", "S1", "DONE", done, self.io)
        self.assertEqual(rc, 2); self.assertIn("ah-8", out); self.assertNotIn("ah-7", out)  # the voided one is never picked
        with env(TURNSTILE_LEAD="1"):
            pass_cmd.approve(self.d, "ah-8", self.io)
        self.assertEqual(pass_cmd.run(self.d, "story", "S1", "DONE", done, self.io), 0)
        self.assertTrue(self.data()["awaiting_human"][1]["consumed_at"])
        # second cycle: the consumed ah-8 is not reused, the newest open entry is
        self.assertEqual(pass_cmd.run(self.d, "story", "S1", "IN_PROGRESS", opts(reason="regression"), self.io), 0)
        self.assertEqual(pass_cmd.run(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="3", head=H), self.io), 0)
        self.assertEqual(pass_cmd.run(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/S.md", head=H), self.io), 0)
        rc, out = run_capture(self.d, "story", "S1", "DONE", done, self.io)
        self.assertEqual(rc, 2); self.assertIn("ah-9", out)
        with env(TURNSTILE_LEAD="1"):
            pass_cmd.approve(self.d, "ah-9", self.io)
        self.assertEqual(pass_cmd.run(self.d, "story", "S1", "DONE", done, self.io), 0)
        self.assertEqual([a["id"] for a in self.data()["awaiting_human"] if a.get("consumed_at")], ["ah-8", "ah-9"])
        # backwards to INTEGRATION_REVIEW also voids
        self.assertEqual(pass_cmd.run(self.d, "story", "S1", "IN_PROGRESS", opts(reason="again"), self.io), 0)
        self.assertEqual(pass_cmd.run(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="4", head=H), self.io), 0)
        self.assertEqual(pass_cmd.run(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/S.md", head=H), self.io), 0)
        self.assertEqual(pass_cmd.run(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(reason="review again"), self.io), 0)
        self.assertTrue(self.data()["awaiting_human"][-1]["voided_at"])

    def test_dev_clears_the_rework_marker_so_deep_review_is_required_again(self):
        # R2-7
        self.to_human()
        self.assertEqual(pass_cmd.run(self.d, "pr", "jsfiller#1", "REWORK", opts(reason="human thread r1"), self.io), 0)
        self.assertIn("rework_since", self.data()["prs"]["jsfiller#1"])
        self.assertEqual(pass_cmd.run(self.d, "pr", "jsfiller#1", "DEV", opts(reason="re-implementation after the review"), self.io), 0)
        self.assertNotIn("rework_since", self.data()["prs"]["jsfiller#1"])
        self.io.heads["jsfiller#1"] = H2
        self.assertEqual(pass_cmd.run(self.d, "pr", "jsfiller#1", "AI_REVIEW", opts(head=H2, ci="success"), self.io), 0)
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(head=H2, ci="success", gate="pdf-review:pass"), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING evidence.deep_review for current head %s" % H2, out)

    def test_start_story_entries_are_opened_for_startable_stories(self):
        data = self.data()
        data["stories"]["S2"] = dict(data["stories"]["S1"], state="PLANNED", after=[], title="Next")
        data["stories"]["S3"] = dict(data["stories"]["S1"], state="PLANNED", after=["S2"], title="Later")
        self.write(data)
        rc = pass_cmd.run(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 0)
        entries = [(a["type"], a.get("story")) for a in self.data()["awaiting_human"]]
        self.assertEqual(entries, [("start_story", "S2")])
        rc, out = run_capture(self.d, "story", "S2", "IN_PROGRESS", opts(), self.io)
        self.assertEqual(rc, 2); self.assertIn("start_story", out)
        ah = self.data()["awaiting_human"][0]["id"]
        with env(TURNSTILE_LEAD="1"):
            pass_cmd.approve(self.d, ah, self.io)
        rc = pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(approved=ah), self.io)
        self.assertEqual(rc, 0)
        self.assertTrue(self.data()["awaiting_human"][0]["consumed_at"])

    def test_send_approval_is_bound_to_the_head_it_was_given_for(self):
        self.to_ready()
        ah = self.data()["awaiting_human"][0]["id"]
        with env(TURNSTILE_LEAD="1"):
            pass_cmd.approve(self.d, ah, self.io)
        self.sent(ah)
        self.io.heads["jsfiller#1"] = H2
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(head=H2, ci="success", deep_review="reports/R.md",
                              gate="pdf-review:pass", slack=LINK, approved=ah), self.io)
        self.assertEqual(rc, 2); self.assertIn("approved for head %s" % H, out)

    def test_offline_cannot_approve_or_merge(self):
        self.to_human()
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "APPROVED", opts(offline=True, approvals="x", open_threads=0), self.io)
        self.assertEqual(rc, 2); self.assertIn("head_verified", out)

    def test_gate_and_ci_evidence_must_match_github(self):
        # R2-5: --gate/--ci are checked against the StatusContext/CheckRun and rollup state for that head
        for gate_state in ("pending", "failure", None):
            self.io.facts["jsfiller#1"] = {"checks": ({"pdf-review": gate_state} if gate_state else {})}
            rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
            self.assertEqual(rc, 2, gate_state); self.assertIn("MISSING gate pdf-review == success on GitHub for head %s (is %s)" % (H, gate_state or "absent"), out)
        self.io.facts["jsfiller#1"] = {"ci": "pending"}
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING CI success on GitHub for head %s (is pending)" % H, out)
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 0, out)
        self.io.facts["docs-platform#2"] = {"ci": "failure"}
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING CI success on GitHub", out)
        self.assertEqual(self.data()["prs"]["jsfiller#1"]["state"], "AI_REVIEW")
        self.io.facts = {}
        self.to_ready()

    def test_copilot_evidence_must_match_github(self):
        data = self.data(); data["epic"]["repos"]["jsfiller"]["copilot"] = True; self.write(data)
        self.io.facts["jsfiller#1"] = {"copilot_threads_open": 2}
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(copilot=0, **READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING Copilot threads == 0 on GitHub for head %s (has 2)" % H, out)

    def test_approvals_and_merge_must_match_github(self):
        self.to_human()
        self.io.facts["jsfiller#1"] = {"approvals": []}
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "APPROVED", opts(approvals="isachivka", open_threads=0), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING approval by isachivka in GitHub latestReviews for head %s" % H, out)
        self.io.facts["jsfiller#1"] = {"human_threads_open": 1}
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "APPROVED", opts(approvals="isachivka", open_threads=0), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING 0 unresolved human threads on GitHub (has 1)", out)
        self.io.facts["jsfiller#1"] = {"changes_requested": ["isachivka"]}
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "APPROVED", opts(approvals="isachivka", open_threads=0), self.io)
        self.assertEqual(rc, 2); self.assertIn("changes requested by isachivka", out)
        self.io.facts = {}
        self.assertEqual(pass_cmd.run(self.d, "pr", "jsfiller#1", "APPROVED", opts(approvals="isachivka", open_threads=0), self.io), 0)
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "MERGED", opts(merged_sha="abcabcabcabcabca"), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING merged on GitHub", out)
        self.io.facts["jsfiller#1"] = {"merged": True, "merged_sha": "abcabcabcabcabca0000"}
        self.assertEqual(pass_cmd.run(self.d, "pr", "jsfiller#1", "MERGED", opts(merged_sha="abcabcabcabcabca"), self.io), 0)

    def test_next_ah_id_tolerates_odd_ids(self):
        self.assertEqual(pass_cmd._next_ah_id({"awaiting_human": [{"id": "ah-x"}, {"id": "ah-4"}, {"id": "zz"}]}), "ah-5")
        self.assertEqual(pass_cmd._next_ah_id({"awaiting_human": []}), "ah-1")

@contextlib.contextmanager
def env(**kw):
    old = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
