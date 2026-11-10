"""0.6.2 (lead 2026-11-10): an approval is read from the review history (a re-request wipes it from latestReviews), answered
threads the reviewer never resolved do not hold APPROVED back, an approver of the head is never re-requested, and the board's
"Awaiting humans" tab lists only what still needs a person."""
import contextlib, copy, io as _io, json, pathlib, shutil, subprocess, tempfile, unittest
from unittest import mock
from turnstile_cli import board, github, pass_cmd, reconcile, threads
from turnstile_cli.github import PrFacts
from tests.test_pass import FakeIO, opts, run_capture, H, H2, LINK, READY_OPTS
from tests.test_threads import cm, th
from tests.test_rerequest import Back, Reconcile as RerequestReconcile, CMD

D = pathlib.Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((D / "gh_pr_13222.json").read_text())
T0, T1, T2, T3 = "2026-11-10T09:50:00Z", "2026-11-10T10:00:00Z", "2026-11-10T10:40:00Z", "2026-11-10T11:00:00Z"

def review(login, state, oid, at, typename="User"):
    return {"author": {"__typename": typename, "login": login}, "state": state, "commit": {"oid": oid}, "submittedAt": at}

class ReviewHistory(unittest.TestCase):
    def payload(self, reviews, latest=None):
        p = copy.deepcopy(PAYLOAD)
        p["latestReviews"]["nodes"] = [r for r in p["latestReviews"]["nodes"] if r["author"]["login"] != "isachivka"] + (latest or [])
        p["reviews"] = {"nodes": reviews}
        return p
    def test_query_asks_for_the_review_history(self):
        self.assertIn("reviews(last:50){nodes{author{__typenamelogin}statecommit{oid}submittedAt}}", github.QUERY.replace(" ", "").replace("\n", ""))
    def test_approval_survives_a_re_request_that_wiped_latest_reviews(self):
        head = PAYLOAD["headRefOid"]
        f = github.parse("jsfiller#1", self.payload([review("isachivka", "APPROVED", head, T0)]))
        self.assertEqual(f.approvals, ["isachivka"]); self.assertTrue(f.approved_by("ISACHIVKA")); self.assertEqual(f.review_decision, "APPROVED")
        self.assertEqual(f.review_heads["isachivka"], head)
    def test_a_newer_head_or_a_later_changes_requested_or_dismissal_voids_it_and_a_comment_does_not(self):
        head = PAYLOAD["headRefOid"]
        p = self.payload([review("isachivka", "APPROVED", head, T0)]); p["headRefOid"] = "ffffffff66666666ffff0288e05b49fa4583d881"
        self.assertEqual(github.parse("jsfiller#1", p).approvals, [])
        p = self.payload([review("isachivka", "APPROVED", head, T0), review("isachivka", "CHANGES_REQUESTED", head, T1)])
        self.assertEqual(github.parse("jsfiller#1", p).approvals, [])
        p = self.payload([review("isachivka", "APPROVED", head, T0), review("isachivka", "DISMISSED", head, T1)])
        self.assertEqual(github.parse("jsfiller#1", p).approvals, [])
        p = self.payload([review("isachivka", "APPROVED", head, T0), review("isachivka", "COMMENTED", head, T1)])
        self.assertEqual(github.parse("jsfiller#1", p).approvals, ["isachivka"])
        p = self.payload([review("isachivka", "CHANGES_REQUESTED", head, T0), review("isachivka", "APPROVED", head, T1)])
        self.assertEqual(github.parse("jsfiller#1", p).approvals, ["isachivka"])
    def test_bots_and_approvals_of_older_heads_in_the_history_do_not_count(self):
        head = PAYLOAD["headRefOid"]
        p = self.payload([review("github-actions", "APPROVED", head, T0, "Bot"), review("oldhand", "APPROVED", "0000000011111111aaa0288e05b49fa4583d8812", T0),
                          review("sonarqubecloud", "APPROVED", head, T1)])
        self.assertEqual(github.parse("jsfiller#1", p).approvals, [])
    def test_latest_reviews_alone_still_count_when_the_history_is_absent(self):
        f = github.parse("jsfiller#1", PAYLOAD)
        self.assertEqual(f.approvals, ["isachivka"]); self.assertEqual(f.review_decision, "APPROVED")

