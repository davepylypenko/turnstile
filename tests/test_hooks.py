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

    def test_curl_o_writes_the_figma_reference_into_evidence_only(self):
        # round 2 R2-6: figma.png comes from a URL (download_assets / get_screenshot / the REST export) through `curl -o`
        ev = str(self.ws / "delivery" / "evidence" / "S1" / "TP-1")
        url = "https://figma-alpha-api.s3.us-west-2.amazonaws.com/images/abc?X-Amz-Expires=600&X-Amz-Signature=def"
        self.assertAllowed(["mkdir -p %s && curl -sSf -o %s/figma.png \"%s\"" % (ev, ev, url),
                            "curl --output %s/figma.png -L '%s'" % (ev, url),
                            "curl -s -H \"X-Figma-Token: $FIGMA_TOKEN\" \"https://api.figma.com/v1/images/KEY?ids=1-2&format=png&scale=2\" | jq -r '.images[\"1:2\"]'",
                            "curl -sSf -o %s/figma.png \"$(curl -s -H \"X-Figma-Token: $FIGMA_TOKEN\" 'https://api.figma.com/v1/images/KEY?ids=1-2&format=png' | jq -r '.images[\"1:2\"]')\"" % ev])
        d = str(self.ws / "delivery")
        self.assertBlocked(["curl -o %s/state.json %s" % (d, url), "curl -o %s/ledger.md %s" % (d, url), "curl -o %s/figma.png %s" % (d, url),
                            "curl -o %s/../state.json %s" % (ev, url), "curl -o %s/$CASE/figma.png %s" % (str(self.ws / "delivery" / "evidence"), url),
                            "curl -o delivery/evidence/S1/../../board.html %s" % url], "delivery-write")

    def test_tree_wide_git_resets_in_the_knowledge_worktree_are_blocked(self):
        # round 2 R2-8: `git checkout -- .` at the worktree root rolls state.json and ledger.md back without naming them
        (self.ws / ".git").mkdir(); (self.ws / "docs").mkdir(); (self.ws / "docs" / "x.md").write_text("x")
        self.assertBlocked(["git checkout -- .", "git restore .", "git restore --staged --worktree .", "git clean -fd", "git clean -fdx",
                            "git checkout HEAD~3 -- .", "git reset --hard", "git reset --hard HEAD~1", "git reset", "git stash", "git stash pop",
                            "git checkout develop", "git checkout -b other", "git switch main", "git checkout -- :/", "git restore -- ..",
                            "git checkout -- delivery", "git -C %s checkout -- ." % self.ws, "cd docs && git checkout -- ..",
                            "git checkout -- %s" % self.ws], "knowledge-worktree-reset")
        self.assertAllowed(["git checkout -- docs/x.md", "git restore docs/x.md", "git stash list", "git stash show -p", "git clean -n",
                            "git clean --dry-run -d", "git status", "git diff", "git log --oneline"])
        other = pathlib.Path(tempfile.mkdtemp())  # a repo that is not the knowledge worktree: tree-wide resets are its own business
        r = hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": "git checkout -- ."}, "cwd": str(other)}, other)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": "git -C %s checkout -- ." % self.ws}, "cwd": str(other)}, other)
        self.assertEqual(r.returncode, 2); self.assertIn("knowledge-worktree-reset", r.stderr)

    def test_tester_role_cannot_push_commit_or_write_prs(self):
        # round 2 R2-12: the tester's hooks run the guard with TURNSTILE_ROLE=tester (or the payload names the agent); pushes are then blocked
        role = {"TURNSTILE_ROLE": "tester"}
        for cmd in ["git push origin x", "git push", "git -C /tmp/r push -u origin feature/x", "git commit -m 'x'", "gh pr comment 1 --body x",
                    "gh pr review 1 --approve", "gh pr create --title x", "gh pr edit 1 --body x", "gh api -X POST repos/o/r/issues/1/comments -f body=x",
                    "gh issue comment 1 --body x"]:
            r = hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(self.ws)}, self.ws, env=role)
            self.assertEqual(r.returncode, 2, cmd); self.assertIn("tester", r.stderr, cmd)
        ev = str(self.ws / "delivery" / "evidence" / "S1" / "TP-1")
        for cmd in ["git log --oneline -3", "git status", "gh pr view 1 --repo o/r", "gh api repos/o/r/pulls/1", "npx playwright screenshot https://x %s/env.png" % ev,
                    "mkdir -p %s" % ev, "git fetch origin", "git diff HEAD~1"]:
            r = hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(self.ws)}, self.ws, env=role)
            self.assertEqual(r.returncode, 0, cmd + "\n" + r.stderr)
        self.assertAllowed(["git push origin x", "git commit -m 'x'"])  # no role: the orchestrator and the implementer may
        r = hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": "git push origin x"}, "cwd": str(self.ws), "agent_type": "turnstile:tester"}, self.ws)
        self.assertEqual(r.returncode, 2); self.assertIn("tester", r.stderr)
        r = hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": "git push origin x"}, "cwd": str(self.ws), "agent_type": "turnstile:implementer"}, self.ws)
        self.assertEqual(r.returncode, 0, r.stderr)

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

    def test_content_in_files_and_file_queries(self):
        # R2-11: a trailer, footer or mutation that lives in a file the command points at
        (self.ws / "trailer.txt").write_text("fix: x\n\nCo-Authored-By: Claude <n@a>\n")
        (self.ws / "footer.md").write_text("Scope: x\n\nGenerated with [Claude Code](https://claude.com/claude-code)\n")
        (self.ws / "clean.txt").write_text("fix: x\n")
        (self.ws / "body.json").write_text('{"body": "Generated with [Claude Code]"}')
        self.assertBlocked(["git commit -F trailer.txt", "git commit --file=trailer.txt", "git commit -S --file trailer.txt"], "trailer")
        self.assertBlocked(["gh pr create --title x --body-file footer.md", "gh pr edit 1 --body-file=footer.md",
                            "gh api -X PATCH repos/o/r/pulls/1 --input body.json"], "footer")
        self.assertBlocked(["gh api graphql -F query=@m.graphql", "gh api graphql --input q.json", "gh api graphql -f query=@m.graphql -F n=1"], "graphql-file")
        self.assertBlocked(["git config pull.rebase true", "git config --global pull.rebase true"], "rebase")
        self.assertBlocked(["gh workflow run x -f service_github_tag ''", 'prometey ensure --service_github_tag "" --x 1',
                            "gh workflow run x --field service_github_tag=\"\" -f y=1"], "empty-variant-tag")
        self.assertAllowed(["git commit -F clean.txt", "git commit -F missing.txt", "gh pr create --title x --body-file clean.txt",
                            "gh api graphql -f query='query{viewer{login}}'", "git config pull.rebase false", "gh api -F n=1 repos/o/r/pulls/1"])

    def test_delivery_dir_writes_blocked_through_any_interpreter(self):
        # R2-2: a command that mentions state.json or the delivery dir and is not read-only is refused, whatever the tool
        d = str(self.ws / "delivery")
        self.assertBlocked(["perl -pi -e 's/DEV/READY/' delivery/state.json", "node -e \"require('fs').writeFileSync('delivery/state.json','{}')\"",
                            "ruby -e 'File.write(\"delivery/state.json\", \"{}\")'", "python3 - <<EOF\nimport json\nopen('delivery/' + 'state.json','w')\nEOF",
                            "sed -i '' s/a/b/ state.*", "rm -rf %s/reports" % d, "echo x > %s/ledger.md" % d, "cd delivery && rm ledger.md",
                            "mkdir delivery/x", "cat delivery/state.json | python3",
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

    def test_evidence_reports_briefs_are_writable_by_any_command(self):
        # 2026-10-14 finding 1: the tester writes evidence (PNG, JSON) with any tool; state.json, ledger.md, plan.md, decisions.md,
        # board.html, .state.lock and the delivery root stay the CLI's / the Write tool's
        d = str(self.ws / "delivery")
        self.assertAllowed(["mkdir -p delivery/evidence/S1/TP-1", "mkdir -p %s/evidence/S1/TP-1" % d,
                            "node shot.mjs --out %s/evidence/S1/TP-1/env.png" % d, "node shot.mjs --out=%s/evidence/S1/TP-1/env.png" % d,
                            "npx playwright screenshot --full-page https://x.test %s/evidence/S1/TP-1/env.png" % d,
                            "cp /tmp/a.png delivery/evidence/S1/TP-1/env.png", "echo '{}' > delivery/evidence/S1/TP-1/dom.json",
                            "cat > delivery/reports/X.md <<EOF\nhi\nEOF", "cp /tmp/b.md delivery/briefs/B.md", "rm delivery/evidence/S1/TP-1/env.png",
                            "python3 measure.py --out delivery/evidence/S1/TP-1/dom.json", "mv delivery/evidence/S1 /tmp/x",
                            "cat /tmp/a.png | tee delivery/evidence/S1/TP-1/figma.png", "rm -rf delivery/evidence/S1/",
                            "mkdir -p delivery/evidence/S1 && cp /tmp/a.png delivery/evidence/S1/env.png && echo done"])
        self.assertBlocked(["echo x > delivery/evidence/../state.json", "cp a delivery/evidence/../../delivery/ledger.md",
                            "cp a delivery/evidence/./../plan.md", "cp a 'delivery/evidence/S1/../../decisions.md'", "echo x > delivery/board.html",
                            "echo x > delivery/.state.lock", "echo x > delivery/decisions.md", "echo x > delivery/plan.md", "rm -rf delivery/evidence",
                            "rm -rf delivery/evidence/S1/..", "mkdir delivery/x", "tar cf delivery/evidence/S1/all.tar delivery/",
                            "cp delivery/state.json delivery/evidence/S1/s.json", "mv delivery/plan.md delivery/evidence/S1/",
                            "echo x > delivery/evidence/$S/x", "echo x > delivery/evidence/*/x", "echo x > delivery/evidence/`echo S1`/x",
                            "ln -s ../ledger.md delivery/evidence/S1/x", "ln -s %s/ledger.md delivery/evidence/S1/x" % d,
                            "ln -s ../state.json delivery/evidence/S1/x", "git add delivery/evidence/S1", "git -C delivery add evidence",
                            "cd delivery/evidence/S1 && node x --out env.png", "cd delivery/evidence && echo x > ../ledger.md",
                            "X=delivery/state.json; cp a $X", "echo x > delivery/evidence/S1/state.json",
                            "python3 - <<EOF\nopen('delivery/evidence/S1/x','w')\nEOF"], "delivery-")

    def test_evidence_symlinks_resolve_outside_are_blocked(self):
        ev = self.ws / "delivery" / "evidence" / "S1"; ev.mkdir(parents=True)
        (ev / "link.png").symlink_to("../../ledger.md"); (ev / "up").symlink_to("../..")
        (self.ws / "delivery" / "ledger.md").write_text("- x\n")
        self.assertBlocked(["echo x > delivery/evidence/S1/link.png", "cp a delivery/evidence/S1/up/plan.md", "cp a delivery/evidence/S1/up/new.md",
                            "echo x > %s/evidence/S1/up/evidence/S1/../../state.json" % (self.ws / "delivery")], "delivery-")
        self.assertAllowed(["echo x > delivery/evidence/S1/ok.png", "cp a delivery/evidence/S1/up/evidence/S1/ok.png"])

    def test_round2_cwd_inside_delivery_inline_code_and_shells_get_no_allowance(self):
        d = self.ws / "delivery"; (d / "evidence" / "S1").mkdir(parents=True)
        def at(cwd, cmd):
            return hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}, cwd).returncode
        for cwd, cmd in [(d / "evidence", "cp /tmp/x ../ledger.md"), (d, "cp /tmp/x ledger.md"), (d, "echo x > board.html"),
                         (d / "evidence" / "S1", "cp /tmp/x env.png")]:
            self.assertEqual(at(cwd, cmd), 2, (cwd, cmd))
        for cwd, cmd in [(d, "cat state.json"), (d, "ls -la"), (d / "evidence", "git log -1"), (d, "turnstile status")]:
            self.assertEqual(at(cwd, cmd), 0, (cwd, cmd))
        self.assertBlocked(["node -e \"require('fs').writeFileSync(require('path').join('delivery','ledger.md'),'x')\" delivery/evidence/S1/a",
                            "tar -xPf /tmp/evil.tar -C delivery/evidence/S1", "sh delivery/evidence/run.sh", "bash delivery/evidence/S1/x.sh"], "delivery-write")
        self.assertAllowed(["node shot.mjs --out delivery/evidence/S1/TP-1/env.png", "tar -xf /tmp/a.tar -C delivery/evidence/S1"])

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
        self.assertAllowed(["git commit -m 'feat(turnstile): approve flow'", "turnstile status", "turnstile pass pr jsfiller#1 READY --head a",
                            "turnstile init --epic MYD-1 --workitem demo --knowledge ../k --lead a --lead-github b --github-org o",
                            "turnstile plan-submitted",
                            "turnstile bug add --story S1 --title x --source y", "turnstile bug set b01 --state done",
                            "turnstile brief tester ENV-S1 --var story_id=S1"])

    def test_round3_computed_subcommands_and_writers(self):
        # R3-1: a computed subcommand forged `approve` with the lead's ledger line; R3-2: env/awk/find/sort/git config wrote state.json
        self.assertBlocked(["turnstile $(echo approve) ah-3", "turnstile appr$(echo ove) ah-3", "X=approve; turnstile $X ah-3",
                            "env \"$(printf 'TURNSTILE\\137LEAD=1')\" turnstile $(printf 'appr%s' ove) ah-3",
                            "scripts/turnstile `echo approve` ah-3", "turnstile --delivery d $(echo approve) ah-1"], "lead-approve")
        self.assertBlocked(["env perl -pi -e 's/a/b/' delivery/state.json", "awk 'BEGIN{system(\"cp /tmp/s delivery/state.json\")}'",
                            "find delivery -name state.json -delete", "find delivery -name state.json -exec cp /tmp/s {} \\;",
                            "sort -o delivery/state.json /tmp/s", "git -C delivery config --file state.json a.b c",
                            "git -C delivery worktree add ../x"], "delivery-write")
        self.assertAllowed(["turnstile status", "turnstile --delivery d pass pr jsfiller#1 READY", "git -C turnstile log --oneline",
                            "cd /x/turnstile && python3 -m unittest", "find delivery -name '*.md'", "sort delivery/ledger.md",
                            "env | sort", "python3 -m turnstile_cli reconcile --json"])

    def test_malformed_payload_blocks(self):
        for payload in ("{}", "[]", "not json", json.dumps({"tool_input": {"command": 5}}), json.dumps({"tool_input": "x"})):
            self.assertEqual(hook("guard_bash.py", payload, self.ws).returncode, 2, payload)

    def test_hooks_json_wraps_commands_to_fail_closed(self):
        h = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        cmds = [x["command"] for ev in h.values() for m in ev for x in m["hooks"]]
        self.assertTrue(cmds)
        for c in cmds:
            self.assertTrue(c.endswith("|| exit 2"), c)
        matchers = [m["matcher"] for m in h["PreToolUse"]]
        self.assertIn("Edit|Write|MultiEdit", matchers)
        post = h["PostToolUse"]
        self.assertEqual(len(post), 1); self.assertIn("slack", post[0]["matcher"]); self.assertIn("post_slack.py", post[0]["hooks"][0]["command"])
        self.assertEqual(post[0]["matcher"], next(m["matcher"] for m in h["PreToolUse"] if "slack" in m["matcher"]))

