import contextlib, io, json, pathlib, shutil, tempfile, unittest
from turnstile_cli import bug_cmd
from tests.test_pass import FakeIO

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class Bugs(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch(); self.io = FakeIO()
    def data(self): return json.loads((self.d / "state.json").read_text())

    def test_next_id(self):
        self.assertEqual(bug_cmd.next_id([]), "b01"); self.assertEqual(bug_cmd.next_id([{"id": "b03"}, {"id": "b11"}, {"id": "x"}]), "b12")

    def test_add_and_set(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bug_cmd.add(self.d, "S1", "Share visible", "tester 2026-10-13", pr="jsfiller#13384", figma="F:1-2", io=self.io)
        self.assertEqual(rc, 0); self.assertIn("OK bug b01 added (S1)", buf.getvalue())
        b = self.data()["bugs"][0]
        self.assertEqual((b["id"], b["story"], b["state"], b["pr"], b["figma"]), ("b01", "S1", "todo", "jsfiller#13384", "F:1-2")); self.assertTrue(b["created_at"])
        self.assertEqual(bug_cmd.set_(self.d, "b01", state="testing", note="on desk05", io=self.io), 0)
        b = self.data()["bugs"][0]; self.assertEqual((b["state"], b["note"]), ("testing", "on desk05"))
        self.assertEqual(len(self.io.commits), 2); self.assertEqual(self.io.renders, 2)
        self.assertIn("bug b01 → testing", (self.d / "ledger.md").read_text()); self.assertTrue((self.d / "board.html").exists())

    def test_bug_add_validates_story_and_pr(self):
        before = (self.d / "state.json").read_text()
        self.assertEqual(bug_cmd.add(self.d, "S9", "x", "s", io=self.io), 2)
        self.assertEqual(bug_cmd.add(self.d, "S1", "x", "s", pr="jsfiller-13222", io=self.io), 2)
        self.assertEqual(bug_cmd.add(self.d, "S1", "  ", "s", io=self.io), 2)
        self.assertEqual((self.d / "state.json").read_text(), before); self.assertEqual(self.io.commits, [])

    def test_set_validates(self):
        bug_cmd.add(self.d, "S1", "x", "s", io=self.io)
        self.assertEqual(bug_cmd.set_(self.d, "b01", state="fixed", io=self.io), 2)
        self.assertEqual(bug_cmd.set_(self.d, "b02", state="done", io=self.io), 2)
        self.assertEqual(bug_cmd.set_(self.d, "b01", io=self.io), 2)

    def test_timestamps_carry_seconds(self):
        # round 2 R2-9: the board compares a db override's updatedAt with the bug's stamp; minute precision tied within a minute
        import re
        bug_cmd.add(self.d, "S1", "x", "s", io=self.io); bug_cmd.set_(self.d, "b01", state="ai", io=self.io)
        b = self.data()["bugs"][0]
        for k in ("created_at", "updated_at"): self.assertRegex(b[k], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", k)
