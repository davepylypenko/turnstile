import json, os, pathlib, shutil, subprocess, tempfile, unittest
from unittest import mock
from turnstile_cli import init_cmd
from turnstile_cli.errors import TurnstileError

_env = mock.patch.dict(os.environ, {"TURNSTILE_USER_CONFIG": os.path.join(tempfile.mkdtemp(), "none.json")})
def setUpModule(): _env.start()
def tearDownModule(): _env.stop()

JS = '{"name":"jsfiller","base":"develop","epic_branch":"epic_myd-1","slack":"C1","gate":"pdf-review","ci_ignore":["pdf-review","gate / gate"]}'
MONO = '{"name":"pdffiller","base":"master","epic_branch":"l2f","slack":"G1","gate":"run-lint","gate_check":null,"copilot":true,"branch_prefix":"l2f-myd-"}'

def opts(ws, knowledge, **kw):
    base = dict(epic="MYD-1", workitem="demo", knowledge=str(knowledge), lead="lead@example.com", lead_github="leadlogin",
                github_org="pdffiller", repos=[JS, MONO], variant="v1", desk="desk05", workspace=str(ws))
    base.update(kw); return init_cmd.InitOptions(**base)

class FakeGit(init_cmd.InitIO):
    def __init__(self, fail=()): self.calls = []; self.fail = set(fail); self.branches = {}
    def git(self, args, cwd):
        self.calls.append((args, pathlib.Path(cwd)))
        if args[0] in self.fail:
            raise TurnstileError("git %s failed: simulated" % args[0])
        if args[:2] == ["branch", "--show-current"]:
            return self.branches.get(pathlib.Path(cwd), "epic/myd-1" if pathlib.Path(cwd).name == "pdffiller-knowledge" else "ws/myd-1") + "\n"  # an existing worktree made by an earlier run is on its branch
        if args[:2] == ["worktree", "add"]:
            wt = pathlib.Path(args[4] if args[2] == "-b" else args[2]); wt.mkdir(parents=True); self.branches[wt] = args[3]
        return ""

def clones(tmp, *names):
    for n in names: (tmp / n / ".git").mkdir(parents=True, exist_ok=True)

class ParseRepo(unittest.TestCase):
    def test_defaults_and_required(self):
        name, cfg = init_cmd.parse_repo(JS)
        self.assertEqual(name, "jsfiller")
        self.assertEqual(cfg, {"base": "develop", "epic_branch": "epic_myd-1", "slack": "C1", "gate": "pdf-review",
                               "gate_check": "pdf-review", "ci_ignore": ["pdf-review", "gate / gate"], "copilot": False})
        name, cfg = init_cmd.parse_repo(MONO)
        self.assertEqual((cfg["gate_check"], cfg["ci_ignore"], cfg["copilot"], cfg["branch_prefix"]), (None, [], True, "l2f-myd-"))
        _, cfg = init_cmd.parse_repo('{"name":"locales","base":"main","epic_branch":"e","slack":"C2"}')
        self.assertEqual((cfg["gate"], cfg["gate_check"], cfg["ci_ignore"]), (None, None, []))
        for bad in ['{"name":"x"}', "not json", '["jsfiller"]', '{"name":"x","base":"b","epic_branch":"e","slack":"c","gate":"g","unknown":1}']:
            with self.assertRaises(TurnstileError, msg=bad):
                init_cmd.parse_repo(bad)
    def test_epic_branch_is_optional_and_defaults_to_the_base(self):
        _, cfg = init_cmd.parse_repo('{"name":"app","base":"main","slack":"C9"}')
        self.assertEqual(cfg["epic_branch"], "main"); self.assertEqual(cfg["base"], "main")
        with self.assertRaises(TurnstileError): init_cmd.parse_repo('{"name":"app","epic_branch":"e","slack":"C9"}')
    def test_epic_branch_name(self):
        self.assertEqual(init_cmd.epic_branch_name("MYD-16538"), "epic/myd-16538")

