import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"

def hook(name, payload, cwd):
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(ROOT))
    return subprocess.run([sys.executable, str(ROOT / "hooks" / name)], input=json.dumps(payload), cwd=cwd, capture_output=True, text=True, env=env)

class Hooks(unittest.TestCase):
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")

    def bash(self, cmd):
        return hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(self.ws)}, self.ws)

    def test_bash_blocks(self):
        for cmd in ["gh pr merge 1", "gh pr ready 1", "gh pr edit 1 --add-reviewer x", "git push --force origin x", "git push -f",
                    "git rebase develop", "git commit --no-gpg-sign -m x", "git commit -m 'x\n\nCo-Authored-By: a'",
                    "gh api -X POST repos/o/r/pulls/1/requested_reviewers -f 'reviewers[]=isachivka'",
                    "gh workflow run x -f service_github_tag= -f y=1"]:
            r = self.bash(cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn("blocked by rule", r.stderr)

    def test_bash_allows(self):
        for cmd in ["git push origin feature/x", "gh pr view 1", "gh api -X POST repos/o/r/pulls/1/requested_reviewers -f 'reviewers[]=copilot-pull-request-reviewer[bot]'",
                    "git commit -S -m 'feat: x'", "gh workflow run x -f service_github_tag=l2f-funnel-abc"]:
            self.assertEqual(self.bash(cmd).returncode, 0, cmd)

    def slack(self, text):
        return hook("guard_slack.py", {"tool_name": "mcp__plugin_slack_slack__slack_send_message", "tool_input": {"channel_id": "C1", "text": text}, "cwd": str(self.ws)}, self.ws)

    def test_slack_blocks_without_approval(self):
        r = self.slack("PR: <https://github.com/pdffiller/jsfiller/pull/1>"); self.assertEqual(r.returncode, 2)
        r = self.slack("hello"); self.assertEqual(r.returncode, 2)

    def test_slack_allows_approved_send_of_ready_pr(self):
        d = json.loads((self.ws / "delivery" / "state.json").read_text())
        d["prs"]["jsfiller#1"]["state"] = "READY"
        d["awaiting_human"] = [{"id": "ah-1", "owner": "lead", "type": "send", "pr": "jsfiller#1", "created_at": "x", "payload": None, "approved_at": "2026-10-13T10:00Z"}]
        (self.ws / "delivery" / "state.json").write_text(json.dumps(d))
        self.assertEqual(self.slack("PR: <https://github.com/pdffiller/jsfiller/pull/1>").returncode, 0)

    def test_slack_fails_closed_on_broken_state(self):
        (self.ws / "delivery" / "state.json").write_text("{not json")
        r = self.slack("PR: <https://github.com/pdffiller/jsfiller/pull/1>"); self.assertEqual(r.returncode, 2)
        shutil.rmtree(self.ws / "delivery")
        r = self.slack("PR: <https://github.com/pdffiller/jsfiller/pull/1>"); self.assertEqual(r.returncode, 2)

    def test_state_edit_warns(self):
        r = hook("guard_state_edit.py", {"tool_name": "Edit", "tool_input": {"file_path": str(self.ws / "delivery" / "state.json")}, "cwd": str(self.ws)}, self.ws)
        self.assertEqual(r.returncode, 0); self.assertIn("turnstile pass", r.stdout)
