import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"
COPILOT = "copilot-pull-request-reviewer[bot]"

def hook(name, payload, cwd, env=None):
    e = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(ROOT)); e.pop("TURNSTILE_MIGRATION", None); e.pop("CLAUDE_PROJECT_DIR", None); e.update(env or {})
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

    def test_delivery_write_keys_on_the_resolved_dir_not_the_bare_word(self):
        # 2026-11-03: without a workspace the word `delivery/` in a command protects nothing; with one, every spelling of the
        # resolved delivery dir is a write and an unrelated …/delivery/ elsewhere on disk is not
        other = pathlib.Path(tempfile.mkdtemp()); (other / "MYD-docs").mkdir()
        def at(cwd, cmd, env=None):
            return hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}, cwd, env=env)
        for cmd in ["printf '%%s\\n' 'ledger: see delivery/ for the state; the board | notes' >> %s/MYD-docs/ledger.md" % other, "rm -rf delivery/",
                    "mkdir -p delivery/evidence", "echo x > delivery/ledger.md", "git -C delivery worktree add ../x", "cd delivery && rm ledger.md"]:
            r = at(other, cmd); self.assertEqual(r.returncode, 0, cmd + "\n" + r.stderr)
        # 2026-11-04: outside a workspace the guard is inert, so a state.json name alone no longer blocks either
        self.assertEqual(at(other, "echo '{}' > state.json").returncode, 0); self.assertEqual(at(other, "cp x delivery/state.json").returncode, 0)
        self.assertBlocked(["echo '{}' > state.json", "cp x delivery/state.json"], "delivery-write")
        d = self.ws / "delivery"; real = os.path.realpath(str(d))
        self.assertBlocked(["echo x > %s/ledger.md" % d, "echo x > %s/ledger.md" % real, "echo x > delivery/ledger.md", "echo x > ./delivery/ledger.md",
                            "cp /tmp/x ../%s/delivery/ledger.md" % self.ws.name, "git -C %s worktree add ../x" % d, "git worktree add %s/x" % d,
                            "printf 'see delivery/ notes' >> %s/ledger.md" % d, "cd %s && echo x > ledger.md" % real], "delivery-write")
        home = {"HOME": str(self.ws.parent)}
        for cmd in ["echo x > ~/%s/delivery/ledger.md" % self.ws.name, "echo x > $HOME/%s/delivery/ledger.md" % self.ws.name]:
            r = at(self.ws, cmd, env=home); self.assertEqual(r.returncode, 2, cmd); self.assertIn("delivery-write", r.stderr)
        elsewhere = pathlib.Path(tempfile.mkdtemp()) / "delivery"; elsewhere.mkdir()
        self.assertAllowed(["echo x > %s/notes.md" % elsewhere, "mkdir -p %s/evidence" % elsewhere, "rm -rf %s" % elsewhere, "cp a %s/ledger.md" % elsewhere,
                            "printf 'see delivery/ notes' >> %s/ledger.md" % elsewhere.parent, "git -C %s checkout -- ." % elsewhere.parent,
                            "git -C %s worktree add ../x" % elsewhere, "echo x > ~/%s/notes.md" % elsewhere.parent.name])
        r = at(self.ws, "echo x > ~/%s/delivery/notes.md" % elsewhere.parent.name, env={"HOME": str(elsewhere.parent.parent)}); self.assertEqual(r.returncode, 0, r.stderr)

    def test_turnstile_init_and_attach_pass_while_model_worktrees_on_the_delivery_dir_do_not(self):
        self.assertAllowed(["turnstile init --epic MYD-1 --workitem demo --lead a --lead-github b --github-org o --repo '{\"name\":\"app\",\"base\":\"main\",\"slack\":\"C1\"}'",
                            "turnstile init --epic MYD-1 --workitem demo --clone-root ~/Desktop/pdffiller --knowledge ../pdffiller-knowledge --lead a --lead-github b --github-org o",
                            "turnstile attach --epic MYD-1 --clone-root .", "cd ~/Desktop/pdffiller && turnstile attach --epic MYD-1",
                            "git worktree add ../myd-1/jsfiller -b ws/myd-1 origin/develop", "git -C /tmp/jsfiller worktree list"])
        self.assertBlocked(["git -C delivery worktree add ../x", "git worktree add %s/wt" % (self.ws / "delivery"), "cd delivery && git worktree add ../x",
                            "git -C %s worktree remove x" % (self.ws / "delivery")], "delivery-write")
        ws = pathlib.Path(tempfile.mkdtemp()); kn = ws / "pdffiller-knowledge"; d = kn / "context" / "workitems" / "demo" / "delivery"; d.mkdir(parents=True)
        shutil.copy(FIX, d / "state.json"); (ws / ".turnstile").write_text("pdffiller-knowledge/context/workitems/demo/delivery\n")
        (kn / ".git").write_text("gitdir: /x\n"); (ws / "jsfiller").mkdir(); (ws / "jsfiller" / ".git").write_text("gitdir: /y\n")
        def at(cwd, cmd):
            return hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}, cwd)
        for cmd in ["git checkout -- .", "git reset --hard origin/develop", "git checkout -b feature/MYD-2-x origin/develop", "git stash"]:
            self.assertEqual(at(ws / "jsfiller", cmd).returncode, 0, cmd)
            r = at(kn, cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn("knowledge-worktree-reset", r.stderr)
        r = at(ws / "jsfiller", "echo x > ../pdffiller-knowledge/context/workitems/demo/delivery/ledger.md"); self.assertEqual(r.returncode, 2); self.assertIn("delivery-write", r.stderr)
        self.assertEqual(at(ws / "jsfiller", "echo x > ../pdffiller-knowledge/context/workitems/demo/delivery/reports/R.md").returncode, 0)

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
                            "TURNSTILE_MIGRATION=1 python3 gen.py > delivery/state.json", "env | grep TURNSTILE_MIGRATION",
                            "TURNSTILE_USER_CONFIG=delivery/state.json turnstile config set review_skill=/x", "export TURNSTILE_USER_CONFIG=/tmp/x.json; turnstile config list",
                            "env TURNSTILE_USER_CONFIG=/tmp/x.json turnstile config set models.reviewer=opus", "\"TURNSTILE_USER_CONFIG\"=/tmp/x.json turnstile config list",
                            "bash -c 'TURNSTILE_USER_CONFIG=/tmp/x.json turnstile config list'", "echo $TURNSTILE_USER_CONFIG"], "lead-")
        self.assertAllowed(["git commit -m 'feat(turnstile): approve flow'", "turnstile status", "turnstile pass pr jsfiller#1 READY --head a",
                            "turnstile init --epic MYD-1 --workitem demo --knowledge ../k --lead a --lead-github b --github-org o",
                            "turnstile plan-submitted",
                            "turnstile bug add --story S1 --title x --source y", "turnstile bug set b01 --state done",
                            "turnstile brief tester ENV-S1 --var story_id=S1", "turnstile config list", "turnstile config set models.reviewer=sonnet:medium",
                            "turnstile config set review_skill=/my-review --epic", "turnstile pr add jsfiller#2 --story S1 --ticket MYD-11",
                            "turnstile sync", "turnstile attach --knowledge ../k --epic MYD-1 --workspace ."])

    def test_lead_marker_is_refused_as_an_assignment_or_use_not_as_prose(self):
        # 2026-11-04: a ledger note that merely mentions the marker is prose; setting, exporting or reading the variable is the lead's
        self.assertAllowed(["printf '%s\\n' 'ledger: the lead approves from the prompt (TURNSTILE_LEAD); see README' >> notes.md",
                            "echo 'TURNSTILE_LEAD marker documented' > notes.md", "grep -rn TURNSTILE_LEAD README.md", "git log --grep TURNSTILE_LEAD",
                            "cat > notes.md <<'EOF'\nthe lead types the TURNSTILE_LEAD line themself\nEOF"])
        self.assertBlocked(["TURNSTILE_LEAD=1 turnstile status", "env TURNSTILE_LEAD=1 turnstile status", "export TURNSTILE_LEAD", "export TURNSTILE_LEAD=1",
                            "echo ${TURNSTILE_LEAD}", "echo $TURNSTILE_LEAD", "bash -c 'TURNSTILE_LEAD=1 turnstile status'", "printf 'x' | TURNSTILE_LEAD=1 cat",
                            "declare -x TURNSTILE_LEAD=1", "unset TURNSTILE_LEAD", "\"TURNSTILE_LEAD\"=1 turnstile status", "T\\URNSTILE_LEAD=1 turnstile status",
                            "printf '%s\\n' 'TURNSTILE_LEAD=1 turnstile approve ah-3' >> notes.md"], "lead-approve")

    def test_sync_git_traffic_keeps_todays_verdicts(self):
        # the CLI itself fetches, fast-forwards and pushes; a model-issued push/fetch was already read-only for the guard, a merge inside
        # the delivery dir and any rebase stay blocked, a merge at the worktree root stays as it was (allowed)
        subprocess.run(["git", "init", "-q"], cwd=self.ws, check=True)
        self.assertAllowed(["git push -q origin HEAD:refs/heads/epic/myd-1", "git fetch -q origin epic/myd-1", "git merge -q --ff-only origin/epic/myd-1"])
        self.assertBlocked(["cd delivery && git merge origin/epic/myd-1"], "delivery-write")
        self.assertBlocked(["git rebase origin/epic/myd-1", "git push --force origin epic/myd-1"], "")

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
        self.assertEqual([m for m in matchers if "slack" in m.lower()], [])  # 2026-11-05: no PreToolUse gate on Slack sends
        self.assertFalse((ROOT / "hooks" / "guard_slack.py").exists())
        post = h["PostToolUse"]
        self.assertEqual(len(post), 1); self.assertIn("post_slack.py", post[0]["hooks"][0]["command"])
        import re
        for tool in ("mcp__plugin_slack_slack__slack_send_message", "mcp__plugin_slack_slack__slack_send_message_draft", "mcp__plugin_slack_slack__slack_schedule_message"):
            self.assertTrue(re.fullmatch(post[0]["matcher"], tool), tool)

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

