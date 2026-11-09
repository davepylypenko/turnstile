import json, os, pathlib, shutil, subprocess, tempfile, unittest
from unittest import mock
from turnstile_cli import board, config, config_cmd, members, state as st_mod

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())

def _delivery(epic: dict, plan: str = "", briefs: dict = None) -> pathlib.Path:
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "state.json").write_text(json.dumps({"epic": epic, "prs": {}, "stories": {}}))
    if plan:
        (d / "plan.md").write_text(plan)
    for name, text in (briefs or {}).items():
        (d / "briefs").mkdir(exist_ok=True); (d / "briefs" / name).write_text(text)
    return d

def _user_cfg() -> dict:
    return {"TURNSTILE_USER_CONFIG": str(pathlib.Path(tempfile.mkdtemp()) / "config.json")}

class JiraBaseUrl(unittest.TestCase):
    def test_migration_derives_the_site_from_a_plan_browse_link(self):
        d = _delivery({"key": "E"}, plan="see https://acme.atlassian.net/browse/MYD-12 for the epic")
        self.assertEqual(st_mod.load(d / "state.json").data["epic"]["jira_base_url"], "https://acme.atlassian.net")
    def test_migration_derives_the_site_from_a_brief(self):
        d = _delivery({"key": "E"}, plan="no links", briefs={"a.md": "ticket https://other.atlassian.net/browse/AB-3"})
        self.assertEqual(st_mod.load(d / "state.json").data["epic"]["jira_base_url"], "https://other.atlassian.net")
    def test_migration_falls_back_to_the_default(self):
        d = _delivery({"key": "E"}, plan="https://example.com/browse/MYD-1 is not Jira")
        self.assertEqual(st_mod.load(d / "state.json").data["epic"]["jira_base_url"], "https://pdffiller.atlassian.net")
    def test_migration_keeps_an_existing_value(self):
        d = _delivery({"key": "E", "jira_base_url": "https://kept.atlassian.net"}, plan="https://acme.atlassian.net/browse/MYD-12")
        self.assertEqual(st_mod.load(d / "state.json").data["epic"]["jira_base_url"], "https://kept.atlassian.net")
    def test_config_set_round_trips_in_the_user_layer_and_wins_over_the_epic(self):
        env = _user_cfg(); cfg = pathlib.Path(env["TURNSTILE_USER_CONFIG"])
        with mock.patch.dict(os.environ, env):
            self.assertEqual(config_cmd.set_(None, "jira_base_url=https://mine.atlassian.net/"), 0)
            self.assertEqual(json.loads(cfg.read_text())["jira_base_url"], "https://mine.atlassian.net")
            data = {"epic": {"jira_base_url": "https://epic.atlassian.net"}}
            self.assertEqual(config.jira_base_url(data), "https://mine.atlassian.net")
            self.assertEqual(config_cmd.set_(None, "jira_base_url=default"), 0)
            self.assertEqual(config.jira_base_url(data), "https://epic.atlassian.net")
            self.assertEqual(config.jira_base_url({"epic": {}}), "https://pdffiller.atlassian.net")
    def test_config_set_refuses_a_non_https_value(self):
        with mock.patch.dict(os.environ, _user_cfg()):
            self.assertEqual(config_cmd.set_(None, "jira_base_url=javascript:alert(1)"), 2)
    def test_key_is_listed_and_normalised(self):
        self.assertIn("jira_base_url", config.KEYS_HELP)
        self.assertEqual(config.parse_value("jira_base_url", " https://a.atlassian.net/ "), "https://a.atlassian.net")

class BoardLinks(unittest.TestCase):
    def render(self, data):
        return board.render(data, pathlib.Path(tempfile.mkdtemp())).read_text()
    def data(self):
        d = json.loads(json.dumps(FIX)); d["epic"]["jira_base_url"] = "https://acme.atlassian.net"
        return d
    def test_state_carries_the_base_in_the_full_board_and_every_member_board(self):
        d = self.data(); d["epic"]["members"] = {"alice": members.new_entry("Alice", None, None, None)}
        files = board.render_files(d)
        self.assertGreater(len(files), 1)
        for rel, html in files.items():
            self.assertIn('"jira_base_url": "https://acme.atlassian.net"', html, rel)
    def test_render_injects_the_effective_base_when_state_has_none(self):
        d = json.loads(json.dumps(FIX)); d["epic"].pop("jira_base_url", None)
        with mock.patch.dict(os.environ, _user_cfg()):
            self.assertIn('"jira_base_url": "https://pdffiller.atlassian.net"', self.render(d))
    def test_template_links_pr_story_bug_awaiting_and_progress_tickets(self):
        tpl = board.TEMPLATE.read_text()
        for s in ("'/browse/' + k", "ticket(p.ticket)", "tickets(s)", "ticket(b.ticket)", "ticket(r.p.ticket)", "ticket(a.ticket || STATE.prs[a.pr].ticket)",
                  "target=\"_blank\" rel=\"noopener\">' + esc(k)"):
            self.assertIn(s, tpl, s)
        self.assertNotIn("esc(p.ticket)", tpl)
        self.assertIn("esc(b.title)", tpl); self.assertIn("esc(s.title)", tpl)
        self.assertNotIn("ticket(s.title)", tpl); self.assertNotIn("ticket(b.title)", tpl)
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_ticket_helper_links_keys_only(self):
        tpl = board.TEMPLATE.read_text()
        lines = [l for l in tpl.splitlines() if l.startswith(("const esc =", "const jiraBase =", "const ticket =", "const tickets ="))]
        self.assertEqual(len(lines), 4)
        script = "\n".join(["var STATE = {epic: {jira_base_url: 'https://acme.atlassian.net/'}};"] + lines + [
            "console.log(JSON.stringify([ticket('MYD-12'), ticket('not a key'), ticket('Fix MYD-12 login'), tickets({tickets: ['A1-2', 'BB-3']}), ticket(null)]));"])
        out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out[0], '<a href="https://acme.atlassian.net/browse/MYD-12" target="_blank" rel="noopener">MYD-12</a>')
        self.assertEqual(out[1], "not a key"); self.assertEqual(out[2], "Fix MYD-12 login")
        self.assertEqual(out[3].count("/browse/"), 2); self.assertIn("BB-3", out[3]); self.assertEqual(out[4], "")
        script = script.replace("https://acme.atlassian.net/", "javascript:alert(1)")
        out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out[0], "MYD-12")
