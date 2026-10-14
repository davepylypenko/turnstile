import copy, json, pathlib, shutil, tempfile, unittest
from turnstile_cli import board, reconcile, rules, pass_cmd
from turnstile_cli.errors import TurnstileError
from tests.test_pass import FakeIO, opts, run_capture, READY_OPTS, H

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class OrgRequired(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        data = json.loads(FIX.read_text()); del data["epic"]["github_org"]
        (self.d / "state.json").write_text(json.dumps(data)); (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok")
        (self.d / ".state.lock").touch()
    def test_rule(self):
        self.assertEqual(rules.require_org(json.loads(FIX.read_text())), "pdffiller")
        with self.assertRaises(TurnstileError):
            rules.require_org(json.loads((self.d / "state.json").read_text()))
    def test_pass_refuses(self):
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), FakeIO(heads={"jsfiller#1": H}))
        self.assertEqual(rc, 2); self.assertIn("MISSING epic.github_org", out)
    def test_reconcile_refuses(self):
        with self.assertRaises(TurnstileError):
            reconcile.cli(self.d)
    def test_board_has_no_fallback(self):
        html = board.render_html(json.loads(FIX.read_text()))
        self.assertNotIn("'pdffiller'", html)
