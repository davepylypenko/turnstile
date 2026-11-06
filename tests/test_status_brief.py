import contextlib, io, json, pathlib, shutil, tempfile, unittest
from unittest import mock
from turnstile_cli import reconcile

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class StatusBrief(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch()
    def status(self, brief):
        buf = io.StringIO()
        with mock.patch.object(reconcile.github, "fetch", side_effect=RuntimeError("no gh")), contextlib.redirect_stdout(buf):
            reconcile.cli(self.d, status=True, brief=brief)
        return buf.getvalue()
    def set_pr(self, pid, **kw):
        p = self.d / "state.json"; data = json.loads(p.read_text()); data["prs"][pid].update(kw); p.write_text(json.dumps(data))
    def test_changes_between_snapshots(self):
        prev = {"prs": {"a#1": ["DEV", "h1"], "a#2": ["DEV", "h2"]}, "stories": {"S1": ["IN_PROGRESS"]}}
        now = {"prs": {"a#1": ["DEV", "h1"], "a#2": ["AI_REVIEW", "h2"], "a#3": ["DEV", "h3"]}, "stories": {"S1": ["IN_PROGRESS"]}}
        self.assertEqual(reconcile.changes(prev, now), ["pr a#2: DEV h2 → AI_REVIEW h2", "pr a#3: new → DEV h3"])
        self.assertEqual(reconcile.changes(now, now), [])
    def test_brief_prints_only_the_changes_after_the_first_call(self):
        first = self.status(True)
        self.assertIn("changed since the previous status: 3", first); self.assertIn("pr jsfiller#1: new", first)
        self.assertNotIn("config:", first); self.assertNotIn("story S1 [", first); self.assertIn("awaiting humans:", first); self.assertIn("== reconcile:", first)
        self.assertTrue(first.startswith("SYNC:"), first[:40])
        second = self.status(True)
        self.assertIn("changed since the previous status: 0", second); self.assertNotIn("jsfiller#1: new", second)
        self.set_pr("jsfiller#1", head="ffffffff66666666")
        third = self.status(True)
        self.assertIn("changed since the previous status: 1", third); self.assertIn("pr jsfiller#1:", third); self.assertIn("ffffffff66666666", third)
    def test_snapshot_lives_outside_state_json_and_full_status_is_unchanged(self):
        before = (self.d / "state.json").read_text()
        full = self.status(False)
        self.assertEqual((self.d / "state.json").read_text(), before)
        self.assertIn("last_status", json.loads((self.d / ".status-cache.json").read_text()))
        self.assertIn("config: models", full); self.assertIn("pr jsfiller#1", full); self.assertNotIn("changed since", full)
    def test_unreadable_cache_is_ignored(self):
        (self.d / ".status-cache.json").write_text("{not json")
        self.assertIn("changed since the previous status: 3", self.status(True))

if __name__ == "__main__":
    unittest.main()
