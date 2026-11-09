import contextlib, io, json, os, pathlib, shutil, subprocess, tempfile, unittest
from unittest import mock
from turnstile_cli import attach_cmd, brief_cmd, init_cmd, reconcile, state, workspace

APP = '{"name":"app","base":"main","slack":"C1","gate":"pr-review","gate_check":null}'
WEB = '{"name":"web","base":"develop","slack":"C2"}'
ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIEFS = ROOT / "skills" / "turnstile" / "references" / "briefs"

def out_of(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = fn(*a, **kw)
    return rc, buf.getvalue()

def init_opts(key, **kw):
    o = dict(epic=key, workitem="demo-" + key.lower(), lead="l", lead_github="lg", github_org="o", repos=[APP, WEB]); o.update(kw)
    return init_cmd.InitOptions(**o)

class Workspace(unittest.TestCase):
    """Network-free: bare origins for the knowledge repo and two code repos, their clones side by side in a clone root."""
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        cfg = self.tmp / "gitconfig"; cfg.write_text("[user]\n\tname = t\n\temail = t@t\n[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n")
        env = {"GIT_CONFIG_GLOBAL": str(cfg), "GIT_CONFIG_NOSYSTEM": "1", "TURNSTILE_USER_CONFIG": str(self.tmp / "u.json"), "HOME": str(self.tmp)}
        self.env = mock.patch.dict(os.environ, env); self.env.start(); self.addCleanup(self.env.stop)
        self.gh = mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")); self.gh.start(); self.addCleanup(self.gh.stop)
        self.bases = {"pdffiller-knowledge": "main", "app": "main", "web": "develop"}; self.bares = {}
        for name, base in self.bases.items():
            bare = self.tmp / "origin" / (name + ".git"); bare.parent.mkdir(exist_ok=True)
            self.git(self.tmp, "init", "-q", "--bare", str(bare)); self.git(bare, "symbolic-ref", "HEAD", "refs/heads/" + base)
            seed = self.tmp / "seed" / name; seed.mkdir(parents=True); self.git(seed, "init", "-q", "-b", base); (seed / "README.md").write_text(name + "\n")
            self.git(seed, "add", "."); self.git(seed, "commit", "-qm", "seed"); self.git(seed, "push", "-q", str(bare), "HEAD:refs/heads/" + base)
            self.bares[name] = bare
        self.root = self.tmp / "root"; self.clone_all(self.root)
        self.old_cwd = os.getcwd(); self.addCleanup(os.chdir, self.old_cwd)
    def clone_all(self, root):
        root.mkdir()
        for name, bare in self.bares.items(): self.git(self.tmp, "clone", "-q", str(bare), str(root / name))
    def git(self, cwd, *args):
        return subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()
    def branch(self, wt): return self.git(wt, "branch", "--show-current")
    def head(self, wt): return self.git(wt, "rev-parse", "HEAD")
    def origin_head(self, name): return self.git(self.bares[name], "rev-parse", self.bases[name])
    def assert_layout(self, ws, key):
        self.assertEqual(self.branch(ws / "pdffiller-knowledge"), "epic/" + key)
        for name in ("app", "web"):
            self.assertEqual(self.branch(ws / name), "ws/" + key, name); self.assertEqual(self.head(ws / name), self.origin_head(name), name)
            self.assertTrue((ws / name / "README.md").exists())
        delivery = ws / "pdffiller-knowledge" / "context" / "workitems" / ("demo-" + key) / "delivery"
        self.assertEqual((ws / ".turnstile").read_text().strip(), "pdffiller-knowledge/context/workitems/demo-%s/delivery" % key)
        rec = json.loads((delivery / ".workspace.json").read_text())
        self.assertEqual(rec["repos"], {"app": str(ws / "app"), "web": str(ws / "web")}); self.assertEqual(rec["workspace"], str(ws)); self.assertEqual(rec["knowledge"], str(ws / "pdffiller-knowledge"))
        self.assertEqual(rec["member"], "lg")
        data = json.loads((delivery / "state.json").read_text())["epic"]
        self.assertEqual(list(data["members"]), ["lg"])
        self.assertEqual((data["repos"]["app"]["path"], data["repos"]["web"]["path"]), ("app", "web")); self.assertNotIn("workspace", data); self.assertNotIn(str(ws), json.dumps(data))
        self.assertEqual(self.git(ws / "pdffiller-knowledge", "status", "--porcelain"), "")
        text = (ws / "CLAUDE.md").read_text(); self.assertIn("`app/` (ws/%s from `origin/main`)" % key, text); self.assertIn("`web/` (ws/%s from `origin/develop`)" % key, text)
        return delivery

    def test_init_from_the_clone_root_then_brief_attach_and_refusals(self):
        os.chdir(self.root)
        rc, out = out_of(init_cmd.run, init_opts("MYD-1")); self.assertEqual(rc, 0, out)
        ws = self.root / "myd-1"; d = self.assert_layout(ws, "myd-1")
        for needle in ["WORKSPACE: %s (clone root %s)" % (ws, self.root), "REPO: app → %s (ws/myd-1 from origin/main)" % (ws / "app"),
                       "REPO: web → %s (ws/myd-1 from origin/develop)" % (ws / "web"), "SYNC: pushed", "NEXT: write %s" % (d / "plan.md")]:
            self.assertIn(needle, out, needle)
        self.assertNotIn("&& claude", out)
        self.assertEqual(self.git(self.bares["pdffiller-knowledge"], "rev-parse", "epic/myd-1"), self.head(ws / "pdffiller-knowledge"))
        self.assertEqual(self.branch(self.root / "app"), "main"); self.assertEqual(self.branch(self.root / "web"), "develop")  # the clones stay on their base
        self.approve_plan(d)
        vars = [("repo=app" if p == "repo" else "%s=v" % p) for p in sorted(set(brief_cmd.PLACEHOLDER.findall((BRIEFS / "implementer.md").read_text())))
                if p not in brief_cmd.builtins({"epic": {}}, d, "implementer", "X") and p != "repo_path"]
        rc, out = out_of(brief_cmd.run, d, "implementer", "MYD-2", vars); self.assertEqual(rc, 0, out)
        text = (d / "briefs" / "MYD-2.md").read_text(); self.assertIn("worktree `%s`" % (ws / "app"), text); self.assertNotIn("{{", text)
        rc, out = out_of(brief_cmd.run, d, "implementer", "MYD-3", [v for v in vars if v != "repo=app"] + ["repo=nope"]); self.assertEqual(rc, 2); self.assertIn("not in epic.repos", out)
        rc, out = out_of(brief_cmd.run, d, "tester", "ENV-S1", ["%s=v" % p for p in ("story_id", "story_title", "mode", "rerun_cases", "builds", "stack_head", "test_user", "test_cases", "figma_frames", "tolerance", "copy_source")])
        self.assertEqual(rc, 0, out); self.assertIn("`app` → `%s`, `web` → `%s`" % (ws / "app", ws / "web"), (d / "briefs" / "ENV-S1.md").read_text())
        shutil.rmtree(ws / "web")
        rc, out = out_of(brief_cmd.run, d, "implementer", "MYD-4", [v for v in vars if v != "repo=app"] + ["repo=web"]); self.assertEqual(rc, 2); self.assertIn("does not exist", out); self.assertIn("turnstile attach --epic MYD-1", out)
        self.git(self.root / "web", "worktree", "prune")
        os.chdir(self.root / "pdffiller-knowledge")
        rc, out = out_of(init_cmd.run, init_opts("MYD-2")); self.assertEqual(rc, 0, out); self.assert_layout(self.root / "myd-2", "myd-2")
        os.chdir(self.root)
        (self.root / "myd-3").mkdir(); (self.root / "myd-3" / "notes.txt").write_text("x")
        rc, out = out_of(init_cmd.run, init_opts("MYD-3")); self.assertEqual(rc, 2); self.assertIn("is not empty (notes.txt)", out)
        self.assertEqual(sorted(p.name for p in (self.root / "myd-3").iterdir()), ["notes.txt"])
        rc, out = out_of(init_cmd.run, init_opts("MYD-4", repos=[APP, '{"name":"ghost","base":"main","slack":"C3"}'])); self.assertEqual(rc, 2)
        self.assertIn("no clone of ghost at %s" % (self.root / "ghost"), out); self.assertFalse((self.root / "myd-4").exists())
        self.assertEqual(self.git(self.root / "app", "branch", "--list", "ws/myd-4"), "")
        nowhere = self.tmp / "nowhere"; nowhere.mkdir(); os.chdir(nowhere)
        rc, out = out_of(init_cmd.run, init_opts("MYD-5")); self.assertEqual(rc, 2); self.assertIn("no clone root", out); self.assertIn("pdffiller-knowledge, app, web", out)
        self.assertEqual(list(nowhere.iterdir()), [])
        root2 = self.tmp / "root2"; self.clone_all(root2); os.chdir(root2)
        rc, out = out_of(attach_cmd.run, attach_cmd.AttachOptions(epic="MYD-1", github="lg")); self.assertEqual(rc, 0, out); self.assertIn("OK attach MYD-1", out)
        d2 = self.assert_layout(root2 / "myd-1", "myd-1"); self.assertNotIn("NEXT:", out); self.assertNotIn("&& claude", out)
        shutil.rmtree(str(root2 / "myd-1" / "app"), True); self.git(root2 / "app", "worktree", "prune")
        for nested in (root2 / "app", root2 / "pdffiller-knowledge", root2 / "pdffiller-knowledge" / "docs" if (root2 / "pdffiller-knowledge" / "docs").is_dir() else root2 / "web"):
            os.chdir(nested)
            rc, out = out_of(attach_cmd.run, attach_cmd.AttachOptions(epic="MYD-1", github="lg")); self.assertEqual(rc, 0, out)
            self.assertIn("WORKSPACE: %s (clone root %s)" % (root2 / "myd-1", root2), out)
        self.assertEqual(json.loads((d2 / "state.json").read_text())["epic"]["repos"], json.loads((d / "state.json").read_text())["epic"]["repos"])
        self.assertEqual(json.loads((d2 / ".workspace.json").read_text())["clone_root"], str(root2))
        os.chdir(self.root); shutil.rmtree(ws / "app"); self.git(self.root / "app", "worktree", "prune")
        rc, out = out_of(init_cmd.run, init_opts("MYD-1")); self.assertEqual(rc, 0, out); self.assertIn("already holds epic MYD-1; attaching", out)
        self.assertEqual(self.branch(ws / "app"), "ws/myd-1"); self.assertEqual(self.branch(ws / "web"), "ws/myd-1")
        rc, out = out_of(attach_cmd.run, attach_cmd.AttachOptions(epic="MYD-9", github="lg")); self.assertEqual(rc, 2); self.assertIn("origin has no epic/myd-9", out)
        self.assertFalse((self.root / "myd-9").exists())

    def approve_plan(self, d):
        (d / "plan.md").write_text("# plan\n"); digest = state.digest("# plan\n")
        data = json.loads((d / "state.json").read_text()); data["epic"]["plan"] = {"path": "plan.md", "submitted_at": "x", "digest": digest}
        data["awaiting_human"] = [{"id": "ah-1", "owner": "lead", "type": "plan", "payload": "plan.md", "digest": digest, "created_at": "x",
                                   "approved_at": "2026-10-13T10:00Z", "approved_via": "lead-terminal"}]
        (d / "state.json").write_text(state.dumps(data)); self.git(d, "add", "-A", "."); self.git(d, "commit", "-qm", "plan"); self.git(d, "push", "-q", "origin", "HEAD:refs/heads/epic/myd-1")
