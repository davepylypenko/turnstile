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
    def test_legend_mentions_bug_states_and_fold_back(self):
        html = self.html(); self.assertIn("turnstile bug set", html); self.assertIn("todo → ai", html)
