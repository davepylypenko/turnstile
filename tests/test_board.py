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
