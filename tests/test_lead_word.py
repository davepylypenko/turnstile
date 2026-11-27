import json, os, pathlib, shutil, tempfile, unittest

from tests.test_hooks import FIX, hook
from turnstile_cli import config
from turnstile_cli.errors import TurnstileError

MERGE = "gh pr merge 13 --repo pdffiller/jsfiller --squash"
REPLY = "gh api -X POST repos/pdffiller/other/pulls/7/comments/101/replies -f body='Fixed in abc1234'"


class LeadWordGuard(unittest.TestCase):
    """Lead rule 2026-11-27: with lead_word in the lead's user config, the orchestrator merges with `gh pr merge` and replies on any
    review thread on the lead's word in chat; subagents, --admin/--auto, computed PRs and GraphQL/REST merges stay refused."""

    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")
        self.cfg = pathlib.Path(tempfile.mkdtemp()) / "config.json"

    def bash(self, cmd, actions=None, **payload):
        if actions is None:
            self.cfg.unlink(missing_ok=True)
        else:
            self.cfg.write_text(json.dumps({"lead_word": actions}))
        p = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(self.ws)}; p.update(payload)
        return hook("guard_bash.py", p, self.ws, env={"TURNSTILE_USER_CONFIG": str(self.cfg), "PATH": "/usr/bin:/bin"})

    def assertBlocked(self, cmd, rule, actions=None, **payload):
        r = self.bash(cmd, actions, **payload); self.assertEqual(r.returncode, 2, cmd); self.assertIn(rule, r.stderr, cmd)

    def assertAllowed(self, cmd, actions=None, **payload):
        r = self.bash(cmd, actions, **payload); self.assertEqual(r.returncode, 0, cmd + "\n" + r.stderr)

    def test_merge_stays_refused_without_the_setting(self):
        self.assertBlocked(MERGE, "rule merge")
        self.assertBlocked(MERGE, "rule merge", ["reply"])

    def test_orchestrator_merges_on_the_lead_word(self):
        for cmd in [MERGE, "gh pr merge 13 --squash", "gh -R pdffiller/jsfiller pr merge 13 --merge --delete-branch", "gh pr merge 13 -R o/r --squash && echo ok"]:
            self.assertAllowed(cmd, ["merge"])

    def test_risky_merges_stay_refused(self):
        for cmd in ["gh pr merge 13 --squash --admin", "gh pr merge 13 --auto --squash", "gh pr merge $N --squash", "gh pr merge `echo 1`"]:
            self.assertBlocked(cmd, "rule merge", ["merge"])
        self.assertBlocked("gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { clientMutationId } }'",
                           "graphql-merge-or-ready", ["merge"])
        self.assertBlocked("gh api -X PUT repos/pdffiller/jsfiller/pulls/13/merge", "rest-merge", ["merge"])

    def test_subagents_never_merge(self):
        self.assertBlocked(MERGE, "rule merge", ["merge"], agent_type="turnstile:implementer")

    def test_orchestrator_replies_on_the_lead_word(self):
        self.assertBlocked(REPLY, "reply-unknown-pr")
        self.assertAllowed(REPLY, ["reply"])
        self.assertBlocked(REPLY, "reply-unknown-pr", ["reply"], agent_type="turnstile:comments-handler")
        self.assertBlocked("gh api -X POST repos/pdffiller/other/pulls/$N/comments/101/replies -f body=x", "rest-computed-route", ["reply"])

    def test_other_review_writes_stay_refused(self):
        self.assertBlocked("gh pr comment 7 --body x", "issue-comment", ["merge", "reply"])
        self.assertBlocked("gh api -X POST repos/pdffiller/other/pulls/7/comments -f body=x -f commit_id=a -f path=b -F line=1", "review-comment",
                           ["merge", "reply"])


class LeadWordConfig(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(config.parse_value("lead_word", "reply, merge"), ["merge", "reply"])
        with self.assertRaises(TurnstileError):
            config.parse_value("lead_word", "merge,approve")

    def test_user_layer_only_and_shape_checked(self):
        self.assertEqual(config.lead_word_actions({"lead_word": ["merge"]}), {"merge"})
        self.assertEqual(config.lead_word_actions({"lead_word": ["push"]}), set())
        self.assertEqual(config.lead_word_actions({}), set())
        eff = config.effective({"epic": {"lead_word": ["merge"]}}, {})
        self.assertEqual(eff["lead_word"], {"value": [], "source": "default"})
        self.assertIn("lead_word = none (default)", config.lines(eff))


if __name__ == "__main__":
    unittest.main()
