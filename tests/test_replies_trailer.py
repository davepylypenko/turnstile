import copy, json, pathlib, shutil, tempfile, unittest
from turnstile_cli import github, pass_cmd, state
from tests.test_pass import FakeIO, opts, run_capture, env, H, LINK, READY_OPTS

D = pathlib.Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((D / "gh_pr_13222.json").read_text())

class Parse(unittest.TestCase):
    def test_threads_trailer_body(self):
        f = github.parse("jsfiller#1", PAYLOAD)
        self.assertEqual(len(f.threads), 4); self.assertEqual(f.threads[0]["id"], "PRRT_1"); self.assertTrue(f.threads[0]["human"]); self.assertFalse(f.threads[1]["human"])
        self.assertEqual(f.threads[0]["opened_at"], "2026-10-12T09:00:00Z"); self.assertEqual(f.threads[0]["replies"], [])
        self.assertEqual(f.trailered, []); self.assertFalse(f.body_footer)
        p = copy.deepcopy(PAYLOAD); p["allCommits"]["nodes"][0]["commit"]["message"] = "x\n\nCo-Authored-By: a"; p["body"] += "\n\n🤖 Generated with [Claude Code](https://x)"
        f = github.parse("jsfiller#1", p); self.assertEqual(len(f.trailered), 1); self.assertTrue(f.body_footer)
    def test_ts(self):
        self.assertLess(github.ts("2026-10-13T10:00Z"), github.ts("2026-10-13T10:00:30Z")); self.assertIsNone(github.ts("nope"))

class Trailer(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(D / "state_min.json", self.d / "state.json"); (self.d / ".state.lock").touch()
        (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok"); self.io = FakeIO(heads={"jsfiller#1": H})
    def test_trailer_and_footer_refused(self):
        self.io.facts["jsfiller#1"] = {"trailered": ["abc12345"]}
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("Co-Authored-By", out); self.assertIn("abc12345", out)
        self.io.facts["jsfiller#1"] = {"body_footer": True}
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("generated-with footer", out)