class TreeResetRealLayout(unittest.TestCase):
    def test_round3_resets_from_other_cwds_and_wrappers_are_blocked(self):
        # round 3: the real layout (.turnstile at the workspace root, the knowledge worktree a child of it); one-command cd, subshells,
        # sh -c, command, --work-tree / GIT_WORK_TREE and read-tree / checkout-index / revert passed in round 2
        ws = pathlib.Path(tempfile.mkdtemp()); kn = ws / "kn"; d = kn / "ctx" / "delivery"; d.mkdir(parents=True)
        (kn / ".git").write_text("gitdir: /nowhere\n"); shutil.copy(FIX, d / "state.json"); (ws / ".turnstile").write_text("kn/ctx/delivery\n")
        js = ws / "jsfiller"; js.mkdir(); (js / ".git").mkdir()
        def run(cmd, cwd):
            return hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}, cwd)
        for cwd, cmd in [(js, "cd ../kn && git checkout -- ."), (js, "cd %s && git restore ." % kn), (js, "(cd ../kn; git reset --hard)"),
                         (kn, "(git checkout -- .)"), (kn, "sh -c 'git checkout -- .'"), (kn, "command git reset --hard"),
                         (js, "git --work-tree=../kn --git-dir=x checkout -- ."), (js, "GIT_WORK_TREE=../kn GIT_DIR=x git checkout -- ."),
                         (kn, "git read-tree -u --reset HEAD~1"), (kn, "git checkout-index -a -f"), (kn, "git revert --no-edit HEAD")]:
            r = run(cmd, cwd); self.assertEqual(r.returncode, 2, cmd); self.assertIn("knowledge-worktree-reset", r.stderr, cmd)
        for cwd, cmd in [(js, "git checkout -- ."), (js, "git reset --hard"), (js, "cd ../kn && git status"), (kn, "git stash list")]:
            r = run(cmd, cwd); self.assertEqual(r.returncode, 0, cmd + "\n" + r.stderr)

