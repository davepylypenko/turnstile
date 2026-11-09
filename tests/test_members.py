import contextlib, io, json, pathlib, shutil, tempfile, unittest
from unittest import mock
from turnstile_cli import attach_cmd, board, brief_cmd, config, init_cmd, members, models, pass_cmd, reconcile, state, threads, workspace
from turnstile_cli.errors import TurnstileError
from tests.test_pass import FakeIO
from tests.test_sync import Attach, FakeGit

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"
APP = '{"name":"app","base":"main","slack":"C1"}'

def out_of(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = fn(*a, **kw)
    return rc, buf.getvalue()

class Delivery(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir(); shutil.copy(FIX, self.d / "state.json")
        self.addCleanup(shutil.rmtree, str(self.d.parent), True)
        self.io = FakeIO(heads={})
    def data(self): return json.loads((self.d / "state.json").read_text())
    def put(self, data): (self.d / "state.json").write_text(state.dumps(data))
    def record_member(self, login):
        workspace.record(self.d, self.d.parent / "ws", self.d.parent, self.d.parent / "k", {}, member=login)
    def with_members(self):
        d = self.data(); d["epic"]["members"] = {
            "leadlogin": members.new_entry("Lead", "v1", "desk05", "https://claude.ai/artifact/lead"),
            "second": members.new_entry("Second", "myd-1-second", None, None)}
        self.put(d); return d

class Migration(Delivery):
    def test_old_state_gets_the_lead_member_from_environment_and_board(self):
        data = state.load(self.d / "state.json").data
        self.assertEqual(list(data["epic"]["members"]), ["leadlogin"])
        m = data["epic"]["members"]["leadlogin"]
        self.assertEqual((m["variant"], m["desk"]), ("v1", "desk05")); self.assertEqual(m["board"]["artifact_url"], "https://claude.ai/artifact/x")
        self.assertEqual(m["board"]["capabilities"], ["db", "user"]); self.assertIn("added_at", m)

    def test_migration_is_idempotent_and_keeps_existing_members(self):
        data = state.load(self.d / "state.json").data; before = json.dumps(data, sort_keys=True)
        self.assertFalse(members.migrate(data)); self.assertEqual(json.dumps(data, sort_keys=True), before)
        data["epic"]["environment"]["variant"] = "changed"; members.migrate(data)
        self.assertEqual(data["epic"]["members"]["leadlogin"]["variant"], "v1")

    def test_a_state_without_a_lead_login_is_left_alone(self):
        data = {"epic": {"roles": {}, "environment": {"variant": "v"}}}
        self.assertFalse(members.migrate(data)); self.assertNotIn("members", data["epic"])

class Current(Delivery):
    def test_workspace_member_then_lead_fallback_then_refusal(self):
        self.with_members(); data = state.load(self.d / "state.json").data
        self.assertEqual(members.current(data, self.d)[0], "leadlogin")
        self.record_member("second"); self.assertEqual(members.current(data, self.d)[0], "second")
        self.record_member("ghost")
        with self.assertRaises(TurnstileError) as cm: members.current(data, self.d)
        self.assertIn("turnstile attach --epic MYD-1 --github ghost", str(cm.exception))

class InitMembers(unittest.TestCase):
    def test_init_builds_the_lead_member_and_keeps_the_old_keys(self):
        o = init_cmd.InitOptions(epic="MYD-1", workitem="w", lead="Lead Name", lead_github="lg", github_org="o", repos=[APP], variant="myd-1-lg", desk="desk07", board_url="https://claude.ai/artifact/b")
        e = init_cmd.build_state(o)["epic"]
        self.assertEqual(list(e["members"]), ["lg"]); m = e["members"]["lg"]
        self.assertEqual((m["name"], m["variant"], m["desk"], m["board"]["artifact_url"]), ("Lead Name", "myd-1-lg", "desk07", "https://claude.ai/artifact/b"))
        self.assertEqual(e["environment"]["variant"], "myd-1-lg"); self.assertEqual(e["board"]["artifact_url"], "https://claude.ai/artifact/b")

class AttachMembers(unittest.TestCase):
    setUp = Attach.setUp
    attach = Attach.attach
    def delivery(self): return self.ws / "pdffiller-knowledge" / "context" / "workitems" / "demo" / "delivery"
    def members(self): return json.loads((self.delivery() / "state.json").read_text())["epic"]["members"]
    def run_attach(self, **kw):
        writer = kw.pop("writer", None) or FakeIO(heads={}); git = kw.pop("git", None) or FakeGit()
        o = attach_cmd.AttachOptions(**dict(dict(knowledge=str(self.knowledge), epic="MYD-1", workspace=str(self.ws)), **kw))
        return out_of(attach_cmd.run, o, git, writer), writer

    def test_new_member_gets_the_default_variant_prints_member_and_next_and_is_recorded(self):
        (rc, out), writer = self.run_attach(github="Ivanov")
        self.assertEqual(rc, 1, out)
        m = self.members()["Ivanov"]; self.assertEqual((m["name"], m["variant"], m["desk"], m["board"]["artifact_url"]), ("Ivanov", "myd-1-ivanov", None, None))
        self.assertIn("leadlogin", self.members())
        self.assertIn("MEMBER: Ivanov · variant myd-1-ivanov · desk none · board new artifact", out)
        self.assertIn("NEXT: the variant does not exist yet: dispatch the deployer (turnstile brief deployer DEPLOY-env-Ivanov …) to create it through the prometey-variant skill; "
                      "then turnstile board-url <url> after the first board publish", out)
        self.assertEqual(json.loads((self.delivery() / ".workspace.json").read_text())["member"], "Ivanov")
        self.assertEqual(len(writer.commits), 1); self.assertEqual(writer.pushes, ["epic/myd-1"])
        self.assertEqual(out.count("MEMBER: Ivanov · variant myd-1-ivanov"), 2)

    def test_flags_set_the_entry_and_a_second_attach_updates_without_duplicating(self):
        (rc, out), w1 = self.run_attach(github="ivanov", name="Ivan I", variant="custom-v", desk="desk09", board_url="https://claude.ai/code/artifact/abc")
        m = self.members()["ivanov"]; self.assertEqual((m["name"], m["variant"], m["desk"], m["board"]["artifact_url"]), ("Ivan I", "custom-v", "desk09", "https://claude.ai/code/artifact/abc"))
        (rc, out), w2 = self.run_attach(github="ivanov", desk="desk11")
        m = self.members()["ivanov"]; self.assertEqual((m["name"], m["variant"], m["desk"], m["board"]["artifact_url"]), ("Ivan I", "custom-v", "desk11", "https://claude.ai/code/artifact/abc"))
        self.assertEqual(sorted(self.members()), ["ivanov", "leadlogin"]); self.assertEqual(len(w2.commits), 1)
        (rc, out), w3 = self.run_attach(github="ivanov"); self.assertEqual(w3.commits, [])
        self.assertEqual(self.members()["ivanov"]["desk"], "desk11")

    def test_login_comes_from_gh_when_the_flag_is_absent_and_is_required_otherwise(self):
        git = FakeGit(); git.github_login = lambda: "from-gh"
        (rc, out), w = self.run_attach(git=git); self.assertEqual(rc, 1, out); self.assertIn("from-gh", self.members())
        shutil.rmtree(str(self.ws)); self.ws.mkdir()
        (rc, out), w = self.run_attach(); self.assertEqual(rc, 2); self.assertIn("MISSING --github <login> is required", out)
        self.assertFalse((self.ws / ".turnstile").exists()); self.assertEqual(w.commits, [])

    def test_a_bad_board_url_is_refused_before_anything_is_touched(self):
        (rc, out), w = self.run_attach(github="x", board_url="https://example.com/a")
        self.assertEqual(rc, 2); self.assertIn("board url must look like", out); self.assertFalse((self.ws / ".turnstile").exists())

class BoardUrl(Delivery):
    def test_validation(self):
        self.with_members()
        for bad in ("http://claude.ai/artifact/x", "https://claude.ai/other/x", "https://evil.com/artifact/x", "", "https://claude.ai/artifact/"):
            rc, out = out_of(members.board_url, self.d, bad, self.io); self.assertEqual(rc, 2, bad); self.assertIn("board url must look like", out)
        self.assertEqual(self.io.commits, [])
        for good in ("https://claude.ai/artifact/abc", "https://claude.ai/code/artifact/1234-abcd"):
            self.assertEqual(out_of(members.board_url, self.d, good, self.io)[0], 0)

    def test_the_lead_also_updates_the_epic_board_and_another_member_does_not(self):
        self.with_members()
        rc, out = out_of(members.board_url, self.d, "https://claude.ai/artifact/new-lead", self.io); self.assertEqual(rc, 0, out)
        e = self.data()["epic"]; self.assertEqual(e["members"]["leadlogin"]["board"]["artifact_url"], "https://claude.ai/artifact/new-lead")
        self.assertEqual(e["board"]["artifact_url"], "https://claude.ai/artifact/new-lead"); self.assertEqual(self.io.pushes, ["epic/myd-1"])
        self.record_member("second")
        rc, out = out_of(members.board_url, self.d, "https://claude.ai/artifact/second-board", self.io); self.assertEqual(rc, 0, out)
        e = self.data()["epic"]; self.assertEqual(e["members"]["second"]["board"]["artifact_url"], "https://claude.ai/artifact/second-board")
        self.assertEqual(e["board"]["artifact_url"], "https://claude.ai/artifact/new-lead")
        self.assertEqual(e["members"]["leadlogin"]["board"]["artifact_url"], "https://claude.ai/artifact/new-lead")

    def test_an_unknown_member_is_refused_with_the_attach_line(self):
        self.record_member("ghost"); rc, out = out_of(members.board_url, self.d, "https://claude.ai/artifact/a", self.io)
        self.assertEqual(rc, 2); self.assertIn("turnstile attach --epic MYD-1 --github ghost", out)

class Consumers(Delivery):
    def test_brief_builtins_read_the_current_member_and_fall_back_to_the_environment(self):
        self.with_members(); data = self.data()
        b = brief_cmd.builtins(data, self.d, "deployer", "X"); self.assertEqual((b["variant"], b["desk"], b["member"]), ("v1", "desk05", "leadlogin"))
        self.record_member("second"); b = brief_cmd.builtins(data, self.d, "deployer", "X"); self.assertEqual((b["variant"], b["desk"], b["member"]), ("myd-1-second", "desk05", "second"))
        data["epic"]["members"]["second"]["desk"] = "desk02"; self.assertEqual(brief_cmd.builtins(data, self.d, "deployer", "X")["desk"], "desk02")
        self.record_member("ghost"); b = brief_cmd.builtins(data, self.d, "deployer", "X"); self.assertEqual((b["variant"], b["desk"], b["member"]), ("v1", "desk05", ""))
        old = {"epic": {"environment": {"variant": "e", "desk": "d", "recipe": "r"}}}; b = brief_cmd.builtins(old, self.d, "deployer", "X")
        self.assertEqual((b["variant"], b["desk"], b["env_recipe"]), ("e", "d", "r"))

    def test_board_line_is_per_member(self):
        self.with_members(); data = self.data()
        self.assertEqual(members.board_line(data, self.d), "BOARD: publish %s → https://claude.ai/artifact/lead" % (self.d / "boards" / "leadlogin.html"))
        self.record_member("second")
        self.assertIn("→ new artifact (capabilities: db, user) — then: turnstile board-url <url>", members.board_line(data, self.d))
        data["epic"]["members"]["second"]["board"]["artifact_url"] = "https://claude.ai/artifact/s"
        self.assertTrue(members.board_line(data, self.d).endswith("→ https://claude.ai/artifact/s"))

    def test_pass_prints_the_current_members_board_line_and_deploy_records_variant_and_by(self):
        d = self.with_members(); self.record_member("second")
        rc, out = out_of(pass_cmd.jira_synced, self.d, "docs-platform#2", "In progress", self.io, assignee="a1"); self.assertEqual(rc, 0, out)
        story = {"evidence": {}}; o = pass_cmd.Options(build="7", head="aaaaaaaa11111111")
        pass_cmd._apply_story_evidence(story, o, members.current(state.load(self.d / "state.json").data, self.d))
        self.assertEqual((story["evidence"]["deploy"]["variant"], story["evidence"]["deploy"]["by"]), ("myd-1-second", "second"))
        story = {"evidence": {}}; pass_cmd._apply_story_evidence(story, o); self.assertNotIn("variant", story["evidence"]["deploy"])

    def test_status_prints_the_member_line_after_sync_and_reconcile_lists_member_unknown(self):
        self.with_members(); self.record_member("second")
        with mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")):
            rc, out = out_of(reconcile.cli, self.d, status=True); lines = out.splitlines()
            self.assertTrue(lines[0].startswith("SYNC:")); self.assertEqual(lines[1], "MEMBER: second · variant myd-1-second · desk none · board none · board file boards/second.html")
            self.assertNotIn("member_unknown", out)
            rc, out = out_of(reconcile.cli, self.d, status=True, brief=True); self.assertEqual(out.splitlines()[1], "MEMBER: second · variant myd-1-second · desk none · board none · board file boards/second.html")
            rc, out = out_of(reconcile.cli, self.d); self.assertNotIn("MEMBER:", out)
            self.record_member("ghost"); rc, out = out_of(reconcile.cli, self.d, status=True)
            self.assertIn("MEMBER: unknown", out); self.assertIn("epic member_unknown:", out); self.assertIn("→ turnstile attach --epic MYD-1 --github ghost", out)

    def test_board_header_lists_the_members(self):
        self.with_members(); html = board.render_html(self.data())
        self.assertIn('id="members"', html); self.assertIn('"members"', html); self.assertIn("renderMembers", html)

class Reviewer(unittest.TestCase):
    def test_reviewer_defaults_to_opus_high_and_xhigh_is_a_previous_default(self):
        self.assertEqual(models.DEFAULTS["reviewer"], {"model": "opus", "effort": "high"}); self.assertEqual(models.DEFAULTS["story-reviewer"], {"model": "opus", "effort": "xhigh"})
        self.assertIn({"model": "opus", "effort": "xhigh"}, models.PREVIOUS_DEFAULTS["reviewer"])
        frozen = {"epic": {"models": dict(models.defaults(), reviewer={"model": "opus", "effort": "xhigh"})}}
        eff = config.effective(frozen, {})["models"]["reviewer"]; self.assertEqual((eff["effort"], eff["source"]), ("high", "default"))
        lines = config.lines(config.effective(frozen, {})); self.assertIn("models.reviewer = opus:high (default)", lines)
        partial = {"epic": {"models": {"reviewer": {"model": "opus", "effort": "xhigh"}}}}
        eff = config.effective(partial, {})["models"]["reviewer"]; self.assertEqual((eff["effort"], eff["source"]), ("xhigh", "epic"))

if __name__ == "__main__":
    unittest.main()
