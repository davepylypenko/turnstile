import json, os, pathlib, subprocess, tempfile, unittest
from turnstile_cli import __version__

ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts" / "install-cli.sh"

class InstallCli(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.bin = self.tmp / "bin"; self.cfg = self.tmp / "claude"
        (self.cfg / "plugins").mkdir(parents=True)
        r = subprocess.run(["sh", str(INSTALL), str(self.bin)], capture_output=True, text=True, env=dict(os.environ, PATH="/usr/bin:/bin"))
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("not on PATH", r.stdout)
        self.shim = self.bin / "turnstile"
    def run_shim(self, *args, **env):
        e = dict(os.environ, HOME=str(self.tmp), CLAUDE_CONFIG_DIR=str(self.cfg)); e.pop("TURNSTILE_HOME", None); e.update(env)
        return subprocess.run([str(self.shim)] + list(args), capture_output=True, text=True, env=e)
    def fake_plugin(self, marketplace, version, mtime):
        d = self.cfg / "plugins" / "cache" / marketplace / "turnstile" / version; (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "turnstile").write_text("#!/bin/sh\necho fake-%s $1\n" % version); os.utime(d, (mtime, mtime))
        return d
    def test_shim_is_executable_and_resolves_the_registered_install(self):
        self.assertTrue(self.shim.stat().st_mode & 0o111)
        (self.cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {"turnstile@turnstile": [{"scope": "user", "installPath": str(ROOT), "version": __version__}]}}))
        r = self.run_shim("--version"); self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stdout.strip(), "turnstile " + __version__)
    def test_registered_entry_without_files_falls_back_to_the_newest_cache_entry(self):
        (self.cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {"turnstile@turnstile": [{"installPath": str(self.tmp / "gone"), "version": "9.9.9"}]}}))
        self.fake_plugin("turnstile", "0.1.0", 1_700_000_000); self.fake_plugin("other-marketplace", "0.2.0", 1_700_000_100)
        r = self.run_shim("status"); self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stdout.strip(), "fake-0.2.0 status")
    def test_turnstile_home_wins(self):
        self.fake_plugin("turnstile", "0.1.0", 1_700_000_000)
        r = self.run_shim("--version", TURNSTILE_HOME=str(ROOT)); self.assertEqual(r.stdout.strip(), "turnstile " + __version__)
    def test_no_plugin_fails_loudly(self):
        r = self.run_shim("--version"); self.assertEqual(r.returncode, 127); self.assertIn("claude plugin install turnstile@turnstile", r.stderr)
        self.assertIn(str(self.cfg), r.stderr)
    def test_reinstall_replaces_the_shim(self):
        self.shim.write_text("stale\n")
        subprocess.run(["sh", str(INSTALL), str(self.bin)], check=True, capture_output=True); self.assertNotIn("stale", self.shim.read_text())
