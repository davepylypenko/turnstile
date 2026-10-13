import copy, json, pathlib, unittest
from turnstile_cli import github, reconcile

D = pathlib.Path(__file__).parent / "fixtures"
FIX = json.loads((D / "state_min.json").read_text())
PAYLOAD = json.loads((D / "gh_pr_13222.json").read_text())
H = "aaaaaaaa11111111"
HUMAN = {"head": H, "sent_head": H, "slack_permalink": "u", "approved": "ah-1", "open_threads": 0, "approvals": []}

class Parse(unittest.TestCase):
    def test_parse(self):
        f = github.parse("jsfiller#1", PAYLOAD)
        self.assertTrue(f.head.startswith("aaaaaaaa1111"))
        self.assertEqual(f.ci, "success"); self.assertEqual(f.checks["pdf-review"], "success")
        self.assertEqual(f.human_threads_open, 1); self.assertEqual(f.copilot_threads_open, 0)
        self.assertEqual(f.approvals, ["isachivka"]); self.assertFalse(f.merged)
        self.assertTrue(f.checks_complete); self.assertTrue(f.head_signed)
    def test_bots_ignored_and_stale_approvals_dropped(self):
        f = github.parse("jsfiller#1", PAYLOAD)
        self.assertNotIn("github-actions", f.approvals); self.assertNotIn("oldhand", f.approvals); self.assertNotIn("sonarqubecloud", f.approvals)
        self.assertEqual(f.human_threads_open, 1)  # github-actions (Bot) and application-pdffiller are not humans
    def test_changes_requested_collected(self):
        p = copy.deepcopy(PAYLOAD); p["latestReviews"]["nodes"][0]["state"] = "CHANGES_REQUESTED"
        f = github.parse("jsfiller#1", p)
        self.assertEqual(f.changes_requested, ["isachivka"]); self.assertEqual(f.approvals, [])
    def test_pending_checks_are_pending_and_duplicates_take_the_worst(self):
        p = copy.deepcopy(PAYLOAD)
        p["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]["nodes"] = [
            {"name": "pdf-review", "conclusion": None, "status": "IN_PROGRESS"},
            {"name": "ci", "conclusion": "SUCCESS", "status": "COMPLETED"}, {"name": "ci", "conclusion": "FAILURE", "status": "COMPLETED"},
            {"name": "cancelled", "conclusion": "CANCELLED", "status": "COMPLETED"}, {"context": "snyk", "state": "PENDING"},
            {"name": "skip", "conclusion": "SKIPPED", "status": "COMPLETED"}]
        f = github.parse("jsfiller#1", p)
        self.assertEqual(f.checks, {"pdf-review": "pending", "ci": "failure", "cancelled": "failure", "snyk": "pending", "skip": "skipped"})
    def test_incomplete_contexts_and_unsigned(self):
        p = copy.deepcopy(PAYLOAD)
        p["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]["totalCount"] = 150
        p["commits"]["nodes"][0]["commit"]["signature"] = {"isValid": False}
        f = github.parse("jsfiller#1", p)
        self.assertFalse(f.checks_complete); self.assertFalse(f.head_signed)
    def test_query_asks_for_what_parse_needs(self):
        for s in ("__typename", "commit{oid}", "signature{isValid}", "totalCount", "contexts(first:100)"):
            self.assertIn(s, github.QUERY.replace(" ", "").replace("\n", "") if s.startswith(("commit", "signature", "contexts")) else github.QUERY, s)

class Compare(unittest.TestCase):
    def facts(self, **kw):
        f = github.parse("jsfiller#1", PAYLOAD)
        for k, v in kw.items(): setattr(f, k, v)
        return {"jsfiller#1": f}
    def data(self, state, **ev):
        d = copy.deepcopy(FIX); p = d["prs"]["jsfiller#1"]; p["state"] = state; p["evidence"].update(ev); return d
    def kinds(self, props):
        return [p.kind for p in props]

    def test_push_after_send_proposes_rework(self):
        props = reconcile.compare(self.data("ON_HUMAN_REVIEW", human=HUMAN), self.facts(head="ffffffff66666666"))
        self.assertEqual(props[0].kind, "head_changed"); self.assertIn("REWORK --head ffffffff66666666", props[0].suggested_cmd)
    def test_head_changed_in_ready_proposes_ai_review_reentry_only_when_pass_accepts(self):
        props = reconcile.compare(self.data("READY"), self.facts(head="ffffffff66666666", ci="success"))
        self.assertEqual(props[0].kind, "head_changed")
        self.assertEqual(props[0].suggested_cmd, "turnstile pass pr jsfiller#1 AI_REVIEW --head ffffffff66666666 --ci success")
        props = reconcile.compare(self.data("AI_REVIEW"), self.facts(head="ffffffff66666666", ci="pending"))
        self.assertEqual(props[0].kind, "head_changed"); self.assertIsNone(props[0].suggested_cmd); self.assertIn("MISSING", props[0].message)
        props = reconcile.compare(self.data("AI_REVIEW"), self.facts(head="ffffffff66666666", ci="failure"))
        self.assertIsNone(props[0].suggested_cmd)
    def test_head_changed_in_dev_and_rework_has_no_command(self):
        for st in ("DEV", "REWORK"):
            props = reconcile.compare(self.data(st), self.facts(head="ffffffff66666666", ci="success", human_threads_open=0))
            self.assertEqual(props[0].kind, "head_changed", st); self.assertIsNone(props[0].suggested_cmd, st)
    def test_human_thread_proposes_rework(self):
        props = reconcile.compare(self.data("ON_HUMAN_REVIEW", human=HUMAN), self.facts())
        self.assertEqual(self.kinds(props), ["human_thread"]); self.assertIn("REWORK", props[0].suggested_cmd)
    def test_changes_requested_proposes_rework(self):
        props = reconcile.compare(self.data("ON_HUMAN_REVIEW", human=HUMAN), self.facts(human_threads_open=0, approvals=[], changes_requested=["isachivka"]))
        self.assertEqual(self.kinds(props), ["changes_requested"]); self.assertIn('REWORK --reason "changes requested by isachivka"', props[0].suggested_cmd)
    def test_approved_with_no_threads(self):
        props = reconcile.compare(self.data("ON_HUMAN_REVIEW", human=HUMAN), self.facts(human_threads_open=0))
        self.assertEqual(props[0].kind, "approved"); self.assertIn("--approvals isachivka --open-threads 0", props[0].suggested_cmd)
    def test_dry_run_applies_the_github_facts_checks(self):
        # the approved proposal carries facts.approvals, so it passes; a merged proposal whose state says a different merged_sha is dropped
        d = self.data("APPROVED"); d["prs"]["jsfiller#1"]["merged_sha"] = "1111111122222222"
        props = reconcile.compare(d, self.facts(merged=True, merged_sha="abcabcabcabcabca"))
        self.assertEqual(props[0].kind, "merged"); self.assertIn("--merged-sha abcabcabcabcabca", props[0].suggested_cmd)  # --merged-sha overrides the stale value
        d = self.data("READY", gate={"name": "pdf-review", "head": H, "result": "pass"}, ci={"head": H, "status": "success"})
        f = self.facts(head="ffffffff66666666", ci="failure")
        props = reconcile.compare(d, f)
        self.assertEqual(props[0].kind, "head_changed"); self.assertIsNone(props[0].suggested_cmd)

    def test_approved_proposal_is_dry_run_against_rules(self):
        stale = dict(HUMAN, sent_head="dddddddd44444444")
        props = reconcile.compare(self.data("ON_HUMAN_REVIEW", human=stale), self.facts(human_threads_open=0))
        self.assertEqual(props[0].kind, "approved"); self.assertIsNone(props[0].suggested_cmd); self.assertIn("sent_head", props[0].message)
    def test_merged(self):
        props = reconcile.compare(self.data("APPROVED"), self.facts(merged=True, merged_sha="abcabcabcabcabca"))
        self.assertEqual(props[0].kind, "merged"); self.assertIn("MERGED --merged-sha abcabcabcabcabca", props[0].suggested_cmd)
        props = reconcile.compare(self.data("AI_REVIEW"), self.facts(merged=True, merged_sha="abcabcabcabcabca"))
        self.assertEqual(props[0].kind, "merged"); self.assertIsNone(props[0].suggested_cmd); self.assertIn("anomaly", props[0].message)
    def test_gate_red_only_on_failure(self):
        d = self.data("READY", gate={"name": "pdf-review", "head": H, "result": "pass"})
        f = self.facts(human_threads_open=0); f["jsfiller#1"].checks["pdf-review"] = "failure"
        self.assertIn("gate_red", self.kinds(reconcile.compare(d, f)))
        f["jsfiller#1"].checks["pdf-review"] = "pending"
        self.assertNotIn("gate_red", self.kinds(reconcile.compare(d, f)))
    def test_gate_unknown_when_contexts_truncated(self):
        d = self.data("READY", gate={"name": "pdf-review", "head": H, "result": "pass"})
        f = self.facts(human_threads_open=0, checks_complete=False); del f["jsfiller#1"].checks["pdf-review"]
        self.assertIn("gate_unknown", self.kinds(reconcile.compare(d, f)))
    def test_ci_red_copilot_thread_draft_mismatch_unsigned(self):
        d = self.data("READY", ci={"head": H, "status": "success"}, copilot={"head": H, "open_threads": 0})
        f = self.facts(human_threads_open=0, ci="failure", copilot_threads_open=2, head_signed=False)
        kinds = self.kinds(reconcile.compare(d, f))
        for k in ("ci_red", "copilot_thread", "unsigned"):
            self.assertIn(k, kinds)
        d = self.data("ON_HUMAN_REVIEW", human=HUMAN)
        self.assertIn("draft_mismatch", self.kinds(reconcile.compare(d, self.facts(human_threads_open=0, approvals=[], draft=True))))
    def test_jira_unsynced(self):
        d = self.data("AI_REVIEW"); d["prs"]["jsfiller#1"]["jira"]["synced"] = False
        self.assertIn("jira_unsynced", self.kinds(reconcile.compare(d, self.facts(human_threads_open=0))))
    def test_approval_unlogged_when_ledger_lacks_the_lead_terminal_line(self):
        d = self.data("READY")
        d["awaiting_human"] = [{"id": "ah-1", "type": "send", "pr": "jsfiller#1", "approved_at": "2026-10-13T10:00Z"},
                               {"id": "ah-2", "type": "merge", "pr": "jsfiller#1", "approved_at": "2026-10-13T10:00Z"},
                               {"id": "ah-3", "type": "merge", "pr": "jsfiller#1", "approved_at": None}]
        ledger = ("# Ledger\n\n- 2026-10-13 10:00 UTC approved ah-1 (send jsfiller#1 by lead) approved_via: lead-terminal\n"
                  "- 2026-10-13 10:01 UTC approved ah-2 (merge jsfiller#1 by lead)\n")
        props = reconcile.compare_ledger(d, ledger)
        self.assertEqual([(p.kind, p.pr) for p in props], [("approval_unlogged", "ah-2")])
        self.assertIn("lead-terminal", props[0].message)
        props = reconcile.compare_ledger(d, "")
        self.assertEqual([p.pr for p in props], ["ah-1", "ah-2"])
        d["awaiting_human"][0]["approved_via"] = "lead-terminal"
        self.assertEqual([p.pr for p in reconcile.compare_ledger(d, "")], ["ah-1", "ah-2"])  # the field alone proves nothing

    def test_compare_never_mutates_state(self):
        d = self.data("READY"); before = json.dumps(d, sort_keys=True)
        reconcile.compare(d, self.facts(head="ffffffff66666666", ci="success"))
        self.assertEqual(json.dumps(d, sort_keys=True), before)
