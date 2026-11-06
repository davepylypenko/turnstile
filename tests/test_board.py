import json, pathlib, tempfile, unittest
from turnstile_cli import board

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())

class Board(unittest.TestCase):
    def test_render_embeds_state_and_updated(self):
        d = pathlib.Path(tempfile.mkdtemp())
        out = board.render(FIX, d)
        html = out.read_text()
        self.assertEqual(out, d / "board.html")
        self.assertIn('"jsfiller#1"', html)
        self.assertNotIn("__TURNSTILE_STATE__", html)
        self.assertNotIn("__TURNSTILE_UPDATED__", html)
        self.assertIn("<title>", html)
        self.assertIn("prefers-color-scheme: dark", html)
    def test_trunk_story_shows_mode_flag_and_arm_results(self):
        d = pathlib.Path(tempfile.mkdtemp()); html = board.render(FIX, d).read_text()
        for needle in ["s.mode === 'trunk'", "trunk · flag", "lastArm('treatment')", "lastArm('control')", "not_testable_here"]: self.assertIn(needle, html, needle)
        self.assertIn("'env ' + runMark(e.env_test)", html)
    def test_tiles_filter_the_tables_and_deep_link_by_hash(self):
        # 2026-11-06: the status tiles are buttons that filter the PR table (or the bug list to open bugs); the selection lives in location.hash
        d = pathlib.Path(tempfile.mkdtemp()); html = board.render(FIX, d).read_text()
        for s in ('data-tile="REWORK"', 'data-tile="bugs"', 'data-tile="awaiting"', 'aria-pressed="false"', "b.setAttribute('aria-pressed', on ? 'true' : 'false')",
                  "b.disabled = !n[k] && !on", "Showing ' + esc(view.state) + ' only", 'id="show-all"', "addEventListener('hashchange', applyHash)",
                  "history.replaceState(null, ''", "'&state=' + view.state", "'&open=1'", "new URLSearchParams(location.hash.slice(1))", "if (location.hash) applyHash()",
                  "button.tile { font:inherit; text-align:left; color:inherit; cursor:pointer }", ".tile:disabled { opacity:.6; cursor:default }",
                  '.tile[aria-pressed="true"] { border-color:var(--accent) }', '.tile[aria-pressed="true"] b { color:var(--accent) }',
                  "!view.state || p.state === view.state", "!view.open || bugState(b) !== 'done'", "view.tab = b.dataset.tab; show(); writeHash();"):
            self.assertIn(s, html, s)
        self.assertEqual(html.count('<button type="button" class="tile" data-tile="'), 10)
        # aria-pressed only on the tiles that toggle a filter: the Stories and Awaiting humans tiles switch tabs
        self.assertEqual(html.count('aria-pressed="false"'), 8)
        self.assertIn('<button type="button" class="tile" data-tile="stories"><b>', html); self.assertIn('<button type="button" class="tile" data-tile="awaiting"><b>', html)
        self.assertIn("if (b.hasAttribute('aria-pressed')) b.setAttribute('aria-pressed', on ? 'true' : 'false')", html)
        self.assertIn("""view.state = null; show(); writeHash(); document.querySelector('.tabs button[data-tab="prs"]').focus();""", html)
        self.assertIn("""'<p class="filter">Showing open bugs only · <a href="#" id="show-all-bugs">show all</a></p>'""", html)
        self.assertIn("""view.open = false; show(); writeHash(); document.querySelector('.tabs button[data-tab="bugs"]').focus();""", html)
        self.assertIn("<button role=\"tab\" aria-selected=\"true\" data-tab=\"prs\" class=\"on\">PRs</button><button role=\"tab\" aria-selected=\"false\" data-tab=\"stories\">", html)
    def test_json_is_script_safe(self):
        d = pathlib.Path(tempfile.mkdtemp())
        data = json.loads(json.dumps(FIX)); data["bugs"] = [{"id": "b1", "title": "</script><b>x", "state": "todo", "story": "S1", "source": "", "pr": "", "note": ""}]
        html = board.render(data, d).read_text()
        self.assertNotIn("</script><b>x", html)
        self.assertIn("\\u003c/script>", html)
    def test_html_comment_opener_and_link_values_are_inert(self):
        d = pathlib.Path(tempfile.mkdtemp())
        data = json.loads(json.dumps(FIX)); data["epic"]["key"] = "<!--<script>"
        html = board.render(data, d).read_text()
        self.assertNotIn("<!--<script>", html)
        tpl = board.TEMPLATE.read_text()
        self.assertIn("esc(prUrl(id))", tpl); self.assertIn("esc(prUrl(b.pr))", tpl)
        self.assertIn("/^https:\\/\\//.test(h.slack_permalink", tpl)
    def test_legend_note_colours_and_tabs(self):
        tpl = board.TEMPLATE.read_text()
        for s in ("need the lead", "a.thread", "self-resolved threads"):
            self.assertIn(s, tpl, s)
        # lead rule 2026-10-14 (re-request): a push-only return to humans pings nobody and says so; a thread-driven one names the re-request
        for s in ("h.reviewer_notified === false", "reviewers not notified (push-only rework: the lead decides)", "'re-requested ' + ", "re-request the thread authors"):
            self.assertIn(s, tpl, s)
        # 2026-11-06: the Jira cell names the recorded assignee (name, else the account id) or reads "unassigned" in the muted style
        for s in ("esc(a.name || a.account_id)", "<span class=\"muted\">· unassigned</span>", "jiraAssignee(p)"):
            self.assertIn(s, tpl, s)
        for s in ("Jira mapping", "reviewer not notified", "role=\"tablist\"", "aria-selected", "PLANNED:'var(--planned)'", "todo:'var(--todo)'",
                  "(r.cases || {}).fail", "<th>Note</th>", "--merged:#4b5563",
                  "a.type !== 'send' && !a.approved_at", "a.type === 'send' ? '<span class=\"muted\">legacy send entry</span>'"):
            self.assertIn(s, tpl, s)
        d = pathlib.Path(tempfile.mkdtemp())
        data = json.loads(json.dumps(FIX)); data["stories"]["S1"]["evidence"] = {"env_test": {"report": "r"}}
        self.assertIn('"env_test"', board.render(data, d).read_text())
