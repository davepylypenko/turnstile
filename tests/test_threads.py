"""2026-10-14 rule: a reviewer thread the agent resolved itself gets the agent's reply at once; only threads that need the lead's
decision wait for a lead-approved `reply` entry of their own. Classification comes from GitHub facts (`turnstile threads`)."""
import contextlib, copy, io as _io, json, pathlib, shutil, tempfile, unittest
from turnstile_cli import github, pass_cmd, state, threads
from tests.test_pass import FakeIO, opts, run_capture, env, H, H2

D = pathlib.Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((D / "gh_pr_13222.json").read_text())
SENT = "2026-10-13T10:00Z"
SEND = {"id": "ah-1", "owner": "lead", "type": "send", "pr": "jsfiller#1", "head": H, "created_at": "2026-10-13T09:00Z", "payload": None,
        "approved_at": "2026-10-13T09:30Z", "approved_via": "lead-terminal", "used_at": SENT, "message_ts": "1.2", "consumed_at": "2026-10-13T10:01Z"}
ROLES = {"lead": "lead@example.com", "lead_github": "leadlogin", "agent_github": "agentlogin"}

def cm(login, at, cid, bot=False):
    return {"id": str(cid), "login": login, "at": at, "bot": bot}

def th(tid, *comments, resolved=False, human=True):
    first = comments[0]
    return {"id": tid, "resolved": resolved, "human": human, "opened_at": first["at"], "author": first["login"], "comment_id": first["id"],
            "comment_ids": [c["id"] for c in comments], "comments": list(comments), "truncated": False,
            "replies": [{"login": c["login"], "at": c["at"]} for c in comments[1:]]}

def rework_pr():
    return {"_id": "jsfiller#1", "state": "REWORK", "head": H2, "rework_since": {"head": H, "at": "2026-10-13T12:00Z", "reason": "human thread"},
            "evidence": {"human": {"head": H, "sent_head": H, "sent_at": "2026-10-13T10:02Z", "approved": "ah-1", "slack_permalink": "https://x.slack.com/archives/C1/p1"}},
            "threads": {}}

def classified(cls, last, cid="101"):
    return {"class": cls, "classified_at": "2026-10-13T13:00:00Z", "comment_id": cid, "comment_ids": [cid], "reviewer": "isachivka", "last_reviewer_at": last}

class Parse(unittest.TestCase):
    def test_threads_carry_rest_comment_ids_authors_and_bot_flags(self):
        p = copy.deepcopy(PAYLOAD)
        p["reviewThreads"]["nodes"][0]["comments"] = {"totalCount": 3, "nodes": [
            {"databaseId": 101, "author": {"__typename": "User", "login": "lMakDen"}, "createdAt": "2026-10-12T09:00:00Z"},
            {"databaseId": 102, "author": {"__typename": "User", "login": "leadlogin"}, "createdAt": "2026-10-12T10:00:00Z"},
            {"databaseId": 103, "author": {"__typename": "Bot", "login": "github-actions"}, "createdAt": "2026-10-12T11:00:00Z"}]}
        t = github.parse("jsfiller#1", p).threads[0]
        self.assertEqual((t["id"], t["author"], t["comment_id"], t["comment_ids"]), ("PRRT_1", "lMakDen", "101", ["101", "102", "103"]))
        self.assertEqual([c["bot"] for c in t["comments"]], [False, False, True]); self.assertFalse(t["truncated"])
        self.assertEqual(t["replies"], [{"login": "leadlogin", "at": "2026-10-12T10:00:00Z"}, {"login": "github-actions", "at": "2026-10-12T11:00:00Z"}])
        p["reviewThreads"]["nodes"][0]["comments"]["totalCount"] = 150
        self.assertTrue(github.parse("jsfiller#1", p).threads[0]["truncated"])
    def test_query_asks_for_comment_database_ids(self):
        self.assertIn("databaseId", github.QUERY); self.assertIn("comments(first:100){totalCount", github.QUERY.replace(" ", ""))

