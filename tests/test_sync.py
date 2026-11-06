import contextlib, io, json, os, pathlib, shutil, tempfile, unittest
from unittest import mock
from turnstile_cli import attach_cmd, init_cmd, pass_cmd, reconcile, state, sync
from turnstile_cli.errors import TurnstileError
from tests.test_pass import FakeIO, opts, run_capture, READY_OPTS, H

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"

def out_of(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = fn(*a, **kw)
    return rc, buf.getvalue()

class Writers(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir(); shutil.copy(FIX, self.d / "state.json"); sync.record(self.d, True, H)
        (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok")
        self.io = FakeIO(heads={"jsfiller#1": H, "docs-platform#2": "bbbbbbbb22222222"})
    def data(self): return json.loads((self.d / "state.json").read_text())
    def rec(self): return json.loads((self.d / ".sync.json").read_text())

    def test_every_write_fetches_then_pushes_the_epic_branch_after_the_commit(self):
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.io.fetches, ["epic/myd-1"]); self.assertEqual(self.io.pushes, ["epic/myd-1"])
        self.assertEqual(self.rec()["pushed"], True); self.assertEqual(self.rec()["head"], self.io.head); self.assertNotIn("WARN", out)
        self.assertEqual((self.d / ".gitignore").read_text().splitlines(), [".*.tmp", ".sync.json", ".workspace.json", ".status-cache.json"])
        d = self.data(); d["epic"]["knowledge"] = {"branch": "epic/other", "remote": "origin"}; (self.d / "state.json").write_text(state.dumps(d)); self.io.branch = "epic/other"
        run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(self.io.pushes[-1], "epic/other")  # the branch init recorded wins over the worktree's current branch

    def test_failed_push_warns_records_and_gates_the_verified_targets(self):
        self.io.fail_push = "rejected: non-fast-forward"
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 0); self.assertIn("WARN: not pushed: rejected: non-fast-forward", out); self.assertEqual(self.data()["prs"]["docs-platform#2"]["state"], "AI_REVIEW")
        self.assertEqual((self.rec()["pushed"], self.rec()["reason"]), (False, "rejected: non-fast-forward")); self.assertEqual(len(self.io.commits), 1)
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("not pushed since", out); self.assertIn("run: turnstile sync", out); self.assertEqual(self.data()["prs"]["jsfiller#1"]["state"], "AI_REVIEW")
        self.assertEqual(sync.missing_for(self.d, True)[0][:8], "MISSING "); self.assertEqual(sync.missing_for(self.d, False), [])
        self.io.fail_push = None; self.assertEqual(sync.run(self.d, self.io), 0); self.assertEqual(sync.missing_for(self.d, True), [])
        self.assertEqual(run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)[0], 0)

    def test_no_push_flag_commits_without_pushing_and_records_it(self):
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success", no_push=True), self.io)
        self.assertEqual(rc, 0); self.assertIn("WARN: not pushed: --no-push", out); self.assertEqual(self.io.pushes, []); self.assertEqual(len(self.io.commits), 1)
        self.assertEqual((self.rec()["pushed"], self.rec()["reason"]), (False, "--no-push"))
        from turnstile_cli import bug_cmd, config_cmd
        self.assertEqual(out_of(bug_cmd.add, self.d, "S1", "x", "lead", io=self.io, no_push=True)[0], 0); self.assertEqual(self.io.pushes, [])
        self.assertEqual(out_of(config_cmd.set_, self.d, "review_skill=/x", epic=True, io=self.io)[0], 0); self.assertEqual(self.io.pushes, ["epic/myd-1"])
        self.assertEqual(out_of(pass_cmd.jira_synced, self.d, "docs-platform#2", "In progress", self.io, no_push=True)[0], 0); self.assertEqual(len(self.io.pushes), 1)

    def test_behind_origin_refuses_before_any_write(self):
        self.io.behind = 2; before = (self.d / "state.json").read_text()
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING epic branch epic/myd-1 behind origin by 2 commit(s) — run: turnstile sync", out)
        self.assertEqual((self.d / "state.json").read_text(), before); self.assertEqual(self.io.commits, []); self.assertEqual(self.io.pushes, []); self.assertFalse((self.d / "ledger.md").exists())
        self.io.behind, self.io.ahead = 0, 3
        self.assertEqual(run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)[0], 0)
        self.assertEqual(self.io.pushes, ["epic/myd-1"])

    def test_fetch_failure_warns_and_proceeds_on_local_facts(self):
        self.io.fail_fetch = "could not resolve host"
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 0); self.assertIn("WARN fetch origin epic/myd-1 failed (could not resolve host)", out); self.assertEqual(self.io.pushes, ["epic/myd-1"])

    def test_fetch_failure_refuses_gated_transitions_unless_no_push(self):
        # review P2-4
        self.io.fail_fetch = "could not resolve host"; before = (self.d / "state.json").read_text()
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING fetch failed: could not resolve host — fix the network or run with --no-push for local-only work", out)
        self.assertEqual((self.d / "state.json").read_text(), before); self.assertEqual(self.io.commits, [])
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(no_push=True, **READY_OPTS), self.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.data()["prs"]["jsfiller#1"]["state"], "READY"); self.assertEqual(self.rec()["reason"], "--no-push")
    def test_missing_or_corrupt_sync_record_is_unknown_and_gates(self):
        # review P3-6
        (self.d / ".sync.json").unlink()
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io); self.assertEqual(rc, 2); self.assertIn("MISSING a recorded push of the epic branch on this machine", out)
        (self.d / ".sync.json").write_text("{not json"); self.assertIsNone(sync.load(self.d))
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io); self.assertEqual(rc, 2); self.assertIn("absent or unreadable", out)
        (self.d / ".sync.json").write_text('{"pushed": "yes"}')
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io); self.assertEqual(rc, 2)
        self.assertEqual(sync.run(self.d, self.io), 0); self.assertEqual(run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)[0], 0)
        (self.d / ".sync.json").unlink()
        self.assertEqual(run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)[0], 0)  # not gated
    def test_push_refused_off_the_epic_branch(self):
        # review P3-7
        self.io.branch = ""
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 2); self.assertIn("detached HEAD and epic.knowledge.branch is unset", out); self.assertEqual(self.io.commits, [])
        d = self.data(); d["epic"]["knowledge"] = {"branch": "epic/myd-1", "remote": "origin"}; (self.d / "state.json").write_text(state.dumps(d))
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertEqual(rc, 0); self.assertIn("WARN: not pushed: worktree is on a detached HEAD, not epic/myd-1", out); self.assertEqual(self.io.pushes, [])
        self.io.branch = "feature/x"; rc, out = out_of(sync.run, self.d, self.io); self.assertEqual(rc, 2); self.assertIn("worktree is on feature/x, not epic/myd-1", out); self.assertEqual(self.io.pushes, [])
        self.io.branch = "epic/myd-1"; self.assertEqual(sync.run(self.d, self.io), 0); self.assertEqual(self.io.pushes, ["epic/myd-1"])
    def test_origin_branch_missing_after_fetch_is_an_error(self):
        # review P3-8
        import subprocess
        git = pathlib.Path(tempfile.mkdtemp()); subprocess.run(["git", "init", "-q"], cwd=git, check=True)
        with self.assertRaises(TurnstileError) as cm: pass_cmd.IO().behind_ahead(git, "epic/none")
        self.assertIn("origin/epic/none not found after the fetch", str(cm.exception))
    def test_no_commit_skips_fetch_and_push(self):
        rc, out = run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success", no_commit=True), self.io)
        self.assertEqual(rc, 0); self.assertEqual((self.io.fetches, self.io.pushes, self.io.commits), ([], [], [])); self.assertEqual((self.rec()["pushed"], self.rec()["head"]), (True, H))

    def test_status_and_reconcile_print_the_sync_state_first(self):
        (self.d / ".sync.json").unlink()
        with mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")):
            rc, out = out_of(reconcile.cli, self.d, status=True); self.assertTrue(out.startswith("SYNC: unknown"), out[:60]); self.assertIn("run: turnstile sync", out)
            run_capture(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
            rc, out = out_of(reconcile.cli, self.d); self.assertTrue(out.startswith("SYNC: pushed %s" % self.io.head), out[:60])
            self.io.fail_push = "x"; run_capture(self.d, "pr", "docs-platform#2", "DEV", opts(head="bbbbbbbb22222222", reason="r"), self.io)
            rc, out = out_of(reconcile.cli, self.d, status=True); self.assertTrue(out.startswith("SYNC: NOT PUSHED since"), out[:60])
            rc, out = out_of(reconcile.cli, self.d, as_json=True); self.assertNotIn("SYNC", out)

class SyncCmd(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir(); shutil.copy(FIX, self.d / "state.json"); self.io = FakeIO()
    def rec(self): return json.loads((self.d / ".sync.json").read_text())
    def test_up_to_date_or_ahead_pushes(self):
        rc, out = out_of(sync.run, self.d, self.io); self.assertEqual(rc, 0); self.assertIn("OK sync %s → origin/epic/myd-1" % self.io.head, out)
        self.assertEqual((self.io.fetches, self.io.ffs, self.io.pushes), (["epic/myd-1"], [], ["epic/myd-1"])); self.assertTrue(self.rec()["pushed"])
    def test_behind_fast_forwards_then_pushes(self):
        self.io.behind = 3; rc, out = out_of(sync.run, self.d, self.io)
        self.assertEqual(rc, 0); self.assertIn("fast-forwarded epic/myd-1 by 3 commit(s)", out); self.assertEqual((self.io.ffs, self.io.pushes), (["epic/myd-1"], ["epic/myd-1"]))
    def test_diverged_refuses_with_both_heads_and_touches_nothing(self):
        self.io.behind, self.io.ahead = 1, 2; rc, out = out_of(sync.run, self.d, self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING histories diverged on epic/myd-1", out); self.assertIn(self.io.head, out); self.assertIn("0r1g1n0000000000", out)
        self.assertIn("never rebases or forces", out); self.assertEqual((self.io.ffs, self.io.pushes), ([], [])); self.assertFalse((self.d / ".sync.json").exists())
    def test_fetch_and_push_failures(self):
        self.io.fail_fetch = "offline"; rc, out = out_of(sync.run, self.d, self.io); self.assertEqual(rc, 2); self.assertIn("MISSING fetch origin epic/myd-1 failed: offline", out)
        self.io.fail_fetch = None; self.io.fail_push = "rejected"; rc, out = out_of(sync.run, self.d, self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING SYNC: NOT PUSHED", out); self.assertEqual(self.rec()["reason"], "rejected")
    def test_line(self):
        self.assertIn("unknown", sync.line(None)); self.assertEqual(sync.line({"pushed": True, "head": "a", "at": "t"}), "SYNC: pushed a at t")
        self.assertEqual(sync.line({"pushed": False, "head": "a", "at": "t", "reason": "r"}), "SYNC: NOT PUSHED since t (r) — run: turnstile sync")

class FakeGit(init_cmd.InitIO):
    def __init__(self, fail=(), workitems=("demo",), key="MYD-1", current="epic/myd-1", local_branch=False):
        self.calls = []; self.fail = set(fail); self.workitems = workitems; self.key = key; self.current = current; self.local_branch = local_branch; self.branches = {}
    def git(self, args, cwd):
        self.calls.append((args, pathlib.Path(cwd)))
        if args[0] in self.fail:
            raise TurnstileError("git %s failed: simulated" % args[0])
        if args[:2] == ["branch", "--show-current"]: return self.branches.get(pathlib.Path(cwd), self.current if pathlib.Path(cwd).name == "pdffiller-knowledge" else "ws/myd-1") + "\n"
        if args[:2] == ["branch", "--list"]: return ("  %s\n" % args[2]) if self.local_branch and args[2].startswith("epic/") else ""
        if args[:1] == ["rev-parse"]: return "abc123\n"
        if args[:2] == ["worktree", "add"]:
            wt = pathlib.Path(args[4] if args[2] == "-b" else args[2]); self.branches[wt] = args[3]
            if args[3].startswith("epic/"): self.populate(wt)
            else: wt.mkdir(parents=True)
        return ""
    def populate(self, wt):
        for w in self.workitems:
            d = wt / "context" / "workitems" / w / "delivery"; d.mkdir(parents=True)
            data = json.loads(FIX.read_text()); data["epic"]["key"] = self.key; data["epic"]["chat_language"] = "Ukrainian"; (d / "state.json").write_text(state.dumps(data))

class Attach(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve(); self.ws = self.tmp / "ws"; self.ws.mkdir()
        self.knowledge = self.tmp / "pdffiller-knowledge"; (self.knowledge / ".git").mkdir(parents=True)
        for repo in ("jsfiller", "docs-platform"): (self.tmp / repo / ".git").mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"TURNSTILE_USER_CONFIG": str(self.tmp / "none.json")}); self.env.start(); self.addCleanup(self.env.stop)
        self.gh = mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")); self.gh.start(); self.addCleanup(self.gh.stop)
    def attach(self, git, **kw):
        o = attach_cmd.AttachOptions(**dict(dict(knowledge=str(self.knowledge), epic="MYD-1", workspace=str(self.ws)), **kw))
        return out_of(attach_cmd.run, o, git)
    def test_attach_adds_the_worktree_marker_claude_md_and_prints_status(self):
        git = FakeGit(); rc, out = self.attach(git)
        self.assertEqual(rc, 1, out)  # attach itself is fine; status exits 1 because gh facts are missing offline
        wt = self.ws / "pdffiller-knowledge"; d = wt / "context" / "workitems" / "demo" / "delivery"
        self.assertIn((["fetch", "origin", "epic/myd-1"], self.knowledge), git.calls)
        self.assertIn((["worktree", "add", "-b", "epic/myd-1", str(wt), "origin/epic/myd-1"], self.knowledge), git.calls)
        self.assertFalse(any(c[0][0] == "merge" for c in git.calls)); self.assertFalse(any(c[0][0] in ("commit", "push") for c in git.calls))
        for bad in ("..", "a/b", "../x", "x\\y", "."):
            rc, out = self.attach(FakeGit(), workitem=bad); self.assertEqual(rc, 2, bad); self.assertIn("--workitem must be a folder name", out)
        rc, out = self.attach(git); self.assertEqual(rc, 1, out)
        self.assertFalse((self.ws / "CLAUDE.md.turnstile").exists()); self.assertIn("CLAUDE_MD: %s" % (self.ws / "CLAUDE.md"), out)
        self.assertEqual((self.ws / ".turnstile").read_text().strip(), "pdffiller-knowledge/context/workitems/demo/delivery")
        text = (self.ws / "CLAUDE.md").read_text(); self.assertIn("MYD-1", text); self.assertIn("Chat with the lead in Ukrainian", text); self.assertIn("turnstile config", text)
        self.assertEqual(json.loads((d / ".sync.json").read_text())["pushed"], True)
        for needle in ["WORKTREE: %s (epic/myd-1)" % wt, "DELIVERY: %s" % d, "CLAUDE_MD: %s" % (self.ws / "CLAUDE.md"), "NEXT: ask the lead once (skill § preferences)",
                       "OK attach MYD-1", "SYNC: pushed abc123", "== MYD-1", "config: models", "WARN jsfiller#1"]:
            self.assertIn(needle, out, needle)
        self.assertFalse((self.tmp / "none.json").exists())
    def test_attach_refusals_touch_nothing(self):
        (self.ws / ".turnstile").write_text("other/delivery\n"); git = FakeGit(); rc, out = self.attach(git)
        self.assertEqual(rc, 2); self.assertIn("points at another delivery", out); self.assertFalse(any(c[0][:2] == ["worktree", "add"] for c in git.calls))
        (self.ws / ".turnstile").unlink()
        rc, out = self.attach(FakeGit(fail={"fetch"})); self.assertEqual(rc, 2); self.assertIn("origin has no epic/myd-1", out); self.assertFalse((self.ws / ".turnstile").exists())
        ws2 = self.tmp / "ws2"; ws2.mkdir(); rc, out = self.attach(FakeGit(key="MYD-7"), workspace=str(ws2))
        self.assertEqual(rc, 2); self.assertIn("belongs to epic MYD-7, not MYD-1", out); self.assertFalse((ws2 / ".turnstile").exists()); self.assertFalse((ws2 / "CLAUDE.md").exists())
        ws3 = self.tmp / "ws3"; ws3.mkdir(); rc, out = self.attach(FakeGit(workitems=("a", "b")), workspace=str(ws3))
        self.assertEqual(rc, 2); self.assertIn("2 delivery dir(s)", out); self.assertIn("pass --workitem", out)
        rc, out = self.attach(FakeGit(workitems=("a", "b")), workspace=str(ws3), workitem="b"); self.assertEqual(rc, 1); self.assertIn("OK attach MYD-1", out)
        self.assertEqual((ws3 / ".turnstile").read_text().strip(), "pdffiller-knowledge/context/workitems/b/delivery")
        rc, out = self.attach(FakeGit(), workspace=str(ws3), workitem="zzz"); self.assertEqual(rc, 2); self.assertIn("no state.json", out)
        rc, out = self.attach(FakeGit(), knowledge=str(self.tmp / "nope")); self.assertEqual(rc, 2); self.assertIn("not a git clone", out)
    def test_attach_reuses_an_existing_worktree_fast_forwards_and_keeps_claude_md(self):
        (self.ws / "CLAUDE.md").write_text("mine\n"); git = FakeGit(); git.populate(self.ws / "pdffiller-knowledge")
        rc, out = self.attach(git); self.assertEqual(rc, 1, out)
        self.assertFalse(any(c[0][:2] == ["worktree", "add"] and c[1] == self.knowledge for c in git.calls)); self.assertIn((["merge", "-q", "--ff-only", "origin/epic/myd-1"], self.ws / "pdffiller-knowledge"), git.calls)
        for repo, base in (("jsfiller", "develop"), ("docs-platform", "main")):
            self.assertIn((["worktree", "add", "-b", "ws/myd-1", str(self.ws / repo), "origin/" + base], self.tmp / repo), git.calls)
        rec = json.loads((self.ws / "pdffiller-knowledge" / "context" / "workitems" / "demo" / "delivery" / ".workspace.json").read_text())
        self.assertEqual((rec["workspace"], rec["clone_root"], rec["repos"]["jsfiller"]), (str(self.ws), str(self.tmp), str(self.ws / "jsfiller")))
        self.assertEqual((self.ws / "CLAUDE.md").read_text(), "mine\n"); self.assertIn("MYD-1", (self.ws / "CLAUDE.md.turnstile").read_text()); self.assertIn("CLAUDE_MD: %s" % (self.ws / "CLAUDE.md.turnstile"), out)
        rc, out = self.attach(FakeGit()); self.assertEqual(rc, 1, out); self.assertIn("MYD-1", (self.ws / "CLAUDE.md.turnstile").read_text())
        (self.ws / "CLAUDE.md.turnstile").write_text("theirs\n"); rc, out = self.attach(FakeGit()); self.assertEqual(rc, 2); self.assertIn("is not turnstile's own", out)
        self.assertEqual((self.ws / "CLAUDE.md.turnstile").read_text(), "theirs\n")
        rc, out = self.attach(FakeGit(current="main")); self.assertEqual(rc, 2); self.assertIn("exists on branch 'main', not epic/myd-1", out)
        ws2 = self.tmp / "ws2"; ws2.mkdir(); git = FakeGit(fail={"merge"}, local_branch=True); rc, out = self.attach(git, workspace=str(ws2))
        self.assertEqual(rc, 1, out); self.assertIn((["worktree", "add", str(ws2 / "pdffiller-knowledge"), "epic/myd-1"], self.knowledge), git.calls)
        self.assertIn("WARN epic/myd-1 not fast-forwarded to origin", out); self.assertTrue(out.index("WARN epic/myd-1 not fast") < out.index("SYNC: NOT PUSHED"))
        rec = json.loads((ws2 / "pdffiller-knowledge" / "context" / "workitems" / "demo" / "delivery" / ".sync.json").read_text())
        self.assertFalse(rec["pushed"]); self.assertIn("not fast-forwarded", rec["reason"])
