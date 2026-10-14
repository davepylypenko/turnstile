import json, os, pathlib, subprocess, tempfile, unittest
from turnstile_cli import init_cmd
from turnstile_cli.errors import TurnstileError

JS = '{"name":"jsfiller","base":"develop","epic_branch":"epic_myd-1","slack":"C1","gate":"pdf-review","ci_ignore":["pdf-review","gate / gate"]}'
MONO = '{"name":"pdffiller","base":"master","epic_branch":"l2f","slack":"G1","gate":"run-lint","gate_check":null,"copilot":true,"branch_prefix":"l2f-myd-"}'

def opts(ws, knowledge, **kw):
    base = dict(epic="MYD-1", workitem="demo", knowledge=str(knowledge), lead="lead@example.com", lead_github="leadlogin",
                github_org="pdffiller", repos=[JS, MONO], variant="v1", desk="desk05", workspace=str(ws))
    base.update(kw); return init_cmd.InitOptions(**base)

class FakeGit(init_cmd.InitIO):
    def __init__(self, fail=()): self.calls = []; self.fail = set(fail)
    def git(self, args, cwd):
        self.calls.append((args, pathlib.Path(cwd)))
        if args[0] in self.fail:
            raise TurnstileError("git %s failed: simulated" % args[0])
        if args[:2] == ["branch", "--show-current"]:
            return "epic/myd-1\n"  # an existing worktree made by an earlier run is on the epic branch
        if args[:2] == ["worktree", "add"]:
            pathlib.Path(args[4] if args[2] == "-b" else args[2]).mkdir(parents=True)
        return ""

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
    def test_epic_branch_name(self):
        self.assertEqual(init_cmd.epic_branch_name("MYD-16538"), "epic/myd-16538")

class Init(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve(); self.ws = self.tmp / "ws"; self.ws.mkdir()  # resolved: macOS /var → /private/var
        self.knowledge = self.tmp / "pdffiller-knowledge"; (self.knowledge / ".git").mkdir(parents=True)

    def test_init_creates_worktree_delivery_marker_and_claude_md(self):
        io = FakeGit()
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), io), 0)
        wt = self.ws / "pdffiller-knowledge"; d = wt / "context" / "workitems" / "demo" / "delivery"
        add = next(c for c in io.calls if c[0][:2] == ["worktree", "add"])  # the branch probe (`git branch --list`) precedes it
        self.assertEqual(add[0], ["worktree", "add", "-b", "epic/myd-1", str(wt), "origin/main"]); self.assertEqual(add[1], self.knowledge)  # minor 12: after a fetch
        self.assertIn((["fetch", "origin", "main"], self.knowledge), io.calls)
        data = json.loads((d / "state.json").read_text())
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
        self.assertEqual(io.calls[-1][0][:3], ["commit", "-q", "-m"]); self.assertEqual(io.calls[-1][1], d)

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

    def test_init_keeps_existing_claude_md(self):
        (self.ws / "CLAUDE.md").write_text("mine\n")
        init_cmd.run(opts(self.ws, self.knowledge), FakeGit())
        self.assertEqual((self.ws / "CLAUDE.md").read_text(), "mine\n"); self.assertTrue((self.ws / "CLAUDE.md.turnstile").exists())

    def test_init_reuses_worktree_and_refuses_existing_state(self):
        io = FakeGit(); init_cmd.run(opts(self.ws, self.knowledge), io); n = len(io.calls)
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), io), 2)
        self.assertFalse(any(c[0][:2] == ["worktree", "add"] for c in io.calls[n:]))
        self.assertFalse(any(c[0][:1] == ["commit"] for c in io.calls[n:]))

    def test_init_validates_before_touching_disk(self):
        io = FakeGit()
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge, repos=["{bad"]), io), 2); self.assertEqual(io.calls, [])
        self.assertEqual(init_cmd.run(opts(self.ws, self.tmp / "nope"), io), 2); self.assertEqual(io.calls, [])

    def test_init_with_real_git(self):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.knowledge, check=True)
        (self.knowledge / "README.md").write_text("k\n")
        g = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
        subprocess.run(g + ["add", "."], cwd=self.knowledge, check=True); subprocess.run(g + ["commit", "-qm", "init"], cwd=self.knowledge, check=True)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        class RealGit(init_cmd.InitIO):
            def git(self, args, cwd):
                out = subprocess.run(["git", "-c", "commit.gpgsign=false"] + args, cwd=str(cwd), capture_output=True, text=True, env=env)
                if out.returncode != 0: raise TurnstileError(out.stderr)
                return out.stdout
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), RealGit()), 0)
        wt = self.ws / "pdffiller-knowledge"
        self.assertEqual(subprocess.run(["git", "branch", "--show-current"], cwd=wt, capture_output=True, text=True).stdout.strip(), "epic/myd-1")
        self.assertIn("turnstile: init MYD-1", subprocess.run(["git", "log", "--oneline"], cwd=wt, capture_output=True, text=True).stdout)
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True).stdout, "")

    def test_init_refuses_knowledge_clone_inside_workspace_and_foreign_marker(self):
        k = self.ws / "pdffiller-knowledge"
        subprocess.run(["git", "init", "-q", "-b", "main", str(k)], check=True)
        io = init_cmd.InitIO()
        self.assertEqual(init_cmd.run(opts(self.ws, k), io), 2)
        self.assertFalse((k / "context").exists())
        (self.ws / ".turnstile").write_text("other/delivery\n")
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), FakeGit()), 2)
        self.assertEqual((self.ws / ".turnstile").read_text(), "other/delivery\n")
