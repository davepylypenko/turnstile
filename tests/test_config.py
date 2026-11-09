import contextlib, io, json, os, pathlib, shutil, tempfile, unittest
from unittest import mock
from turnstile_cli import brief_cmd, config, config_cmd, init_cmd, models, pass_cmd, reconcile, state
from turnstile_cli.errors import TurnstileError
from tests.test_pass import FakeIO
from tests.test_init import opts as init_opts

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"

def out_of(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = fn(*a, **kw)
    return rc, buf.getvalue()

class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve(); self.user = self.tmp / "home" / "turnstile.json"; self.user.parent.mkdir()
        self.env = mock.patch.dict(os.environ, {"TURNSTILE_USER_CONFIG": str(self.user)}); self.env.start(); self.addCleanup(self.env.stop)
        self.d = self.tmp / "ws" / "delivery"; self.d.mkdir(parents=True); shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch()
        self.io = FakeIO()
    def data(self): return json.loads((self.d / "state.json").read_text())

    def test_precedence_user_over_epic_over_default(self):
        eff = config.effective({"epic": {}}, {})
        self.assertEqual({a: (m["model"], m["effort"], m["source"]) for a, m in eff["models"].items()},
                         {a: (d["model"], d["effort"], "default") for a, d in models.DEFAULTS.items()})
        self.assertEqual(eff["review_skill"], {"value": "/code-review", "source": "default"}); self.assertEqual(eff["story_review_skill"]["source"], "default")
        epic = {"epic": {"models": dict(models.defaults(), reviewer={"model": "opus", "effort": "low"}), "review_skill": "/pdf-review:run"}}
        eff = config.effective(epic, {})
        self.assertEqual((eff["models"]["reviewer"]["effort"], eff["models"]["reviewer"]["source"]), ("low", "epic"))
        self.assertEqual(eff["models"]["implementer"]["source"], "default")  # equal to the default: not an override
        old = {"epic": {"models": dict(models.defaults(), reviewer={"model": "opus", "effort": "medium"}, **{"story-reviewer": {"model": "opus", "effort": "high"}})}}
        for agent in ("reviewer", "story-reviewer"):  # an epic created before 0.4.1 froze every then default; the full set reads as the current defaults
            self.assertEqual(config.effective(old, {})["models"][agent], dict(models.DEFAULTS[agent], source="default"))
        self.assertIn("models.reviewer = opus:high (default)", config.lines(config.effective(old, {}))); self.assertIn("(all defaults)", config.one_line(config.effective(old, {})))
        explicit = {"epic": {"models": {"reviewer": {"model": "opus", "effort": "high"}}}}
        self.assertEqual(config.effective(explicit, {})["models"]["reviewer"], {"model": "opus", "effort": "high", "source": "epic"})
        self.assertEqual(eff["review_skill"], {"value": "/pdf-review:run", "source": "epic"})
        user = {"models": {"reviewer": {"model": "sonnet", "effort": None}}, "review_skill": "/my-review"}
        eff = config.effective(epic, user)
        self.assertEqual(eff["models"]["reviewer"], {"model": "sonnet", "effort": None, "source": "user"})
        self.assertEqual(eff["review_skill"], {"value": "/my-review", "source": "user"}); self.assertEqual(eff["story_review_skill"]["source"], "default")
        self.assertEqual(config.effective(None, {})["models"]["tester"]["model"], "sonnet")
        self.assertIn("overrides: user models.reviewer, user review_skill", config.one_line(eff)); self.assertIn("reviewer=sonnet", config.one_line(eff))
        self.assertIn("(all defaults)", config.one_line(config.effective(None, {})))

    def test_user_file_path_env_and_default(self):
        self.assertEqual(config.user_path(), self.user.resolve())
        with mock.patch.dict(os.environ, {"TURNSTILE_USER_CONFIG": ""}):
            self.assertEqual(config.user_path(), pathlib.Path(os.path.expanduser("~")) / ".config" / "turnstile" / "config.json")
        self.assertEqual(config.load_user(), {})
        self.user.write_text("nope")
        with self.assertRaises(TurnstileError): config.load_user()
        for bad in ["[]", '{"models": "opus"}', '{"models": {"reviewer": "opus"}}', '{"review_skill": "pdf-review"}', '{"story_review_skill": 3}', '{"review_skill": "/a b"}']:
            self.user.write_text(bad)
            with self.assertRaises(TurnstileError, msg=bad): config.load_user()
        self.user.write_text('{"review_skill": "/pdf-review:run", "models": {"reviewer": {"model": "sonnet"}}}'); self.assertEqual(config.load_user()["review_skill"], "/pdf-review:run")
    def test_user_path_refuses_checkouts_and_non_json_and_creates_only_its_own_dir(self):
        # review P2-1: TURNSTILE_USER_CONFIG=<delivery>/state.json must never become a write path
        (self.tmp / "ws" / ".git").mkdir(parents=True)
        for bad in [self.d / "state.json", self.d / "x.json", self.tmp / "ws" / "any.json", self.tmp / "home" / "cfg.txt"]:
            with mock.patch.dict(os.environ, {"TURNSTILE_USER_CONFIG": str(bad)}):
                with self.assertRaises(TurnstileError, msg=str(bad)): config.user_path()
                rc, out = out_of(config_cmd.set_, self.d, "review_skill=/x", io=self.io); self.assertEqual(rc, 2); self.assertIn("TURNSTILE_USER_CONFIG must be", out)
        self.assertEqual(json.loads((self.d / "state.json").read_text()), json.loads(FIX.read_text())); self.assertFalse((self.d / "x.json").exists())
        with mock.patch.dict(os.environ, {"TURNSTILE_USER_CONFIG": str(self.tmp / "nodir" / "u.json")}):
            with self.assertRaises(TurnstileError): config.save_user({})
        self.assertFalse((self.tmp / "nodir").exists())
        with mock.patch.dict(os.environ, {"TURNSTILE_USER_CONFIG": ""}), mock.patch.object(config, "default_user_dir", return_value=self.tmp / "dot" / "turnstile"):
            config.save_user({"review_skill": "/x"}); self.assertTrue((self.tmp / "dot" / "turnstile" / "config.json").exists())

    def test_skill_values_must_be_slash_commands(self):
        for bad in ["pdf-review", "/pdf review", "/x;rm", "http://x", "/", "/..", "/.", "/:", "/a:", "/:b", "/a:b:c", "/-x", "/.hidden"]:
            with self.assertRaises(TurnstileError, msg=bad): config.parse_value("review_skill", bad)
        for ok in ["/code-review", "/pdf-review:run", "/my-review", "/my.review_2", "/kn:qa-test_v2"]: self.assertEqual(config.parse_value("story_review_skill", ok), ok)
        self.assertEqual(config.SKILL_RX.pattern, r"^/(?:[\w][\w.-]*:)?[\w][\w.-]*$")
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
        rc, out = out_of(config_cmd.unset, self.d, "models.reviewer", io=self.io); self.assertEqual(rc, 0); self.assertIn("models.reviewer = opus:high (default)", out)
        self.assertEqual(json.loads(self.user.read_text()), {"review_skill": "/my-review"})
        rc, out = out_of(config_cmd.set_, self.d, "review_skill=default", io=self.io); self.assertEqual(json.loads(self.user.read_text()), {})

    def approve(self, ah):
        with mock.patch.dict(os.environ, {"TURNSTILE_LEAD": "1"}): rc, out = out_of(pass_cmd.approve, self.d, ah, self.io)
        self.assertEqual(rc, 0, out)
    def test_set_epic_layer_opens_a_lead_entry_and_apply_commits_it(self):
        # review P2-2: the epic layer is shared state, so it changes only after the lead's word (same pattern as send/merge)
        rc, out = out_of(config_cmd.set_, self.d, "review_skill=/pdf-review:run", epic=True, io=self.io)
        self.assertEqual(rc, 0, out); self.assertIn("APPROVAL: the lead types: ! TURNSTILE_LEAD=1 turnstile approve ah-1", out); self.assertIn("THEN: turnstile config apply ah-1", out)
        self.assertNotIn("review_skill", self.data()["epic"]); self.assertFalse(self.user.exists())
        e = self.data()["awaiting_human"][0]; self.assertEqual((e["type"], e["payload"], e["old"], e["new"], e["reset"], e["approved_at"]), ("config", "review_skill", None, "/pdf-review:run", False, None))
        self.assertEqual(len(self.io.commits), 1); self.assertIn("config set review_skill=/pdf-review:run proposed for the epic (ah-1 awaits the lead)", (self.d / "ledger.md").read_text())
        rc, out = out_of(config_cmd.apply, self.d, "ah-1", io=self.io); self.assertEqual(rc, 2); self.assertIn("approved_at", out); self.assertNotIn("review_skill", self.data()["epic"])
        rc, out = out_of(config_cmd.apply, self.d, "ah-9", io=self.io); self.assertEqual(rc, 2); self.assertIn("unknown id", out)
        with mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")):
            rc, out = out_of(reconcile.cli, self.d, status=True); self.assertIn("ah-1 lead config review_skill", out); self.assertNotIn("APPLY:", out)
            self.approve("ah-1")
            rc, out = out_of(reconcile.cli, self.d, status=True); self.assertIn("APPLY: turnstile config apply ah-1 (review_skill approved by the lead)", out)
        rc, out = out_of(config_cmd.apply, self.d, "ah-1", io=self.io)
        self.assertEqual(rc, 0, out); self.assertIn("review_skill = /pdf-review:run (epic)", out); self.assertIn("OK config set review_skill (epic, ah-1)", out)
        self.assertEqual(self.data()["epic"]["review_skill"], "/pdf-review:run"); self.assertTrue(self.data()["awaiting_human"][0]["consumed_at"])
        self.assertIn("config set review_skill=/pdf-review:run (epic, approved ah-1)", (self.d / "ledger.md").read_text())
        rc, out = out_of(config_cmd.apply, self.d, "ah-1", io=self.io); self.assertEqual(rc, 2); self.assertIn("not consumed yet", out)
        out_of(config_cmd.set_, self.d, "models.reviewer=opus:high", epic=True, io=self.io); self.approve("ah-2")
        d = self.data(); d["epic"]["models"] = dict(models.defaults(), reviewer={"model": "sonnet", "effort": None}); (self.d / "state.json").write_text(state.dumps(d))
        rc, out = out_of(config_cmd.apply, self.d, "ah-2", io=self.io); self.assertEqual(rc, 2); self.assertIn("changed since ah-2 was proposed", out)
        d["epic"]["models"]["reviewer"] = dict(models.DEFAULTS["reviewer"]); (self.d / "state.json").write_text(state.dumps(d))
        rc, out = out_of(config_cmd.apply, self.d, "ah-2", io=self.io); self.assertEqual(rc, 2); self.assertIn("changed since", out)  # old was None (no epic.models in the fixture)
        d["epic"].pop("models"); (self.d / "state.json").write_text(state.dumps(d))
        rc, out = out_of(config_cmd.apply, self.d, "ah-2", io=self.io); self.assertEqual(rc, 0, out)
        self.assertEqual(self.data()["epic"]["models"]["reviewer"], {"model": "opus", "effort": "high"}); self.assertIn("models.reviewer = opus:high (epic)", out)
        out_of(config_cmd.unset, self.d, "models.reviewer", epic=True, io=self.io); self.approve("ah-3"); rc, out = out_of(config_cmd.apply, self.d, "ah-3", io=self.io)
        self.assertEqual(rc, 0, out); self.assertNotIn("reviewer", self.data()["epic"]["models"]); self.assertIn("models.reviewer = opus:high (default)", out)
        self.assertIn("config unset models.reviewer (epic, approved ah-3)", (self.d / "ledger.md").read_text())
        out_of(config_cmd.set_, self.d, "review_skill=/my-review", io=self.io)
        rc, out = out_of(config_cmd.list_, self.d); self.assertIn("review_skill = /my-review (user)", out); self.assertIn("USER_CONFIG: %s" % self.user, out)
        rc, out = out_of(config_cmd.apply, None, "ah-1", io=self.io); self.assertEqual(rc, 2); self.assertIn("needs a delivery", out)

    OLD_SET = dict(models.defaults(), reviewer={"model": "opus", "effort": "medium"}, **{"story-reviewer": {"model": "opus", "effort": "high"}})

    def test_only_a_frozen_full_set_reads_old_defaults_as_defaults(self):
        for agent, raw in [("reviewer", {"model": "opus", "effort": "medium"}), ("story-reviewer", {"model": "opus", "effort": "high"}), ("implementer", {"model": "sonnet", "effort": None})]:
            eff = config.effective({"epic": {"models": {agent: raw}}}, {})["models"][agent]
            self.assertEqual(eff, dict(raw, source="epic"), agent)
        eff = config.effective({"epic": {"models": self.OLD_SET}}, {})["models"]
        self.assertEqual({a: (m["effort"], m["source"]) for a, m in eff.items() if a in models.PREVIOUS_DEFAULTS}, {"reviewer": ("high", "default"), "story-reviewer": ("xhigh", "default")})
        self.assertTrue(all(m["source"] == "default" for m in eff.values()))
        self.assertTrue(config.is_frozen_set(self.OLD_SET)); self.assertFalse(config.is_frozen_set({"reviewer": {"model": "opus", "effort": "medium"}})); self.assertFalse(config.is_frozen_set(None))
        e = {"models": dict(self.OLD_SET, tester={"model": "opus", "effort": None})}; config.drop_frozen_defaults(e)
        self.assertEqual(e["models"], {"tester": {"model": "opus", "effort": None}})
        e = {"models": {"reviewer": {"model": "opus", "effort": "medium"}}}; config.drop_frozen_defaults(e); self.assertEqual(e["models"], {"reviewer": {"model": "opus", "effort": "medium"}})

    def test_init_models_with_an_old_default_value_is_stored_and_honoured(self):
        data = init_cmd.build_state(init_opts(self.tmp / "ws2", self.tmp / "kn", models='{"reviewer":{"effort":"medium"},"story-reviewer":{"model":"opus","effort":"high"}}'))
        self.assertEqual(data["epic"]["models"], {"reviewer": {"model": "opus", "effort": "medium"}, "story-reviewer": {"model": "opus", "effort": "high"}})
        eff = config.effective(data, {})
        self.assertEqual(eff["models"]["reviewer"], {"model": "opus", "effort": "medium", "source": "epic"}); self.assertEqual(eff["models"]["story-reviewer"]["effort"], "high")
        self.assertEqual(brief_cmd.builtins(data, self.d, "reviewer", "x", eff)["review_effort"], " medium")
        self.assertIn("overrides: epic models.reviewer, epic models.story-reviewer", config.one_line(eff))

    def test_explicit_epic_override_beats_the_previous_default_rule(self):
        d = self.data(); d["epic"]["models"] = dict(self.OLD_SET); (self.d / "state.json").write_text(state.dumps(d))
        rc, out = out_of(config_cmd.list_, self.d); self.assertIn("models.reviewer = opus:high (default)", out); self.assertIn("models.story-reviewer = opus:xhigh (default)", out)
        out_of(config_cmd.set_, self.d, "models.reviewer=opus:high", epic=True, io=self.io); self.approve("ah-1")
        rc, out = out_of(config_cmd.apply, self.d, "ah-1", io=self.io); self.assertEqual(rc, 0, out); self.assertIn("models.reviewer = opus:high (epic)", out)
        self.assertEqual(self.data()["epic"]["models"], {"reviewer": {"model": "opus", "effort": "high"}})
        d = self.data(); d["epic"]["models"] = dict(self.OLD_SET); (self.d / "state.json").write_text(state.dumps(d))
        out_of(config_cmd.set_, self.d, "models.story-reviewer=opus:high", epic=True, io=self.io); self.approve("ah-2")
        rc, out = out_of(config_cmd.apply, self.d, "ah-2", io=self.io); self.assertEqual(rc, 0, out); self.assertIn("models.story-reviewer = opus:high (epic)", out)
        self.assertEqual(self.data()["epic"]["models"], {"story-reviewer": {"model": "opus", "effort": "high"}})
        self.assertEqual(config.effective(self.data(), {})["models"]["reviewer"]["effort"], "high")
        d = self.data(); d["epic"]["models"] = dict(self.OLD_SET); (self.d / "state.json").write_text(state.dumps(d))
        out_of(config_cmd.unset, self.d, "models.reviewer", epic=True, io=self.io); self.approve("ah-3")
        rc, out = out_of(config_cmd.apply, self.d, "ah-3", io=self.io); self.assertEqual(rc, 0, out); self.assertEqual(self.data()["epic"]["models"], {})

    def test_story_reviewer_old_default_set_on_a_fresh_epic_is_honoured(self):
        out_of(config_cmd.set_, self.d, "models.story-reviewer=opus:high", epic=True, io=self.io); self.approve("ah-1")
        rc, out = out_of(config_cmd.apply, self.d, "ah-1", io=self.io); self.assertEqual(rc, 0, out); self.assertIn("models.story-reviewer = opus:high (epic)", out)
        self.assertEqual(self.data()["epic"]["models"], {"story-reviewer": {"model": "opus", "effort": "high"}})
        eff = config.effective(self.data(), {}); self.assertEqual(eff["models"]["story-reviewer"], {"model": "opus", "effort": "high", "source": "epic"})
        self.assertEqual(brief_cmd.builtins(self.data(), self.d, "story-reviewer", "x", eff)["review_effort"], " high")

    def test_list_shows_the_resolved_effort_like_the_agent_line(self):
        out_of(config_cmd.set_, self.d, "models.reviewer=sonnet", io=self.io); out_of(config_cmd.set_, self.d, "models.tester=haiku", io=self.io)
        rc, out = out_of(config_cmd.list_, self.d)
        self.assertIn("models.reviewer = sonnet:high (user; effort = agent default)", out); self.assertIn("models.tester = haiku (user)", out)
        self.assertIn("models.story-reviewer = opus:xhigh (default)", out)
        eff = config.effective(self.data())
        self.assertIn("reviewer=sonnet:high", config.one_line(eff)); self.assertIn("tester=haiku ", config.one_line(eff))
        self.assertEqual(models.agent_line("reviewer", eff["models"]["reviewer"]), "AGENT: turnstile:reviewer model=sonnet effort=high")
        out_of(config_cmd.set_, self.d, "models.reviewer=sonnet:low", io=self.io)
        rc, out = out_of(config_cmd.list_, self.d); self.assertIn("models.reviewer = sonnet:low (user)", out)
        self.assertIn("models.reviewer = sonnet:high (user; effort = agent default)", "\n".join(config.lines(config.effective(None, {"models": {"reviewer": {"model": "sonnet", "effort": None}}}))))
        self.assertIn("models.reviewer = sonnet:high (user)", "\n".join(config.lines(config.effective(None, {"models": {"reviewer": {"model": "sonnet"}}}))))
    def test_flag_is_epic_only(self):
        rc, out = out_of(config_cmd.set_, self.d, "flag=pwr-l2f", io=self.io); self.assertEqual(rc, 2); self.assertIn("flag is epic state", out); self.assertFalse(self.user.exists())
        rc, out = out_of(config_cmd.set_, self.d, "flag=pwr-l2f", epic=True, io=self.io); self.assertEqual(rc, 0, out); self.approve("ah-1")
        rc, out = out_of(config_cmd.apply, self.d, "ah-1", io=self.io); self.assertEqual(rc, 0, out)
        self.assertEqual(self.data()["epic"]["flag"], "pwr-l2f"); self.assertIn("flag = pwr-l2f (epic)", out); self.assertIn("flag=pwr-l2f", config.one_line(config.effective(self.data(), {})))
        rc, out = out_of(config_cmd.set_, self.d, "flag=", epic=True, io=self.io); self.assertEqual(rc, 2); self.assertIn("non-empty flag name", out)
        rc, out = out_of(config_cmd.unset, self.d, "flag", epic=True, io=self.io); self.assertEqual(rc, 0); self.approve("ah-2")
        rc, out = out_of(config_cmd.apply, self.d, "ah-2", io=self.io); self.assertEqual(rc, 0); self.assertIsNone(self.data()["epic"]["flag"]); self.assertIn("flag = none (default)", out)
        self.assertIn("config set flag=pwr-l2f (epic, approved ah-1)", (self.d / "ledger.md").read_text())
    def test_list_without_a_delivery(self):
        rc, out = out_of(config_cmd.list_, None)
        self.assertEqual(rc, 0); self.assertIn("EPIC: none", out); self.assertIn("(absent)", out)
        for a, d in models.DEFAULTS.items(): self.assertIn("models.%s = %s (default)" % (a, config.fmt_model(d)), out)
        self.assertIn("story_review_skill = /code-review (default)", out); self.assertIn("send_skill = /send-pr-review (default)", out); self.assertIn("OK config list", out)

    def test_send_skill_is_a_third_skill_key_in_every_layer(self):
        # 2026-11-06: the send skill is a name the plugin resolves on the developer's machine, never a copy in the repo
        self.assertEqual(config.SKILL_KEYS, ("review_skill", "story_review_skill", "send_skill")); self.assertIn("send_skill", config.KEYS_HELP)
        self.assertEqual(config.effective(None, {})["send_skill"], {"value": "/send-pr-review", "source": "default"})
        self.assertEqual(config.effective({"epic": {"send_skill": "/team-send"}}, {})["send_skill"], {"value": "/team-send", "source": "epic"})
        self.assertEqual(config.effective({"epic": {"send_skill": "/team-send"}}, {"send_skill": "/my-send"})["send_skill"], {"value": "/my-send", "source": "user"})
        self.assertEqual(config.effective({"epic": {"key": "OLD"}}, {})["send_skill"]["value"], "/send-pr-review")  # a state file from before the key
        self.assertIsNone(json.loads((init_cmd.TEMPLATES / "state.json").read_text())["epic"]["send_skill"])
        for bad in ["send-pr-review", "/a b", ""]:
            with self.assertRaises(TurnstileError, msg=bad): config.parse_value("send_skill", bad)
        self.user.write_text('{"send_skill": "nope"}')
        with self.assertRaises(TurnstileError): config.load_user()
        self.user.unlink()
        rc, out = out_of(config_cmd.set_, self.d, "send_skill=/my-send", io=self.io)
        self.assertEqual(rc, 0, out); self.assertIn("send_skill = /my-send (user)", out); self.assertEqual(json.loads(self.user.read_text()), {"send_skill": "/my-send"})
        rc, out = out_of(config_cmd.list_, self.d); self.assertIn("send_skill = /my-send (user)", out)
        self.assertIn("send_skill=/my-send", config.one_line(config.effective(self.data()))); self.assertIn("user send_skill", config.one_line(config.effective(self.data())))
        rc, out = out_of(config_cmd.set_, self.d, "send_skill=/team-send", epic=True, io=self.io); self.assertEqual(rc, 0, out); self.approve("ah-1")
        rc, out = out_of(config_cmd.apply, self.d, "ah-1", io=self.io); self.assertEqual(rc, 0, out); self.assertEqual(self.data()["epic"]["send_skill"], "/team-send")
        self.assertIn("send_skill = /my-send (user)", out)  # the user layer still wins
        rc, out = out_of(config_cmd.unset, self.d, "send_skill", io=self.io); self.assertEqual(rc, 0); self.assertIn("send_skill = /team-send (epic)", out)
        self.assertIn("config set send_skill=/team-send (epic, approved ah-1)", (self.d / "ledger.md").read_text())

    def test_skill_path_looks_in_home_cwd_roots_and_the_plugin_cache(self):
        home = self.tmp / "fakehome"; (home / ".claude" / "skills").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"HOME": str(home), "CLAUDE_CONFIG_DIR": ""}):
            self.assertIsNone(config.skill_path("/send-pr-review")); self.assertIsNone(config.skill_path("/pdf-review:run"))
            plain = home / ".claude" / "skills" / "send-pr-review" / "SKILL.md"; plain.parent.mkdir(); plain.write_text("---\nname: send-pr-review\n---\n")
            self.assertEqual(config.skill_path("/send-pr-review"), plain)
            (home / ".claude" / "skills" / "empty").mkdir(); self.assertIsNone(config.skill_path("/empty"))  # a folder without SKILL.md is not a skill
            plugin = home / ".claude" / "plugins" / "cache" / "pdffiller-knowledge" / "pdf-review" / "1.2.3" / "skills" / "run" / "SKILL.md"
            plugin.parent.mkdir(parents=True); plugin.write_text("x")
            self.assertEqual(config.skill_path("/pdf-review:run"), plugin); self.assertEqual(config.skill_path("/run"), plugin)
            self.assertIsNone(config.skill_path("/other-plugin:run")); self.assertIsNone(config.skill_path("/pdf-review:init"))
            root = self.tmp / "root"; local = root / ".claude" / "skills" / "team-send" / "SKILL.md"; local.parent.mkdir(parents=True); local.write_text("y")
            self.assertIsNone(config.skill_path("/team-send")); self.assertEqual(config.skill_path("/team-send", [root]), local)
            self.assertEqual(config.skill_path("/team-send", [None, root]), local)
            from turnstile_cli import workspace
            workspace.record(self.d, self.tmp / "ws", root, self.tmp / "ws" / "kn", {})
            self.assertEqual([str(r) for r in config.skill_roots(self.d)][1:], [str(self.tmp / "ws"), str(root)])
            self.assertEqual(config.skill_roots(None), [pathlib.Path.cwd()])
            gone = self.tmp / "gone"; gone.mkdir(); before = os.getcwd(); os.chdir(gone); self.addCleanup(os.chdir, before); gone.rmdir()
            self.assertEqual(config.skill_roots(None), []); self.assertEqual(config.skill_path("/send-pr-review", config.skill_roots(self.d)), plain); os.chdir(before)
            self.assertEqual(config.send_skill(self.data(), self.d), ("/send-pr-review", plain))
            self.user.write_text('{"send_skill": "/team-send"}'); self.assertEqual(config.send_skill(self.data(), self.d), ("/team-send", local))
            self.user.write_text('{"send_skill": "/ghost"}'); self.assertEqual(config.send_skill(self.data(), self.d), ("/ghost", None))
        self.assertEqual(config.send_skill_line("/send-pr-review", plain), "SEND_SKILL: /send-pr-review (found: %s)" % plain)
        self.assertEqual(config.send_skill_line("/send-pr-review", None), "SEND_SKILL: /send-pr-review not found on this machine — NEXT: ask the lead which skill "
                         "sends PRs to review (then turnstile config set send_skill=/<name>) or install the default: ln -s <pdffiller-knowledge clone>/playground/"
                         "zolotukhin-ivan/skills/send-pr-review ~/.claude/skills/send-pr-review")
        self.assertTrue(config.send_skill_line("/ghost", None).endswith("or install it")); self.assertNotIn("ln -s", config.send_skill_line("/ghost", None))
        self.assertIsNone(config.send_skill_warning("/x", plain))
        self.assertEqual(config.send_skill_warning("/x", None), "WARN: send skill /x not found on this machine (config set send_skill=… or install it)")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads every directory")
    def test_skill_path_never_raises_on_unreadable_directories(self):
        home = self.tmp / "fakehome"; skills = home / ".claude" / "skills"; locked = skills / "send-pr-review"; locked.mkdir(parents=True); (locked / "SKILL.md").write_text("x")
        locked.chmod(0); self.addCleanup(locked.chmod, 0o755)
        with mock.patch.dict(os.environ, {"HOME": str(home), "CLAUDE_CONFIG_DIR": ""}):
            self.assertIsNone(config.skill_path("/send-pr-review"))
            skills.chmod(0); self.addCleanup(skills.chmod, 0o755)
            self.assertIsNone(config.skill_path("/send-pr-review")); self.assertIsNone(config.skill_path("/pdf-review:run"))
            self.assertEqual(config.send_skill(self.data(), self.d), ("/send-pr-review", None))
            cache = home / ".claude" / "plugins" / "cache"; cache.mkdir(parents=True); cache.chmod(0); self.addCleanup(cache.chmod, 0o755)
            self.assertIsNone(config.skill_path("/pdf-review:run")); self.assertIsNone(config.skill_path("/run"))

    def test_skill_path_covers_commands_and_plugin_layouts(self):
        home = self.tmp / "fakehome"; cfg = home / ".claude"; (cfg / "commands").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"HOME": str(home), "CLAUDE_CONFIG_DIR": ""}):
            cmd = cfg / "commands" / "my-send.md"; cmd.write_text("x"); self.assertEqual(config.skill_path("/my-send"), cmd)
            root = self.tmp / "root"; rcmd = root / ".claude" / "commands" / "team-send.md"; rcmd.parent.mkdir(parents=True); rcmd.write_text("x")
            self.assertIsNone(config.skill_path("/team-send")); self.assertEqual(config.skill_path("/team-send", [root]), rcmd)
            cache = cfg / "plugins" / "cache"; version = cache / "marketplace" / "kn" / "1.0.0"
            deep = version / "skills" / "qa" / "test-feature" / "SKILL.md"; deep.parent.mkdir(parents=True); deep.write_text("x")
            self.assertEqual(config.skill_path("/kn:test-feature"), deep); self.assertIsNone(config.skill_path("/other:test-feature"))
            pcmd = version / "commands" / "run.md"; pcmd.parent.mkdir(parents=True); pcmd.write_text("x")
            self.assertEqual(config.skill_path("/kn:run"), pcmd); self.assertEqual(config.skill_path("/run"), pcmd)
            skill = version / "skills" / "run" / "SKILL.md"; skill.parent.mkdir(parents=True); skill.write_text("x")
            self.assertEqual(config.skill_path("/kn:run"), skill); self.assertEqual(config.skill_path("/run"), skill)
            self.assertIsNone(config.skill_path("/kn:nope")); self.assertIsNone(config.skill_path("/nope"))
            flat = cache / "marketplace" / "solo" / "2.0.0" / "solo" / "SKILL.md"; flat.parent.mkdir(parents=True); flat.write_text("x")
            self.assertEqual(config.skill_path("/solo:solo"), flat)
        other = self.tmp / "cfgdir"; (other / "skills" / "x-send").mkdir(parents=True); (other / "skills" / "x-send" / "SKILL.md").write_text("x")
        (other / "commands").mkdir(); (other / "commands" / "x-cmd.md").write_text("x")
        with mock.patch.dict(os.environ, {"HOME": str(home), "CLAUDE_CONFIG_DIR": str(other)}):
            self.assertEqual(config.claude_dir(), other)
            self.assertEqual(config.skill_path("/x-send"), other / "skills" / "x-send" / "SKILL.md"); self.assertEqual(config.skill_path("/x-cmd"), other / "commands" / "x-cmd.md")
            self.assertIsNone(config.skill_path("/my-send")); self.assertIsNone(config.skill_path("/kn:run"))

    def test_status_warns_once_when_the_send_skill_is_missing_and_the_hint_names_it(self):
        home = self.tmp / "fakehome"; home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home), "CLAUDE_CONFIG_DIR": ""}), mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")):
            rc, out = out_of(reconcile.cli, self.d, status=True)
            self.assertTrue(out.startswith("SYNC:"), out[:40]); self.assertEqual(out.count("WARN: send skill"), 1)
            self.assertIn("WARN: send skill /send-pr-review not found on this machine (config set send_skill=… or install it)", out.splitlines())
            rc, out = out_of(reconcile.cli, self.d); self.assertNotIn("send skill", out)  # reconcile alone stays quiet
            skill = home / ".claude" / "skills" / "my-send" / "SKILL.md"; skill.parent.mkdir(parents=True); skill.write_text("x")
            out_of(config_cmd.set_, self.d, "send_skill=/my-send", io=self.io)
            rc, out = out_of(reconcile.cli, self.d, status=True); self.assertNotIn("WARN: send skill", out); self.assertIn("send_skill=/my-send", out)
            d = self.data(); d["stories"]["S1"]["state"] = "DONE"; (self.d / "state.json").write_text(state.dumps(d)); self.io.heads = {"docs-platform#2": "bbbbbbbb22222222"}
            rc, out = out_of(pass_cmd.run, self.d, "pr", "docs-platform#2", "AI_REVIEW", pass_cmd.Options(head="bbbbbbbb22222222", ci="success"), self.io)
            self.assertEqual(rc, 0, out)
            self.assertIn("send the story's units with /send-pr-review <pr urls> on the lead's word in chat", self.data()["stories"]["S1"]["next_action"])
            self.assertNotIn("/my-send", (self.d / "state.json").read_text())
            rc, out = out_of(reconcile.cli, self.d, status=True); self.assertIn("send_skill=/my-send", out); self.assertIn("with /send-pr-review <pr urls>", out)
            out_of(config_cmd.set_, self.d, "send_skill=/team-send", epic=True, io=self.io); self.approve("ah-1")
            rc, out = out_of(config_cmd.apply, self.d, "ah-1", io=self.io); self.assertEqual(rc, 0, out)
            self.assertIn("with /team-send <pr urls>", self.data()["stories"]["S1"]["next_action"]); self.assertNotIn("/my-send", (self.d / "state.json").read_text())
            rc, out = out_of(reconcile.cli, self.d, status=True); self.assertIn("send_skill=/my-send", out); self.assertIn("with /team-send <pr urls>", out)
            out_of(config_cmd.unset, self.d, "send_skill", epic=True, io=self.io); self.approve("ah-2")
            rc, out = out_of(config_cmd.apply, self.d, "ah-2", io=self.io); self.assertEqual(rc, 0, out)
            self.assertIn("with /send-pr-review <pr urls>", self.data()["stories"]["S1"]["next_action"])

    def test_persisted_hints_ignore_the_user_file_and_a_broken_one_never_blocks_writers(self):
        from turnstile_cli import bug_cmd, plan_cmd, pr_cmd
        from tests.test_plan_cmd import PLAN
        self.user.write_text('{"send_skill": "nope"}')
        with self.assertRaises(TurnstileError): config.load_user()
        (self.d / "plan.md").write_text(PLAN); rc, out = out_of(plan_cmd.run, self.d, self.io); self.assertEqual(rc, 0, out); self.approve("ah-1")
        d = self.data(); d["stories"]["S1"]["state"] = "DONE"; (self.d / "state.json").write_text(state.dumps(d))
        self.io.heads = {"docs-platform#2": "bbbbbbbb22222222", "jsfiller#7": "cccccccc33333333"}; self.io.facts["jsfiller#7"] = {"base": "epic_myd-1", "branch": "feature/MYD-11"}
        (self.d / "briefs").mkdir(); (self.d / "briefs" / "MYD-11.md").write_text("brief\n")
        rc, out = out_of(pass_cmd.run, self.d, "pr", "docs-platform#2", "AI_REVIEW", pass_cmd.Options(head="bbbbbbbb22222222", ci="success"), self.io); self.assertEqual(rc, 0, out)
        rc, out = out_of(pr_cmd.add, self.d, "jsfiller#7", "S1", "MYD-11", io=self.io); self.assertEqual(rc, 0, out)
        rc, out = out_of(bug_cmd.add, self.d, "S1", "x", "tester", io=self.io); self.assertEqual(rc, 0, out)
        (self.d / "plan.md").write_text(PLAN + "\nmore\n"); rc, out = out_of(plan_cmd.run, self.d, self.io); self.assertEqual(rc, 0, out)
        text = (self.d / "state.json").read_text(); self.assertNotIn("nope", text); self.assertIn("with /send-pr-review <pr urls>", self.data()["stories"]["S1"]["next_action"])
        self.user.write_text('{"send_skill": "/my-send"}')
        rc, out = out_of(pass_cmd.run, self.d, "pr", "jsfiller#7", "AI_REVIEW", pass_cmd.Options(head="cccccccc33333333", ci="success"), self.io); self.assertEqual(rc, 0, out)
        self.assertNotIn("/my-send", (self.d / "state.json").read_text()); self.assertIn("with /send-pr-review <pr urls>", self.data()["stories"]["S1"]["next_action"])

    def test_status_prints_the_effective_line(self):
        out_of(config_cmd.set_, self.d, "models.reviewer=sonnet", io=self.io)
        with mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")):
            rc, out = out_of(reconcile.cli, self.d, status=True)
        line = next(l for l in out.splitlines() if l.startswith("config: "))
        self.assertIn("reviewer=sonnet", line); self.assertIn("review_skill=/code-review", line); self.assertIn("overrides: user models.reviewer", line)
