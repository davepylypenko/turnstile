import contextlib, io, json, pathlib, re, shutil, tempfile, unittest
from turnstile_cli import brief_cmd
from tests.test_pass import FakeIO

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"
BRIEFS = ROOT / "skills" / "turnstile" / "references" / "briefs"
def placeholders(text): return sorted(set(brief_cmd.PLACEHOLDER.findall(text)))

class Templates(unittest.TestCase):
    def test_one_template_per_agent_with_required_placeholders(self):
        self.assertEqual(sorted(p.stem for p in BRIEFS.glob("*.md")), sorted(p.stem for p in (ROOT / "agents").glob("*.md")))
        for p in BRIEFS.glob("*.md"):
            ph = placeholders(p.read_text())
            self.assertIn("report_path", ph, p.name); self.assertIn("epic_key", ph, p.name)
    def test_builtins_name_the_skill_dir_for_references(self):
        b = brief_cmd.builtins({"epic": {}}, pathlib.Path("/tmp/d"), "tester", "X")
        self.assertEqual(b["skill_dir"], str(ROOT / "skills" / "turnstile")); self.assertTrue((pathlib.Path(b["skill_dir"]) / "references" / "tools" / "figma.md").exists())
        tpl = (BRIEFS / "tester.md").read_text(); self.assertIn("{{skill_dir}}/references/tools/figma.md", tpl); self.assertIn("{{skill_dir}}/{{env_recipe}}", tpl)
    def test_render_reports_missing(self):
        self.assertEqual(brief_cmd.render("a {{x}} b {{y}} {{x}}", {"x": "1"}), ("a 1 b {{y}} 1", ["y"]))

class Run(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir(); (self.d / "briefs").mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch(); self.io = FakeIO()
    def run_brief(self, agent, name, var, force=False):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = brief_cmd.run(self.d, agent, name, var, force=force, io=self.io)
        return rc, buf.getvalue()
    def all_vars(self, agent):
        builtin = brief_cmd.builtins(json.loads(FIX.read_text()), self.d, agent, "X")
        return ["%s=v-%s" % (p, p) for p in placeholders((BRIEFS / (agent + ".md")).read_text()) if p not in builtin]
    def test_every_template_renders_with_builtins_plus_vars(self):
        for p in BRIEFS.glob("*.md"):
            rc, out = self.run_brief(p.stem, "T-" + p.stem, self.all_vars(p.stem)); self.assertEqual(rc, 0, out)
            text = (self.d / "briefs" / ("T-" + p.stem + ".md")).read_text()
            self.assertEqual(placeholders(text), [], p.name); self.assertIn("MYD-1", text); self.assertIn("reports/T-" + p.stem + ".md", text)
            self.assertIn("AGENT: turnstile:" + p.stem, out); self.assertIn("PROMPT: Read and execute", out)
        self.assertEqual(len(self.io.commits), 8); self.assertIn("brief T-tester for tester", (self.d / "ledger.md").read_text())
    def test_brief_refuses_unfilled_placeholder(self):
        rc, out = self.run_brief("tester", "ENV-S1", [])
        self.assertEqual(rc, 2); self.assertIn("MISSING placeholder", out)
        self.assertFalse((self.d / "briefs" / "ENV-S1.md").exists()); self.assertEqual(self.io.commits, [])
    def test_refuses_unknown_agent_bad_name_and_existing_brief(self):
        self.assertEqual(self.run_brief("nobody", "N", [])[0], 2)
        self.assertEqual(self.run_brief("investigator", "../x", self.all_vars("investigator"))[0], 2)
        self.run_brief("investigator", "I", self.all_vars("investigator"))
        rc, out = self.run_brief("investigator", "I", self.all_vars("investigator")); self.assertEqual(rc, 2); self.assertIn("--force", out)
        self.assertEqual(self.run_brief("investigator", "I", self.all_vars("investigator"), force=True)[0], 0)
    def test_builtins(self):
        b = brief_cmd.builtins(json.loads(FIX.read_text()), self.d, "tester", "ENV-S1")
        self.assertEqual((b["report_path"], b["variant"], b["desk"], b["env_recipe"], b["github_org"]), ("reports/ENV-S1.md", "v1", "desk05", "", "pdffiller"))
        self.assertTrue(pathlib.Path(b["delivery"]).is_absolute())
