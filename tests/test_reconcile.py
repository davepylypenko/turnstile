import copy, json, pathlib, unittest
from turnstile_cli import github, reconcile

D = pathlib.Path(__file__).parent / "fixtures"
FIX = json.loads((D / "state_min.json").read_text())
PAYLOAD = json.loads((D / "gh_pr_13222.json").read_text())

class Parse(unittest.TestCase):
    def test_parse(self):
        f = github.parse("jsfiller#1", PAYLOAD)
        self.assertTrue(f.head.startswith("aaaaaaaa1111"))
        self.assertEqual(f.ci, "success"); self.assertEqual(f.checks["pdf-review"], "success")
        self.assertEqual(f.human_threads_open, 1); self.assertEqual(f.copilot_threads_open, 0)
        self.assertEqual(f.approvals, ["isachivka"]); self.assertFalse(f.merged)

class Compare(unittest.TestCase):
    def facts(self, **kw):
        f = github.parse("jsfiller#1", PAYLOAD)
        for k, v in kw.items(): setattr(f, k, v)
        return {"jsfiller#1": f}
    def data(self, state, **ev):
        d = copy.deepcopy(FIX); p = d["prs"]["jsfiller#1"]; p["state"] = state; p["evidence"].update(ev); return d
    def test_push_after_send_proposes_rework(self):
        d = self.data("ON_HUMAN_REVIEW", human={"head": "aaaaaaaa11111111", "sent_head": "aaaaaaaa11111111", "slack_permalink": "u", "approved": "ah-1", "open_threads": 0, "approvals": []})
        props = reconcile.compare(d, self.facts(head="ffffffff66666666"))
        self.assertEqual(props[0].kind, "head_changed"); self.assertIn("REWORK", props[0].suggested_cmd)
    def test_human_thread_proposes_rework(self):
        d = self.data("ON_HUMAN_REVIEW", human={"head": "aaaaaaaa11111111", "sent_head": "aaaaaaaa11111111", "slack_permalink": "u", "approved": "ah-1", "open_threads": 0, "approvals": []})
        props = reconcile.compare(d, self.facts())
        self.assertEqual([p.kind for p in props], ["human_thread"])
    def test_approved_with_no_threads(self):
        d = self.data("ON_HUMAN_REVIEW", human={"head": "aaaaaaaa11111111", "sent_head": "aaaaaaaa11111111", "slack_permalink": "u", "approved": "ah-1", "open_threads": 0, "approvals": []})
        props = reconcile.compare(d, self.facts(human_threads_open=0))
        self.assertEqual(props[0].kind, "approved"); self.assertIn("--approvals isachivka", props[0].suggested_cmd)
    def test_merged(self):
        props = reconcile.compare(self.data("APPROVED"), self.facts(merged=True, merged_sha="abcabcabcabcabca"))
        self.assertEqual(props[0].kind, "merged"); self.assertIn("MERGED --merged-sha abcabcabcabcabca", props[0].suggested_cmd)
    def test_gate_red_against_recorded_pass(self):
        d = self.data("READY", gate={"name": "pdf-review", "head": "aaaaaaaa11111111", "result": "pass"})
        f = self.facts(human_threads_open=0); f["jsfiller#1"].checks["pdf-review"] = "failure"
        self.assertIn("gate_red", [p.kind for p in reconcile.compare(d, f)])
    def test_jira_unsynced(self):
        d = self.data("AI_REVIEW"); d["prs"]["jsfiller#1"]["jira"]["synced"] = False
        self.assertIn("jira_unsynced", [p.kind for p in reconcile.compare(d, self.facts(human_threads_open=0))])
