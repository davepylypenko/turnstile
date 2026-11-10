import datetime, json, pathlib, unittest
from turnstile_cli import repo_cmd, rules
from tests.test_pass import PassCmd, LINK, run_capture, opts, H
from tests.test_sync import out_of


class SentAt(unittest.TestCase):
    def setUp(self):
        self.p = PassCmd("test_refuses_without_evidence_and_writes_nothing"); self.p.setUp()
        self.d = self.p.d

    def human(self):
        return self.p.data()["prs"]["jsfiller#1"]["evidence"]["human"]

    def test_sent_at_is_the_time_in_the_slack_permalink_not_the_pass_time(self):
        self.p.to_human()
        expected = datetime.datetime.fromtimestamp(1760000000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(self.human()["sent_at"], expected)
        self.assertEqual(rules.slack_sent_at("https://x.slack.com/archives/C1/p1794233127291529"), "2026-11-09T14:05:27Z")
        self.assertIsNone(rules.slack_sent_at("https://x.slack.com/archives/C1"))

    def test_sent_at_flag_corrects_an_existing_record_and_is_validated(self):
        self.p.to_human()
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(sent_at="2026-11-09T14:05:27Z"), self.p.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.human()["sent_at"], "2026-11-09T14:05:27Z")
        self.assertIn("evidence.human.sent_at corrected", (self.d / "ledger.md").read_text())
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(sent_at="yesterday"), self.p.io)
        self.assertEqual(rc, 2); self.assertIn("--sent-at", out); self.assertEqual(self.human()["sent_at"], "2026-11-09T14:05:27Z")


class RepoSet(unittest.TestCase):
    def setUp(self):
        self.p = PassCmd("test_refuses_without_evidence_and_writes_nothing"); self.p.setUp()
        self.d = self.p.d

    def repo(self, name="docs-platform"):
        return self.p.data()["epic"]["repos"][name]

    def test_set_writes_the_keys_through_the_writer(self):
        rc, out = out_of(repo_cmd.set_, self.d, "docs-platform", ["gate=pdf-review", "gate_check=gate / gate", "copilot=false", "ci_ignore=a,b"], io=self.p.io)
        self.assertEqual(rc, 0, out)
        r = self.repo(); self.assertEqual((r["gate"], r["gate_check"], r["copilot"], r["ci_ignore"]), ("pdf-review", "gate / gate", False, ["a", "b"]))
        self.assertEqual(len(self.p.io.commits), 1); self.assertEqual(self.p.io.pushes, ["epic/myd-1"])
        self.assertIn("repo docs-platform set", (self.d / "ledger.md").read_text())
        rc, out = out_of(repo_cmd.set_, self.d, "docs-platform", ["gate_check=null"], io=self.p.io)
        self.assertEqual(rc, 0, out); self.assertIsNone(self.repo()["gate_check"])

    def test_ci_ignore_takes_a_json_list_or_a_comma_list(self):
        rc, out = out_of(repo_cmd.set_, self.d, "docs-platform", ['ci_ignore=["CodeRabbit", "WIP", "gate / gate"]'], io=self.p.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.repo()["ci_ignore"], ["CodeRabbit", "WIP", "gate / gate"])
        self.assertIn('ci_ignore=["CodeRabbit", "WIP", "gate / gate"]', out)
        rc, out = out_of(repo_cmd.set_, self.d, "docs-platform", ["ci_ignore=CodeRabbit, WIP,gate / gate"], io=self.p.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.repo()["ci_ignore"], ["CodeRabbit", "WIP", "gate / gate"])
        rc, out = out_of(repo_cmd.set_, self.d, "docs-platform", ["ci_ignore=[]"], io=self.p.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.repo()["ci_ignore"], [])
        before = (self.d / "state.json").read_text()
        for bad in ('ci_ignore=["CodeRabbit"', 'ci_ignore=[1, 2]', 'ci_ignore=["a", ["b"]]'):
            rc, out = out_of(repo_cmd.set_, self.d, "docs-platform", [bad], io=self.p.io)
            self.assertEqual(rc, 2, bad); self.assertIn("MISSING ci_ignore", out); self.assertIn("JSON list", out)
        self.assertEqual((self.d / "state.json").read_text(), before)

    def test_unknown_repo_key_or_value_is_refused_and_writes_nothing(self):
        before = (self.d / "state.json").read_text()
        for name, args in [("nope", ["gate=x"]), ("docs-platform", ["bogus=1"]), ("docs-platform", ["copilot=maybe"]), ("docs-platform", ["slack="]), ("docs-platform", [])]:
            rc, out = out_of(repo_cmd.set_, self.d, name, args, io=self.p.io); self.assertEqual(rc, 2, (name, args)); self.assertIn("MISSING", out)
        self.assertEqual((self.d / "state.json").read_text(), before); self.assertEqual(self.p.io.commits, [])


if __name__ == "__main__":
    unittest.main()
