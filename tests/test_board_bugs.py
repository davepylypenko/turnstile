import json, pathlib, unittest
from turnstile_cli import board

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())

class BoardBugs(unittest.TestCase):
    def html(self):
        data = json.loads(json.dumps(FIX))
        data["bugs"] = [{"id": "b01", "story": "S1", "title": "Share visible", "source": "tester", "pr": "jsfiller#13384", "figma": "F:1", "state": "todo", "note": "", "created_at": "x"}]
        return board.render_html(data)
    def test_overlay_wiring(self):
        html = self.html()
        for needle in ["claude.use('db')", "claude.use('user')", "user.can('data.write')", "db.collection('bugs').onSnapshot(",
                       "bugsDb.doc('bugs/' + id).set({", 'data-bug="', "const BUG_STATES = ['todo', 'ai', 'testing', 'done']",
                       "BUG_STATES.includes(", "typeof window.claude.use === 'function'", "<th>Figma</th>"]:
            self.assertIn(needle, html, needle)
    def test_select_disabled_without_write(self):
        self.assertIn("(bugsCanWrite ? '' : ' disabled title=\"Status changes are saved by the board owner\"')", self.html())
    def test_override_loses_to_a_newer_state_json_bug(self):
        # 2026-10-14 finding 6: a db status older than the bug's updated_at in state.json loses; the newer one renders
        html = self.html()
        self.assertIn("const ts = s =>", html)
        self.assertIn("ts(o.updatedAt) > ts(b.updated_at || b.created_at)", html)
        self.assertNotIn("bugOverrides[b.id] && BUG_STATES.includes(bugOverrides[b.id].status)) ? bugOverrides[b.id].status : b.state", html)
    def test_awaiting_tile_counts_only_open_entries(self):
        self.assertIn("filter(a => !a.approved_at && !a.voided_at && !a.consumed_at).length", self.html())
    def test_snapshot_does_not_destroy_an_open_dropdown(self):
        html = self.html()
        self.assertIn("document.activeElement", html); self.assertIn("matches('select.bug')", html); self.assertIn("renderPending", html)
    def test_case_column(self):
        self.assertIn("<th>Case</th>", self.html())
    def test_legend_mentions_bug_states_and_fold_back(self):
        html = self.html(); self.assertIn("turnstile bug set", html); self.assertIn("todo → ai", html)
