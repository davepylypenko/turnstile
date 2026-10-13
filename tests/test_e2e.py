import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"
H = "aaaaaaaa11111111"

def sh(args, cwd, env=None):
    return subprocess.run([str(ROOT / "scripts" / "turnstile")] + args, cwd=cwd, capture_output=True, text=True, env=env)

class E2E(unittest.TestCase):
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")
        subprocess.run(["git", "init", "-q"], cwd=self.ws, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."], cwd=self.ws, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-qm", "init"], cwd=self.ws, check=True)
        self.env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def test_full_pr_path_with_real_git_commit(self):
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.ws, check=True)
        r = sh(["pass", "pr", "jsfiller#1", "READY", "--head", H, "--ci", "success", "--deep-review", "reports/R.md", "--rounds", "1", "--gate", "pdf-review:pass"], cwd=self.ws / "delivery")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.strip().splitlines()[-1].startswith("OK pass pr jsfiller#1 AI_REVIEW → READY"))
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.ws, capture_output=True, text=True).stdout
        self.assertIn("turnstile: pass pr jsfiller#1", log)
        self.assertTrue((self.ws / "delivery" / "board.html").exists())
        r = sh(["pass", "pr", "jsfiller#1", "ON_HUMAN_REVIEW", "--head", H], cwd=self.ws)
        self.assertEqual(r.returncode, 2); self.assertIn("MISSING evidence.human.slack_permalink", r.stdout)

    def test_status_without_network(self):
        # PATH with python3 only: `gh` is absent, so fetch raises and cli prints WARN lines instead of calling GitHub
        bin_dir = self.ws / "bin"; bin_dir.mkdir(); (bin_dir / "python3").symlink_to(sys.executable)
        r = sh(["status"], cwd=self.ws, env=dict(self.env, PATH=str(bin_dir)))
        self.assertIn("WARN jsfiller#1", r.stdout)
        self.assertEqual(r.returncode, 0)
        self.assertIn("== MYD-1", r.stdout); self.assertIn("awaiting humans:", r.stdout)
