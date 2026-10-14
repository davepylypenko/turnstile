"""Lead rule 2026-10-14 (re-request): once every human thread on a REWORK PR has our latest reply and Copilot reviewed the current
head with 0 open threads (repos without Copilot: the repo gate green on the current head), the agents re-request review on GitHub
from the reviewers who commented on those threads. No lead approval; Slack stays lead-approved. A push-only rework pings nobody and
records `reviewer_notified: false` (the lead decides)."""
import copy, json, pathlib, unittest
from turnstile_cli import github, pass_cmd, reconcile, rules, threads
from tests.test_pass import opts, run_capture, H, H2
from tests.test_threads import ThreadsCmd, cm, th, rework_pr, classified, ROLES, SEND

D = pathlib.Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((D / "gh_pr_13222.json").read_text())
CMD = "gh api -X POST repos/pdffiller/jsfiller/pulls/1/requested_reviewers -f 'reviewers[]=isachivka'"

class Parse(unittest.TestCase):
    def test_review_requests_request_events_copilot_review_and_check_times(self):
        p = copy.deepcopy(PAYLOAD); head = p["headRefOid"]
        p["reviewRequests"] = {"nodes": [{"requestedReviewer": {"__typename": "User", "login": "isachivka"}}, {"requestedReviewer": {"__typename": "Team"}}]}
        p["timelineItems"] = {"nodes": [{"createdAt": "2026-10-13T09:00:00Z", "requestedReviewer": {"__typename": "User", "login": "isachivka"}},
                                        {"createdAt": "2026-10-13T13:05:00Z", "requestedReviewer": {"__typename": "User", "login": "isachivka"}},
                                        {"createdAt": "2026-10-13T13:06:00Z", "requestedReviewer": {"__typename": "Team"}}]}
        p["latestReviews"]["nodes"].append({"author": {"__typename": "Bot", "login": "copilot-pull-request-reviewer"}, "state": "COMMENTED",
                                            "commit": {"oid": head}, "submittedAt": "2026-10-13T12:50:00Z"})
        p["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]["nodes"] = [
            {"name": "pdf-review", "conclusion": "FAILURE", "status": "COMPLETED", "completedAt": "2026-10-13T12:00:00Z"},
            {"name": "pdf-review", "conclusion": "SUCCESS", "status": "COMPLETED", "completedAt": "2026-10-13T12:40:00Z"},
            {"context": "snyk", "state": "SUCCESS", "createdAt": "2026-10-13T12:30:00Z"}]
        f = github.parse("jsfiller#1", p)
        self.assertEqual(f.review_requests, ["isachivka"])
        self.assertEqual(f.review_requested_at, {"isachivka": "2026-10-13T13:05:00Z"})
        self.assertEqual((f.copilot_review_head, f.copilot_review_at), (head, "2026-10-13T12:50:00Z"))
        self.assertEqual(f.review_heads["isachivka"], head); self.assertNotIn("copilot-pull-request-reviewer", f.review_heads)
        self.assertEqual(f.check_times, {"pdf-review": "2026-10-13T12:40:00Z", "snyk": "2026-10-13T12:30:00Z"})
    def test_query_asks_for_requests_events_and_times(self):
        q = github.QUERY.replace(" ", "")
        for s in ("reviewRequests(first:", "REVIEW_REQUESTED_EVENT", "ReviewRequestedEvent{createdAt", "submittedAt", "completedAt", "StatusContext{contextstatecreatedAt"):
            self.assertIn(s, q, s)
    def test_old_payloads_without_the_new_fields_parse(self):
        f = github.parse("jsfiller#1", PAYLOAD)
        self.assertEqual((f.review_requests, f.review_requested_at, f.copilot_review_head), ([], {}, None))