class SlackRecorder(unittest.TestCase):
    """2026-11-05 (lead's decision): Slack sends are gated by the lead's word in chat only. The plugin records a send that went out
    (a ledger line, an old open `send` entry marked used) and never blocks, asks or exits 2."""
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")
        self.git = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "init", "-q"], cwd=self.ws, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.ws, check=True)
        subprocess.run(["git", "add", "."], cwd=self.ws, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=self.ws, check=True, env=dict(os.environ, **self.git))

    MSG = "PR: <https://github.com/pdffiller/jsfiller/pull/1>"
    OK = {"content": [{"type": "text", "text": json.dumps({"ok": True, "channel": "C1", "message_ts": "1760000000.123456"})}]}

    def post(self, text, response=None, channel="C1", tool="mcp__plugin_slack_slack__slack_send_message"):
        return hook("post_slack.py", {"tool_name": tool, "tool_input": {"channel_id": channel, "text": text}, "tool_response": response or self.OK,
                                      "cwd": str(self.ws)}, self.ws, env=self.git)

    def porcelain(self):
        return subprocess.run(["git", "status", "--porcelain"], cwd=self.ws, capture_output=True, text=True).stdout

    def state(self):
        return json.loads((self.ws / "delivery" / "state.json").read_text())

    def write(self, d):
        (self.ws / "delivery" / "state.json").write_text(json.dumps(d))

    def ledger(self):
        path = self.ws / "delivery" / "ledger.md"
        return path.read_text() if path.exists() else ""

    def with_entry(self, pr="jsfiller#1", **entry):
        d = self.state()
        e = {"id": "ah-1", "owner": "lead", "type": "send", "pr": pr, "created_at": "x", "payload": None, "approved_at": "2026-10-13T10:00Z"}
        e.update(entry); d["awaiting_human"] = [e]; self.write(d)

    def test_records_a_sent_message_without_any_entry(self):
        r = self.post(self.MSG); self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stdout, "")
        self.assertIn("slack send to C1 ts 1760000000.123456 for jsfiller#1", self.ledger())
        self.assertEqual(self.state()["awaiting_human"], [])
        self.assertTrue((self.ws / "delivery" / "board.html").exists())
        self.assertEqual(self.porcelain(), "")
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.ws, capture_output=True, text=True).stdout
        self.assertIn("turnstile: slack send to C1 ts 1760000000.123456 for jsfiller#1", log)

    def test_nothing_recorded_without_a_message_ts(self):
        r = self.post(self.MSG, {"content": [{"type": "text", "text": "Error: channel_not_found"}]}); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ledger(), ""); self.assertEqual(self.porcelain(), "")
        r = self.post(self.MSG, "sent, ts=1760000000.2 message_ts missing"); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ledger(), "")

    def test_string_responses_are_read(self):
        r = self.post(self.MSG, '{"ok":true,"message_ts":"1760000000.1"}'); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("slack send to C1 ts 1760000000.1 for jsfiller#1", self.ledger())

    def test_an_open_send_entry_is_marked_used_once(self):
        self.with_entry()
        r = self.post(self.MSG); self.assertEqual(r.returncode, 0, r.stderr)
        e = self.state()["awaiting_human"][0]
        self.assertTrue(e["used_at"]); self.assertEqual(e["used_channel"], "C1"); self.assertEqual(e["message_ts"], "1760000000.123456")
        self.assertIn("slack send to C1 ts 1760000000.123456 for jsfiller#1 (ah-1 used)", self.ledger())
        r = self.post(self.MSG, '{"ok":true,"message_ts":"1760000000.9"}'); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state()["awaiting_human"][0]["message_ts"], "1760000000.123456")
        self.assertIn("slack send to C1 ts 1760000000.9 for jsfiller#1\n", self.ledger())

    def test_consumed_voided_or_unapproved_entries(self):
        for extra in (dict(consumed_at="x"), dict(voided_at="x")):
            self.with_entry(**extra)
            r = self.post(self.MSG); self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("used_at", self.state()["awaiting_human"][0])
        self.with_entry(approved_at=None)
        r = self.post(self.MSG); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.state()["awaiting_human"][0]["used_at"])

    def test_never_blocks(self):
        d = self.state(); d["prs"]["jsfiller#1"]["state"] = "AI_REVIEW"; d["stories"]["S1"]["state"] = "IN_PROGRESS"; self.write(d)
        cases = [dict(text=self.MSG, channel="C9"), dict(text="hello"), dict(text=self.MSG + "\nLocales: <https://github.com/pdffiller/locales/pull/5>"),
                 dict(text=self.MSG, tool="mcp__plugin_slack_slack__slack_schedule_message"), dict(text=self.MSG, tool="mcp__plugin_slack_slack__slack_send_message_draft"),
                 dict(text=self.MSG + " and jsfiller#99")]
        for kw in cases:
            r = self.post(**kw); self.assertEqual(r.returncode, 0, (kw, r.stderr)); self.assertEqual(r.stdout, "", kw)
        text = self.ledger()
        self.assertIn("slack send to C9 ts 1760000000.123456 for jsfiller#1", text)
        self.assertIn("slack send to C1 ts 1760000000.123456\n", text)
        self.assertIn("for jsfiller#1, locales#5", text); self.assertIn("for jsfiller#1, jsfiller#99", text)
        self.assertEqual(text.count("slack send"), len(cases))

    def test_unreadable_state_records_nothing_and_exits_zero(self):
        (self.ws / "delivery" / "state.json").write_text("{not json")
        r = self.post(self.MSG); self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stderr, ""); self.assertEqual(self.ledger(), "")
        self.write({"prs": [], "awaiting_human": [{"pr": "jsfiller#1", "type": "send", "approved_at": "x"}]})
        r = self.post(self.MSG); self.assertEqual(r.returncode, 0, r.stderr)
        shutil.rmtree(self.ws / "delivery")
        r = self.post(self.MSG); self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stderr, "")
        for payload in ("{}", "[]", "not json", json.dumps({"tool_input": "x", "cwd": str(self.ws)})):
            self.assertEqual(hook("post_slack.py", payload, self.ws).returncode, 0, payload)

    def test_commit_failure_is_a_warning_not_a_block(self):
        shutil.rmtree(self.ws / ".git")
        r = self.post(self.MSG); self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("not committed", r.stderr)
        self.assertIn("slack send to C1 ts 1760000000.123456 for jsfiller#1", self.ledger())

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
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")

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
                            "gh api -X POST repos/pdffiller/jsfiller/pulls/1/requested_reviewers -f reviewers[]=$WHO"], "human-reviewer-request")
        self.assertBlocked(["gh api -X POST repos/pdffiller/jsfiller/pulls/$N/requested_reviewers -f 'reviewers[]=isachivka'"], "computed")
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

