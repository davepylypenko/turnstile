import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"
EXPECTED = {"implementer": ("sonnet", None), "reviewer": ("opus", "xhigh"), "story-reviewer": ("fable", None), "stack-step": ("opus", None),
            "comments-handler": ("opus", None), "investigator": ("opus", None), "tester": ("opus", None), "deployer": ("sonnet", None)}
SECTIONS = ["## Role", "## Procedure", "## Cannot", "## Report", "## Common rules"]
COMMON = ["Poll every 2 minutes or less", "never silent for more than 5 minutes", "reports/", "8 lines", "no subagents", "TURNSTILE_LEAD"]
FORBIDDEN_TOOLS = ["slack_send_message", "slack_send_message_draft", "slack_schedule_message", "transitionJiraIssue", "Agent"]

def parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "no frontmatter"
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1); out[k.strip()] = v.strip()
    return out

class Agents(unittest.TestCase):
    def test_all_eight_exist_with_expected_model_and_effort(self):
        self.assertEqual(sorted(p.stem for p in AGENTS.glob("*.md")), sorted(EXPECTED))
        for name, (model, effort) in EXPECTED.items():
            fm = parse_frontmatter((AGENTS / (name + ".md")).read_text())
            self.assertEqual(fm["name"], name); self.assertEqual(fm["model"], model, name); self.assertEqual(fm.get("effort"), effort, name)
            self.assertTrue(len(fm["description"]) > 40, name); self.assertIn("tools", fm, name)
    def test_sections_and_common_rules(self):
        for p in AGENTS.glob("*.md"):
            text = p.read_text()
            for s in SECTIONS: self.assertIn(s, text, "%s lacks %s" % (p.name, s))
            for c in COMMON: self.assertIn(c, text, "%s lacks common rule %r" % (p.name, c))
    def test_no_forbidden_tools(self):
        for p in AGENTS.glob("*.md"):
            tools = [x.strip() for x in parse_frontmatter(p.read_text())["tools"].split(",")]
            for t in FORBIDDEN_TOOLS: self.assertNotIn(t, tools, "%s allows %s" % (p.name, t))
    def test_role_specific_tools(self):
        fm = parse_frontmatter((AGENTS / "investigator.md").read_text()); self.assertNotIn("Edit", fm["tools"]); self.assertNotIn("Write", fm["tools"])
        fm = parse_frontmatter((AGENTS / "tester.md").read_text())
        for t in ["mcp__claude_ai_Figma__get_screenshot", "mcp__claude_ai_Figma__get_design_context", "mcp__claude_ai_Figma__get_variable_defs"]: self.assertIn(t, fm["tools"])
        self.assertNotIn("Edit", fm["tools"])
        self.assertIn("Skill", parse_frontmatter((AGENTS / "deployer.md").read_text())["tools"])