class RoundAuthors(unittest.TestCase):
    REVIEW = cm("isachivka", "2026-10-13T11:00:00Z", 101)
    def test_the_reviewers_who_commented_in_this_round_on_threads_in_scope(self):
        pr = rework_pr(); aw = [copy.deepcopy(SEND)]
        ts = [th("PRRT_a", self.REVIEW, cm("agentlogin", "2026-10-13T11:05:00Z", 102)),
              th("PRRT_b", cm("agentlogin", "2026-10-13T11:00:00Z", 201), cm("lMakDen", "2026-10-13T11:10:00Z", 202)),
              th("PRRT_c", cm("copilot-pull-request-reviewer", "2026-10-13T11:00:00Z", 301, bot=True), human=False),
              th("PRRT_o", cm("oldhand", "2026-10-12T09:00:00Z", 90), resolved=True)]
        self.assertEqual(threads.round_authors(pr, ts, ROLES, aw), ["isachivka", "lMakDen"])
        self.assertEqual(threads.request_route("pdffiller", "jsfiller#1", ["isachivka", "lMakDen"]),
                         "gh api -X POST repos/pdffiller/jsfiller/pulls/1/requested_reviewers -f 'reviewers[]=isachivka' -f 'reviewers[]=lMakDen'")
    def test_a_later_round_counts_only_comments_after_the_return(self):
        pr = rework_pr(); pr["evidence"]["human"]["returned_at"] = "2026-10-13T14:00:00Z"; aw = [copy.deepcopy(SEND)]
        old = th("PRRT_a", self.REVIEW, cm("agentlogin", "2026-10-13T11:05:00Z", 102))  # answered in the first round, still unresolved
        self.assertEqual(threads.round_authors(pr, [old], ROLES, aw), [])
        old["comments"].append(cm("isachivka", "2026-10-13T14:30:00Z", 103))
        self.assertEqual(threads.round_authors(pr, [old], ROLES, aw), ["isachivka"])

