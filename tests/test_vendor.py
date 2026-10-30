import pathlib, shutil, subprocess, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class Vendor(unittest.TestCase):
    def setUp(self):
        self.dest = pathlib.Path(tempfile.mkdtemp()) / "turnstile"
        self.tag = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    def test_vendor_copies_plugin_files_and_stamps_vendored_from(self):
        r = subprocess.run(["sh", str(ROOT / "scripts" / "vendor.sh"), self.tag, str(self.dest)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for rel in (".claude-plugin/plugin.json", "agents/tester.md", "hooks/hooks.json", "hooks/guard_bash.py", "skills/turnstile/SKILL.md",
                    "templates/board.html", "scripts/turnstile", "turnstile_cli/main.py", "tests/test_pass.py", "README.md", "LICENSE", "VENDORED_FROM"):
            self.assertTrue((self.dest / rel).exists(), rel)
        self.assertFalse((self.dest / "docs").exists()); self.assertFalse((self.dest / ".superpowers").exists())
        stamp = (self.dest / "VENDORED_FROM").read_text()
        self.assertIn("repo: https://github.com/davepylypenko/turnstile", stamp); self.assertIn("tag: %s" % self.tag, stamp)
        self.assertRegex(stamp, r"commit: [0-9a-f]{40}"); self.assertIn("command: scripts/vendor.sh %s" % self.tag, stamp)
        self.assertTrue((self.dest / "scripts" / "turnstile").stat().st_mode & 0o111, "scripts/turnstile must stay executable")
        (self.dest / "stale.txt").write_text("x")
        r = subprocess.run(["sh", str(ROOT / "scripts" / "vendor.sh"), self.tag, str(self.dest)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertFalse((self.dest / "stale.txt").exists(), "a re-vendor replaces the tree")

    def test_unknown_tag_fails(self):
        r = subprocess.run(["sh", str(ROOT / "scripts" / "vendor.sh"), "v0.0.0-nope", str(self.dest)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0); self.assertIn("v0.0.0-nope", r.stderr); self.assertFalse(self.dest.exists())

    def test_dirty_destination_outside_git_is_refused(self):
        self.dest.mkdir(parents=True); (self.dest / "mine.txt").write_text("x")
        r = subprocess.run(["sh", str(ROOT / "scripts" / "vendor.sh"), self.tag, str(self.dest)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0); self.assertIn("VENDORED_FROM", r.stderr); self.assertTrue((self.dest / "mine.txt").exists())
