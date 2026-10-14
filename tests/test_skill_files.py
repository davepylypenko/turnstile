import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "turnstile"
REFS = SKILL / "references"

def parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "no frontmatter"
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1); out[k.strip()] = v.strip()
    return out

class SkillFiles(unittest.TestCase):
    def test_skill_md_short_with_frontmatter_and_commands(self):
        text = (SKILL / "SKILL.md").read_text(); fm = parse_frontmatter(text)
        self.assertEqual(fm["name"], "turnstile"); self.assertTrue(len(fm["description"]) > 60)
        self.assertLessEqual(len(text.splitlines()), 170)
        for h in ["## init", "## status", "## pass", "## dispatch", "## story-gate", "## plan"]: self.assertIn(h, text)
        for cli in ["turnstile status", "turnstile pass", "! TURNSTILE_LEAD=1 turnstile approve", "turnstile jira-synced", "turnstile plan-submitted",
                    "turnstile brief", "turnstile bug add", "turnstile bug set", "--full", "--companions"]:
            self.assertIn(cli, text, cli)
        self.assertNotIn("you run `turnstile approve", text.lower())
        self.assertIn("-r2", text)  # 2026-10-14 minor 13: a second round gets a new brief name, never --force over the first
    def test_every_reference_link_exists(self):
        for md in [SKILL / "SKILL.md"] + list(REFS.glob("*.md")) + list((REFS / "env").glob("*.md")) + list((REFS / "briefs").glob("*.md")):
            for rel in re.findall(r"`(references/[A-Za-z0-9_./-]+\.md)`", md.read_text()):
                self.assertTrue((SKILL / rel).exists(), "%s links missing %s" % (md.name, rel))
    def test_reference_files_present(self):
        for name in ["lifecycle.md", "kickoff.md", "plan.md", "pr-body.md", "slack.md", "reports.md", "evidence.md", "env/pdffiller-dev.md"]:
            self.assertTrue((REFS / name).exists(), name)
    def test_lifecycle_tables_cover_every_state(self):
        text = (REFS / "lifecycle.md").read_text()
        for k in ["turnstile threads", "self_resolved", "needs_lead"]: self.assertIn(k, text, k)
        skill = (SKILL / "SKILL.md").read_text()
        for k in ["turnstile threads", "self_resolved", "needs_lead"]: self.assertIn(k, skill, k)
        spec = (ROOT / "docs" / "superpowers" / "specs" / "2026-10-13-turnstile-design.md").read_text()
        for k in ["2026-10-14", "self_resolved", "needs_lead", "turnstile threads", "/replies"]: self.assertIn(k, spec, k)
        readme = (ROOT / "README.md").read_text()
        for k in ["turnstile threads", "self_resolved", "needs_lead", "agent_github", "resolve-human-thread", "issue-comment"]: self.assertIn(k, readme, k)
        # lead rule 2026-10-14 (re-request): documented wherever the REWORK return is
        for name, doc in [("lifecycle", text), ("SKILL", skill), ("spec", spec), ("README", readme)]:
            for k in ["requested_reviewers", "--rerequested", "reviewer_notified", "push-only"]: self.assertIn(k, doc, "%s lacks %s" % (name, k))
        for k in ["rerequest-not-authors", "rerequest-copilot", "rerequest-replies"]: self.assertIn(k, readme, k)
        self.assertIn("2026-10-14 (lead, re-request)", spec)
        for s in ["DEV", "AI_REVIEW", "READY", "ON_HUMAN_REVIEW", "REWORK", "APPROVED", "MERGED", "PLANNED", "IN_PROGRESS", "INTEGRATION_REVIEW", "ENV_TESTING", "DONE"]:
            self.assertIn("**" + s + "**", text)
        for k in ["used_at", "rework_since", "human_review: per_pr", "--full", "stories.<S>.branch"]: self.assertIn(k, text, k)
    def test_slack_review_request_format(self):
        text = (REFS / "slack.md").read_text()
        for line in ["Reviewers: <@", "PR: <https://github.com/", "Task description:", "Estimate review: +", "Locales:"]: self.assertIn(line, text)
    def test_reports_has_a_template_per_agent(self):
        text = (REFS / "reports.md").read_text()
        for h in ["## Ticket", "## Review", "## Story review", "## Stack", "## Comments", "## Investigation", "## Env test", "## Deploy"]: self.assertIn(h, text)
    def test_env_recipe_pdffiller(self):
        text = (REFS / "env" / "pdffiller-dev.md").read_text()
        for needle in ["www.pdffillers.com", "jsfillerEnv=desk", "Forward-Variant-pdffiller", "developer_access", "md5", ".pdffillers.com",
                       "never as a request header", "x-server-name", "isolated headless", "+tester"]:
            self.assertIn(needle, text, needle)
        self.assertNotIn("qwe123", text); self.assertNotIn("airslate", text)