class Back(unittest.TestCase):
    """REWORK → ON_HUMAN_REVIEW: thread-driven rework needs the re-request on GitHub; push-only rework records reviewer_notified false."""
    def setUp(self):
        self.t = ThreadsCmd("test_without_ids_it_lists_and_writes_nothing"); self.t.setUp(); self.d, self.io = self.t.d, self.t.io
        data = self.t.data(); pr = data["prs"]["jsfiller#1"]
        pr["evidence"]["deep_review"] = {"head": H, "report": "reports/COMMENTS-1.md", "rounds": 1, "clean": True}
        data["stories"]["S1"]["state"] = "DONE"; self.write(data)
        self.io.heads["jsfiller#1"] = H2
        f = self.io.facts["jsfiller#1"]; f["threads"] = [f["threads"][0], f["threads"][2]]  # PRRT_a (isachivka 11:00) + the Copilot thread
    def write(self, data):
        (self.d / "state.json").write_text(json.dumps(data))
    def back(self, **kw):
        kw = dict(dict(head=H2, ci="success", gate="pdf-review:pass"), **kw)
        return run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(**kw), self.io)
    def replied(self, at="2026-10-13T13:00:00Z"):
        self.t.go(self_ids="PRRT_a"); self.io.facts["jsfiller#1"]["threads"][0]["comments"].append(cm("agentlogin", at, 102))
    def requested(self, at="2026-10-13T13:05:00Z", pending=True):
        f = self.io.facts["jsfiller#1"]; f["review_requested_at"] = {"isachivka": at}; f["review_requests"] = ["isachivka"] if pending else []
    def human(self):
        return self.t.data()["prs"]["jsfiller#1"]["evidence"]["human"]

    def test_thread_driven_rework_prints_the_exact_re_request_and_needs_it(self):
        self.replied()
        rc, out = self.back(); self.assertEqual(rc, 2, out)
        self.assertIn(CMD, out); self.assertIn("--rerequested isachivka", out)
        self.requested()
        rc, out = self.back(rerequested="isachivka"); self.assertEqual(rc, 0, out)
        h = self.human()
        self.assertEqual((h["rerequested"]["logins"], h["rerequested"]["head"], h["reviewer_notified"]), (["isachivka"], H2, True))
        self.assertTrue(h["rerequested"]["at"]); self.assertEqual(h["sent_head"], H2)
        self.assertIn("re-requested review from isachivka", (self.d / "ledger.md").read_text())
    def test_the_re_request_is_verified_against_github(self):
        self.replied()
        rc, out = self.back(rerequested="isachivka"); self.assertEqual(rc, 2); self.assertIn("isachivka", out); self.assertIn(CMD, out)
        self.requested(at="2026-10-13T12:59:00Z")  # before the reply: not the re-request the rule asks for
        rc, out = self.back(rerequested="isachivka"); self.assertEqual(rc, 2); self.assertIn("predates", out)
        self.requested(pending=False)  # requested after the reply, but no longer pending and no review on the head
        rc, out = self.back(rerequested="isachivka"); self.assertEqual(rc, 2); self.assertIn("reviewRequests", out)
        self.io.facts["jsfiller#1"]["review_heads"] = {"isachivka": H2}  # the reviewer already looked at the head again
        rc, out = self.back(rerequested="isachivka"); self.assertEqual(rc, 0, out)
    def test_exactly_the_thread_authors(self):
        self.replied(); self.requested()
        for logins in ("isachivka,lMakDen", "lMakDen", "isachivka,copilot-pull-request-reviewer[bot]"):
            rc, out = self.back(rerequested=logins); self.assertEqual(rc, 2, logins); self.assertIn("exactly", out, logins)
        rc, out = self.back(rerequested="ISACHIVKA"); self.assertEqual(rc, 0, out)  # GitHub logins are case-insensitive
        self.assertEqual(self.human()["rerequested"]["logins"], ["isachivka"])
    def test_with_copilot_the_request_follows_copilots_review_of_the_head(self):
        data = self.t.data(); data["epic"]["repos"]["jsfiller"]["copilot"] = True; self.write(data)
        self.replied(); self.requested(at="2026-10-13T13:05:00Z")
        f = self.io.facts["jsfiller#1"]; f["copilot_review_head"] = H2; f["copilot_review_at"] = "2026-10-13T13:10:00Z"
        rc, out = self.back(copilot=0, rerequested="isachivka"); self.assertEqual(rc, 2); self.assertIn("predates", out); self.assertIn("Copilot", out)
        self.requested(at="2026-10-13T13:15:00Z")
        rc, out = self.back(copilot=0, rerequested="isachivka"); self.assertEqual(rc, 0, out)
    def test_push_only_rework_pings_nobody_and_records_reviewer_not_notified(self):
        self.io.facts["jsfiller#1"]["threads"] = self.io.facts["jsfiller#1"]["threads"][1:]  # no human thread at all
        rc, out = self.back(rerequested="isachivka"); self.assertEqual(rc, 2); self.assertIn("push-only", out)
        rc, out = self.back(); self.assertEqual(rc, 0, out)
        h = self.human(); self.assertIs(h["reviewer_notified"], False); self.assertNotIn("rerequested", h)
        self.assertIn("reviewers not notified", (self.d / "ledger.md").read_text())
        self.assertIn("not notified", self.t.data()["prs"]["jsfiller#1"]["next_action"])
    def test_a_second_round_without_new_reviewer_comments_is_push_only(self):
        self.replied()
        data = self.t.data(); data["prs"]["jsfiller#1"]["evidence"]["human"]["returned_at"] = "2026-10-13T14:00:00Z"; self.write(data)
        rc, out = self.back(); self.assertEqual(rc, 0, out); self.assertIs(self.human()["reviewer_notified"], False)
    def test_rerequested_is_refused_on_every_other_transition(self):
        data = self.t.data(); data["prs"]["jsfiller#1"]["state"] = "ON_HUMAN_REVIEW"; self.write(data)
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "REWORK", opts(reason="x", rerequested="isachivka"), self.io)
        self.assertEqual(rc, 2); self.assertIn("--rerequested", out)

