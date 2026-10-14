import subprocess, sys, unittest, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

class CliSmoke(unittest.TestCase):
    def test_version(self):
        out = subprocess.run([sys.executable, "-m", "turnstile_cli", "--version"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "turnstile 0.2.1")

    def test_bug_without_subcommand_exits_2_with_help(self):
        # 2026-10-14 nit 15
        import tempfile, shutil
        ws = pathlib.Path(tempfile.mkdtemp()); (ws / "delivery").mkdir(); (ws / ".turnstile").write_text("delivery\n")
        shutil.copy(ROOT / "tests" / "fixtures" / "state_min.json", ws / "delivery" / "state.json")
        out = subprocess.run([sys.executable, "-m", "turnstile_cli", "bug"], cwd=ws, capture_output=True, text=True, env=dict(__import__("os").environ, PYTHONPATH=str(ROOT)))
        self.assertEqual(out.returncode, 2); self.assertIn("usage:", out.stdout + out.stderr); self.assertIn("add", out.stdout + out.stderr)

    def test_threads_subcommand_is_wired(self):
        out = subprocess.run([sys.executable, "-m", "turnstile_cli", "threads", "--help"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        for flag in ("--self-resolved", "--needs-lead", "--report"): self.assertIn(flag, out.stdout)
    def test_shim_forwards(self):
        out = subprocess.run([str(ROOT / "scripts" / "turnstile"), "--version"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "turnstile 0.2.1")