class RepliesMissing(unittest.TestCase):
    def setUp(self):
        self.pr = rework_pr(); self.awaiting = [copy.deepcopy(SEND)]
    def miss(self, ts, roles=ROLES):
        return threads.replies_missing(self.pr, "jsfiller#1", ts, roles, self.awaiting, "pdffiller")
    REVIEW = cm("isachivka", "2026-10-13T11:00:00Z", 101)

    def test_unclassified_thread_since_the_send_is_missing(self):
        out = self.miss([th("PRRT_a", self.REVIEW)])
        self.assertEqual(len(out), 1); self.assertIn("PRRT_a", out[0]); self.assertIn("turnstile threads jsfiller#1", out[0])
    def test_self_resolved_needs_the_agents_reply_after_the_last_reviewer_comment(self):
        self.pr["threads"]["PRRT_a"] = classified("self_resolved", "2026-10-13T11:00:00Z")
        out = self.miss([th("PRRT_a", self.REVIEW)])
        self.assertTrue(out and "agentlogin" in out[0] and "repos/pdffiller/jsfiller/pulls/1/comments/101/replies" in out[0], out)
        self.assertTrue(self.miss([th("PRRT_a", self.REVIEW, cm("someoneelse", "2026-10-13T12:00:00Z", 102))]))
        self.assertTrue(self.miss([th("PRRT_a", cm("agentlogin", "2026-10-13T10:30:00Z", 100), self.REVIEW)]))  # ours predates the comment
        self.assertEqual(self.miss([th("PRRT_a", self.REVIEW, cm("agentlogin", "2026-10-13T11:05:00Z", 102))]), [])
    def test_a_reviewer_follow_up_after_the_classification_needs_a_new_classification(self):
        self.pr["threads"]["PRRT_a"] = classified("self_resolved", "2026-10-13T11:00:00Z")
        t = th("PRRT_a", self.REVIEW, cm("agentlogin", "2026-10-13T11:05:00Z", 102), cm("isachivka", "2026-10-13T11:20:00Z", 103))
        out = self.miss([t]); self.assertEqual(len(out), 1); self.assertIn("re-classif", out[0]); self.assertIn("2026-10-13T11:20:00Z", out[0])
        self.pr["threads"]["PRRT_a"] = classified("self_resolved", "2026-10-13T11:20:00Z")
        self.assertTrue(self.miss([t]))  # classified again, but the agent's reply is older than the follow-up
        t["comments"].append(cm("agentlogin", "2026-10-13T11:30:00Z", 104)); self.assertEqual(self.miss([t]), [])
    def test_needs_lead_waits_for_an_approved_reply_entry_and_a_reply_after_it(self):
        self.pr["threads"]["PRRT_b"] = classified("needs_lead", "2026-10-13T11:00:00Z")
        entry = {"id": "ah-4", "owner": "lead", "type": "reply", "pr": "jsfiller#1", "thread": "PRRT_b", "last_reviewer_at": "2026-10-13T11:00:00Z",
                 "created_at": "2026-10-13T13:00Z", "payload": None, "approved_at": None}
        self.awaiting.append(entry)
        replied = th("PRRT_b", self.REVIEW, cm("agentlogin", "2026-10-13T13:30:00Z", 102))
        out = self.miss([replied]); self.assertTrue(out and "ah-4" in out[0] and "TURNSTILE_LEAD=1 turnstile approve ah-4" in out[0], out)
        entry["approved_at"] = "2026-10-13T14:00Z"
        out = self.miss([replied]); self.assertTrue(out and "after" in out[0], out)  # the reply went out before the lead's word
        self.assertEqual(self.miss([th("PRRT_b", self.REVIEW, cm("agentlogin", "2026-10-13T14:00:20Z", 102))]), [])
        entry["voided_at"] = "2026-10-13T14:10Z"
        self.assertTrue(self.miss([th("PRRT_b", self.REVIEW, cm("agentlogin", "2026-10-13T14:00:20Z", 102))]))
    def test_the_lead_replying_in_person_settles_a_needs_lead_thread(self):
        self.pr["threads"]["PRRT_b"] = classified("needs_lead", "2026-10-13T11:00:00Z")
        self.assertEqual(self.miss([th("PRRT_b", self.REVIEW, cm("leadlogin", "2026-10-13T12:00:00Z", 102))]), [])
        same = dict(ROLES, agent_github="leadlogin")  # one account for the lead and the agents: the entry is the only proof of the lead's word
        self.assertTrue(self.miss([th("PRRT_b", self.REVIEW, cm("leadlogin", "2026-10-13T12:00:00Z", 102))], roles=same))
    def test_scope_is_every_thread_since_the_send_and_every_unresolved_one(self):
        old_resolved = th("PRRT_o", cm("isachivka", "2026-10-12T09:00:00Z", 90), resolved=True)
        old_open = th("PRRT_u", cm("isachivka", "2026-10-12T09:00:00Z", 91))
        new_resolved = th("PRRT_n", cm("isachivka", "2026-10-13T10:00:30Z", 92), resolved=True)  # same minute as the send counts
        out = self.miss([old_resolved, old_open, new_resolved])
        self.assertEqual(sorted(m.split("thread ")[1].split(" ")[0] for m in out), ["PRRT_n", "PRRT_u"])
    def test_bot_threads_and_threads_without_a_reviewer_comment_are_ignored(self):
        bot = th("PRRT_c", cm("copilot-pull-request-reviewer", "2026-10-13T11:00:00Z", 1, bot=True), human=False)
        ours = th("PRRT_d", cm("leadlogin", "2026-10-13T11:00:00Z", 2), cm("agentlogin", "2026-10-13T11:10:00Z", 3))
        self.assertEqual(self.miss([bot, ours]), [])
    def test_fails_closed_without_logins_send_time_or_complete_comments(self):
        t = th("PRRT_a", self.REVIEW)
        self.assertTrue(any("agent_github" in m for m in self.miss([t], roles={"lead_github": None})))
        self.pr["evidence"]["human"]["sent_at"] = "yesterday"; self.awaiting = []
        self.assertTrue(any("sent_at" in m for m in self.miss([t])))
        self.pr = rework_pr(); self.pr["threads"]["PRRT_a"] = classified("self_resolved", "2026-10-13T11:00:00Z")
        t = th("PRRT_a", self.REVIEW, cm("agentlogin", "2026-10-13T11:05:00Z", 102)); t["truncated"] = True
        self.assertTrue(any("100 comments" in m for m in self.miss([t])))

