import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"
COPILOT = "copilot-pull-request-reviewer[bot]"

def hook(name, payload, cwd, env=None):
    e = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(ROOT)); e.pop("TURNSTILE_MIGRATION", None); e.update(env or {})
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(ROOT / "hooks" / name)], input=data, cwd=cwd, capture_output=True, text=True, env=e)

class BashGuard(unittest.TestCase):
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")

    def bash(self, cmd):
        return hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(self.ws)}, self.ws)

    def assertBlocked(self, cmds, rule=None):
        for cmd in cmds:
            r = self.bash(cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn("blocked by rule", r.stderr, cmd)
            if rule:
                self.assertIn(rule, r.stderr, cmd)

    def assertAllowed(self, cmds):
        for cmd in cmds:
            r = self.bash(cmd); self.assertEqual(r.returncode, 0, cmd + "\n" + r.stderr)

    def test_blocks_round2_evasions(self):
        self.assertBlocked(['git -C "/my dir" push --force', '"git" push --force', "gh --repo=o/r pr merge 1", "gh pr --repo o/r merge 1",
                            'gh "pr" merge 1', "gh pr 'merge' 1", "gh api --method=PUT repos/o/r/pulls/1/merge",
                            "gh api -XPUT repos/o/r/pulls/1/merge", "git pull --rebase", "git pull -r origin x"])
        self.assertAllowed(["git pull origin develop", "gh pr view 1 --repo o/r"])

    def test_blocks(self):
        self.assertBlocked(["gh pr merge 1", "gh pr ready 1", "gh pr edit 1 --add-reviewer x", "git push --force origin x", "git push -f",
                            "git rebase develop", "git commit --no-gpg-sign -m x", "git commit -m 'x\n\nCo-Authored-By: a'",
                            "gh api -X POST repos/o/r/pulls/1/requested_reviewers -f 'reviewers[]=isachivka'",
                            "gh workflow run x -f service_github_tag= -f y=1", "git push -fu origin x", "git push origin x \"--force\"",
                            "gh workflow run x -f \"service_github_tag=\"", "gh workflow run x -f service_github_tag=''"])

    def test_global_options_before_the_subcommand(self):
        self.assertBlocked(["git -C /tmp/x push --force origin y", "git -c core.x=y rebase develop", "gh -R pdffiller/jsfiller pr merge 1",
                            "gh --repo pdffiller/jsfiller pr ready 1", "git -C dir -c a=b push -f", "cd x && git push --force-with-lease"])

    def test_rest_and_graphql_routes(self):
        self.assertBlocked(["gh api -X PUT repos/pdffiller/jsfiller/pulls/13222/merge", "gh api graphql -f query='mutation{mergePullRequest(input:{})}'",
                            "gh api graphql -f query='mutation { markPullRequestReadyForReview(input: {pullRequestId: \"x\"}) { pullRequest { id } } }'",
                            "gh api graphql -f query='mutation{requestReviews(input:{})}'", "gh api -X POST repos/o/r/pulls/1/ready_for_review",
                            "git -c commit.gpgsign=false commit -m x", "git -c commit.gpgsign=false -c user.name=t commit -m x"])

    def test_reviewer_requests(self):
        self.assertBlocked(["gh api -X POST repos/o/r/pulls/1/requested_reviewers -f 'reviewers[]=%s' -f 'reviewers[]=isachivka'" % COPILOT,
                            "gh api -X POST repos/o/r/pulls/1/requested_reviewers --input body.json",
                            "gh api repos/o/r/pulls/1/requested_reviewers -f reviewers[]=lMakDen"], "human-reviewer-request")
        self.assertAllowed(["gh api -X POST repos/o/r/pulls/1/requested_reviewers -f 'reviewers[]=%s'" % COPILOT,
                            "gh api repos/o/r/pulls/1/requested_reviewers", "gh api -X GET repos/o/r/pulls/1/requested_reviewers --jq '.users[].login'"])

    def test_trailer_and_footer_only_on_writes(self):
        self.assertBlocked(["gh pr create --title x --body 'y\n\nGenerated with [Claude Code]'", "gh pr edit 1 --body 'Generated with [Claude Code](u)'",
                            "git commit -m 'x' -m 'Co-Authored-By: Claude <n@a>'", "gh api -X PATCH repos/o/r/pulls/1 -f body='Generated with [Claude Code]'"])
        self.assertAllowed(["git log --grep Co-Authored-By", "grep -rn 'Co-Authored-By' .", "gh pr view 1 --json body | grep 'Generated with [Claude Code]'"])

    def test_allows(self):
        self.assertAllowed(["git push origin feature/x", "gh pr view 1", "git commit -S -m 'feat: x'", "gh workflow run x -f service_github_tag=l2f-funnel-abc",
                            "gh workflow run x -f service_github_tag='v1.2'", "git push origin x && rm -f tmp", "git push origin x; echo +1",
                            "git push --follow-tags origin x", "git -C /tmp/x status", "gh -R pdffiller/jsfiller pr view 1", "git -c a=b log",
                            "cat delivery/state.json", "jq .prs delivery/state.json", "turnstile pass pr jsfiller#1 READY --head a", "turnstile status",
                            "git merge origin/develop", "gh api repos/o/r/pulls/1/merge"])

    def test_state_json_writes(self):
        self.assertBlocked(["echo '{}' > delivery/state.json", "cat x >> /ws/delivery/state.json", "sed -i '' 's/DEV/READY/' delivery/state.json",
                            "sed --in-place s/a/b/ delivery/state.json", "jq '.x=1' state.json | tee delivery/state.json",
                            "python3 -c \"import json; json.dump({}, open('delivery/state.json','w'))\"", "cp other.json delivery/state.json",
                            "mv tmp.json delivery/state.json", "rm delivery/state.json", "python -c 'open(\"state.json\",\"w\")'"], "delivery-write")
        self.assertAllowed(["echo delivery > .turnstile", "python3 -c 'print(1)' > out.txt", "sed -i '' s/a/b/ README.md"])

    def test_delivery_dir_writes_blocked_through_any_interpreter(self):
        # R2-2: a command that mentions state.json or the delivery dir and is not read-only is refused, whatever the tool
        d = str(self.ws / "delivery")
        self.assertBlocked(["perl -pi -e 's/DEV/READY/' delivery/state.json", "node -e \"require('fs').writeFileSync('delivery/state.json','{}')\"",
                            "ruby -e 'File.write(\"delivery/state.json\", \"{}\")'", "python3 - <<EOF\nimport json\nopen('delivery/' + 'state.json','w')\nEOF",
                            "sed -i '' s/a/b/ state.*", "rm -rf %s/reports" % d, "echo x > %s/ledger.md" % d, "cd delivery && rm ledger.md",
                            "cat > delivery/reports/X.md <<EOF\nhi\nEOF", "mkdir delivery/x", "cat delivery/state.json | python3",
                            "cat other.json | tee delivery/state.json", "cp -r delivery /tmp/d", "jq '.x=1' delivery/state.json > tmp && mv tmp delivery/state.json",
                            "perl -e 'print 1' > delivery/state.json", "git add delivery/state.json && git commit -m x"], "delivery-write")
        self.assertBlocked(["git checkout HEAD~3 -- delivery/state.json", "git restore delivery/state.json", "git stash push -- delivery",
                            "git reset --hard HEAD~1 -- delivery/", "git -C delivery checkout .", "git checkout -- %s/state.json" % d,
                            "git restore --source=HEAD~1 state.json"], "delivery-git-restore")
        self.assertAllowed(["cat delivery/state.json", "jq .prs delivery/state.json", "grep READY delivery/state.json | head -3", "git diff -- delivery/",
                            "git log --oneline -- delivery/state.json", "git show HEAD:delivery/state.json", "less delivery/ledger.md",
                            "cd delivery && turnstile status", "ls -la delivery", "python3 -m turnstile_cli status --delivery delivery",
                            "scripts/turnstile reconcile --delivery %s" % d, "git -C delivery status", "head -50 delivery/ledger.md",
                            "tail -n 5 delivery/ledger.md 2>/dev/null", "diff delivery/state.json other.json", "wc -l delivery/ledger.md",
                            "find delivery -name '*.md'", "git -C delivery push origin epic/x", "turnstile --delivery %s pass pr jsfiller#1 READY" % d,
                            "sed -n 1,5p delivery/ledger.md", "cat delivery/state.json | jq .prs | grep READY", "git checkout feature/x",
                            "git stash", "git reset --hard origin/develop", "echo hi > out.txt"])

    def test_approve_and_lead_markers_are_blocked_in_every_form(self):
        # R2-1: the lead approves only from the Claude Code prompt with the `!` prefix, outside the model's tool calls.
        # Any model-issued command that carries the approve command or the lead/migration markers is refused.
        self.assertBlocked(["turnstile approve ah-3", "scripts/turnstile approve ah-3", "turnstile --delivery d approve ah-3",
                            "python3 -m turnstile_cli approve ah-3", "python3 -c 'from turnstile_cli import pass_cmd; pass_cmd.approve(\"d\", \"ah-3\")'",
                            "export TURNSTILE_LEAD=1; turnstile approve ah-3", "TURNSTILE_LEAD=1 turnstile approve ah-3",
                            "TURNSTILE_LEAD=1 scripts/turnstile approve ah-3", "env TURNSTILE_LEAD=1 turnstile approve ah-3",
                            'bash -c "TURNSTILE_LEAD=1 turnstile approve ah-3"', "T\\URNSTILE_LEAD=1 turnstile approve ah-3",
                            "\"turnstile\" 'approve' ah-3", "turnstile   approve ah-3", "bash <<EOF\nTURNSTILE_LEAD=1 turnstile approve ah-1\nEOF",
                            "echo $TURNSTILE_LEAD", "export TURNSTILE_LEAD=1", "TURNSTILE_MIGRATION=1 cp new.json delivery/state.json",
                            "TURNSTILE_MIGRATION=1 python3 gen.py > delivery/state.json", "env | grep TURNSTILE_MIGRATION"], "lead-")
        self.assertAllowed(["git commit -m 'feat(turnstile): approve flow'", "turnstile status", "turnstile pass pr jsfiller#1 READY --head a"])

    def test_malformed_payload_blocks(self):
        for payload in ("{}", "[]", "not json", json.dumps({"tool_input": {"command": 5}}), json.dumps({"tool_input": "x"})):
            self.assertEqual(hook("guard_bash.py", payload, self.ws).returncode, 2, payload)

    def test_hooks_json_wraps_commands_to_fail_closed(self):
        h = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        cmds = [x["command"] for ev in h.values() for m in ev for x in m["hooks"]]
        self.assertTrue(cmds)
        for c in cmds:
            self.assertTrue(c.endswith("|| exit 2"), c)
        self.assertNotIn("PostToolUse", h)
        matchers = [m["matcher"] for m in h["PreToolUse"]]
        self.assertIn("Edit|Write|MultiEdit", matchers)

class SlackGuard(unittest.TestCase):
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")

    def state(self):
        return json.loads((self.ws / "delivery" / "state.json").read_text())

    def write(self, d):
        (self.ws / "delivery" / "state.json").write_text(json.dumps(d))

    def ready_with(self, pr="jsfiller#1", state="READY", **entry):
        d = self.state(); d["prs"][pr]["state"] = state
        e = {"id": "ah-1", "owner": "lead", "type": "send", "pr": pr, "created_at": "x", "payload": None, "approved_at": "2026-10-13T10:00Z"}
        e.update(entry); d["awaiting_human"] = [e]; self.write(d)

    def slack(self, text, channel="C1", tool="mcp__plugin_slack_slack__slack_send_message"):
        return hook("guard_slack.py", {"tool_name": tool, "tool_input": {"channel_id": channel, "text": text}, "cwd": str(self.ws)}, self.ws)

    MSG = "PR: <https://github.com/pdffiller/jsfiller/pull/1>"

    def test_blocks_without_approval(self):
        r = self.slack(self.MSG); self.assertEqual(r.returncode, 2)
        r = self.slack("hello"); self.assertEqual(r.returncode, 2)
        self.ready_with(approved_at=None)
        self.assertEqual(self.slack(self.MSG).returncode, 2)

    def test_allows_approved_send_of_ready_pr_once_and_records_use(self):
        self.ready_with()
        r = self.slack(self.MSG); self.assertEqual(r.returncode, 0, r.stderr)
        e = self.state()["awaiting_human"][0]
        self.assertTrue(e["used_at"]); self.assertEqual(e["used_channel"], "C1")
        self.assertIn("slack send", (self.ws / "delivery" / "ledger.md").read_text())
        r = self.slack(self.MSG); self.assertEqual(r.returncode, 2); self.assertIn("already used", r.stderr)

    def test_send_needs_ready_reply_needs_rework(self):
        self.ready_with(state="AI_REVIEW"); self.assertEqual(self.slack(self.MSG).returncode, 2)
        self.ready_with(state="REWORK", type="reply"); self.assertEqual(self.slack(self.MSG).returncode, 0)
        self.ready_with(state="ON_HUMAN_REVIEW", type="reply"); self.assertEqual(self.slack(self.MSG).returncode, 2)
        self.ready_with(state="READY", type="merge"); self.assertEqual(self.slack(self.MSG).returncode, 2)

    def test_consumed_or_voided_entries_do_not_unlock(self):
        self.ready_with(consumed_at="x"); self.assertEqual(self.slack(self.MSG).returncode, 2)
        self.ready_with(voided_at="x"); self.assertEqual(self.slack(self.MSG).returncode, 2)

    def test_channel_must_be_the_repo_channel(self):
        self.ready_with()
        r = self.slack(self.MSG, channel="C9"); self.assertEqual(r.returncode, 2); self.assertIn("channel", r.stderr)
        self.assertIsNone(self.state()["awaiting_human"][0].get("used_at"))

    def test_every_pr_in_the_message_needs_its_own_entry(self):
        self.ready_with()
        two = self.MSG + "\nLocales: <https://github.com/pdffiller/docs-platform/pull/2>"
        self.assertEqual(self.slack(two).returncode, 2)

    def test_schedule_and_draft_are_guarded_too(self):
        self.ready_with()
        self.assertEqual(self.slack(self.MSG, tool="mcp__plugin_slack_slack__slack_schedule_message").returncode, 0)
        import re
        m = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
        m = next(x["matcher"] for x in m if "slack" in x["matcher"])
        for tool in ("mcp__plugin_slack_slack__slack_send_message", "mcp__plugin_slack_slack__slack_send_message_draft", "mcp__plugin_slack_slack__slack_schedule_message"):
            self.assertTrue(re.fullmatch(m, tool), tool)

    def test_fails_closed_on_broken_state(self):
        (self.ws / "delivery" / "state.json").write_text("{not json")
        self.assertEqual(self.slack(self.MSG).returncode, 2)
        shutil.rmtree(self.ws / "delivery")
        self.assertEqual(self.slack(self.MSG).returncode, 2)

    def test_fails_closed_on_unexpected_shape(self):
        self.write({"prs": [], "awaiting_human": [{"pr": "jsfiller#1", "type": "send", "approved_at": "x"}]})
        self.assertEqual(self.slack(self.MSG).returncode, 2)

class StateEditGuard(unittest.TestCase):
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")

    def edit(self, path, tool="Edit", env=None):
        return hook("guard_state_edit.py", {"tool_name": tool, "tool_input": {"file_path": path}, "cwd": str(self.ws)}, self.ws, env=env)

    def test_blocks_state_json_unless_migration(self):
        p = str(self.ws / "delivery" / "state.json")
        for tool in ("Edit", "Write", "MultiEdit"):
            r = self.edit(p, tool); self.assertEqual(r.returncode, 2, tool); self.assertIn("turnstile pass", r.stderr)
        self.assertEqual(self.edit(p, env={"TURNSTILE_MIGRATION": "1"}).returncode, 0)
        self.assertEqual(self.edit(str(self.ws / "delivery" / "ledger.md")).returncode, 0)
        self.assertEqual(self.edit(str(self.ws / "delivery" / "reports" / "state.json.md")).returncode, 0)