class Init(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve(); self.ws = self.tmp / "ws"; self.ws.mkdir()  # resolved: macOS /var → /private/var
        self.knowledge = self.tmp / "pdffiller-knowledge"; (self.knowledge / ".git").mkdir(parents=True); clones(self.tmp, "jsfiller", "pdffiller")

    def test_init_creates_worktree_delivery_marker_and_claude_md(self):
        import contextlib, io as _io
        io = FakeGit(); buf = _io.StringIO()
        with contextlib.redirect_stdout(buf): self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), io), 0)
        wt = self.ws / "pdffiller-knowledge"; d = wt / "context" / "workitems" / "demo" / "delivery"
        add = next(c for c in io.calls if c[0][:2] == ["worktree", "add"])  # the branch probe (`git branch --list`) precedes it
        self.assertEqual(add[0], ["worktree", "add", "-b", "epic/myd-1", str(wt), "origin/main"]); self.assertEqual(add[1], self.knowledge)  # minor 12: after a fetch
        self.assertIn((["fetch", "origin", "main"], self.knowledge), io.calls)
        for repo, base in (("jsfiller", "develop"), ("pdffiller", "master")):  # a worktree of <clone root>/<repo> on the per-workspace branch, cut from the fetched base
            self.assertIn((["fetch", "origin", base], self.tmp / repo), io.calls)
            self.assertIn((["worktree", "add", "-b", "ws/myd-1", str(self.ws / repo), "origin/" + base], self.tmp / repo), io.calls)
            self.assertIn("REPO: %s → %s (ws/myd-1 from origin/%s)" % (repo, self.ws / repo, base), buf.getvalue())
        rec = json.loads((d / ".workspace.json").read_text())
        self.assertEqual(rec["repos"], {"jsfiller": str(self.ws / "jsfiller"), "pdffiller": str(self.ws / "pdffiller")})
        self.assertEqual((rec["workspace"], rec["clone_root"], rec["knowledge"]), (str(self.ws), str(self.tmp), str(wt)))
        self.assertIn("WORKSPACE: %s (clone root %s)" % (self.ws, self.tmp), buf.getvalue()); self.assertIn("NEXT: cd %s && claude" % self.ws, buf.getvalue())
        data = json.loads((d / "state.json").read_text())
        self.assertEqual(data["epic"]["repos"]["jsfiller"]["path"], "jsfiller"); self.assertNotIn("workspace", data["epic"])
        self.assertIn("`jsfiller/` (ws/myd-1 from `origin/develop`)", (self.ws / "CLAUDE.md").read_text()); self.assertIn(".workspace.json", (d / ".gitignore").read_text())
        self.assertEqual((data["epic"]["key"], data["epic"]["github_org"], data["epic"]["roles"]["lead_github"]), ("MYD-1", "pdffiller", "leadlogin"))
        self.assertEqual(data["epic"]["repos"]["pdffiller"]["branch_prefix"], "l2f-myd-")
        self.assertEqual(data["epic"]["repos"]["jsfiller"]["ci_ignore"], ["pdf-review", "gate / gate"])
        self.assertEqual(data["epic"]["plan"], {"digest": None, "path": "plan.md", "submitted_at": None})
        self.assertEqual(data["epic"]["environment"], {"desk": "desk05", "recipe": "references/env/pdffiller-dev.md", "variant": "v1"})
        for name in ("ledger.md", "decisions.md", "plan.md", "briefs/.gitkeep", "reports/.gitkeep", "evidence/.gitkeep", ".gitattributes", ".state.lock", ".gitignore"):
            self.assertTrue((d / name).exists(), name)
        self.assertIn("MYD-1", (d / "plan.md").read_text()); self.assertIn("turnstile-stories", (d / "plan.md").read_text())
        self.assertEqual((self.ws / ".turnstile").read_text().strip(), "pdffiller-knowledge/context/workitems/demo/delivery")
        self.assertIn("MYD-1", (self.ws / "CLAUDE.md").read_text()); self.assertIn("TURNSTILE_LEAD=1", (self.ws / "CLAUDE.md").read_text())
        self.assertIn("Chat with the lead in English", (self.ws / "CLAUDE.md").read_text()); self.assertEqual(data["epic"]["chat_language"], "English")
        self.assertEqual([c[0][0] for c in io.calls[-3:]], ["commit", "rev-parse", "push"]); self.assertEqual(io.calls[-3][1], d)
        self.assertEqual(io.calls[-1][0], ["push", "-q", "origin", "HEAD:refs/heads/epic/myd-1"]); self.assertEqual(io.calls[-1][1], d)
        self.assertEqual(data["epic"]["knowledge"], {"branch": "epic/myd-1", "remote": "origin"})
        self.assertTrue(json.loads((d / ".sync.json").read_text())["pushed"]); self.assertIn(".sync.json", (d / ".gitignore").read_text())

    def test_workspace_claude_md_names_the_cli_path(self):
        from unittest import mock
        with mock.patch.object(init_cmd.shutil, "which", return_value=None):
            self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), FakeGit()), 0)
        text = (self.ws / "CLAUDE.md").read_text()
        self.assertIn("CLI: `%s`" % (init_cmd.ROOT / "scripts" / "turnstile"), text); self.assertNotIn("{{cli}}", text)
        ws2 = self.tmp / "ws2"; ws2.mkdir()
        with mock.patch.object(init_cmd.shutil, "which", return_value="/home/x/.local/bin/turnstile"):
            self.assertEqual(init_cmd.run(opts(ws2, self.knowledge), FakeGit()), 0)
        self.assertIn("CLI: `/home/x/.local/bin/turnstile`", (ws2 / "CLAUDE.md").read_text())
    def test_agent_github_is_optional_and_recorded(self):
        # 2026-10-14: the replies to self_resolved threads come from the agents' GitHub account (default: the lead's)
        init_cmd.run(opts(self.ws, self.knowledge), FakeGit())
        d = self.ws / "pdffiller-knowledge" / "context" / "workitems" / "demo" / "delivery"
        self.assertIsNone(json.loads((d / "state.json").read_text())["epic"]["roles"]["agent_github"])
        self.assertIn("agent_github", json.loads((init_cmd.TEMPLATES / "state.json").read_text())["epic"]["roles"])
        self.assertEqual(init_cmd.build_state(opts(self.ws, self.knowledge, agent_github="agentbot"))["epic"]["roles"]["agent_github"], "agentbot")
    def test_models_default_merge_and_validate(self):
        # lead rules 2026-10-19 / 2026-10-26: agent models live in epic.models; --models is a partial JSON override
        from turnstile_cli import models
        init_cmd.run(opts(self.ws, self.knowledge), FakeGit())
        d = self.ws / "pdffiller-knowledge" / "context" / "workitems" / "demo" / "delivery"
        written = json.loads((d / "state.json").read_text())["epic"]["models"]
        self.assertEqual(written, models.DEFAULTS); self.assertEqual(written["reviewer"], {"model": "opus", "effort": "xhigh"})
        self.assertEqual(written["story-reviewer"], {"model": "opus", "effort": "xhigh"}); self.assertEqual(written["investigator"]["model"], "haiku")
        m = init_cmd.build_state(opts(self.ws, self.knowledge, models='{"reviewer":{"model":"opus","effort":"high"},"tester":{"model":"opus"}}'))["epic"]["models"]
        self.assertEqual(m["reviewer"], {"model": "opus", "effort": "high"}); self.assertEqual(m["tester"], {"model": "opus", "effort": None})
        self.assertEqual(m["implementer"], models.DEFAULTS["implementer"]); self.assertEqual(sorted(m), sorted(models.DEFAULTS))
        self.assertEqual(models.parse('{"reviewer":{"effort":null}}')["reviewer"], {"model": "opus", "effort": None})
        for bad in ["not json", "[]", '{"nobody":{"model":"opus"}}', '{"reviewer":{"model":"gpt"}}', '{"reviewer":{"effort":"max"}}',
                    '{"reviewer":{"tools":"x"}}', '{"reviewer":{}}', '{"reviewer":"opus"}']:
            with self.assertRaises(TurnstileError, msg=bad): models.parse(bad)
        io = FakeGit(); self.assertEqual(init_cmd.run(opts(self.tmp / "ws9", self.knowledge, models='{"reviewer":{"model":"gpt"}}'), io), 2); self.assertEqual(io.calls, [])
    def test_init_records_flag_and_story_mode(self):
        import contextlib, io as _io
        st = init_cmd.build_state(opts(self.ws, self.knowledge, flag=" pwr-l2f-funnel ", story_mode="trunk"))["epic"]
        self.assertEqual((st["flag"], st["story_mode"]), ("pwr-l2f-funnel", "trunk"))
        st = init_cmd.build_state(opts(self.ws, self.knowledge))["epic"]; self.assertEqual((st["flag"], st["story_mode"]), (None, "stack"))
        with self.assertRaises(TurnstileError): init_cmd.build_state(opts(self.ws, self.knowledge, story_mode="branchy"))
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf): rc = init_cmd.run(opts(self.ws, self.knowledge, flag="pwr-x", story_mode="trunk"), FakeGit())
        self.assertEqual(rc, 0); self.assertIn("flag=pwr-x", buf.getvalue())
        t = json.loads((init_cmd.TEMPLATES / "state.json").read_text())["epic"]; self.assertIn("flag", t); self.assertEqual(t["story_mode"], "stack")
    def test_init_prints_the_effective_config_and_the_preferences_prompt(self):
        import contextlib, io as _io
        from turnstile_cli import config
        config.save_user({"review_skill": "/my-review"}); buf = _io.StringIO()
        with contextlib.redirect_stdout(buf): rc = init_cmd.run(opts(self.ws, self.knowledge, models='{"reviewer":{"effort":"high"}}'), FakeGit())
        self.assertEqual(rc, 0); out = buf.getvalue()
        self.assertIn("CONFIG: models implementer=sonnet", out); self.assertIn("reviewer=opus:high", out); self.assertIn("review_skill=/my-review", out)
        self.assertIn("overrides: epic models.reviewer, user review_skill", out); self.assertIn("NEXT: ask the lead once (skill § preferences)", out); self.assertIn("turnstile config set", out)
        d = self.ws / "pdffiller-knowledge" / "context" / "workitems" / "demo" / "delivery"; data = json.loads((d / "state.json").read_text())
        self.assertIsNone(data["epic"]["review_skill"]); self.assertIsNone(data["epic"]["story_review_skill"])  # the user's skill never lands in git
        self.assertIn("turnstile config", (self.ws / "CLAUDE.md").read_text())
    def test_chat_language_comes_from_init_not_the_template(self):
        # 2026-10-14 minor 11: personal items stay out of the plugin
        self.assertNotIn("Ukrainian", (init_cmd.TEMPLATES / "CLAUDE.md.workspace").read_text())
        init_cmd.run(opts(self.ws, self.knowledge, chat_language="Ukrainian"), FakeGit())
        self.assertIn("Chat with the lead in Ukrainian", (self.ws / "CLAUDE.md").read_text())
        d = self.ws / "pdffiller-knowledge" / "context" / "workitems" / "demo" / "delivery"
        self.assertEqual(json.loads((d / "state.json").read_text())["epic"]["chat_language"], "Ukrainian")

    def test_stale_local_base_fallback_and_rollback_on_failure(self):
        # 2026-10-14 minor 12: cut from origin/<base> after a fetch, fall back to the local base with a WARN; a failure after
        # state.json was written rolls the delivery dir, the marker and the generated CLAUDE.md back and says how to re-run
        import contextlib, io as _io
        git = FakeGit(fail={"fetch"}); buf = _io.StringIO()
        with contextlib.redirect_stdout(buf): rc = init_cmd.run(opts(self.ws, self.knowledge), git)
        self.assertEqual(rc, 0); self.assertIn("WARN", buf.getvalue())
        add = next(c for c in git.calls if c[0][:2] == ["worktree", "add"]); self.assertEqual(add[0][-1], "main")
        ws2 = self.tmp / "ws2"; ws2.mkdir()
        git = FakeGit(fail={"commit"}); buf = _io.StringIO()
        with contextlib.redirect_stdout(buf): rc = init_cmd.run(opts(ws2, self.knowledge), git)
        self.assertEqual(rc, 2); out = buf.getvalue()
        self.assertIn("rolled back", out); self.assertIn("re-run", out)
        d = ws2 / "pdffiller-knowledge" / "context" / "workitems" / "demo" / "delivery"
        self.assertFalse(d.exists()); self.assertFalse((ws2 / ".turnstile").exists()); self.assertFalse((ws2 / "CLAUDE.md").exists())
        self.assertEqual(init_cmd.run(opts(ws2, self.knowledge), FakeGit()), 0)  # a clean re-run works

    def test_failed_init_keeps_a_migrated_delivery_dir(self):
        # round 2: plan 3 moves ledger/briefs/reports in before init; a rollback must not delete them, init must not overwrite plan/decisions
        import contextlib, io as _io
        ws3 = self.tmp / "ws3"; d = ws3 / "pdffiller-knowledge" / "context" / "workitems" / "demo" / "delivery"; (d / "reports").mkdir(parents=True)
        (d / "ledger.md").write_text("old ledger\n"); (d / "reports" / "R.md").write_text("r"); (d / "decisions.md").write_text("mine")
        with contextlib.redirect_stdout(_io.StringIO()): rc = init_cmd.run(opts(ws3, self.knowledge), FakeGit(fail={"commit"}))
        self.assertEqual(rc, 2); self.assertTrue((d / "reports" / "R.md").exists()); self.assertIn("old ledger", (d / "ledger.md").read_text())
        self.assertEqual((d / "decisions.md").read_text(), "mine"); self.assertFalse((d / "state.json").exists())
        with contextlib.redirect_stdout(_io.StringIO()): self.assertEqual(init_cmd.run(opts(ws3, self.knowledge), FakeGit()), 0)

    def test_init_records_a_failed_push_as_not_pushed(self):
        import contextlib, io as _io
        git = FakeGit(fail={"push"}); buf = _io.StringIO()
        with contextlib.redirect_stdout(buf): rc = init_cmd.run(opts(self.ws, self.knowledge), git)
        self.assertEqual(rc, 0); self.assertIn("WARN: not pushed: git push failed: simulated", buf.getvalue()); self.assertIn("SYNC: NOT PUSHED", buf.getvalue())
        d = self.ws / "pdffiller-knowledge" / "context" / "workitems" / "demo" / "delivery"
        rec = json.loads((d / ".sync.json").read_text()); self.assertFalse(rec["pushed"]); self.assertIn("simulated", rec["reason"])
    def test_init_keeps_existing_claude_md(self):
        (self.ws / "CLAUDE.md").write_text("mine\n")
        init_cmd.run(opts(self.ws, self.knowledge), FakeGit())
        self.assertEqual((self.ws / "CLAUDE.md").read_text(), "mine\n"); self.assertTrue((self.ws / "CLAUDE.md.turnstile").exists())

    def test_init_on_the_same_epic_workspace_attaches_and_refuses_a_cleaned_marker(self):
        import contextlib, io as _io
        from turnstile_cli import reconcile
        io = FakeGit(); init_cmd.run(opts(self.ws, self.knowledge), io); n = len(io.calls); buf = _io.StringIO()
        with mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")), contextlib.redirect_stdout(buf):
            self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), io), 0)
        self.assertIn("already holds epic MYD-1; attaching", buf.getvalue()); self.assertIn("OK attach MYD-1", buf.getvalue())
        self.assertFalse(any(c[0][:2] == ["worktree", "add"] for c in io.calls[n:])); self.assertFalse(any(c[0][:1] == ["commit"] for c in io.calls[n:]))
        self.assertIn((["fetch", "origin", "epic/myd-1"], self.knowledge), io.calls[n:])
        (self.ws / ".turnstile").unlink(); n = len(io.calls)
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), io), 2)
        self.assertFalse(any(c[0][0] in ("worktree", "commit") for c in io.calls[n:]))

    def test_init_validates_before_touching_disk(self):
        io = FakeGit()
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge, repos=["{bad"]), io), 2); self.assertEqual(io.calls, [])
        self.assertEqual(init_cmd.run(opts(self.ws, self.tmp / "nope"), io), 2); self.assertTrue(all(c[0][0] == "remote" for c in io.calls))

    def test_init_refuses_a_foreign_workspace_and_a_missing_clone_before_any_worktree(self):
        import contextlib, io as _io
        (self.ws / "notes.txt").write_text("x"); git = FakeGit(); buf = _io.StringIO()
        with contextlib.redirect_stdout(buf): rc = init_cmd.run(opts(self.ws, self.knowledge), git)
        self.assertEqual(rc, 2); self.assertIn("is not empty (notes.txt)", buf.getvalue()); self.assertFalse(any(c[0][0] == "worktree" for c in git.calls))
        ws2 = self.tmp / "ws2"; git = FakeGit(); buf = _io.StringIO()
        with contextlib.redirect_stdout(buf): rc = init_cmd.run(opts(ws2, self.knowledge, repos=[JS, '{"name":"ghost","base":"main","slack":"C3"}']), git)
        self.assertEqual(rc, 2); self.assertIn("no clone of ghost at %s" % (self.tmp / "ghost"), buf.getvalue()); self.assertFalse(ws2.exists())
        self.assertFalse(any(c[0][0] == "worktree" for c in git.calls))
        other = self.tmp / "elsewhere" / "ghost"; (other / ".git").mkdir(parents=True); git = FakeGit()
        rc = init_cmd.run(opts(ws2, self.knowledge, repos=[JS, '{"name":"ghost","base":"main","slack":"C3","path":"%s"}' % other]), git)
        self.assertEqual(rc, 0); self.assertIn((["worktree", "add", "-b", "ws/myd-1", str(ws2 / "ghost"), "origin/main"], other), git.calls)
        data = json.loads((ws2 / "pdffiller-knowledge" / "context" / "workitems" / "demo" / "delivery" / "state.json").read_text())
        self.assertEqual(data["epic"]["repos"]["ghost"]["path"], "ghost"); self.assertNotIn(str(other), json.dumps(data))

    def test_init_defaults_the_workspace_to_clone_root_slash_key(self):
        import contextlib, io as _io
        git = FakeGit(); buf = _io.StringIO()
        with contextlib.redirect_stdout(buf): rc = init_cmd.run(opts(None, self.knowledge, workspace=None, clone_root=str(self.tmp), epic="MYD-19001"), git)
        self.assertEqual(rc, 0, buf.getvalue()); ws = self.tmp / "myd-19001"
        self.assertTrue((ws / ".turnstile").exists()); self.assertIn((["worktree", "add", "-b", "ws/myd-19001", str(ws / "jsfiller"), "origin/develop"], self.tmp / "jsfiller"), git.calls)
        self.assertTrue((ws / "pdffiller-knowledge").exists()); self.assertIn("WORKSPACE: %s" % ws, buf.getvalue())
        rc = init_cmd.run(opts(None, self.knowledge, workspace=None, clone_root=str(self.tmp / "nope"), epic="MYD-2"), FakeGit()); self.assertEqual(rc, 2)

    def test_init_with_real_git(self):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.knowledge, check=True)
        (self.knowledge / "README.md").write_text("k\n")
        g = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
        subprocess.run(g + ["add", "."], cwd=self.knowledge, check=True); subprocess.run(g + ["commit", "-qm", "init"], cwd=self.knowledge, check=True)
        for repo, base in (("jsfiller", "develop"), ("pdffiller", "master")):
            shutil.rmtree(self.tmp / repo); subprocess.run(["git", "init", "-q", "-b", base, repo], cwd=self.tmp, check=True); (self.tmp / repo / "a.txt").write_text("a\n")
            subprocess.run(g + ["add", "."], cwd=self.tmp / repo, check=True); subprocess.run(g + ["commit", "-qm", "seed"], cwd=self.tmp / repo, check=True)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        class RealGit(init_cmd.InitIO):
            def git(self, args, cwd):
                out = subprocess.run(["git", "-c", "commit.gpgsign=false"] + args, cwd=str(cwd), capture_output=True, text=True, env=env)
                if out.returncode != 0: raise TurnstileError(out.stderr)
                return out.stdout
        import contextlib, io as _io
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf): self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), RealGit()), 0)
        wt = self.ws / "pdffiller-knowledge"
        self.assertEqual(subprocess.run(["git", "branch", "--show-current"], cwd=wt, capture_output=True, text=True).stdout.strip(), "epic/myd-1")
        for repo in ("jsfiller", "pdffiller"):  # no origin: the WARN names the local fallback and the worktree still lands on ws/<key>
            self.assertEqual(subprocess.run(["git", "branch", "--show-current"], cwd=self.ws / repo, capture_output=True, text=True).stdout.strip(), "ws/myd-1")
            self.assertTrue((self.ws / repo / "a.txt").exists())
        self.assertIn("cutting ws/myd-1 for jsfiller from the local develop", buf.getvalue()); self.assertIn("cutting ws/myd-1 for pdffiller from the local master", buf.getvalue())
        self.assertIn("turnstile: init MYD-1", subprocess.run(["git", "log", "--oneline"], cwd=wt, capture_output=True, text=True).stdout)
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True).stdout, "")
        rec = json.loads((wt / "context" / "workitems" / "demo" / "delivery" / ".sync.json").read_text()); self.assertFalse(rec["pushed"])  # no origin

    def test_init_refuses_knowledge_clone_inside_workspace_and_foreign_marker(self):
        k = self.ws / "pdffiller-knowledge"; clones(self.ws, "jsfiller", "pdffiller")
        subprocess.run(["git", "init", "-q", "-b", "main", str(k)], check=True)
        io = init_cmd.InitIO()
        self.assertEqual(init_cmd.run(opts(self.ws, k), io), 2)
        self.assertFalse((k / "context").exists()); self.assertFalse((self.ws / ".turnstile").exists())
        (self.ws / ".turnstile").write_text("other/delivery\n")
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), FakeGit()), 2)
        self.assertEqual((self.ws / ".turnstile").read_text(), "other/delivery\n")
