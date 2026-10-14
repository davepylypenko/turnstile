import subprocess, sys, unittest, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

class CliSmoke(unittest.TestCase):
    def test_version(self):
        out = subprocess.run([sys.executable, "-m", "turnstile_cli", "--version"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "turnstile 0.2.0")

    def test_shim_forwards(self):
        out = subprocess.run([str(ROOT / "scripts" / "turnstile"), "--version"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "turnstile 0.2.0")
