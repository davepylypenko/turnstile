import contextlib, io, json, os, pathlib, shutil, tempfile, unittest
from unittest import mock
from turnstile_cli import config, config_cmd, models, reconcile, state
from turnstile_cli.errors import TurnstileError
from tests.test_pass import FakeIO

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"

def out_of(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = fn(*a, **kw)
    return rc, buf.getvalue()

class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.user = self.tmp / "home" / "turnstile.json"
        self.env = mock.patch.dict(os.environ, {"TURNSTILE_USER_CONFIG": str(self.user)}); self.env.start(); self.addCleanup(self.env.stop)
        self.d = self.tmp / "ws" / "delivery"; self.d.mkdir(parents=True); shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch()
        self.io = FakeIO()
    def data(self): return json.loads((self.d / "state.json").read_text())

    def test_precedence_user_over_epic_over_default(self):
        eff = config.effective({"epic": {}}, {})
        self.assertEqual({a: (m["model"], m["effort"], m["source"]) for a, m in eff["models"].items()},
                         {a: (d["model"], d["effort"], "default") for a, d in models.DEFAULTS.items()})
        self.assertEqual(eff["review_skill"], {"value": "/code-review", "source": "default"}); self.assertEqual(eff["story_review_skill"]["source"], "default")
        epic = {"epic": {"models": dict(models.defaults(), reviewer={"model": "opus", "effort": "high"}), "review_skill": "/pdf-review:run"}}
        eff = config.effective(epic, {})
        self.assertEqual((eff["models"]["reviewer"]["effort"], eff["models"]["reviewer"]["source"]), ("high", "epic"))
        self.assertEqual(eff["models"]["implementer"]["source"], "default")  # equal to the default: not an override
        self.assertEqual(eff["review_skill"], {"value": "/pdf-review:run", "source": "epic"})
        user = {"models": {"reviewer": {"model": "sonnet", "effort": None}}, "review_skill": "/my-review"}
        eff = config.effective(epic, user)
        self.assertEqual(eff["models"]["reviewer"], {"model": "sonnet", "effort": None, "source": "user"})
        self.assertEqual(eff["review_skill"], {"value": "/my-review", "source": "user"}); self.assertEqual(eff["story_review_skill"]["source"], "default")
        self.assertEqual(config.effective(None, {})["models"]["tester"]["model"], "sonnet")
        self.assertIn("overrides: user models.reviewer, user review_skill", config.one_line(eff)); self.assertIn("reviewer=sonnet", config.one_line(eff))
        self.assertIn("(all defaults)", config.one_line(config.effective(None, {})))

    def test_user_file_path_env_and_default(self):
        self.assertEqual(config.user_path(), self.user)
        with mock.patch.dict(os.environ, {"TURNSTILE_USER_CONFIG": ""}):
            self.assertEqual(config.user_path(), pathlib.Path(os.path.expanduser("~")) / ".config" / "turnstile" / "config.json")
        self.assertEqual(config.load_user(), {})
        self.user.parent.mkdir(parents=True); self.user.write_text("nope")
        with self.assertRaises(TurnstileError): config.load_user()
        self.user.write_text("[]")
        with self.assertRaises(TurnstileError): config.load_user()

    def test_keys_and_values_are_validated(self):
        for key in ["model", "models.", "models.nobody", "gate", "review", ""]:
            with self.assertRaises(TurnstileError, msg=key): config.parse_key(key)
        self.assertEqual(config.parse_value("models.reviewer", "sonnet:medium"), {"model": "sonnet", "effort": "medium"})
        self.assertEqual(config.parse_value("models.tester", "haiku"), {"model": "haiku", "effort": None})
        for key, value in [("models.reviewer", "gpt"), ("models.reviewer", "opus:max"), ("models.reviewer", ""), ("models.reviewer", ":high"),
                           ("review_skill", ""), ("story_review_skill", "   ")]:
            with self.assertRaises(TurnstileError, msg=key + "=" + value): config.parse_value(key, value)
        with self.assertRaises(TurnstileError): config.effective({"epic": {}}, {"models": {"reviewer": {"model": "gpt"}}})

    def test_set_refuses_bad_input_and_writes_nothing(self):
        before = (self.d / "state.json").read_text()
        for assignment in ["models.reviewer", "models.reviewer=gpt", "models.nobody=opus", "gate=x", "review_skill=", "models.reviewer=opus:max"]:
            for epic in (False, True):
                rc, out = out_of(config_cmd.set_, self.d, assignment, epic=epic, io=self.io)
                self.assertEqual(rc, 2, assignment); self.assertIn("MISSING", out)
        self.assertFalse(self.user.exists()); self.assertEqual((self.d / "state.json").read_text(), before); self.assertEqual(self.io.commits, [])
        rc, out = out_of(config_cmd.set_, None, "review_skill=/x", epic=True, io=self.io); self.assertEqual(rc, 2); self.assertIn("--epic needs a delivery", out)

    def test_set_user_layer_writes_only_the_user_file(self):
        rc, out = out_of(config_cmd.set_, self.d, "models.reviewer=sonnet:medium", io=self.io)
        self.assertEqual(rc, 0, out); self.assertIn("models.reviewer = sonnet:medium (user)", out); self.assertIn("OK config set models.reviewer (user)", out)
        self.assertEqual(json.loads(self.user.read_text()), {"models": {"reviewer": {"model": "sonnet", "effort": "medium"}}})
        rc, out = out_of(config_cmd.set_, None, "review_skill=/my-review", io=self.io); self.assertEqual(rc, 0)  # no delivery needed for the user layer
        self.assertEqual(json.loads(self.user.read_text())["review_skill"], "/my-review")
        self.assertEqual(self.io.commits, []); self.assertNotIn("models", self.data()["epic"]); self.assertNotIn("review_skill", self.data()["epic"])
        self.assertEqual([p.name for p in self.d.iterdir()], [".state.lock", "state.json"]); self.assertFalse((self.d / "ledger.md").exists())
        self.assertFalse(str(self.user).startswith(str(self.d)))
        rc, out = out_of(config_cmd.unset, self.d, "models.reviewer", io=self.io); self.assertEqual(rc, 0); self.assertIn("models.reviewer = opus:medium (default)", out)
        self.assertEqual(json.loads(self.user.read_text()), {"review_skill": "/my-review"})
        rc, out = out_of(config_cmd.set_, self.d, "review_skill=default", io=self.io); self.assertEqual(json.loads(self.user.read_text()), {})

    def test_set_epic_layer_commits_through_the_guarded_path_with_a_ledger_line(self):
        rc, out = out_of(config_cmd.set_, self.d, "review_skill=/pdf-review:run", epic=True, io=self.io)
        self.assertEqual(rc, 0, out); self.assertIn("review_skill = /pdf-review:run (epic)", out); self.assertIn("OK config set review_skill (epic)", out)
        self.assertEqual(self.data()["epic"]["review_skill"], "/pdf-review:run"); self.assertFalse(self.user.exists())
        self.assertEqual(len(self.io.commits), 1); self.assertIn("config set review_skill=/pdf-review:run (epic)", (self.d / "ledger.md").read_text())
        rc, out = out_of(config_cmd.set_, self.d, "models.reviewer=opus:high", epic=True, io=self.io)
        self.assertEqual(self.data()["epic"]["models"]["reviewer"], {"model": "opus", "effort": "high"}); self.assertEqual(sorted(self.data()["epic"]["models"]), sorted(models.DEFAULTS))
        self.assertIn("models.reviewer = opus:high (epic)", out)
        rc, out = out_of(config_cmd.unset, self.d, "models.reviewer", epic=True, io=self.io)
        self.assertEqual(self.data()["epic"]["models"]["reviewer"], models.DEFAULTS["reviewer"]); self.assertIn("(default)", out)
        self.assertEqual(len(self.io.commits), 3); self.assertIn("config unset models.reviewer (epic)", (self.d / "ledger.md").read_text())
        out_of(config_cmd.set_, self.d, "review_skill=/my-review", io=self.io)  # the user layer still wins over the epic one
        rc, out = out_of(config_cmd.list_, self.d); self.assertIn("review_skill = /my-review (user)", out); self.assertIn("USER_CONFIG: %s" % self.user, out)

    def test_list_without_a_delivery(self):
        rc, out = out_of(config_cmd.list_, None)
        self.assertEqual(rc, 0); self.assertIn("EPIC: none", out); self.assertIn("(absent)", out)
        for a, d in models.DEFAULTS.items(): self.assertIn("models.%s = %s (default)" % (a, config.fmt_model(d)), out)
        self.assertIn("story_review_skill = /code-review (default)", out); self.assertIn("OK config list", out)

    def test_status_prints_the_effective_line(self):
        out_of(config_cmd.set_, self.d, "models.reviewer=sonnet", io=self.io)
        with mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")):
            rc, out = out_of(reconcile.cli, self.d, status=True)
        line = next(l for l in out.splitlines() if l.startswith("config: "))
        self.assertIn("reviewer=sonnet", line); self.assertIn("review_skill=/code-review", line); self.assertIn("overrides: user models.reviewer", line)