class ThreadsCmd(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(D / "state_min.json", self.d / "state.json"); (self.d / ".state.lock").touch()
        (self.d / "reports").mkdir(); (self.d / "reports" / "COMMENTS-1.md").write_text("drafts")
        data = json.loads((self.d / "state.json").read_text()); data["epic"]["roles"]["agent_github"] = "agentlogin"
        pr = data["prs"]["jsfiller#1"]; pr["state"] = "REWORK"; pr["rework_since"] = {"head": H, "at": "2026-10-13T12:00Z", "reason": "threads"}
        pr["evidence"]["human"] = {"head": H, "sent_head": H, "sent_at": "2026-10-13T10:02Z", "approved": "ah-1", "slack_permalink": "https://x.slack.com/archives/C1/p1"}
        data["awaiting_human"] = [copy.deepcopy(SEND)]
        (self.d / "state.json").write_text(state.dumps(data))
        self.io = FakeIO(heads={"jsfiller#1": H})
        self.io.facts["jsfiller#1"] = {"threads": [
            th("PRRT_a", cm("isachivka", "2026-10-13T11:00:00Z", 101)),
            th("PRRT_b", cm("lMakDen", "2026-10-13T11:10:00Z", 201), cm("agentlogin", "2026-10-13T11:12:00Z", 202)),
            th("PRRT_c", cm("copilot-pull-request-reviewer", "2026-10-13T11:00:00Z", 301, bot=True), human=False)]}
    def data(self):
        return json.loads((self.d / "state.json").read_text())
    def go(self, self_ids="", lead_ids="", report=None):
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = threads.run(self.d, "jsfiller#1", self_ids, lead_ids, report=report, io=self.io)
        return rc, buf.getvalue()
    def replies(self):
        return [a for a in self.data()["awaiting_human"] if a["type"] == "reply"]

    def test_records_classification_from_github_and_opens_an_entry_only_for_needs_lead(self):
        rc, out = self.go(self_ids="PRRT_a", lead_ids="201", report="reports/COMMENTS-1.md"); self.assertEqual(rc, 0, out)
        t = self.data()["prs"]["jsfiller#1"]["threads"]
        self.assertEqual((t["PRRT_a"]["class"], t["PRRT_a"]["comment_id"], t["PRRT_a"]["last_reviewer_at"], t["PRRT_a"]["reviewer"]),
                         ("self_resolved", "101", "2026-10-13T11:00:00Z", "isachivka"))
        self.assertEqual((t["PRRT_b"]["class"], t["PRRT_b"]["comment_ids"]), ("needs_lead", ["201", "202"]))  # found by the REST comment id
        r = self.replies(); self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["thread"], r[0]["pr"], r[0]["approved_at"], r[0]["payload"], r[0]["last_reviewer_at"]),
                         ("PRRT_b", "jsfiller#1", None, "reports/COMMENTS-1.md", "2026-10-13T11:10:00Z"))
        self.assertIn("repos/pdffiller/jsfiller/pulls/1/comments/101/replies", out)
        self.assertIn("TURNSTILE_LEAD=1 turnstile approve %s" % r[0]["id"], out)
        self.assertIn("threads jsfiller#1: self_resolved PRRT_a; needs_lead PRRT_b", (self.d / "ledger.md").read_text())
        self.assertEqual(len(self.io.commits), 1)
    def test_refuses_unknown_bot_and_doubly_listed_ids_and_a_pr_outside_rework(self):
        for kw, needle in [(dict(self_ids="PRRT_zzz"), "PRRT_zzz"), (dict(self_ids="PRRT_c"), "Copilot"), (dict(self_ids="PRRT_a", lead_ids="PRRT_a"), "both")]:
            rc, out = self.go(**kw); self.assertEqual(rc, 2, kw); self.assertIn(needle, out, kw)
        self.assertEqual(self.replies(), []); self.assertEqual(self.io.commits, [])
        data = self.data(); data["prs"]["jsfiller#1"]["state"] = "ON_HUMAN_REVIEW"; (self.d / "state.json").write_text(state.dumps(data))
        rc, out = self.go(self_ids="PRRT_a"); self.assertEqual(rc, 2); self.assertIn("REWORK", out)
    def test_reclassification_voids_or_renews_the_reply_entry(self):
        self.go(lead_ids="PRRT_b"); first = self.replies()[0]["id"]
        self.go(lead_ids="PRRT_b"); self.assertEqual([a["id"] for a in self.replies()], [first])  # idempotent
        self.io.facts["jsfiller#1"]["threads"][1]["comments"].append(cm("lMakDen", "2026-10-13T12:30:00Z", 203))
        self.go(lead_ids="PRRT_b"); r = self.replies()
        self.assertEqual(len(r), 2); self.assertTrue(r[0].get("voided_at")); self.assertEqual(r[1]["last_reviewer_at"], "2026-10-13T12:30:00Z")
        self.go(self_ids="PRRT_b"); self.assertTrue(all(a.get("voided_at") for a in self.replies()))
        self.assertEqual(self.data()["prs"]["jsfiller#1"]["threads"]["PRRT_b"]["class"], "self_resolved")
    def test_without_ids_it_lists_and_writes_nothing(self):
        rc, out = self.go(); self.assertEqual(rc, 0, out)
        self.assertIn("PRRT_a", out); self.assertIn("unclassified", out); self.assertNotIn("PRRT_c", out)
        self.assertEqual(self.io.commits, []); self.assertFalse((self.d / "ledger.md").exists())

