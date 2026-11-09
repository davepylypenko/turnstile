import contextlib, io, json, os, pathlib, shutil, subprocess, sys, tempfile, unittest
from unittest import mock
from turnstile_cli import init_cmd, paths, plan_cmd, reconcile, repo_cmd, start_cmd
from turnstile_cli.errors import TurnstileError

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = '{"name":"app","base":"main","slack":"C1","gate":"pr-review","gate_check":null}'
WEB = '{"name":"web","base":"develop","slack":"C2"}'
PLAN = """# plan

```json turnstile-stories
{"S1": {"title": "Header", "tickets": ["MYD-10"], "repos": ["%s"], "branch": "epic/myd-1"}}
```
"""

def out_of(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = fn(*a, **kw)
    return rc, buf.getvalue()

class StubIO(init_cmd.InitIO):
    def __init__(self, bares, login="lg", name="Lead G", origin="git@github.com:pdffiller/pdffiller-knowledge.git"):
        self.bares, self.login, self.name, self.origin, self.clones = bares, login, name, origin, []
    def github_login(self): return self.login
    def github_name(self): return self.name
    def gh_clone(self, org, name, dest):
        self.clones.append((org, name, pathlib.Path(dest)))
        subprocess.run(["git", "clone", "-q", str(self.bares[name]), str(dest)], check=True)
    def git(self, args, cwd):
        if args[:3] == ["remote", "get-url", "origin"] and pathlib.Path(cwd).name == "pdffiller-knowledge":
            return self.origin + "\n"
        return super().git(args, cwd)

class Start(unittest.TestCase):
    """Network-free: bare origins for the knowledge repo and two code repos, their clones side by side in a clone root; gh is stubbed."""
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        cfg = self.tmp / "gitconfig"; cfg.write_text("[user]\n\tname = t\n\temail = t@t\n[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n")
        self.user = self.tmp / "cfg" / "u.json"; self.user.parent.mkdir()
        env = {"GIT_CONFIG_GLOBAL": str(cfg), "GIT_CONFIG_NOSYSTEM": "1", "TURNSTILE_USER_CONFIG": str(self.user), "HOME": str(self.tmp)}
        self.env = mock.patch.dict(os.environ, env); self.env.start(); self.addCleanup(self.env.stop); os.environ.pop(paths.EPIC_ENV, None)
        self.gh = mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")); self.gh.start(); self.addCleanup(self.gh.stop)
        self.bases = {"pdffiller-knowledge": "main", "app": "main", "web": "develop"}; self.bares = {}
        for name, base in self.bases.items():
            bare = self.tmp / "origin" / (name + ".git"); bare.parent.mkdir(exist_ok=True)
            self.git(self.tmp, "init", "-q", "--bare", str(bare)); self.git(bare, "symbolic-ref", "HEAD", "refs/heads/" + base)
            seed = self.tmp / "seed" / name; seed.mkdir(parents=True); self.git(seed, "init", "-q", "-b", base); (seed / "README.md").write_text(name + "\n")
            if name == "pdffiller-knowledge":
                for folder, text in (("demo-myd-1", "# Demo\n\nEpic MYD-1: sharing for l2f documents\n"), ("other", "Notes on MYD-10 and MYD-100\n"),
                                     ("myd-3-foo", "# Foo\n"), ("bar", "Epic MYD-3 lives here too\n")):
                    (seed / "context" / "workitems" / folder).mkdir(parents=True); (seed / "context" / "workitems" / folder / "README.md").write_text(text)
            self.git(seed, "add", "."); self.git(seed, "commit", "-qm", "seed"); self.git(seed, "push", "-q", str(bare), "HEAD:refs/heads/" + base)
            self.bares[name] = bare
        self.root = self.tmp / "root"; self.clone_all(self.root); self.io = StubIO(self.bares)
        self.old_cwd = os.getcwd(); self.addCleanup(os.chdir, self.old_cwd)
    def clone_all(self, root):
        root.mkdir()
        for name, bare in self.bares.items(): self.git(self.tmp, "clone", "-q", str(bare), str(root / name))
    def git(self, cwd, *args):
        return subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()
    def start(self, key, io=None, **kw):
        return out_of(start_cmd.run, start_cmd.StartOptions(epic=key, **kw), io or self.io)
    def delivery(self, root=None):
        return (root or self.root) / "myd-1" / "pdffiller-knowledge" / "context" / "workitems" / "demo-myd-1" / "delivery"
    def state(self, root=None):
        return json.loads((self.delivery(root) / "state.json").read_text())
    def nexts(self, out):
        return [ln for ln in out.splitlines() if ln.startswith("NEXT:")]

    def test_start_creates_a_new_epic_without_repos_then_continues_it_from_any_clone(self):
        self.user.write_text('{"chat_language": "uk"}')
        os.chdir(self.root); rc, out = self.start("MYD-1"); self.assertEqual(rc, 0, out)
        ws = self.root / "myd-1"; d = self.delivery()
        self.assertIn("WORKSPACE: %s (clone root %s)" % (ws, self.root), out); self.assertIn("OK init MYD-1", out); self.assertIn("OK start MYD-1", out)
        self.assertEqual(self.nexts(out), [start_cmd.KICKOFF_NEXT]); self.assertNotIn("&& claude", out); self.assertNotIn("REPO:", out)
        self.assertLess(out.index("OK start MYD-1"), out.index("NEXT: kickoff"))
        e = self.state()["epic"]
        self.assertEqual(e["repos"], {}); self.assertEqual(e["workitem"], "demo-myd-1"); self.assertEqual(e["github_org"], "pdffiller")
        self.assertEqual((e["roles"]["lead"], e["roles"]["lead_github"], e["roles"]["agent_github"]), ("Lead G", "lg", "lg"))
        self.assertEqual(e["members"]["lg"]["variant"], "myd-1-lg"); self.assertEqual(e["chat_language"], "uk"); self.assertEqual(e["story_mode"], "stack")
        self.assertIn("Chat with the lead in uk", (ws / "CLAUDE.md").read_text()); self.assertIn("Repo worktrees in this folder: none", (ws / "CLAUDE.md").read_text())
        self.assertEqual((ws / ".turnstile").read_text().strip(), "pdffiller-knowledge/context/workitems/demo-myd-1/delivery")
        self.assertEqual(self.git(self.bares["pdffiller-knowledge"], "rev-parse", "epic/myd-1"), self.git(ws / "pdffiller-knowledge", "rev-parse", "HEAD"))
        reg = paths.load_registry()
        self.assertEqual(reg["epics"]["MYD-1"], {"workspace": str(ws), "clone_root": str(self.root), "delivery": str(d)}); self.assertEqual(reg["active"], {str(self.root): "MYD-1"})
        self.assertEqual(paths.registry_path(), self.user.parent / "workspaces.json")
        for where in (self.root / "pdffiller-knowledge", self.root / "app", ws / "pdffiller-knowledge", ws):
            os.chdir(where); rc, out = self.start("MYD-1"); self.assertEqual(rc, 0, out)
            self.assertIn("WORKSPACE: %s (clone root %s)" % (ws, self.root), out); self.assertIn("OK attach MYD-1", out); self.assertIn("OK start MYD-1", out)
            self.assertEqual(self.nexts(out), [start_cmd.STATUS_NEXT], where); self.assertNotIn("OK init", out); self.assertNotIn("&& claude", out)
            self.assertIn("MEMBER: lg · variant myd-1-lg", out); self.assertIn("== MYD-1", out)
        self.assertEqual(list(self.state()["epic"]["members"]), ["lg"])

    def test_start_attaches_on_another_machine_and_derives_the_member(self):
        os.chdir(self.root); rc, out = self.start("MYD-1"); self.assertEqual(rc, 0, out)
        root2 = self.tmp / "root2"; self.clone_all(root2); os.chdir(root2 / "web")
        io2 = StubIO(self.bares, login="Ivanov", name="Ivan I"); rc, out = self.start("MYD-1", io2); self.assertEqual(rc, 0, out)
        self.assertIn("WORKSPACE: %s (clone root %s)" % (root2 / "myd-1", root2), out); self.assertNotIn("OK init", out)
        self.assertIn("MEMBER: Ivanov · variant myd-1-ivanov · desk none · board new artifact", out); self.assertEqual(self.nexts(out), [start_cmd.STATUS_NEXT])
        self.assertEqual(sorted(self.state(root2)["epic"]["members"]), ["Ivanov", "lg"]); self.assertEqual(self.state(root2)["epic"]["members"]["Ivanov"]["name"], "Ivan I")
        reg = paths.load_registry(); self.assertEqual(reg["epics"]["MYD-1"]["clone_root"], str(root2)); self.assertEqual(reg["active"][str(root2)], "MYD-1")
        self.assertEqual(self.git(root2 / "myd-1" / "pdffiller-knowledge", "branch", "--show-current"), "epic/myd-1")
        rc, out = self.start("MYD-1", io2, desk="desk07"); self.assertEqual(rc, 0, out); self.assertEqual(self.state(root2)["epic"]["members"]["Ivanov"]["desk"], "desk07")

    def test_workitem_detection_none_several_and_override(self):
        os.chdir(self.root)
        rc, out = self.start("MYD-2"); self.assertEqual(rc, 2)
        self.assertIn("MISSING no workitem folder under context/workitems mentions MYD-2; create one (%s/context/workitems/<slug>/) or pass --workitem <name>" % (self.root / "pdffiller-knowledge"), out)
        self.assertFalse((self.root / "myd-2").exists()); self.assertNotIn("MYD-2", paths.load_registry()["epics"])
        rc, out = self.start("MYD-3"); self.assertEqual(rc, 2); self.assertIn("MISSING several workitems mention MYD-3: bar, myd-3-foo — pass --workitem <name>", out)
        rc, out = self.start("MYD-3", workitem="bar"); self.assertEqual(rc, 0, out); self.assertTrue((self.root / "myd-3" / "pdffiller-knowledge" / "context" / "workitems" / "bar" / "delivery" / "state.json").exists())
        self.assertEqual(paths.load_registry()["active"][str(self.root)], "MYD-3")
        self.assertEqual(start_cmd.github_org("https://github.com/pdffiller/x"), "pdffiller"); self.assertEqual(start_cmd.github_org("ssh://git@github.com/org-1/y.git"), "org-1")
        with self.assertRaises(TurnstileError): start_cmd.github_org("/tmp/origin/x.git")
        rc, out = self.start("MYD-4", StubIO(self.bares, login=""), workitem="bar"); self.assertEqual(rc, 2); self.assertIn("no GitHub login", out)
        nowhere = self.tmp / "nowhere"; nowhere.mkdir(); os.chdir(nowhere)
        rc, out = self.start("MYD-1"); self.assertEqual(rc, 2); self.assertIn("no clone root", out)

    def test_repo_add_creates_the_worktree_clones_a_missing_repo_and_refuses_duplicates(self):
        os.chdir(self.root); rc, out = self.start("MYD-1"); self.assertEqual(rc, 0, out); d = self.delivery(); ws = self.root / "myd-1"
        rc, out = out_of(repo_cmd.add, d, APP, init_io=self.io); self.assertEqual(rc, 0, out)
        self.assertIn("REPO: app → %s (ws/myd-1 from origin/main)" % (ws / "app"), out); self.assertIn("OK repo app added (base main)", out)
        e = self.state()["epic"]; self.assertEqual(e["repos"]["app"], {"base": "main", "epic_branch": "main", "slack": "C1", "gate": "pr-review", "gate_check": None, "ci_ignore": [], "copilot": False, "path": "app"})
        self.assertEqual(self.git(ws / "app", "branch", "--show-current"), "ws/myd-1"); self.assertEqual(self.git(self.root / "app", "branch", "--show-current"), "main")
        self.assertEqual(json.loads((d / ".workspace.json").read_text())["repos"], {"app": str(ws / "app")}); self.assertEqual(json.loads((d / ".workspace.json").read_text())["member"], "lg")
        self.assertIn("`app/` (ws/myd-1 from `origin/main`)", (ws / "CLAUDE.md").read_text())
        self.assertIn("turnstile: repo app added", self.git(d, "log", "--oneline", "-1")); self.assertEqual(self.git(d, "status", "--porcelain"), "")
        self.assertEqual(self.git(self.bares["pdffiller-knowledge"], "rev-parse", "epic/myd-1"), self.git(d, "rev-parse", "HEAD"))
        shutil.rmtree(self.root / "web")
        rc, out = out_of(repo_cmd.add, d, WEB, init_io=self.io); self.assertEqual(rc, 0, out)
        self.assertEqual(self.io.clones, [("pdffiller", "web", self.root / "web")]); self.assertIn("CLONE: gh repo clone pdffiller/web %s" % (self.root / "web"), out)
        self.assertEqual(self.git(ws / "web", "branch", "--show-current"), "ws/myd-1"); self.assertTrue((ws / "web" / "README.md").exists())
        self.assertEqual(sorted(self.state()["epic"]["repos"]), ["app", "web"]); self.assertEqual(sorted(json.loads((d / ".workspace.json").read_text())["repos"]), ["app", "web"])
        text = (ws / "CLAUDE.md").read_text(); self.assertIn("`app/` (ws/myd-1 from `origin/main`)", text); self.assertIn("`web/` (ws/myd-1 from `origin/develop`)", text)
        n = len(self.io.clones)
        rc, out = out_of(repo_cmd.add, d, APP, init_io=self.io); self.assertEqual(rc, 2); self.assertIn("app is already an epic repo; edit it with turnstile repo set app", out)
        rc, out = out_of(repo_cmd.add, d, '{"name":"x"}', init_io=self.io); self.assertEqual(rc, 2); self.assertIn("--repo lacks", out)
        self.assertEqual(len(self.io.clones), n); self.assertEqual(sorted(self.state()["epic"]["repos"]), ["app", "web"])
        (d / "plan.md").write_text(PLAN % "ghost"); rc, out = out_of(plan_cmd.run, d); self.assertEqual(rc, 2)
        self.assertIn("MISSING story S1 names repo ghost — run: turnstile repo add '{\"name\":\"ghost\",\"base\":\"main\",\"slack\":\"…\"}'", out)
        (d / "plan.md").write_text(PLAN % "app"); rc, out = out_of(plan_cmd.run, d); self.assertEqual(rc, 0, out)

    def test_registry_resolves_the_delivery_from_the_root_the_clones_and_the_env(self):
        os.chdir(self.root); rc, out = self.start("MYD-1"); self.assertEqual(rc, 0, out); d = self.delivery(); ws = self.root / "myd-1"
        for where in (self.root, self.root / "pdffiller-knowledge", self.root / "app", self.root / "app" / "sub", ws / "pdffiller-knowledge" / "context"):
            where.mkdir(parents=True, exist_ok=True)
            self.assertEqual(paths.find_delivery(where, None), d, where)
        nowhere = self.tmp / "nowhere"; nowhere.mkdir()
        with self.assertRaises(TurnstileError) as cm: paths.find_delivery(nowhere, None)
        self.assertIn("run turnstile start <KEY>", str(cm.exception)); self.assertIn("no .turnstile", str(cm.exception))
        with mock.patch.dict(os.environ, {paths.EPIC_ENV: "MYD-1"}): self.assertEqual(paths.find_delivery(nowhere, None), d)
        with mock.patch.dict(os.environ, {paths.EPIC_ENV: "MYD-9"}):
            with self.assertRaises(TurnstileError) as cm: paths.find_delivery(nowhere, None)
            self.assertIn("TURNSTILE_EPIC=MYD-9 names no registered epic (known: MYD-1)", str(cm.exception))
        paths.register("MYD-2", self.root / "myd-2", self.root, d)
        self.assertEqual(paths.find_delivery(self.root / "app", None), d)
        reg = paths.load_registry(); reg["active"] = {}; paths.save_registry(reg)
        with self.assertRaises(TurnstileError) as cm: paths.find_delivery(self.root / "app", None)
        self.assertEqual(str(cm.exception), "several epics in %s: MYD-1, MYD-2 — run turnstile start <KEY>" % self.root)
        self.assertEqual(paths.find_delivery(ws / "pdffiller-knowledge", None), d)
        paths.set_active(self.root, "MYD-2"); self.assertEqual(paths.resolve_registry(self.root / "app")[0], "MYD-2")
        self.assertEqual(paths.known_keys(self.root / "web"), ["MYD-1", "MYD-2"]); self.assertEqual(paths.known_keys(nowhere), [])
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-m", "turnstile_cli", "status"], cwd=nowhere, capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 2, out.stderr); self.assertEqual(out.stdout.strip(), 'NO EPIC: say "start epic <KEY>" — known here: none')
        reg = paths.load_registry(); reg["active"] = {}; paths.save_registry(reg)
        out = subprocess.run([sys.executable, "-m", "turnstile_cli", "status"], cwd=self.root / "app", capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 2, out.stderr); self.assertEqual(out.stdout.strip(), 'NO EPIC: say "start epic <KEY>" — known here: MYD-1, MYD-2')
        out = subprocess.run([sys.executable, "-m", "turnstile_cli", "--delivery", str(d), "status"], cwd=nowhere, capture_output=True, text=True, env=env)
        self.assertIn("== MYD-1", out.stdout, out.stderr)

    def test_a_workspace_found_through_its_marker_registers_itself(self):
        os.chdir(self.root); rc, out = self.start("MYD-1"); self.assertEqual(rc, 0, out); d = self.delivery(); ws = self.root / "myd-1"
        paths.save_registry({"epics": {}, "active": {}})
        with self.assertRaises(TurnstileError): paths.find_delivery(self.root / "app", None)
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-m", "turnstile_cli", "status"], cwd=ws, capture_output=True, text=True, env=env)
        self.assertIn("== MYD-1", out.stdout, out.stderr)
        self.assertEqual(paths.load_registry(), {"epics": {"MYD-1": {"workspace": str(ws), "clone_root": str(self.root), "delivery": str(d)}}, "active": {}})
        self.assertEqual(paths.find_delivery(self.root / "app", None), d)
        self.assertIsNone(paths.ensure_registered(self.tmp / "nowhere"))

    def test_the_old_init_and_attach_clis_still_run_and_register(self):
        os.chdir(self.root)
        rc, out = out_of(init_cmd.run, init_cmd.InitOptions(epic="MYD-1", workitem="demo-myd-1", lead="l", lead_github="lg", github_org="o", repos=[APP]), self.io)
        self.assertEqual(rc, 0, out); self.assertIn("NEXT: ask the lead once", out); self.assertIn("REPO: app →", out); self.assertNotIn("&& claude", out)
        self.assertEqual(paths.load_registry()["epics"]["MYD-1"]["workspace"], str(self.root / "myd-1")); self.assertEqual(paths.load_registry()["active"], {})
        rc, out = out_of(init_cmd.run, init_cmd.InitOptions(epic="MYD-5", workitem="bar", lead="l", lead_github="lg", github_org="o"), self.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.state()["epic"]["repos"]["app"]["path"], "app")
        self.assertEqual(json.loads((self.root / "myd-5" / "pdffiller-knowledge" / "context" / "workitems" / "bar" / "delivery" / "state.json").read_text())["epic"]["repos"], {})