class ApprovedWithAnsweredThreads(unittest.TestCase):
    def setUp(self):
        from turnstile_cli import sync
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir(); sync.record(self.d, True, H)
        shutil.copy(D / "state_min.json", self.d / "state.json")
        self.io = FakeIO(heads={"jsfiller#1": H, "docs-platform#2": "bbbbbbbb22222222"})
        (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok")
        self.assertEqual(pass_cmd.run(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io), 0)
        data = self.data(); data["stories"]["S1"]["state"] = "DONE"; (self.d / "state.json").write_text(json.dumps(data))
        self.assertEqual(pass_cmd.run(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(head=H, slack=LINK, reviewers="isachivka"), self.io), 0)
    def data(self):
        return json.loads((self.d / "state.json").read_text())
    def approve(self, **kw):
        return run_capture(self.d, "pr", "jsfiller#1", "APPROVED", opts(approvals="isachivka", **kw), self.io)
    def test_settled_but_unresolved_threads_do_not_block_and_are_recorded_as_answered(self):
        self.io.facts["jsfiller#1"] = {"human_threads_open": 2, "threads": [
            th("PRRT_1", cm("isachivka", T1, 101), cm("leadlogin", T2, 102)),
            th("PRRT_2", cm("isachivka", T1, 201), cm("leadlogin", T3, 202))]}
        rc, out = self.approve(); self.assertEqual(rc, 0, out)
        h = self.data()["prs"]["jsfiller#1"]["evidence"]["human"]
        self.assertEqual((h["open_threads"], h["answered_threads"], h["approvals"]), (0, 2, ["isachivka"]))
        self.assertEqual(self.data()["prs"]["jsfiller#1"]["state"], "APPROVED")
    def test_an_unsettled_thread_refuses(self):
        self.io.facts["jsfiller#1"] = {"human_threads_open": 2, "threads": [
            th("PRRT_1", cm("isachivka", T1, 101), cm("leadlogin", T2, 102)),
            th("PRRT_2", cm("isachivka", T1, 201), cm("leadlogin", T2, 202), cm("isachivka", T3, 203))]}
        rc, out = self.approve(); self.assertEqual(rc, 2)
        self.assertIn("MISSING 0 open human threads on GitHub (has 1 unresolved without a member's reply; 1 answered, awaiting resolve)", out)
        self.assertEqual(self.data()["prs"]["jsfiller#1"]["state"], "ON_HUMAN_REVIEW")
    def test_open_threads_flag_overrides_the_recorded_count_but_not_github(self):
        self.io.facts["jsfiller#1"] = {"human_threads_open": 1, "threads": [th("PRRT_1", cm("isachivka", T1, 101), cm("leadlogin", T2, 102))]}
        rc, out = self.approve(open_threads=0); self.assertEqual(rc, 0, out)
        h = self.data()["prs"]["jsfiller#1"]["evidence"]["human"]; self.assertEqual((h["open_threads"], h["answered_threads"]), (0, 1))
        self.io.facts["jsfiller#1"] = {"human_threads_open": 1, "threads": [th("PRRT_1", cm("isachivka", T1, 101))]}
        data = self.data(); data["prs"]["jsfiller#1"]["state"] = "ON_HUMAN_REVIEW"; (self.d / "state.json").write_text(json.dumps(data))
        rc, out = self.approve(open_threads=0); self.assertEqual(rc, 2); self.assertIn("MISSING 0 open human threads on GitHub", out)

class ApprovedProposal(unittest.TestCase):
    def test_reconcile_proposes_approved_without_the_open_threads_flag_and_names_the_answered_threads(self):
        d = copy.deepcopy(json.loads((D / "state_min.json").read_text())); p = d["prs"]["jsfiller#1"]; p["state"] = "ON_HUMAN_REVIEW"
        p["evidence"]["human"] = {"head": H, "sent_head": H, "slack_permalink": "u", "approved": "ah-1", "open_threads": 0, "approvals": []}
        f = github.parse("jsfiller#1", PAYLOAD); f.threads[0]["comments"].append(cm("leadlogin", T2, 102))
        props = {x.kind: x for x in reconcile.compare(d, {"jsfiller#1": f})}
        self.assertIn("approved", props); self.assertEqual(props["approved"].suggested_cmd, "turnstile pass pr jsfiller#1 APPROVED --approvals isachivka")
        self.assertIn("1 thread(s) answered, awaiting resolve", props["approved"].message)

class NeverRerequestAnApprover(unittest.TestCase):
    def setUp(self):
        self.b = Back("test_exactly_the_thread_authors"); self.b.setUp()
        self.b.replied(); self.b.io.facts["jsfiller#1"]["approvals"] = ["isachivka"]
    def test_the_return_needs_no_re_request_and_records_the_approver(self):
        rc, out = self.b.back(); self.assertEqual(rc, 0, out)
        h = self.b.human(); self.assertIs(h["reviewer_notified"], True)
        self.assertEqual((h["rerequested"]["logins"], h["rerequested"]["approved"]), ([], ["isachivka"]))
        self.assertIn("isachivka approved head %s: not re-requested" % H2, (self.b.d / "ledger.md").read_text())
    def test_naming_the_approver_in_rerequested_is_tolerated(self):
        rc, out = self.b.back(rerequested="isachivka"); self.assertEqual(rc, 0, out)
    def test_a_second_author_who_did_not_approve_is_still_re_requested(self):
        f = self.b.io.facts["jsfiller#1"]
        f["threads"].append(th("PRRT_b", cm("lMakDen", "2026-10-13T11:10:00Z", 201), cm("agentlogin", "2026-10-13T13:00:00Z", 202)))
        self.b.t.go(self_ids="PRRT_b")
        rc, out = self.b.back(); self.assertEqual(rc, 2)
        self.assertIn("-f 'reviewers[]=lMakDen'", out); self.assertNotIn("reviewers[]=isachivka", out); self.assertIn("--rerequested lMakDen", out)
        rc, out = self.b.back(rerequested="isachivka,lMakDen"); self.assertEqual(rc, 2); self.assertIn("no review request for lMakDen", out)
        f["review_requested_at"] = {"lMakDen": "2026-10-13T13:05:00Z"}; f["review_requests"] = ["lMakDen"]
        rc, out = self.b.back(rerequested="lMakDen"); self.assertEqual(rc, 0, out)
        self.assertEqual(self.b.human()["rerequested"]["logins"], ["lMakDen"])

class RerequestProposalSkipsApprovers(unittest.TestCase):
    def setUp(self):
        self.r = RerequestReconcile("test_proposes_the_re_request_once_replies_and_the_gate_are_clean")
    def test_the_approver_is_dropped(self):
        props = {p.kind: p for p in reconcile.compare(self.r.data(), self.r.facts(approvals=["isachivka"]))}
        self.assertNotIn("rerequest", props); self.assertIn("rerequest_done", props)
        self.assertIn("isachivka approved head %s" % H2[:12], props["rerequest_done"].message); self.assertIn("without --rerequested", props["rerequest_done"].message)
    def test_the_other_author_is_still_proposed(self):
        facts = self.r.facts(approvals=["isachivka"]); f = facts["jsfiller#1"]
        f.threads.append(th("PRRT_b", cm("lMakDen", "2026-10-13T11:10:00Z", 201), cm("agentlogin", "2026-10-13T13:00:00Z", 202)))
        d = self.r.data(); d["prs"]["jsfiller#1"]["threads"]["PRRT_b"] = dict(d["prs"]["jsfiller#1"]["threads"]["PRRT_a"], comment_id="201", comment_ids=["201"],
                                                                              reviewer="lMakDen", last_reviewer_at="2026-10-13T11:10:00Z")
        props = {p.kind: p for p in reconcile.compare(d, facts)}
        self.assertEqual(props["rerequest"].suggested_cmd, CMD.replace("isachivka", "lMakDen"))

class StatusLine(unittest.TestCase):
    def test_status_prints_the_review_decision(self):
        d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; d.mkdir(); shutil.copy(D / "state_min.json", d / "state.json"); (d / ".state.lock").touch()
        f = PrFacts(id="jsfiller#1", head=H, merged=False, merged_sha=None, draft=True, ci="success", approvals=["isachivka"], review_decision="APPROVED")
        buf = _io.StringIO()
        with mock.patch.object(reconcile.github, "fetch", side_effect=lambda pid, org: f if pid == "jsfiller#1" else (_ for _ in ()).throw(RuntimeError("no gh"))), \
                contextlib.redirect_stdout(buf):
            reconcile.cli(d, status=True)
        self.assertIn("GITHUB: review decision APPROVED — jsfiller#1 (approved head %s: isachivka)" % H[:12], buf.getvalue())

def entry(i, type_, **kw):
    e = {"id": "ah-%d" % i, "owner": "lead", "type": type_, "created_at": "2026-11-%02dT10:00Z" % (i % 28 + 1), "payload": None, "approved_at": None}
    e.update(kw); return e

def twenty():
    used = {"approved_at": "2026-11-09T10:00Z", "consumed_at": "2026-11-09T10:05Z"}
    return [entry(1, "merge", pr="jsfiller#1", head=H), entry(2, "start_story", story="S2"),
            entry(3, "reply", pr="jsfiller#1", thread="PRRT_1", payload="reports/COMMENTS-1.md", draft="We keep the hook: " + "x" * 200),
            entry(4, "reply", pr="docs-platform#2", thread="PRRT_9", payload="reports/COMMENTS-2.md", approved_at="2026-11-10T09:00Z"),
            entry(5, "reply", pr="jsfiller#1", thread="PRRT_2", approved_at="2026-11-08T09:00Z", posted_at="2026-11-08T09:10Z"),
            entry(6, "plan", payload="plan.md", **used), entry(7, "start_story", story="S1", **used), entry(8, "send", pr="jsfiller#1"),
            entry(9, "send", pr="docs-platform#2", **used), entry(10, "merge", pr="docs-platform#2", **used), entry(11, "story_done", story="S1", **used),
            entry(12, "reply", pr="jsfiller#1", thread="PRRT_3", voided_at="2026-11-07T10:00Z"), entry(13, "merge", pr="jsfiller#1", voided_at="2026-11-07T10:00Z"),
            entry(14, "config", payload="reviewer=sonnet", **used), entry(15, "story_done", story="S2", voided_at="2026-11-06T10:00Z"),
            entry(16, "reply", pr="docs-platform#2", thread="PRRT_8", **used), entry(17, "plan", payload="plan.md", voided_at="2026-11-05T10:00Z"),
            entry(18, "start_story", story="S2", voided_at="2026-11-05T10:00Z"), entry(19, "merge", pr="jsfiller#1", **used), entry(20, "send", pr="jsfiller#1", **used)]

class AwaitingHumansTab(unittest.TestCase):
    """The tab and the tile share one predicate: open entries plus approved replies not yet on GitHub; the rest sits under History."""
    def setUp(self):
        self.data = copy.deepcopy(json.loads((D / "state_min.json").read_text())); self.data["awaiting_human"] = twenty()
        self.data["epic"]["members"] = {"leadlogin": {"name": "Lead"}, "second": {"name": "Second"}}
        self.data["prs"]["jsfiller#1"]["owner"] = "leadlogin"; self.data["stories"]["S1"]["owner"] = "leadlogin"
        self.data["stories"]["S2"] = dict(copy.deepcopy(self.data["stories"]["S1"]), owner="second", title="Second story", state="PLANNED")
        self.data["prs"]["docs-platform#2"].update(owner="second", story="S2")
    def script(self, state):
        tpl = board.TEMPLATE.read_text()
        head = [l for l in tpl.splitlines() if l.startswith(("const esc =", "const jiraBase =", "const ticket ="))]
        body = tpl[tpl.index("const openEntry ="):tpl.index("document.querySelectorAll('.tabs button').forEach(b => b.addEventListener")]
        return "\n".join(["var el = {innerHTML: ''}; var document = {getElementById: () => el};", "var STATE = %s;" % json.dumps(state)] + head + [body,
                          "awaiting(); var all = STATE.awaiting_human || [];",
                          "console.log(JSON.stringify({tile: all.filter(openEntry).length, html: el.innerHTML}));"])
    def run_js(self, state):
        return json.loads(subprocess.run(["node", "-e", self.script(state)], capture_output=True, text=True, check=True).stdout)
    def test_template_renders_open_rows_and_a_collapsed_history(self):
        tpl = board.TEMPLATE.read_text()
        for s in ("const openEntry = a => a.type !== 'send' && !a.voided_at && !a.consumed_at && (!a.approved_at || (a.type === 'reply' && !a.posted_at))",
                  "awaiting: (STATE.awaiting_human || []).filter(openEntry).length", "'! TURNSTILE_LEAD=1 turnstile approve ' + a.id",
                  "<details><summary>History (' + history.length + ')</summary>", "esc(String(a.draft).slice(0, 160))", "reply not posted yet",
                  "<th>Id</th><th>Kind</th><th>Subject</th><th>Created</th><th>Approve line</th><th>Status</th>", "nothing waits for a human",
                  "if ((h.approvals || []).length) out.push('approved by ' + h.approvals.join(', '))", "' thread(s) answered, awaiting resolve'"):
            self.assertIn(s, tpl, s)
        self.assertNotIn("<details open", tpl)
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_four_open_rows_and_sixteen_under_history_for_twenty_entries(self):
        out = self.run_js(self.data); html = out["html"]
        self.assertEqual(out["tile"], 4)
        open_part, history = html.split("<details>")
        self.assertEqual(open_part.count("<tr>") - 1, 4); self.assertEqual(open_part.count("! TURNSTILE_LEAD=1 turnstile approve ah-"), 3)
        for s in ("ah-1", "ah-2", "ah-3", "ah-4", "approve ah-1", "approve ah-2", "approve ah-3", "reply not posted yet", "We keep the hook: " + "x" * 142):
            self.assertIn(s, open_part, s)
        self.assertNotIn("x" * 143, open_part); self.assertNotIn("approve ah-4", open_part)
        self.assertTrue(history.startswith("<summary>History (16)</summary>")); self.assertEqual(history.count("<tr>") - 1, 16)
        for s in ("ah-5", "ah-8", "legacy send entry", "voided", "(used)"): self.assertIn(s, history, s)
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_member_boards_apply_the_same_rule(self):
        files = board.render_files(self.data)
        for rel in ("board.html", "boards/leadlogin.html", "boards/second.html"):
            self.assertIn("filter(openEntry).length", files[rel], rel); self.assertIn("History (' + history.length + ')", files[rel], rel)
        second = board.member_view(self.data, "second")
        out = self.run_js(second); open_part = out["html"].split("<details>")[0]
        self.assertEqual(out["tile"], open_part.count("<tr>") - 1); self.assertIn("ah-4", open_part); self.assertNotIn("ah-1", open_part); self.assertNotIn("ah-3", open_part)
        lead = board.member_view(self.data, "leadlogin"); out = self.run_js(lead); open_part = out["html"].split("<details>")[0]
        self.assertEqual(out["tile"], open_part.count("<tr>") - 1); self.assertIn("ah-1", open_part); self.assertIn("ah-3", open_part); self.assertNotIn("ah-4", open_part)
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_nothing_open_reads_so_and_history_still_lists_the_rest(self):
        self.data["awaiting_human"] = [e for e in twenty() if not e["id"] in ("ah-1", "ah-2", "ah-3", "ah-4")]
        out = self.run_js(self.data)
        self.assertEqual(out["tile"], 0); self.assertTrue(out["html"].startswith('<p class="muted">nothing waits for a human</p><details>'))

if __name__ == "__main__":
    unittest.main()
