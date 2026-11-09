import contextlib, io, json, os, pathlib, subprocess, tempfile, unittest
from unittest import mock
from turnstile_cli import attach_cmd, config_cmd, init_cmd, pass_cmd, reconcile, sync

JS = '{"name":"jsfiller","base":"develop","slack":"C1","gate":"pdf-review"}'

def out_of(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = fn(*a, **kw)
    return rc, buf.getvalue()

class RealGit(unittest.TestCase):
    """Network-free: a bare origin in a temp dir, two clones, the real InitIO/IO git calls (signing off through GIT_CONFIG_GLOBAL)."""
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        cfg = self.tmp / "gitconfig"; cfg.write_text("[user]\n\tname = t\n\temail = t@t\n[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n")
        env = {"GIT_CONFIG_GLOBAL": str(cfg), "GIT_CONFIG_NOSYSTEM": "1", "TURNSTILE_USER_CONFIG": str(self.tmp / "u.json"), "HOME": str(self.tmp)}
        self.env = mock.patch.dict(os.environ, env); self.env.start(); self.addCleanup(self.env.stop)
        self.gh = mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")); self.gh.start(); self.addCleanup(self.gh.stop)
        self.bare = self.tmp / "origin.git"; self.git(self.tmp, "init", "-q", "--bare", str(self.bare)); self.git(self.bare, "symbolic-ref", "HEAD", "refs/heads/main")
        seed = self.tmp / "seed"; seed.mkdir(); self.git(seed, "init", "-q"); (seed / "README.md").write_text("k\n")
        self.git(seed, "add", "."); self.git(seed, "commit", "-qm", "seed"); self.git(seed, "push", "-q", str(self.bare), "HEAD:refs/heads/main")
        js = self.tmp / "jsfiller.git"; self.git(self.tmp, "init", "-q", "--bare", str(js)); self.git(js, "symbolic-ref", "HEAD", "refs/heads/develop")
        self.git(seed, "push", "-q", str(js), "HEAD:refs/heads/develop")
        self.k1, self.k2 = self.tmp / "m1" / "k1", self.tmp / "m2" / "k2"  # two machines: a clone root each, the knowledge clone and a jsfiller clone in it
        for k in (self.k1, self.k2):
            k.parent.mkdir(); self.git(self.tmp, "clone", "-q", str(self.bare), str(k)); self.git(self.tmp, "clone", "-q", str(js), str(k.parent / "jsfiller"))
    def git(self, cwd, *args):
        return subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()
    def origin(self): return self.git(self.bare, "rev-parse", "epic/myd-1")
    def head(self, wt): return self.git(wt, "rev-parse", "HEAD")
    def approve(self, d, ah):
        with mock.patch.dict(os.environ, {"TURNSTILE_LEAD": "1"}): rc, out = out_of(pass_cmd.approve, d, ah)
        self.assertEqual(rc, 0, out)

    def test_init_writers_attach_sync_detached_and_diverged(self):
        ws1 = self.tmp / "ws1"; ws1.mkdir()
        rc, out = out_of(init_cmd.run, init_cmd.InitOptions(epic="MYD-1", workitem="demo", knowledge=str(self.k1), lead="l", lead_github="lg", github_org="o", repos=[JS], workspace=str(ws1)))
        self.assertEqual(rc, 0, out); self.assertIn("SYNC: pushed", out)
        wt1 = ws1 / "k1"; d1 = wt1 / "context" / "workitems" / "demo" / "delivery"
        self.assertEqual(self.origin(), self.head(wt1)); self.assertTrue(json.loads((d1 / ".sync.json").read_text())["pushed"])
        self.assertEqual(self.git(wt1, "status", "--porcelain"), "")
        rc, out = out_of(config_cmd.set_, d1, "review_skill=/pdf-review:run", epic=True); self.assertEqual(rc, 0, out)
        self.assertEqual(self.origin(), self.head(wt1)); self.assertIn("proposed for the epic", (d1 / "ledger.md").read_text())
        self.approve(d1, "ah-1"); self.assertEqual(self.origin(), self.head(wt1))
        rc, out = out_of(config_cmd.apply, d1, "ah-1"); self.assertEqual(rc, 0, out); self.assertEqual(self.origin(), self.head(wt1))
        self.assertEqual(json.loads((d1 / "state.json").read_text())["epic"]["review_skill"], "/pdf-review:run")
        ws2 = self.tmp / "ws2"; ws2.mkdir()
        rc, out = out_of(attach_cmd.run, attach_cmd.AttachOptions(knowledge=str(self.k2), epic="MYD-1", workspace=str(ws2), github="second"))
        self.assertEqual(rc, 0, out); self.assertIn("OK attach MYD-1", out); self.assertIn("SYNC: pushed %s" % self.origin(), out)  # no PRs yet: status has nothing to miss
        wt2 = ws2 / "k2"; d2 = wt2 / "context" / "workitems" / "demo" / "delivery"
        m2 = json.loads((d2 / "state.json").read_text())["epic"]["members"]; self.assertEqual(sorted(m2), ["lg", "second"]); self.assertEqual(m2["second"]["variant"], "myd-1-second")
        self.assertEqual(json.loads((d2 / ".workspace.json").read_text())["member"], "second"); self.assertEqual(self.origin(), self.head(wt2))
        self.assertEqual(self.git(wt2, "branch", "--show-current"), "epic/myd-1"); self.assertEqual(self.head(wt2), self.origin())
        self.assertEqual(json.loads((d2 / "state.json").read_text())["epic"]["review_skill"], "/pdf-review:run")
        self.assertEqual((ws2 / ".turnstile").read_text().strip(), "k2/context/workitems/demo/delivery"); self.assertIn("MYD-1", (ws2 / "CLAUDE.md").read_text())
        rc, out = out_of(config_cmd.set_, d2, "story_review_skill=/x", epic=True); self.assertEqual(rc, 0, out); self.assertEqual(self.origin(), self.head(wt2))
        rc, out = out_of(config_cmd.set_, d1, "models.tester=opus", epic=True)
        self.assertEqual(rc, 2); self.assertIn("behind origin by 2 commit(s) — run: turnstile sync", out); self.assertEqual(self.git(wt1, "status", "--porcelain"), "")
        rc, out = out_of(sync.run, d1); self.assertEqual(rc, 0, out); self.assertIn("fast-forwarded epic/myd-1 by 2 commit(s)", out); self.assertEqual(self.head(wt1), self.origin())
        rc, out = out_of(config_cmd.set_, d1, "models.tester=opus", epic=True); self.assertEqual(rc, 0, out); self.assertEqual(self.origin(), self.head(wt1))
        self.assertIn("story_review_skill=/x proposed", (d1 / "ledger.md").read_text())
        self.git(wt1, "checkout", "-q", "--detach")
        rc, out = out_of(config_cmd.set_, d1, "models.deployer=opus", epic=True)
        self.assertEqual(rc, 0, out); self.assertIn("WARN: not pushed: worktree is on a detached HEAD, not epic/myd-1", out)
        self.assertFalse(json.loads((d1 / ".sync.json").read_text())["pushed"]); self.assertNotEqual(self.origin(), self.head(wt1))
        rc, out = out_of(sync.run, d1); self.assertEqual(rc, 2); self.assertIn("detached HEAD", out)
        self.git(wt1, "checkout", "-q", "epic/myd-1"); rc, out = out_of(sync.run, d1); self.assertEqual(rc, 0, out); self.assertEqual(self.head(wt1), self.origin())
        rc, out = out_of(config_cmd.set_, d2, "models.stack-step=sonnet", epic=True); self.assertEqual(rc, 2); self.assertIn("behind origin by", out)
        rc, out = out_of(sync.run, d2); self.assertEqual(rc, 0, out); self.assertEqual(self.head(wt2), self.origin())
        rc, out = out_of(config_cmd.set_, d2, "models.stack-step=sonnet", epic=True); self.assertEqual(rc, 0, out); self.assertEqual(self.origin(), self.head(wt2))
        (d1 / "decisions.md").write_text("local\n"); self.git(wt1, "commit", "-qam", "local decision")
        before = self.origin(); rc, out = out_of(sync.run, d1)
        self.assertEqual(rc, 2); self.assertIn("histories diverged on epic/myd-1", out); self.assertIn(self.head(wt1), out); self.assertIn(before, out)
        self.assertEqual(self.origin(), before); self.assertIn("never rebases or forces", out)
        rc, out = out_of(config_cmd.set_, d1, "models.investigator=sonnet", epic=True); self.assertEqual(rc, 2); self.assertIn("behind origin by 1 commit(s) (and ahead by 1)", out)
