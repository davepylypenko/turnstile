import datetime, pathlib, tempfile, unittest
from turnstile_cli import ledger

class Ledger(unittest.TestCase):
    def test_creates_and_appends(self):
        d = pathlib.Path(tempfile.mkdtemp())
        when = datetime.datetime(2026, 10, 13, 12, 0)
        ledger.append(d, "pass jsfiller#1 AI_REVIEW → READY (head aaaaaaaa)", when)
        ledger.append(d, "second", when)
        text = (d / "ledger.md").read_text()
        self.assertTrue(text.startswith("# Ledger\n"))
        self.assertIn("- 2026-10-13 12:00 UTC pass jsfiller#1 AI_REVIEW → READY (head aaaaaaaa)\n", text)
        self.assertTrue(text.endswith("- 2026-10-13 12:00 UTC second\n"))