class NextAction(unittest.TestCase):
    def test_rework_and_unnotified_human_review(self):
        self.assertIn("re-request", rules.next_action_pr({"state": "REWORK"}, {}))
        p = {"state": "ON_HUMAN_REVIEW", "evidence": {"human": {"reviewer_notified": False}}}
        self.assertIn("not notified", rules.next_action_pr(p, {}))
        self.assertNotIn("not notified", rules.next_action_pr({"state": "ON_HUMAN_REVIEW", "evidence": {"human": {"reviewer_notified": True}}}, {}))

class Reconcile(unittest.TestCase):
    T = "2026-10-13T11:00:00Z"
    def data(self, copilot=False):
        d = json.loads((D / "state_min.json").read_text()); d["epic"]["roles"]["agent_github"] = "agentlogin"
        d["epic"]["repos"]["jsfiller"]["copilot"] = copilot
        pr = d["prs"]["jsfiller#1"]; pr["state"] = "REWORK"; pr["rework_since"] = {"head": H, "at": "2026-10-13T12:00Z", "reason": "x"}
        pr["evidence"]["human"] = {"head": H, "sent_head": H, "sent_at": "2026-10-13T10:02Z", "approved": "ah-1", "slack_permalink": "https://x.slack.com/archives/C1/p1"}
        pr["threads"] = {"PRRT_a": classified("self_resolved", self.T)}
        d["awaiting_human"] = [copy.deepcopy(SEND)]
        return d
    def facts(self, **kw):
        f = github.parse("jsfiller#1", PAYLOAD); f.head = H2
        f.threads = [th("PRRT_a", cm("isachivka", self.T, 101), cm("agentlogin", "2026-10-13T13:00:00Z", 102))]
        f.human_threads_open = 1; f.checks = {"pdf-review": "success"}
        for k, v in kw.items(): setattr(f, k, v)
        return {"jsfiller#1": f}
    def kinds(self, props):
        return {p.kind: p for p in props}
    def test_proposes_the_re_request_once_replies_and_the_gate_are_clean(self):
        props = self.kinds(reconcile.compare(self.data(), self.facts()))
        self.assertIn("rerequest", props); self.assertEqual(props["rerequest"].suggested_cmd, CMD)
    def test_nothing_to_run_when_it_happened_for_the_head(self):
        props = self.kinds(reconcile.compare(self.data(), self.facts(review_requests=["isachivka"], review_requested_at={"isachivka": "2026-10-13T13:05:00Z"})))
        self.assertNotIn("rerequest", props); self.assertIn("rerequest_done", props)
        self.assertIsNone(props["rerequest_done"].suggested_cmd); self.assertIn("--rerequested isachivka", props["rerequest_done"].message)
    def test_no_proposal_while_a_reply_or_the_gate_or_copilot_is_missing(self):
        f = self.facts(); f["jsfiller#1"].threads[0]["comments"].pop()
        self.assertNotIn("rerequest", self.kinds(reconcile.compare(self.data(), f)))
        props = self.kinds(reconcile.compare(self.data(), self.facts(checks={"pdf-review": "pending"})))
        self.assertIsNone(props["rerequest"].suggested_cmd); self.assertIn("pending", props["rerequest"].message)
        props = self.kinds(reconcile.compare(self.data(copilot=True), self.facts(copilot_review_head=H, copilot_threads_open=0)))
        self.assertIsNone(props["rerequest"].suggested_cmd); self.assertIn("Copilot", props["rerequest"].message)
        props = self.kinds(reconcile.compare(self.data(copilot=True), self.facts(copilot_review_head=H2, copilot_review_at="2026-10-13T13:01:00Z")))
        self.assertEqual(props["rerequest"].suggested_cmd, CMD)
    def test_push_only_rework_is_named_for_the_lead_without_a_command(self):
        props = self.kinds(reconcile.compare(self.data(), self.facts(threads=[], human_threads_open=0)))
        self.assertIn("push_only", props); self.assertIsNone(props["push_only"].suggested_cmd); self.assertNotIn("rerequest", props)

if __name__ == "__main__":
    unittest.main()