class ReworkBackToHumans(unittest.TestCase):
    """REWORK → ON_HUMAN_REVIEW: replies on GitHub (no blanket reply entry, no Slack), gate + Copilot on the new head."""
    def setUp(self):
        self.t = ThreadsCmd("test_without_ids_it_lists_and_writes_nothing"); self.t.setUp(); self.d, self.io = self.t.d, self.t.io
        data = self.t.data(); pr = data["prs"]["jsfiller#1"]; pr["head"] = H2
        pr["evidence"].update({"deep_review": {"head": H, "report": "reports/COMMENTS-1.md", "rounds": 1, "clean": True}})
        data["stories"]["S1"]["state"] = "DONE"; (self.d / "state.json").write_text(state.dumps(data))
        self.io.heads["jsfiller#1"] = H2
        self.io.facts["jsfiller#1"]["threads"] = self.io.facts["jsfiller#1"]["threads"][:1] + self.io.facts["jsfiller#1"]["threads"][2:]
    def back(self, **kw):
        return run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(head=H2, ci="success", gate="pdf-review:pass", **kw), self.io)
    def test_self_resolved_replies_return_the_pr_without_slack_or_approval(self):
        rc, out = self.back(); self.assertEqual(rc, 2); self.assertIn("PRRT_a", out)
        self.t.go(self_ids="PRRT_a")
        rc, out = self.back(); self.assertEqual(rc, 2); self.assertIn("agentlogin", out)
        self.io.facts["jsfiller#1"]["threads"][0]["comments"].append(cm("agentlogin", "2026-10-13T13:00:00Z", 102))
        rc, out = self.back(); self.assertEqual(rc, 0, out)
        h = self.t.data()["prs"]["jsfiller#1"]["evidence"]["human"]
        self.assertEqual(h["sent_head"], H2); self.assertEqual(h["sent_at"], "2026-10-13T10:02Z"); self.assertTrue(h["returned_at"])
    def test_slack_and_approved_flags_are_refused_on_the_way_back(self):
        rc, out = self.back(slack="https://x.slack.com/archives/C1/p2", approved="ah-1"); self.assertEqual(rc, 2)
        self.assertIn("no --slack", out)
    def test_needs_lead_entries_are_consumed_when_the_pr_returns(self):
        self.t.go(lead_ids="PRRT_a"); ah = self.t.replies()[0]["id"]
        self.io.facts["jsfiller#1"]["threads"][0]["comments"].append(cm("agentlogin", "2026-10-13T13:00:00Z", 102))
        rc, out = self.back(); self.assertEqual(rc, 2); self.assertIn(ah, out)
        with env(TURNSTILE_LEAD="1"):
            self.assertEqual(pass_cmd.approve(self.d, ah, self.io), 0)
        approved_at = next(a for a in self.t.replies() if a["id"] == ah)["approved_at"]
        self.io.facts["jsfiller#1"]["threads"][0]["comments"].append(cm("agentlogin", approved_at.replace("Z", ":30Z"), 103))
        rc, out = self.back(); self.assertEqual(rc, 0, out)
        self.assertTrue(next(a for a in self.t.replies() if a["id"] == ah)["consumed_at"])
    def test_rework_opens_no_blanket_reply_entry(self):
        data = self.t.data(); data["prs"]["jsfiller#1"]["state"] = "ON_HUMAN_REVIEW"; data["prs"]["jsfiller#1"]["head"] = H
        data["prs"]["jsfiller#1"]["evidence"]["head_verified"] = {"head": H, "verified": True}; (self.d / "state.json").write_text(state.dumps(data))
        self.io.heads["jsfiller#1"] = H
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "REWORK", opts(reason="human thread PRRT_a"), self.io); self.assertEqual(rc, 0, out)
        self.assertEqual(self.t.replies(), [])

if __name__ == "__main__":
    unittest.main()