class SlackGuard(unittest.TestCase):
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")
        self.git = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "init", "-q"], cwd=self.ws, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.ws, check=True)
        subprocess.run(["git", "add", "."], cwd=self.ws, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=self.ws, check=True, env=dict(os.environ, **self.git))

    def post(self, text, response, channel="C1", tool="mcp__plugin_slack_slack__slack_send_message"):
        return hook("post_slack.py", {"tool_name": tool, "tool_input": {"channel_id": channel, "text": text}, "tool_response": response,
                                      "cwd": str(self.ws)}, self.ws, env=self.git)

    def porcelain(self):
        return subprocess.run(["git", "status", "--porcelain"], cwd=self.ws, capture_output=True, text=True).stdout

    def state(self):
        return json.loads((self.ws / "delivery" / "state.json").read_text())

    def write(self, d):
        (self.ws / "delivery" / "state.json").write_text(json.dumps(d))

    def ready_with(self, pr="jsfiller#1", state="READY", story_state="DONE", **entry):
        d = self.state(); d["prs"][pr]["state"] = state; d["stories"]["S1"]["state"] = story_state
        e = {"id": "ah-1", "owner": "lead", "type": "send", "pr": pr, "created_at": "x", "payload": None, "approved_at": "2026-10-13T10:00Z"}
        e.update(entry); d["awaiting_human"] = [e]
        if story_state == "DONE":  # round 3: a DONE story is sent only with a deploy.heads snapshot that GitHub confirms
            d["stories"]["S1"]["evidence"] = {"deploy": {"build": "1", "head": "bbbbbbbb22222222",
                "heads": {p: x["head"] for p, x in d["prs"].items() if x.get("story") == "S1" and x["state"] not in ("MERGED", "CLOSED")}}}
        self.write(d)

    def slack(self, text, channel="C1", tool="mcp__plugin_slack_slack__slack_send_message", env=None):
        env = env if env is not None else self.gh_on_path({"jsfiller": "aaaaaaaa11111111", "docs-platform": "bbbbbbbb22222222"})
        return hook("guard_slack.py", {"tool_name": tool, "tool_input": {"channel_id": channel, "text": text}, "cwd": str(self.ws)}, self.ws, env=env)

    MSG = "PR: <https://github.com/pdffiller/jsfiller/pull/1>"

    def test_blocks_without_approval(self):
        r = self.slack(self.MSG); self.assertEqual(r.returncode, 2)
        r = self.slack("hello"); self.assertEqual(r.returncode, 2)
        self.ready_with(approved_at=None)
        self.assertEqual(self.slack(self.MSG).returncode, 2)

    def test_pre_only_checks_post_records_use_on_message_ts_and_commits(self):
        # R2-4: a denied or failed send must not consume the approval; R2-14: the hook's writes are committed
        self.ready_with(); subprocess.run(["git", "commit", "-qam", "ready"], cwd=self.ws, check=True, env=dict(os.environ, **self.git))
        r = self.slack(self.MSG); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("used_at", self.state()["awaiting_human"][0]); self.assertFalse((self.ws / "delivery" / "ledger.md").exists())
        r = self.post(self.MSG, {"content": [{"type": "text", "text": "Error: channel_not_found"}]}); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("used_at", self.state()["awaiting_human"][0])
        self.assertEqual(self.slack(self.MSG).returncode, 0)  # still sendable: nothing was sent
        ok = {"content": [{"type": "text", "text": json.dumps({"ok": True, "channel": "C1", "message_ts": "1760000000.123456"})}]}
        r = self.post(self.MSG, ok); self.assertEqual(r.returncode, 0, r.stderr)
        e = self.state()["awaiting_human"][0]
        self.assertTrue(e["used_at"]); self.assertEqual(e["used_channel"], "C1"); self.assertEqual(e["message_ts"], "1760000000.123456")
        self.assertIn("slack send for jsfiller#1 via ah-1 (send) to C1 ts 1760000000.123456", (self.ws / "delivery" / "ledger.md").read_text())
        self.assertTrue((self.ws / "delivery" / "board.html").exists())
        self.assertEqual(self.porcelain(), "")  # committed
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.ws, capture_output=True, text=True).stdout
        self.assertIn("turnstile: slack send for jsfiller#1", log)
        r = self.slack(self.MSG); self.assertEqual(r.returncode, 2); self.assertIn("already used", r.stderr)
        r = self.post(self.MSG, ok); self.assertEqual(r.returncode, 2); self.assertIn("no usable", r.stderr)  # a second send slipped past: loud

    def test_post_accepts_string_responses_and_ignores_unrelated_tools(self):
        self.ready_with()
        r = self.post(self.MSG, '{"ok":true,"message_ts":"1760000000.1"}'); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state()["awaiting_human"][0]["message_ts"], "1760000000.1")
        self.ready_with()
        r = self.post(self.MSG, "sent, ts=1760000000.2 message_ts missing"); self.assertEqual(r.returncode, 0)
        self.assertNotIn("used_at", self.state()["awaiting_human"][0])

    def test_only_a_send_entry_on_a_ready_pr_unlocks_slack(self):
        # 2026-10-14: a `reply` entry is the lead's word for one GitHub reply on one needs_lead thread, never a Slack message
        self.ready_with(state="AI_REVIEW"); self.assertEqual(self.slack(self.MSG).returncode, 2)
        self.ready_with(state="REWORK", type="reply", thread="PRRT_1"); self.assertEqual(self.slack(self.MSG).returncode, 2)
        self.ready_with(state="ON_HUMAN_REVIEW", type="reply"); self.assertEqual(self.slack(self.MSG).returncode, 2)
        self.ready_with(state="READY", type="merge"); self.assertEqual(self.slack(self.MSG).returncode, 2)
        self.ready_with(state="READY"); self.assertEqual(self.slack(self.MSG).returncode, 0)

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

    def test_unknown_ids_are_named_and_companions_are_allowed(self):
        # R2-12: a paired locales PR or a repo missing from epic.repos must not surface as "cannot read the delivery state"
        self.ready_with()
        paired = self.MSG + "\nLocales: <https://github.com/pdffiller/locales/pull/5>"
        r = self.slack(paired); self.assertEqual(r.returncode, 2)
        self.assertIn("locales#5", r.stderr); self.assertIn("not in epic.repos", r.stderr); self.assertNotIn("cannot read", r.stderr)
        r = self.slack(self.MSG + " and jsfiller#99"); self.assertEqual(r.returncode, 2)
        self.assertIn("no usable (approved, unused) send for jsfiller#99", r.stderr)
        self.ready_with(companions=["locales#5"])
        r = self.slack(paired); self.assertEqual(r.returncode, 0, r.stderr)
        r = self.post(paired, '{"ok":true,"message_ts":"1760000000.9"}'); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state()["awaiting_human"][0]["message_ts"], "1760000000.9")

    def test_allowed_send_asks_the_lead_in_the_ui(self):
        # R3-1: the state check is a filter; the lead confirms every send (permissionDecision "ask")
        self.ready_with()
        r = self.slack(self.MSG); self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "ask"); self.assertIn("jsfiller#1", out["permissionDecisionReason"])

    def test_send_waits_for_the_story(self):
        # R3-3: the Slack guard applies the same story gate as pass READY -> ON_HUMAN_REVIEW
        self.ready_with(story_state="IN_PROGRESS")
        r = self.slack(self.MSG); self.assertEqual(r.returncode, 2); self.assertIn("story S1 is not DONE", r.stderr)
        d = self.state(); d["stories"]["S1"]["human_review"] = "per_pr"; self.write(d)
        self.assertEqual(self.slack(self.MSG).returncode, 0)
        self.ready_with(state="REWORK", type="reply", story_state="IN_PROGRESS")
        self.assertEqual(self.slack(self.MSG).returncode, 2)

    def test_send_refused_when_a_head_changed_after_the_story_deploy(self):
        # round 2: a DONE story whose deploy.heads no longer match the PR heads (a push after DONE) is not sent
        self.ready_with()
        d = self.state(); d["stories"]["S1"]["evidence"] = {"deploy": {"build": "1", "head": "aaaaaaaa11111111",
            "heads": {"jsfiller#1": "aaaaaaaa11111111", "docs-platform#2": "bbbbbbbb22222222"}}}; self.write(d)
        env = self.gh_on_path({"jsfiller": "aaaaaaaa11111111", "docs-platform": "bbbbbbbb22222222"})
        self.assertEqual(self.slack(self.MSG, env=env).returncode, 0)
        d = self.state(); d["prs"]["docs-platform#2"]["head"] = "cccccccc33333333"; self.write(d)
        r = self.slack(self.MSG, env=env); self.assertEqual(r.returncode, 2); self.assertIn("head changed after its deploy", r.stderr)

    def gh_on_path(self, heads):
        """A canned `gh` that answers the GraphQL query with the head for the repo named in `-f r=<repo>`."""
        b = pathlib.Path(tempfile.mkdtemp())
        cases = "".join('*"r=%s"*) h=%s;; ' % (repo, h) for repo, h in heads.items())
        (b / "gh").write_text('#!/bin/sh\ncase "$*" in %s*) h=none;; esac\n'
                              'printf \'{"data":{"repository":{"pullRequest":{"headRefOid":"%%s"}}}}\' "$h"\n' % cases)
        (b / "gh").chmod(0o755)
        return {"PATH": os.pathsep.join([str(b), "/usr/bin", "/bin"])}

    def test_send_asks_github_for_the_deployed_heads(self):
        # round 2 R2-7: state.json may be stale after a push without `pass pr`; the guard verifies deploy.heads on GitHub
        self.ready_with()
        d = self.state(); d["prs"]["docs-platform#2"]["state"] = "READY"
        d["stories"]["S1"]["evidence"] = {"deploy": {"build": "1", "head": "bbbbbbbb22222222",
            "heads": {"jsfiller#1": "aaaaaaaa11111111", "docs-platform#2": "bbbbbbbb22222222"}}}; self.write(d)
        env = self.gh_on_path({"jsfiller": "aaaaaaaa11111111", "docs-platform": "bbbbbbbb22222222"})
        r = self.slack(self.MSG, env=env); self.assertEqual(r.returncode, 0, r.stderr)
        env = self.gh_on_path({"jsfiller": "aaaaaaaa11111111", "docs-platform": "cccccccc33333333"})
        r = self.slack(self.MSG, env=env); self.assertEqual(r.returncode, 2); self.assertIn("GitHub", r.stderr); self.assertIn("docs-platform#2", r.stderr)
        env = {"PATH": os.pathsep.join(["/usr/bin", "/bin"])}  # no gh: fail closed
        self.assertIsNone(shutil.which("gh", path=env["PATH"]))
        r = self.slack(self.MSG, env=env); self.assertEqual(r.returncode, 2); self.assertIn("GitHub", r.stderr)

    def test_schedule_is_refused_draft_is_guarded(self):
        self.ready_with()
        r = self.slack(self.MSG, tool="mcp__plugin_slack_slack__slack_schedule_message"); self.assertEqual(r.returncode, 2)
        self.assertIn("scheduled", r.stderr)
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
        self.assertEqual(self.edit(str(self.ws / "delivery" / "ledger.md")).returncode, 2)  # R3-8: a forged approve line would hide from reconcile
        self.assertEqual(self.edit(str(self.ws / "delivery" / "reports" / "R.md")).returncode, 0)
        self.assertEqual(self.edit(str(self.ws / "delivery" / "reports" / "state.json.md")).returncode, 0)

    def test_delivery_subfolders_and_plan_decisions_writable_rest_of_delivery_not(self):
        # 2026-10-14 finding 1: figma.png lands through Write; plan.md/decisions.md are the orchestrator's; the root and the CLI's files are not
        d = self.ws / "delivery"
        for rel in ("evidence/S1/TP-1/figma.png", "evidence/S1/TP-1/dom.json", "reports/ENV-S1.md", "briefs/ENV-S1.md", "plan.md", "decisions.md"):
            self.assertEqual(self.edit(str(d / rel), "Write").returncode, 0, rel)
        self.assertEqual(self.edit("delivery/evidence/S1/x.png", "Write").returncode, 0)  # relative to cwd
        for rel in ("board.html", ".state.lock", "notes.md", "evidence", "evidence/../state.json", "evidence/../../delivery/ledger.md",
                    "reports/../board.html", "evidence/./../notes.md", ".gitattributes"):
            r = self.edit(str(d / rel), "Write"); self.assertEqual(r.returncode, 2, rel); self.assertIn("turnstile", r.stderr)
        self.assertEqual(self.edit("delivery/evidence/../ledger.md", "Edit").returncode, 2)
        self.assertEqual(self.edit(str(d / "evidence" / "S1" / "x.png"), "Write", env={"TURNSTILE_MIGRATION": "1"}).returncode, 0)
        self.assertEqual(self.edit(str(d / "board.html"), "Write", env={"TURNSTILE_MIGRATION": "1"}).returncode, 0)

    def test_symlinks_inside_evidence_cannot_reach_the_root(self):
        d = self.ws / "delivery"; ev = d / "evidence" / "S1"; ev.mkdir(parents=True)
        (ev / "link.md").symlink_to("../../ledger.md"); (ev / "up").symlink_to("../..")
        self.assertEqual(self.edit(str(ev / "link.md"), "Write").returncode, 2)
        self.assertEqual(self.edit(str(ev / "up" / "plan.md"), "Write").returncode, 0)   # resolves to delivery/plan.md: the orchestrator's file
        self.assertEqual(self.edit(str(ev / "up" / "notes.md"), "Write").returncode, 2)  # resolves to the delivery root
        self.assertEqual(self.edit(str(ev / "up" / "state.json"), "Write").returncode, 2)
        self.assertEqual(self.edit(str(ev / "up" / "evidence" / "S1" / "ok.png"), "Write").returncode, 0)

    def test_round2_cwd_outside_the_workspace_still_protects_the_delivery_root(self):
        d = self.ws / "delivery"
        for name in ("board.html", ".state.lock", "evidence/../board.html"):
            r = hook("guard_state_edit.py", {"tool_name": "Write", "tool_input": {"file_path": str(d / name)}, "cwd": "/"}, "/")
            self.assertEqual(r.returncode, 2, name)

    def test_outside_the_delivery_dir_only_state_and_ledger_names_are_blocked(self):
        self.assertEqual(self.edit(str(self.ws / "other" / "board.html"), "Write").returncode, 0)
        self.assertEqual(self.edit(str(self.ws / "other" / "state.json"), "Write").returncode, 2)


