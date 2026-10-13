import json, os, pathlib, shutil, stat, tempfile, unittest
from turnstile_cli import state, paths
from turnstile_cli.errors import TurnstileError, StaleStateError

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class StateIO(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.delivery = self.tmp / "delivery"; self.delivery.mkdir()
        shutil.copy(FIX, self.delivery / "state.json")
        (self.tmp / ".turnstile").write_text("delivery\n")

    def test_find_delivery_walks_up(self):
        nested = self.tmp / "a" / "b"; nested.mkdir(parents=True)
        self.assertEqual(paths.find_delivery(nested, None), self.delivery.resolve())

    def test_find_delivery_override_and_missing(self):
        self.assertEqual(paths.find_delivery(self.tmp, str(self.delivery)), self.delivery.resolve())
        with self.assertRaises(TurnstileError):
            paths.find_delivery(pathlib.Path(tempfile.mkdtemp()), None)

    def test_round_trip_sorted_keys(self):
        st = state.load(self.delivery / "state.json")
        st.data["prs"]["jsfiller#1"]["state"] = "READY"
        state.save(st)
        text = (self.delivery / "state.json").read_text()
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text)["prs"]["jsfiller#1"]["state"], "READY")
        self.assertLess(text.index('"awaiting_human"'), text.index('"epic"'))  # sorted keys

    def test_save_refuses_stale_file(self):
        st = state.load(self.delivery / "state.json")
        (self.delivery / "state.json").write_text("{}\n")
        with self.assertRaises(StaleStateError):
            state.save(st)

    def test_lookups(self):
        st = state.load(self.delivery / "state.json")
        self.assertEqual(state.pr(st, "jsfiller#1")["ticket"], "MYD-10")
        self.assertEqual(state.story(st, "S1")["title"], "Header")
        self.assertFalse(state.repo_cfg(st, "jsfiller#1")["copilot"])
        with self.assertRaises(TurnstileError):
            state.pr(st, "jsfiller#999")

    def test_two_loaders_second_save_is_stale(self):
        a = state.load(self.delivery / "state.json"); b = state.load(self.delivery / "state.json")
        a.data["prs"]["jsfiller#1"]["state"] = "READY"; state.save(a)
        b.data["prs"]["jsfiller#1"]["state"] = "DEV"
        with self.assertRaises(StaleStateError):
            state.save(b)
        self.assertEqual(json.loads((self.delivery / "state.json").read_text())["prs"]["jsfiller#1"]["state"], "READY")
        self.assertEqual([p.name for p in self.delivery.iterdir() if p.name.startswith("state.json")], ["state.json"])  # no temp left

    def test_lock_is_exclusive(self):
        with state.locked(self.delivery):
            with self.assertRaises(TurnstileError):
                with state.locked(self.delivery, wait=False):
                    pass

    def test_lock_is_a_stable_file_in_the_delivery_dir_not_tmpdir(self):
        # R2-9: hook and CLI processes may see different TMPDIR values; the lock must not depend on it
        other = tempfile.mkdtemp()
        old = os.environ.get("TMPDIR")
        with state.locked(self.delivery):
            self.assertTrue((self.delivery / ".state.lock").exists())
            os.environ["TMPDIR"] = other; tempfile.tempdir = None
            try:
                with self.assertRaises(TurnstileError):
                    with state.locked(self.delivery, wait=False):
                        pass
            finally:
                if old is None:
                    os.environ.pop("TMPDIR", None)
                else:
                    os.environ["TMPDIR"] = old
                tempfile.tempdir = None
        self.assertEqual([p.name for p in pathlib.Path(other).iterdir()], [])

    def test_write_atomic_keeps_the_mode_and_follows_a_symlink(self):
        # R2-10: mkstemp creates 0600 files; the replaced state.json must keep its mode, a symlink must stay a symlink
        path = self.delivery / "state.json"
        os.chmod(path, 0o664)
        st = state.load(path); st.data["prs"]["jsfiller#1"]["state"] = "READY"; state.save(st)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o664)
        real = self.delivery / "real.json"; path.rename(real); path.symlink_to("real.json")
        st = state.load(path); st.data["prs"]["jsfiller#1"]["state"] = "DEV"; state.save(st)
        self.assertTrue(path.is_symlink()); self.assertEqual(json.loads(real.read_text())["prs"]["jsfiller#1"]["state"], "DEV")
        old = os.umask(0o027)
        try:
            fresh = self.delivery / "board.html"; state.write_atomic(fresh, "<html>")
            self.assertEqual(stat.S_IMODE(os.stat(fresh).st_mode), 0o640)
        finally:
            os.umask(old)

    def test_empty_marker_is_an_error(self):
        (self.tmp / ".turnstile").write_text("\n")
        with self.assertRaises(TurnstileError):
            paths.find_delivery(self.tmp, None)
