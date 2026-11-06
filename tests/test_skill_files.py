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
        self.assertLessEqual(len(text.splitlines()), 190)
        for h in ["## init", "## status", "## pass", "## dispatch", "## story-gate", "## plan"]: self.assertIn(h, text)
        for cli in ["turnstile status", "turnstile pass", "! TURNSTILE_LEAD=1 turnstile approve", "turnstile jira-synced", "turnstile plan-submitted",
                    "turnstile brief", "turnstile bug add", "turnstile bug set", "--full", "--assignee <account_id> --assignee-name", "atlassianUserInfo", "editJiraIssue"]:
            self.assertIn(cli, text, cli)
        self.assertNotIn("you run `turnstile approve", text.lower())
        self.assertIn("-r2", text)  # 2026-10-14 minor 13: a second round gets a new brief name, never --force over the first
    def test_token_discipline_section_and_models_from_the_agent_line(self):
        # lead rules 2026-10-19 / 2026-10-26
        text = (SKILL / "SKILL.md").read_text(); readme = (ROOT / "README.md").read_text()
        self.assertIn("## Token discipline", text)
        for doc in (text, readme):
            for needle in ["2026-10-19", "2026-10-26", "Monitor", "never a cron", "still waiting", "once per head", "P1/P2",
                           "one at a time", "different repositories", "never reads diffs or runs suites" if doc is readme else "never read a diff",
                           "epic.models", "--models", "AGENT:"]:
                self.assertIn(needle, doc, needle)
            self.assertNotIn("xhigh, story-reviewer fable", doc); self.assertNotIn("the rest opus", doc)
        self.assertIn("model=opus effort=xhigh", text); self.assertNotIn("effort=medium", text)
        self.assertIn("reviewer (opus, xhigh)", readme); self.assertIn("story-reviewer (opus, xhigh)", readme); self.assertNotIn("story-reviewer opus high", readme)
    def test_preferences_section_three_layers_and_review_skill_semantics(self):
        text = (SKILL / "SKILL.md").read_text(); readme = (ROOT / "README.md").read_text()
        self.assertIn("## preferences", text); self.assertIn("### Per-person overrides", readme)
        for doc in (text, readme):
            for needle in ["~/.config/turnstile/config.json", "TURNSTILE_USER_CONFIG", "turnstile config list", "config set review_skill=/my-review",
                           "epic.review_skill", "epic.story_review_skill", "--epic", "--deep-review", "gate_check", "never in git"]:
                self.assertIn(needle, doc, needle)
        for doc in (text, readme): self.assertIn("turnstile config apply <ah-id>", doc)
        self.assertIn("one** batched", text); self.assertIn("Never ask what the user file already answers".lower(), text.lower()); self.assertIn("reviewer on sonnet", text)
        self.assertIn("turnstile config set models.reviewer=sonnet:medium", readme); self.assertIn("neither replaces the repo gate", readme)
        for name in ("reviewer", "story-reviewer"):
            agent = (ROOT / "agents" / (name + ".md")).read_text(); brief = (REFS / "briefs" / (name + ".md")).read_text()
            self.assertIn("BLOCKED: review skill", agent); self.assertIn("BLOCKED: review skill", brief)
        self.assertIn("`{{review_skill}}{{review_effort}}` — invoke it as written", (REFS / "briefs" / "reviewer.md").read_text())
        self.assertIn("`{{story_review_skill}}{{review_effort}}` — invoke it as written", (REFS / "briefs" / "story-reviewer.md").read_text())
        for doc in (text, readme): self.assertIn("other skill", doc)
        self.assertIn("resolved effort", text)
        self.assertIn("turnstile config", (ROOT / "templates" / "CLAUDE.md.workspace").read_text())
    def test_attach_and_sync_are_documented(self):
        text = (SKILL / "SKILL.md").read_text(); readme = (ROOT / "README.md").read_text(); ws = (ROOT / "templates" / "CLAUDE.md.workspace").read_text()
        self.assertIn("## attach", text); self.assertIn("## Continuing someone else's epic", readme)
        for doc in (text, readme, ws):
            for needle in ["turnstile sync", "SYNC:", "never rebase", "pushe"]: self.assertIn(needle, doc, needle)
        for doc in (text, readme):
            for needle in ["turnstile attach --epic", "--clone-root", "origin/epic/<key>", "behind origin", "--no-push", "preferences", "pushed",
                           ".workspace.json", "cd <workspace> && claude", "ws/<key"]: self.assertIn(needle, doc, needle)
    def test_init_from_the_clone_root_is_documented(self):
        # 2026-11-03: init runs in the clone root, creates <root>/<key> with a worktree per repo; the lead opens that folder
        text = (SKILL / "SKILL.md").read_text(); readme = (ROOT / "README.md").read_text(); ws = (ROOT / "templates" / "CLAUDE.md.workspace").read_text()
        for doc in (text, readme):
            for needle in ["clone root", "--clone-root", "ws/<key", "origin/<base>", "cd <workspace> && claude", "cannot drive the epic", ".workspace.json", "--var repo=<name>"]:
                self.assertIn(needle, doc, needle)
        for needle in ["← clone root", "← created by init", "worktree ws/myd-1 from origin/develop", "epic.repos.<r>.path", "never from `ws/*`"]: self.assertIn(needle, readme, needle)
        for needle in ["{{repos}}", "{{ws_branch}}", "never from", "--var repo=<name>"]: self.assertIn(needle, ws, needle)
        self.assertIn("{{repo_path}}", (REFS / "briefs" / "implementer.md").read_text()); self.assertIn("never from the worktree's own `ws/*`", (REFS / "briefs" / "implementer.md").read_text())
        for name in ("deployer", "investigator", "tester", "story-reviewer"): self.assertIn("{{repo_paths}}", (REFS / "briefs" / (name + ".md")).read_text(), name)
        for name in ("reviewer", "stack-step", "comments-handler"): self.assertIn("{{repo_path}}", (REFS / "briefs" / (name + ".md")).read_text(), name)
        self.assertIn("parked on `ws/<epic>`", (ROOT / "agents" / "implementer.md").read_text())
    def test_trunk_mode_is_documented(self):
        text = (SKILL / "SKILL.md").read_text(); readme = (ROOT / "README.md").read_text(); plan = (REFS / "plan.md").read_text()
        life = (REFS / "lifecycle.md").read_text(); recipe = (REFS / "env" / "pdffiller-dev.md").read_text()
        self.assertIn("## Trunk mode (one flag per epic)", readme); self.assertIn("## trunk mode", text); self.assertIn("## Feature flag", recipe)
        for doc in (text, readme, life):
            for needle in ["--arm", "control_cases", "--stacked-on", "epic.flag", "MERGED"]: self.assertIn(needle, doc, needle)
        for needle in ["--story-mode trunk", "--base-heads", "`identical`/`ahead`", "epic_branch", "human_review: per_pr", "BLOCKED"]: self.assertIn(needle, readme, needle)
        for needle in ['"mode": "trunk"', '"control_cases": []', "| Mode |", "Control cases"]: self.assertIn(needle, plan, needle)
        self.assertIn("BLOCKED: no flag toggle", recipe)
        for name in ("tester", "implementer"):
            self.assertIn("{{flag}}", (REFS / "briefs" / (name + ".md")).read_text(), name)
        self.assertIn("{{arm}}", (REFS / "briefs" / "tester.md").read_text())
        self.assertIn("BLOCKED: no flag toggle", (ROOT / "agents" / "tester.md").read_text()); self.assertIn("flag off", (ROOT / "agents" / "implementer.md").read_text())
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
        for k in ["rework_since", "human_review: per_pr", "--full", "stories.<S>.branch"]: self.assertIn(k, text, k)
    def test_slack_review_request_format(self):
        text = (REFS / "slack.md").read_text()
        for line in ["Reviewers: <@", "PR: <https://github.com/", "Task description:", "Estimate review: +", "Locales:"]: self.assertIn(line, text)
    def test_slack_sends_are_recorded_not_gated(self):
        # 2026-11-05 (lead's decision): the lead's word in chat is the only gate on a Slack send; the plugin records and never blocks
        docs = {name: (path).read_text() for name, path in [("README", ROOT / "README.md"), ("SKILL", SKILL / "SKILL.md"), ("slack", REFS / "slack.md"),
                                                            ("lifecycle", REFS / "lifecycle.md"), ("workspace", ROOT / "templates" / "CLAUDE.md.workspace")]}
        for name, doc in docs.items():
            self.assertIn("lead's word in chat", doc, name); self.assertIn("never blocks", doc, name)
            for stale in ["guard_slack", "--companions", "--approved <ah-id>` (READY", "Slack stays lead-approved", "Slack messages always wait for the lead",
                          "permissionDecision", "one send per approval", "One approval = one message", "`send` on READY", "opens `send`", "block sends"]:
                self.assertNotIn(stale, doc, "%s still says %r" % (name, stale))
        for name in ("README", "SKILL", "lifecycle"):
            self.assertIn("--slack <permalink> --reviewers", docs[name], name)
        for path in (ROOT / "agents").glob("*.md"):
            self.assertNotIn("Slack stays lead-approved", path.read_text(), path.name)
    def test_send_skill_is_a_reference_to_a_local_skill(self):
        # 2026-11-06 (lead's decision): the send skill lives on the developer's machine; the plugin names it, never copies it
        docs = {name: path.read_text() for name, path in [("README", ROOT / "README.md"), ("SKILL", SKILL / "SKILL.md"), ("slack", REFS / "slack.md"),
                                                          ("lifecycle", REFS / "lifecycle.md"), ("workspace", ROOT / "templates" / "CLAUDE.md.workspace")]}
        for name, doc in docs.items():
            self.assertIn("send_skill", doc, name); self.assertIn("/send-pr-review", doc, name); self.assertIn("lead's word in chat", doc, name)
        for name in ("README", "SKILL", "slack", "lifecycle"):
            self.assertIn("explicit channel wins", docs[name], name)
        for name in ("README", "SKILL", "slack"):
            self.assertIn("which skill to install or use", docs[name], name)
        for name in ("README", "slack"):
            self.assertIn("ln -s <", docs[name], name); self.assertIn("playground/zolotukhin-ivan/skills/send-pr-review", docs[name], name); self.assertIn("~/.claude/skills/send-pr-review", docs[name], name)
        self.assertIn("config set send_skill=/my-send", docs["SKILL"]); self.assertIn("SEND_SKILL:", docs["SKILL"]); self.assertIn("WARN: send skill", docs["SKILL"])
        self.assertIn("turnstile config set send_skill=/my-send", docs["README"]); self.assertIn("`send_skill`", docs["README"])
        self.assertFalse(any((ROOT / "skills").rglob("send-pr-review*")), "Ivan's skill must not be copied into the plugin")
        self.assertNotIn("CODEOWNERS", docs["slack"])
        for name, doc in docs.items():
            self.assertNotIn("ln -s <clone>", doc, name)
        self.assertRegex(docs["README"], r"`ln -s <pdffiller-knowledge clone>/playground/zolotukhin-ivan/skills/send-pr-review ~/.claude/skills/send-pr-review`")
        self.assertIn("review skill, send skill and models", docs["README"])
        for layout in ["~/.claude/commands/<name>.md", "commands/<name>.md", "CLAUDE_CONFIG_DIR", "epic or default"]:
            self.assertIn(layout, docs["README"], layout)
    def test_reports_has_a_template_per_agent(self):
        text = (REFS / "reports.md").read_text()
        for h in ["## Ticket", "## Review", "## Story review", "## Stack", "## Comments", "## Investigation", "## Env test", "## Deploy"]: self.assertIn(h, text)
    def test_env_recipe_pdffiller(self):
        text = (REFS / "env" / "pdffiller-dev.md").read_text()
        for needle in ["www.pdffillers.com", "jsfillerEnv=desk", "Forward-Variant-pdffiller", "developer_access", "md5", ".pdffillers.com",
                       "never as a request header", "x-server-name", "isolated headless", "+tester"]:
            self.assertIn(needle, text, needle)
        self.assertNotIn("qwe123", text); self.assertNotIn("airslate", text)
    def test_tester_brief_and_recipe_name_the_password_sources_not_the_password(self):
        brief = (REFS / "briefs" / "tester.md").read_text(); recipe = (REFS / "env" / "pdffiller-dev.md").read_text(); skill = (SKILL / "SKILL.md").read_text()
        self.assertIn("{{test_user}}", brief); self.assertIn("TURNSTILE_TEST_PASSWORD", brief); self.assertNotIn("Credentials: in your launch prompt", brief)
        self.assertIn("## Credentials", recipe); self.assertIn("TURNSTILE_TEST_PASSWORD", recipe); self.assertIn("security add-generic-password", recipe)
        self.assertNotIn("test credentials to the prompt", skill); self.assertIn("TURNSTILE_TEST_PASSWORD", skill)
        for t in (brief, recipe, skill): self.assertNotIn("qwe123", t); self.assertNotIn("airslate", t)