class RoleGuard(unittest.TestCase):
    """Round 2 R2-12: Jira writes through any MCP prefix are the orchestrator's; a turnstile agent (role from the env the
    agent's own hook sets, or the agent name in the payload) is refused."""
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp())

    def jira(self, tool="mcp__claude_ai_Atlassian__transitionJiraIssue", env=None, **payload):
        p = {"tool_name": tool, "tool_input": {"issueIdOrKey": "MYD-1"}, "cwd": str(self.ws)}; p.update(payload)
        return hook("guard_role.py", p, self.ws, env=env)

    def test_agent_roles_are_refused_and_the_orchestrator_passes(self):
        self.assertEqual(self.jira().returncode, 0)
        for role in ("tester", "implementer", "reviewer"):
            r = self.jira(env={"TURNSTILE_ROLE": role}); self.assertEqual(r.returncode, 2); self.assertIn(role, r.stderr)
        r = self.jira(agent_type="turnstile:tester"); self.assertEqual(r.returncode, 2); self.assertIn("tester", r.stderr)
        r = self.jira(tool="mcp__plugin_atlassian_jira__editJiraIssue", env={"TURNSTILE_ROLE": "tester"}); self.assertEqual(r.returncode, 2)
        self.assertEqual(self.jira(env={"TURNSTILE_ROLE": "orchestrator"}).returncode, 0)
        # round 3: any subagent (payload agent_id, as Claude Code 2.1.x sends it) is refused, turnstile or not
        r = self.jira(agent_id="a1", agent_type="general-purpose"); self.assertEqual(r.returncode, 2); self.assertIn("general-purpose", r.stderr)
        r = self.jira(agent_id="a2", agent_type="turnstile:tester"); self.assertEqual(r.returncode, 2); self.assertIn("tester", r.stderr)

    def test_matchers_cover_every_jira_write_under_any_prefix(self):
        import re
        pre = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
        m = next(x["matcher"] for x in pre if "Jira" in x["matcher"])
        for tool in ("mcp__claude_ai_Atlassian__transitionJiraIssue", "mcp__claude_ai_Atlassian__editJiraIssue", "mcp__claude_ai_Atlassian__createJiraIssue",
                     "mcp__claude_ai_Atlassian__addCommentToJiraIssue", "mcp__plugin_atlassian_jira__transitionJiraIssue"):
            self.assertTrue(re.fullmatch(m, tool), tool)
        self.assertFalse(re.fullmatch(m, "mcp__claude_ai_Atlassian__getJiraIssue"))
        self.assertIn("guard_role.py", next(x for x in pre if "Jira" in x["matcher"])["hooks"][0]["command"])

