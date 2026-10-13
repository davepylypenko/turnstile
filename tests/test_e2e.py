import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"
GH_FIX = ROOT / "tests" / "fixtures" / "gh_pr_13222.json"
H = "aaaaaaaa11111111"

def sh(args, cwd, env=None):
    return subprocess.run([str(ROOT / "scripts" / "turnstile")] + args, cwd=cwd, capture_output=True, text=True, env=env)

class E2E(unittest.TestCase):
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")
        (d / "reports").mkdir(); (d / "reports" / "R.md").write_text("clean"); (d / ".state.lock").touch()  # as init leaves it
        subprocess.run(["git", "init", "-q"], cwd=self.ws, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."], cwd=self.ws, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-qm", "init"], cwd=self.ws, check=True)
        self.env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        # a PATH with a canned `gh`: the shim's real IO goes through it, no network
        self.bin = pathlib.Path(tempfile.mkdtemp()) / "bin"; self.bin.mkdir(); (self.bin / "python3").symlink_to(sys.executable)
        self.gh_env = dict(self.env, PATH=os.pathsep.join([str(self.bin), "/usr/bin", "/bin"]))

    def fake_gh(self, payload):
        (self.bin / "gh").write_text("#!/bin/sh\ncat <<'JSON'\n%s\nJSON\n" % json.dumps({"data": {"repository": {"pullRequest": payload}}}))
        (self.bin / "gh").chmod(0o755)

    def test_full_pr_path_with_real_git_commit(self):
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.ws, check=True)
        self.fake_gh(json.loads(GH_FIX.read_text()))
        r = sh(["pass", "pr", "jsfiller#1", "READY", "--head", H, "--ci", "success", "--deep-review", "reports/R.md", "--rounds", "1", "--gate", "pdf-review:pass"],
               cwd=self.ws / "delivery", env=self.gh_env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.strip().splitlines()[-1].startswith("OK pass pr jsfiller#1 AI_REVIEW → READY"))
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.ws, capture_output=True, text=True).stdout
        self.assertIn("turnstile: pass pr jsfiller#1", log)
        self.assertTrue((self.ws / "delivery" / "board.html").exists())
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=self.ws, capture_output=True, text=True).stdout, "")
        r = sh(["pass", "pr", "jsfiller#1", "ON_HUMAN_REVIEW", "--head", H], cwd=self.ws, env=self.gh_env)
        self.assertEqual(r.returncode, 2); self.assertIn("MISSING evidence.human.slack_permalink", r.stdout)

    def test_pass_refuses_when_github_head_differs(self):
        payload = json.loads(GH_FIX.read_text()); payload["headRefOid"] = "ffffffff6666666600000000000000000000ffff"
        self.fake_gh(payload)
        r = sh(["pass", "pr", "jsfiller#1", "READY", "--head", H, "--ci", "success", "--deep-review", "reports/R.md", "--gate", "pdf-review:pass"],
               cwd=self.ws, env=self.gh_env)
        self.assertEqual(r.returncode, 2); self.assertIn("MISSING head %s on GitHub" % H, r.stdout)
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=self.ws, capture_output=True, text=True).stdout, "")

    def test_pass_fails_closed_without_gh(self):
        self.assertIsNone(shutil.which("gh", path=self.gh_env["PATH"]), "gh must be absent from the test PATH")
        r = sh(["pass", "pr", "jsfiller#1", "READY", "--head", H, "--ci", "success", "--deep-review", "reports/R.md", "--gate", "pdf-review:pass"],
               cwd=self.ws, env=self.gh_env)
        self.assertEqual(r.returncode, 2); self.assertIn("MISSING GitHub head for jsfiller#1", r.stdout)

    def test_approve_needs_lead_env(self):
        r = sh(["approve", "ah-1"], cwd=self.ws, env=dict(self.env, TURNSTILE_LEAD=""))
        self.assertEqual(r.returncode, 2); self.assertIn("TURNSTILE_LEAD=1", r.stdout)

    def test_status_without_network(self):
        # PATH without `gh` (only the interpreter and the shim's bash/dirname): fetch raises, cli prints WARN, no network
        r = sh(["status"], cwd=self.ws, env=self.gh_env)
        self.assertIn("WARN jsfiller#1", r.stdout)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # facts missing for an open PR
        self.assertIn("== MYD-1", r.stdout); self.assertIn("awaiting humans:", r.stdout)
        self.assertNotIn("uncommitted", r.stdout)
        (self.ws / "delivery" / "ledger.md").write_text("- stray\n")
        r = sh(["status"], cwd=self.ws, env=self.gh_env)
        self.assertIn("uncommitted changes in delivery (1 file(s)): ledger.md", r.stdout)