class ThreadRulesBypasses(unittest.TestCase):
    """2026-10-14 thread rules review: bypasses of the PR-conversation guard found by probing the real hook, each closed."""
    def setUp(self):
        self.r = ReviewWrites("test_self_resolved_reply_passes_at_once"); self.r.setUp(); self.ws = self.r.ws
        (self.ws / "q.graphql").write_text('mutation{addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:"PRRT_l",body:"x"}){comment{id}}}')
        (self.ws / "body.json").write_text('{"body":"x"}')
    def blocked(self, cmds, rule=None):
        for cmd in cmds:
            r = self.r.bash(cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn("blocked by rule", r.stderr, cmd)
            if rule:
                self.assertIn(rule, r.stderr, cmd)
    def test_attached_flag_values_are_writes(self):
        self.blocked(["gh api repos/pdffiller/jsfiller/issues/1/comments -fbody=x", "gh api repos/pdffiller/jsfiller/issues/1/comments -Fbody=@body.json",
                      "curl -s https://api.github.com/repos/pdffiller/jsfiller/issues/1/comments -d@body.json"], "issue-comment")
        self.blocked(["gh api repos/pdffiller/jsfiller/pulls/1/reviews -fevent=APPROVE"], "review-submission")
        self.blocked(["gh api repos/pdffiller/jsfiller/pulls/1/comments -fbody=x -Fin_reply_to=201"], "review-comment")
        self.blocked(["gh api repos/pdffiller/jsfiller/pulls/1/comments/201/replies -fbody=x"], "reply-needs-lead")
    def test_non_canonical_computed_and_repository_id_routes_are_refused_for_writes(self):
        self.blocked(["gh api -X POST repos/pdffiller/jsfiller/pulls/1/comments/101/../201/replies -f body=x",
                      "gh api -X POST repos//pdffiller/jsfiller/pulls/1/comments/201/replies -f body=x",
                      "gh api -X POST repos/pdffiller/jsfiller/issues/1/../1/comments -f body=x",
                      "gh api -X POST repos/pdffiller/jsfiller/issues/1/c%6fmments -f body=x"], "rest-noncanonical-route")
        self.blocked(["gh api -X POST $(echo repos/pdffiller/jsfiller/pulls/1/comments/201/replies) -f body=x",
                      "gh api -X POST $(echo repos/pdffiller/jsfiller/issues/1/comments) -f body=x",
                      "curl -s -X POST \"https://api.github.com/$(echo repos/pdffiller/jsfiller/issues/1/comments)\" -d @body.json"], "rest-computed-route")
        self.blocked(["gh api -X POST repositories/123456/issues/1/comments -f body=x", "gh api -X POST /repositories/123456/pulls/1/comments/201/replies -f body=x"],
                     "rest-repository-id-route")
        self.r.assertAllowed(["gh api repos/pdffiller/jsfiller/pulls/1/comments --paginate", "gh api repos/pdffiller/jsfiller/issues/1/comments?per_page=100",
                              "gh api -X POST repos/{owner}/{repo}/pulls/1/requested_reviewers -f 'reviewers[]=%s'" % COPILOT])
    def test_other_tools_and_commit_comments_are_github_writes(self):
        self.blocked(["wget -q --post-file=body.json https://api.github.com/repos/pdffiller/jsfiller/issues/1/comments",
                      "http POST https://api.github.com/repos/pdffiller/jsfiller/issues/1/comments body=x",
                      "python3 -c \"import urllib.request as u; u.urlopen(u.Request('https://api.github.com/repos/pdffiller/jsfiller/issues/1/comments', b'{}'))\""])
        self.blocked(["gh api -X POST repos/pdffiller/jsfiller/commits/aaaaaaaa/comments -f body=x", "gh api -X PATCH repos/pdffiller/jsfiller/comments/9 -f body=x",
                      "gh api -X DELETE repos/pdffiller/jsfiller/comments/9"], "commit-comment")
        self.r.assertAllowed(["gh api repos/pdffiller/jsfiller/commits/aaaaaaaa/comments", "curl -s https://api.github.com/repos/pdffiller/jsfiller/pulls/1"])
    def test_graphql_queries_are_literal_and_only_gh_speaks_graphql(self):
        self.blocked(["gh api graphql -f query=\"$(cat q.graphql)\"", "gh api graphql -F query=\"$(cat q.graphql)\"", "gh api graphql -f query=`cat q.graphql`",
                      "gh api graphql -f query=$Q", "gh api graphql --raw-field query=\"$(cat q.graphql)\""], "graphql-computed")
        self.blocked(["curl -s -X POST https://api.github.com/graphql -H \"Authorization: bearer $(gh auth token)\" -d @body.json",
                      "curl -s https://api.github.com/graphql -d@body.json"], "graphql-non-gh")
        self.r.assertAllowed(["gh api graphql -f query='query($o:String!,$r:String!){ repository(owner:$o,name:$r){ id } }' -f o=pdffiller -f r=jsfiller"])
    def test_resolve_names_every_thread_id_literally(self):
        self.blocked(["gh api graphql -f query='mutation($t:ID!){a:resolveReviewThread(input:{threadId:\"PRRT_cop\"}){thread{id}} b:resolveReviewThread(input:{threadId:$t}){thread{id}}}' -f t=$(echo UFJSVF9z | base64 -d)",
                      "gh api graphql -f query='mutation{a:resolveReviewThread(input:{threadId:\"PRRT_cop\"}){thread{id}} b:resolveReviewThread(input:{threadId:\"MDI0OlB1bGxSZXF1ZXN0UmV2aWV3VGhyZWFkMQ==\"}){thread{id}}}'",
                      "gh api graphql -f query='mutation($i:ResolveReviewThreadInput!){resolveReviewThread(input:$i){thread{id}}}' -F i[threadId]=PRRT_cop"], "resolve-thread")
        self.r.assertAllowed(["gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: \"PRRT_cop\"}) { thread { isResolved } } }'"])
    def test_cli_comment_flags_aliases_and_computed_gh_words(self):
        self.blocked(["gh pr close 1 --comment x", "gh issue close 1 -c x", "gh pr reopen 1 --comment=x", "gh -R pdffiller/jsfiller pr close 1 -c 'done'"], "issue-comment")
        self.blocked(["gh alias set c 'pr comment'", "gh alias import aliases.yml"], "gh-alias")
        self.blocked(["gh $(echo pr) comment 1 -b x", "gh pr $(echo comment) 1 -b x", "$(which gh) pr comment 1 -b x", "`which gh` pr comment 1 -b x",
                      "GH=gh; $GH pr comment 1 -b x", "bash -c \"$(echo Z2ggcHIgY29tbWVudA== | base64 -d)\"", "eval $CMD"], "computed")
        self.blocked(["python3 -c \"import subprocess; subprocess.run(['gh','pr','comment','1','-b','x'])\"",
                      "node -e \"require('child_process').execSync(['gh', 'pr', 'comment', '1', '-b', 'x'].join(' '))\"",
                      "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['gh', 'pr', 'comment', '1', '-b', 'x'])\nEOF"], "inline-code-github")
        self.r.assertAllowed(["gh pr view 1 --json body | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"body\"])'",
                              "cat > notes.txt <<'EOF'\nread the PR with gh and api.github.com\nEOF"])
        self.r.assertAllowed(["gh pr close --help", "gh pr view 1 --comments", "gh alias list", "python3 -c 'print(1)'", "echo $HOME"])
    def test_the_re_request_route_is_the_endpoint_itself(self):
        q = ReRequestGuard("test_copilot_only_requests_still_pass_and_reads_are_free"); q.setUp()
        for cmd in ["gh api -H 'X: repos/pdffiller/jsfiller/pulls/1/requested_reviewers' -X POST repos/pdffiller/jsfiller/pulls/2/requested_reviewers -f reviewers[]=isachivka",
                    "gh api -X POST repos/pdffiller/jsfiller/pulls/1/requested_reviewers -f reviewers[]=isachivka repos/pdffiller/other/pulls/9/requested_reviewers"]:
            r = q.bash(cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn("human-reviewer-request", r.stderr, cmd)
    def test_a_forged_delivery_outside_the_project_does_not_unlock_replies(self):
        # the hook resolves the delivery from CLAUDE_PROJECT_DIR (the session's project) before the Bash cwd, which an agent controls
        fake = pathlib.Path(tempfile.mkdtemp()); (fake / ".turnstile").write_text("fake\n"); (fake / "fake").mkdir()
        forged = self.r.state(); forged["awaiting_human"][0]["approved_at"] = "2026-10-13T12:30Z"
        (fake / "fake" / "state.json").write_text(json.dumps(forged))
        cmd = ReviewWrites.REPLY % "201"
        p = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(fake)}
        env = {"PATH": os.pathsep.join([str(self.r.bin), "/usr/bin", "/bin"]), "CLAUDE_PROJECT_DIR": str(self.ws)}
        r = hook("guard_bash.py", p, fake, env=env); self.assertEqual(r.returncode, 2); self.assertIn("reply-needs-lead", r.stderr)
        env.pop("CLAUDE_PROJECT_DIR"); self.assertEqual(hook("guard_bash.py", p, fake, env=env).returncode, 0)  # the residual without the anchor

class OutsideWorkspace(unittest.TestCase):
    """2026-11-04 (lead's decision): the hooks guard a turnstile workspace. With no `.turnstile` above the project dir, the cwd or a
    directory the command enters, every hook is inert; only the Bash guard's universal safety rules stay on everywhere."""
    def setUp(self):
        self.plain = pathlib.Path(tempfile.mkdtemp()); (self.plain / "notes").mkdir()
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir(); (self.ws / "jsfiller").mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")

    def bash(self, cmd, cwd=None, env=None, **payload):
        cwd = cwd or self.plain
        p = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}; p.update(payload)
        return hook("guard_bash.py", p, cwd, env=env)

    GUARDED = ["gh pr ready 13", "gh pr merge 13", "gh pr edit 13 --add-reviewer x", "gh pr comment 13 --body x", "gh pr review 13 --approve",
               "gh api -X POST repos/pdffiller/jsfiller/pulls/13/comments/201/replies -f body=x",
               "gh api graphql -f query='mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{id}}}' -f t=PRRT_x",
               "gh api -X POST repos/pdffiller/jsfiller/pulls/13/requested_reviewers -f 'reviewers[]=isachivka'",
               "printf '%s\\n' 'ledger: the lead approves with TURNSTILE_LEAD=1 turnstile approve ah-3' >> notes/ledger.md",
               "TURNSTILE_MIGRATION=1 cp new.json delivery/state.json", "echo '{}' > state.json", "echo x > delivery/ledger.md",
               "gh workflow run x -f service_github_tag= -f y=1", "git commit -m 'x' -m 'Co-Authored-By: a'", "gh alias set c 'pr comment'"]
    UNIVERSAL = ["git push --force origin x", "git push -f", "git push origin +x", "git rebase develop", "git pull --rebase", "git config pull.rebase true",
                 "git commit --no-gpg-sign -m x", "git -c commit.gpgsign=false commit -m x"]

    def test_bash_guard_is_inert_except_the_universal_rules(self):
        for cmd in self.GUARDED:
            r = self.bash(cmd); self.assertEqual(r.returncode, 0, cmd + "\n" + r.stderr); self.assertEqual(r.stdout, "")
        r = self.bash("git push origin x", env={"TURNSTILE_ROLE": "tester"}); self.assertEqual(r.returncode, 0, r.stderr)
        r = self.bash("git push origin x", agent_type="turnstile:tester"); self.assertEqual(r.returncode, 0, r.stderr)
        for cmd in self.UNIVERSAL:
            r = self.bash(cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn("blocked by rule", r.stderr, cmd)
        for payload in ("{}", "not json", json.dumps({"tool_input": {"command": 5}, "cwd": str(self.plain)})):
            self.assertEqual(hook("guard_bash.py", payload, self.plain).returncode, 0, payload)

    def test_bash_guard_wakes_for_a_workspace_by_cwd_project_dir_or_the_dir_entered(self):
        for cmd in self.GUARDED:
            r = self.bash(cmd, cwd=self.ws / "jsfiller"); self.assertEqual(r.returncode, 2, cmd); self.assertIn("blocked by rule", r.stderr, cmd)
        r = self.bash("gh pr ready 13", env={"CLAUDE_PROJECT_DIR": str(self.ws)}); self.assertEqual(r.returncode, 2); self.assertIn("rule ready", r.stderr)
        for cmd in ["cd %s && gh pr ready 13" % self.ws, "git -C %s push origin x && gh pr merge 13" % self.ws, "(cd %s/jsfiller; gh pr merge 13)" % self.ws,
                    "GIT_WORK_TREE=%s git status && gh pr ready 13" % self.ws, "git --work-tree=%s status; gh pr merge 13" % self.ws]:
            r = self.bash(cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn("blocked by rule", r.stderr, cmd)
        self.assertEqual(hook("guard_bash.py", "{}", self.ws).returncode, 2)

    MSG = "PR: <https://github.com/pdffiller/jsfiller/pull/1>"

    def slack(self, name, cwd, tool="mcp__plugin_slack_slack__slack_send_message", text=MSG, **payload):
        p = {"tool_name": tool, "tool_input": {"channel_id": "C1", "text": text}, "cwd": str(cwd)}; p.update(payload)
        return hook(name, p, cwd)

    def test_slack_recorder_is_inert_outside_and_records_inside(self):
        sent = {"tool_response": '{"ok":true,"message_ts":"1760000000.1"}'}
        for tool in ("mcp__plugin_slack_slack__slack_send_message", "mcp__plugin_slack_slack__slack_schedule_message"):
            r = self.slack("post_slack.py", self.plain, tool, **sent); self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stdout, "")
        self.assertEqual(sorted(p.name for p in self.plain.iterdir()), ["notes"])
        r = self.slack("post_slack.py", self.ws / "jsfiller", **sent); self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stdout, "")
        self.assertIn("slack send to C1 ts 1760000000.1 for jsfiller#1", (self.ws / "delivery" / "ledger.md").read_text())

    def test_role_guard_is_inert(self):
        p = {"tool_name": "mcp__claude_ai_Atlassian__transitionJiraIssue", "tool_input": {"issueIdOrKey": "MYD-1"}, "cwd": str(self.plain),
             "agent_id": "a1", "agent_type": "turnstile:tester"}
        self.assertEqual(hook("guard_role.py", p, self.plain, env={"TURNSTILE_ROLE": "tester"}).returncode, 0)
        p["cwd"] = str(self.ws / "jsfiller")
        r = hook("guard_role.py", p, self.ws, env={"TURNSTILE_ROLE": "tester"}); self.assertEqual(r.returncode, 2); self.assertIn("role-jira", r.stderr)

    def test_state_edit_guard_is_inert(self):
        def edit(fp, cwd):
            return hook("guard_state_edit.py", {"tool_name": "Write", "tool_input": {"file_path": fp}, "cwd": str(cwd)}, cwd)
        for name in ("state.json", "ledger.md", "delivery/state.json", "delivery/board.html"):
            r = edit(str(self.plain / name), self.plain); self.assertEqual(r.returncode, 0, name + "\n" + r.stderr)
        self.assertEqual(edit("state.json", self.plain).returncode, 0)
        self.assertEqual(edit(str(self.ws / "delivery" / "state.json"), self.plain).returncode, 2)  # the target lies in a workspace
        self.assertEqual(edit(str(self.ws / "delivery" / "reports" / "R.md"), self.plain).returncode, 0)
        self.assertEqual(edit(str(self.plain / "state.json"), self.ws / "jsfiller").returncode, 2)  # a workspace session keeps the name rule