CANNED_GH = r'''#!/usr/bin/env python3
import json, os, sys
R = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "responses.json")))
args = sys.argv[1:]
q = next((a[len("query="):] for a in args if a.startswith("query=")), "")
kv = dict(a.split("=", 1) for a in args if "=" in a and not a.startswith("query="))
if "node(" in q:
    a = R.get("nodes", {}).get(kv.get("id"))
    if a is None:
        sys.exit(1)
    print(json.dumps({"data": {"node": {"comments": {"nodes": [{"author": a}]}}}}))
else:
    p = R.get("prs", {}).get("%s#%s" % (kv.get("r"), kv.get("n")))
    if p is None:
        sys.exit(1)
    print(json.dumps({"data": {"repository": {"pullRequest": p}}}))
'''

def gql_thread(tid, comments, resolved=False):
    return {"id": tid, "isResolved": resolved, "comments": {"totalCount": len(comments), "nodes": [
        {"databaseId": cid, "author": {"__typename": "Bot" if login.endswith("reviewer") else "User", "login": login}, "createdAt": at}
        for cid, login, at in comments]}}

class ReviewWrites(unittest.TestCase):
    """2026-10-14: issue comments, review submissions and review comments are refused for every caller (the repo gate's marker
    comments excepted); a reply goes through the REST replies route to a thread classified in state.json — self_resolved at once,
    needs_lead after the lead approved its own `reply` entry; resolving is allowed for bot (Copilot) threads only."""
    T1 = "2026-10-13T11:00:00Z"
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")
        data = json.loads((d / "state.json").read_text()); data["epic"]["roles"]["agent_github"] = "agentlogin"
        pr = data["prs"]["jsfiller#1"]; pr["state"] = "REWORK"
        rec = lambda cls, cid: {"class": cls, "classified_at": "2026-10-13T12:00:00Z", "comment_id": cid, "comment_ids": [cid], "reviewer": "isachivka",
                                "last_reviewer_at": self.T1}
        pr["threads"] = {"PRRT_s": rec("self_resolved", "101"), "PRRT_l": rec("needs_lead", "201")}
        data["awaiting_human"] = [{"id": "ah-3", "owner": "lead", "type": "reply", "pr": "jsfiller#1", "thread": "PRRT_l", "last_reviewer_at": self.T1,
                                   "created_at": "2026-10-13T12:00Z", "payload": None, "approved_at": None}]
        (d / "state.json").write_text(json.dumps(data))
        payload = json.loads((ROOT / "tests" / "fixtures" / "gh_pr_13222.json").read_text())
        payload["reviewThreads"] = {"nodes": [gql_thread("PRRT_s", [(101, "isachivka", self.T1)]), gql_thread("PRRT_l", [(201, "isachivka", self.T1)]),
                                              gql_thread("PRRT_cop", [(301, "copilot-pull-request-reviewer", self.T1)])]}
        self.responses = {"prs": {"jsfiller#1": payload}, "nodes": {"PRRT_cop": {"__typename": "Bot", "login": "copilot-pull-request-reviewer"},
                                                                     "PRRT_s": {"__typename": "User", "login": "isachivka"}}}
        self.bin = pathlib.Path(tempfile.mkdtemp()); (self.bin / "gh").write_text(CANNED_GH); (self.bin / "gh").chmod(0o755); self.save()

    def save(self):
        (self.bin / "responses.json").write_text(json.dumps(self.responses))
    def state(self):
        return json.loads((self.ws / "delivery" / "state.json").read_text())
    def write(self, data):
        (self.ws / "delivery" / "state.json").write_text(json.dumps(data))
    def bash(self, cmd, gh=True, **payload):
        p = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(self.ws)}; p.update(payload)
        path = os.pathsep.join(([str(self.bin)] if gh else []) + ["/usr/bin", "/bin"])
        return hook("guard_bash.py", p, self.ws, env={"PATH": path})
    def assertBlocked(self, cmds, rule):
        for cmd in cmds:
            r = self.bash(cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn(rule, r.stderr, cmd)
    def assertAllowed(self, cmds):
        for cmd in cmds:
            r = self.bash(cmd); self.assertEqual(r.returncode, 0, cmd + "\n" + r.stderr)
    REPLY = "gh api -X POST repos/pdffiller/jsfiller/pulls/1/comments/%s/replies -f body='Fixed in abc1234'"

    def test_issue_comments_reviews_and_review_comments_are_refused_for_everyone(self):
        self.assertBlocked(["gh pr comment 1 --body 'fixed'", "gh pr comment 1 -R pdffiller/jsfiller --body x", "gh -R pdffiller/jsfiller issue comment 1 -b x",
                            "gh api -X POST repos/pdffiller/jsfiller/issues/1/comments -f body=x", "gh api repos/pdffiller/jsfiller/issues/1/comments -f body=x",
                            "gh api -X PATCH repos/pdffiller/jsfiller/issues/comments/9 -f body=x", "gh api -X DELETE repos/pdffiller/jsfiller/issues/comments/9",
                            "curl -s -X POST https://api.github.com/repos/pdffiller/jsfiller/issues/1/comments -d '{\"body\":\"x\"}'"], "issue-comment")
        self.assertBlocked(["gh pr review 1 --approve", "gh pr review 1 --comment -b ok", "gh pr -R pdffiller/jsfiller review 1 --request-changes -b x",
                            "gh api -X POST repos/pdffiller/jsfiller/pulls/1/reviews -f event=APPROVE", "gh api repos/pdffiller/jsfiller/pulls/1/reviews/5/events -f event=COMMENT",
                            "gh api -X PUT repos/pdffiller/jsfiller/pulls/1/reviews/5/dismissals -f message=x"], "review-submission")
        self.assertBlocked(["gh api -X POST repos/pdffiller/jsfiller/pulls/1/comments -f body=x -F in_reply_to=101",
                            "gh api -X PATCH repos/pdffiller/jsfiller/pulls/comments/101 -f body=x", "gh api -X DELETE repos/pdffiller/jsfiller/pulls/comments/101"],
                           "review-comment")
        self.assertBlocked(["gh api graphql -f query='mutation{addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:\"PRRT_s\",body:\"x\"}){comment{id}}}'",
                            "gh api graphql -f query='mutation { addComment(input: {subjectId: \"PR_1\", body: \"x\"}) { clientMutationId } }'",
                            "gh api graphql -f query='mutation{submitPullRequestReview(input:{pullRequestReviewId:\"x\",event:APPROVE}){clientMutationId}}'"],
                           "graphql-review-write")

    def test_reads_and_the_repo_gates_marker_comments_pass(self):
        (self.ws / "result.md").write_text("<!-- pdf-review:result -->\n3 findings, 2 applied\n")
        (self.ws / "plain.md").write_text("just a comment\n")
        self.assertAllowed(["gh api repos/pdffiller/jsfiller/pulls/1/comments --paginate", "gh api repos/pdffiller/jsfiller/pulls/1/reviews",
                            "gh api -X GET repos/pdffiller/jsfiller/pulls/1/comments -F per_page=100", "gh pr view 1 --comments",
                            "gh api repos/pdffiller/jsfiller/issues/1/comments --jq '.[].body'", "grep -rn addComment src",
                            "gh pr comment 1 --body '<!-- pdf-review:summary --> What changed'", "gh pr comment 1 --body-file result.md",
                            "gh api -X PATCH repos/pdffiller/jsfiller/issues/comments/9 -F body=@result.md",
                            "gh api -X POST repos/pdffiller/jsfiller/issues/1/comments -f body='<!-- crit-review:result --> ok'",
                            "gh api graphql -f query='{ repository(owner:\"pdffiller\", name:\"jsfiller\") { pullRequest(number:1) { reviewThreads(first:100) { nodes { id } } } } }'"])
        self.assertBlocked(["gh pr comment 1 --body-file plain.md", "gh pr comment 1 --body-file missing.md"], "issue-comment")

    def test_self_resolved_reply_passes_at_once(self):
        self.assertAllowed([self.REPLY % "101", "gh api --method POST /repos/pdffiller/jsfiller/pulls/1/comments/101/replies -f body=x"])

    def test_needs_lead_reply_waits_for_the_lead_approved_entry_of_that_thread(self):
        r = self.bash(self.REPLY % "201"); self.assertEqual(r.returncode, 2); self.assertIn("reply-needs-lead", r.stderr)
        self.assertIn("ah-3", r.stderr); self.assertIn("TURNSTILE_LEAD=1 turnstile approve", r.stderr)
        d = self.state(); d["awaiting_human"].append({"id": "ah-4", "owner": "lead", "type": "reply", "pr": "jsfiller#1", "thread": "PRRT_s",
                                                      "approved_at": "2026-10-13T12:30Z"}); self.write(d)
        self.assertEqual(self.bash(self.REPLY % "201").returncode, 2)  # an approval for another thread does not count
        d = self.state(); d["awaiting_human"][0]["approved_at"] = "2026-10-13T12:30Z"; self.write(d)
        self.assertAllowed([self.REPLY % "201"])
        d = self.state(); d["awaiting_human"][0]["voided_at"] = "2026-10-13T12:40Z"; self.write(d)
        self.assertEqual(self.bash(self.REPLY % "201").returncode, 2)

    def test_unclassified_foreign_computed_or_off_state_replies_are_refused(self):
        r = self.bash(self.REPLY % "999"); self.assertEqual(r.returncode, 2); self.assertIn("reply-unclassified", r.stderr); self.assertIn("turnstile threads", r.stderr)
        r = self.bash("gh api -X POST repos/pdffiller/other/pulls/1/comments/101/replies -f body=x"); self.assertEqual(r.returncode, 2); self.assertIn("reply-unknown-pr", r.stderr)
        r = self.bash("gh api -X POST repos/someone/jsfiller/pulls/1/comments/101/replies -f body=x"); self.assertEqual(r.returncode, 2); self.assertIn("reply-unknown-pr", r.stderr)
        for cmd in ["gh api -X POST repos/pdffiller/jsfiller/pulls/$N/comments/101/replies -f body=x", "gh api -X POST repos/{owner}/{repo}/pulls/1/comments/101/replies -f body=x",
                    "gh api -X POST \"$URL\" -f body=x"]:
            r = self.bash(cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn("computed", r.stderr, cmd)
        d = self.state(); d["prs"]["jsfiller#1"]["state"] = "ON_HUMAN_REVIEW"; self.write(d)
        r = self.bash(self.REPLY % "101"); self.assertEqual(r.returncode, 2); self.assertIn("REWORK", r.stderr)

    def test_a_reviewer_follow_up_or_github_unavailable_blocks_the_reply(self):
        threads = self.responses["prs"]["jsfiller#1"]["reviewThreads"]["nodes"]
        threads[0]["comments"]["nodes"].append({"databaseId": 102, "author": {"__typename": "User", "login": "isachivka"}, "createdAt": "2026-10-13T13:00:00Z"})
        threads[0]["comments"]["totalCount"] = 2; self.save()
        r = self.bash(self.REPLY % "101"); self.assertEqual(r.returncode, 2); self.assertIn("reply-reclassify", r.stderr); self.assertIn("2026-10-13T13:00:00Z", r.stderr)
        r = self.bash(self.REPLY % "101", gh=False); self.assertEqual(r.returncode, 2); self.assertIn("GitHub", r.stderr)

    def test_resolving_human_threads_is_refused_bot_threads_pass(self):
        q = "gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: \"%s\"}) { thread { isResolved } } }'"
        self.assertAllowed([q % "PRRT_cop"])
        for cmd in [q % "PRRT_s", q.replace("resolveReviewThread", "unresolveReviewThread") % "PRRT_s",
                    "gh api graphql -f query='mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{id}}}' -f t=$T",
                    q % "PRRT_unknown"]:
            r = self.bash(cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn("resolve", r.stderr, cmd)
        r = self.bash(q % "PRRT_cop", gh=False); self.assertEqual(r.returncode, 2)

    def test_tester_role_still_cannot_reply(self):
        r = self.bash(self.REPLY % "101", agent_type="turnstile:tester"); self.assertEqual(r.returncode, 2); self.assertIn("tester", r.stderr)

class ReRequestGuard(unittest.TestCase):
    """Lead rule 2026-10-14 (re-request): a `requested_reviewers` POST for humans passes only for a REWORK PR of the epic whose classified
    threads all have their replies, with Copilot's review of the current head and 0 open Copilot threads (repos without Copilot: the gate
    check green on the head), and only for exactly the reviewers who commented on the threads in this round. Every other human request
    (`--add-reviewer`, GraphQL, teams, JSON bodies, computed logins) stays refused."""
    T1 = "2026-10-13T11:00:00Z"
    REQ = "gh api -X POST repos/pdffiller/jsfiller/pulls/1/requested_reviewers -f 'reviewers[]=%s'"
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")
        data = json.loads((d / "state.json").read_text()); data["epic"]["roles"]["agent_github"] = "agentlogin"
        pr = data["prs"]["jsfiller#1"]; pr["state"] = "REWORK"
        pr["evidence"]["human"] = {"head": "aaaaaaaa11111111", "sent_head": "aaaaaaaa11111111", "sent_at": "2026-10-13T10:02Z", "approved": "ah-1",
                                   "slack_permalink": "https://x.slack.com/archives/C1/p1"}
        pr["threads"] = {"PRRT_s": {"class": "self_resolved", "classified_at": "2026-10-13T11:02:00Z", "comment_id": "101", "comment_ids": ["101"],
                                    "reviewer": "isachivka", "last_reviewer_at": self.T1}}
        data["awaiting_human"] = [{"id": "ah-1", "owner": "lead", "type": "send", "pr": "jsfiller#1", "approved_at": "2026-10-13T09:30Z",
                                   "used_at": "2026-10-13T10:00Z", "consumed_at": "2026-10-13T10:01Z"}]
        self.write(data)
        payload = json.loads((ROOT / "tests" / "fixtures" / "gh_pr_13222.json").read_text())
        payload["reviewThreads"] = {"nodes": [gql_thread("PRRT_s", [(101, "isachivka", self.T1), (102, "agentlogin", "2026-10-13T11:05:00Z")]),
                                              gql_thread("PRRT_cop", [(301, "copilot-pull-request-reviewer", self.T1)], resolved=True)]}
        self.responses = {"prs": {"jsfiller#1": payload}, "nodes": {}}
        self.bin = pathlib.Path(tempfile.mkdtemp()); (self.bin / "gh").write_text(CANNED_GH); (self.bin / "gh").chmod(0o755); self.save()
    def save(self):
        (self.bin / "responses.json").write_text(json.dumps(self.responses))
    def state(self):
        return json.loads((self.ws / "delivery" / "state.json").read_text())
    def write(self, data):
        (self.ws / "delivery" / "state.json").write_text(json.dumps(data))
    def payload(self):
        return self.responses["prs"]["jsfiller#1"]
    def bash(self, cmd, gh=True):
        path = os.pathsep.join(([str(self.bin)] if gh else []) + ["/usr/bin", "/bin"])
        return hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(self.ws)}, self.ws, env={"PATH": path})
    def assertBlocked(self, cmds, rule):
        for cmd in cmds:
            r = self.bash(cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn(rule, r.stderr, cmd)
    def assertAllowed(self, cmds):
        for cmd in cmds:
            r = self.bash(cmd); self.assertEqual(r.returncode, 0, cmd + "\n" + r.stderr)
    def copilot(self, oid=None, open_thread=False):
        d = self.state(); d["epic"]["repos"]["jsfiller"]["copilot"] = True; self.write(d)
        p = self.payload()
        if oid:
            p["latestReviews"]["nodes"].append({"author": {"__typename": "Bot", "login": "copilot-pull-request-reviewer"}, "state": "COMMENTED",
                                                "commit": {"oid": oid}, "submittedAt": "2026-10-13T11:10:00Z"})
        p["reviewThreads"]["nodes"][1]["isResolved"] = not open_thread; self.save()

    def test_the_thread_authors_are_re_requested_once_replies_and_the_gate_are_clean(self):
        self.assertAllowed([self.REQ % "isachivka", "gh api --method POST /repos/pdffiller/jsfiller/pulls/1/requested_reviewers -f reviewers[]=isachivka",
                            "gh api repos/pdffiller/jsfiller/pulls/1/requested_reviewers -F 'reviewers[]=ISACHIVKA'"])
    def test_copilot_only_requests_still_pass_and_reads_are_free(self):
        self.assertAllowed([self.REQ % COPILOT, "gh api repos/pdffiller/jsfiller/pulls/1/requested_reviewers"])
    def test_non_authors_teams_bodies_and_computed_logins_are_refused(self):
        self.assertBlocked([self.REQ % "lMakDen", self.REQ % "isachivka" + " -f 'reviewers[]=lMakDen'", self.REQ % "isachivka" + " -f 'reviewers[]=%s'" % COPILOT],
                           "rerequest-not-authors")
        self.assertBlocked([self.REQ % "isachivka" + " -f 'team_reviewers[]=front'", "gh api -X POST repos/pdffiller/jsfiller/pulls/1/requested_reviewers -f 'team_reviewers[]=front'",
                            "gh api -X POST repos/pdffiller/jsfiller/pulls/1/requested_reviewers --input body.json",
                            "gh api -X POST repos/pdffiller/jsfiller/pulls/1/requested_reviewers -f reviewers[]=$WHO",
                            "gh api -X POST repos/pdffiller/jsfiller/pulls/$N/requested_reviewers -f 'reviewers[]=isachivka'"], "human-reviewer-request")
        self.assertBlocked(["gh pr edit 1 --add-reviewer isachivka"], "add-reviewer")
        self.assertBlocked(["gh api graphql -f query='mutation{requestReviews(input:{pullRequestId:\"x\",userIds:[\"y\"]}){clientMutationId}}'",
                            "gh api graphql -f query='mutation{requestReviewsByLogin(input:{pullRequestId:\"x\",userLogins:[\"isachivka\"]}){clientMutationId}}'"], "graphql")
        self.assertBlocked(["gh pr create --title x --body y --reviewer isachivka", "gh pr create -t x -b y -r isachivka", "gh pr create --draft -r=isachivka -t x",
                            "gh -R pdffiller/jsfiller pr create --reviewer=isachivka,lMakDen -t x", "gh pr edit 1 --add-reviewer=isachivka"], "reviewer")
        self.assertAllowed(["gh pr create --title x --body y --draft --base epic -R pdffiller/jsfiller", "gh pr create -t 'fix: -r flag' -b y --draft",
                            "gh pr view 1 --json reviewRequests --jq '.reviewRequests[].login'"])
    def test_refused_until_every_thread_has_its_reply(self):
        self.payload()["reviewThreads"]["nodes"][0]["comments"]["nodes"].pop(); self.save()
        self.assertBlocked([self.REQ % "isachivka"], "rerequest-replies")
        self.payload()["reviewThreads"]["nodes"][0]["comments"]["nodes"].append(
            {"databaseId": 102, "author": {"__typename": "User", "login": "agentlogin"}, "createdAt": "2026-10-13T11:05:00Z"})
        self.payload()["reviewThreads"]["nodes"].append(gql_thread("PRRT_n", [(401, "lMakDen", "2026-10-13T11:30:00Z")])); self.save()
        r = self.bash(self.REQ % "isachivka"); self.assertEqual(r.returncode, 2); self.assertIn("rerequest-replies", r.stderr); self.assertIn("PRRT_n", r.stderr)
    def test_refused_with_a_red_gate(self):
        ctx = self.payload()["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]["nodes"]
        next(c for c in ctx if c.get("name") == "pdf-review")["conclusion"] = "FAILURE"; self.save()
        self.assertBlocked([self.REQ % "isachivka"], "rerequest-gate")
    def test_with_copilot_its_review_of_the_current_head_and_no_open_thread(self):
        head = self.payload()["headRefOid"]
        self.copilot(); self.assertBlocked([self.REQ % "isachivka"], "rerequest-copilot")                       # Copilot never reviewed
        self.copilot(oid="0000000011111111aaa0288e05b49fa4583d8812"); self.assertBlocked([self.REQ % "isachivka"], "rerequest-copilot")  # stale head
        self.payload()["latestReviews"]["nodes"].pop(); self.copilot(oid=head, open_thread=True)
        self.assertBlocked([self.REQ % "isachivka"], "rerequest-copilot")                                          # an open Copilot thread
        self.copilot(open_thread=False); self.assertAllowed([self.REQ % "isachivka"])
    def test_push_only_off_state_foreign_and_unverifiable_requests_are_refused(self):
        d = self.state(); d["prs"]["jsfiller#1"]["evidence"]["human"]["returned_at"] = "2026-10-13T12:00:00Z"; self.write(d)
        self.assertBlocked([self.REQ % "isachivka"], "rerequest-push-only")
        d = self.state(); del d["prs"]["jsfiller#1"]["evidence"]["human"]["returned_at"]; d["prs"]["jsfiller#1"]["state"] = "ON_HUMAN_REVIEW"; self.write(d)
        self.assertBlocked([self.REQ % "isachivka"], "rerequest-not-rework")
        d["prs"]["jsfiller#1"]["state"] = "REWORK"; self.write(d)
        self.assertBlocked(["gh api -X POST repos/pdffiller/other/pulls/1/requested_reviewers -f 'reviewers[]=isachivka'",
                            "gh api -X POST repos/someone/jsfiller/pulls/1/requested_reviewers -f 'reviewers[]=isachivka'"], "human-reviewer-request")
        r = self.bash(self.REQ % "isachivka", gh=False); self.assertEqual(r.returncode, 2); self.assertIn("rerequest-unverified", r.stderr)
