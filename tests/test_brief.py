import contextlib, io, json, os, pathlib, re, shutil, tempfile, unittest
from unittest import mock
from turnstile_cli import brief_cmd
from tests.test_pass import FakeIO

_env = mock.patch.dict(os.environ, {"TURNSTILE_USER_CONFIG": os.path.join(tempfile.mkdtemp(), "none.json")})
def setUpModule(): _env.start()
def tearDownModule(): _env.stop()

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
    def test_round_mode_comes_from_the_brief_name(self):
        self.assertEqual(brief_cmd.round_mode("REVIEW-7"), "round 1 — full review")
        self.assertIn("round 2 — delta review", brief_cmd.round_mode("REVIEW-7-r2")); self.assertIn("round 13 — delta", brief_cmd.round_mode("STORY-S1-review-r13"))
        self.assertEqual(brief_cmd.round_mode("REVIEW-7-r1"), "round 1 — full review"); self.assertEqual(brief_cmd.round_mode("FIX-3-r2-slug"), "round 1 — full review")
        b = brief_cmd.builtins({"epic": {}}, pathlib.Path("/tmp/d"), "reviewer", "REVIEW-7-r3"); self.assertTrue(b["round_mode"].startswith("round 3 — delta review"))
        for agent in ("reviewer", "story-reviewer"):
            tpl = (BRIEFS / (agent + ".md")).read_text(); self.assertIn("## Round mode", tpl); self.assertIn("{{round_mode}}", tpl); self.assertIn("≤ 80 tool calls", tpl)
        self.assertIn("gate-runner", (BRIEFS / "reviewer.md").read_text())
    def test_gate_runner_brief_placeholders(self):
        ph = placeholders((BRIEFS / "gate-runner.md").read_text())
        for k in ("pr_id", "head", "repo", "repo_path", "base_branch", "gate", "gate_skill", "previous_reports", "scope"): self.assertIn(k, ph, k)
    def test_every_brief_waits_with_one_blocking_command(self):
        for p in BRIEFS.glob("*.md"):
            text = p.read_text(); self.assertIn("ONE blocking command", text, p.name); self.assertIn("600000 ms", text, p.name); self.assertNotIn("Poll ≤ 2 min", text, p.name)
    def test_render_reports_missing(self):
        self.assertEqual(brief_cmd.render("a {{x}} b {{y}} {{x}}", {"x": "1"}), ("a 1 b {{y}} 1", ["y"]))

class Run(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir(); (self.d / "briefs").mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch(); self.io = FakeIO()
        self.approve_plan()
    def approve_plan(self, approved=True):
        from turnstile_cli import state
        (self.d / "plan.md").write_text("# plan\n"); digest = state.digest("# plan\n")
        d = json.loads((self.d / "state.json").read_text()); d["epic"]["plan"] = {"path": "plan.md", "submitted_at": "x", "digest": digest}
        d["awaiting_human"] = [{"id": "ah-1", "owner": "lead", "type": "plan", "payload": "plan.md", "digest": digest, "created_at": "x",
                                "approved_at": "2026-10-13T10:00Z" if approved else None, "approved_via": "lead-terminal"}]
        (self.d / "state.json").write_text(state.dumps(d))
    def run_brief(self, agent, name, var, force=False):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = brief_cmd.run(self.d, agent, name, var, force=force, io=self.io)
        return rc, buf.getvalue()
    def all_vars(self, agent):
        builtin = brief_cmd.builtins(json.loads(FIX.read_text()), self.d, agent, "X")
        return [("repo_path=" + str(self.d.parent)) if p == "repo_path" else "%s=v-%s" % (p, p) for p in placeholders((BRIEFS / (agent + ".md")).read_text()) if p not in builtin]
    def test_every_template_renders_with_builtins_plus_vars(self):
        for p in BRIEFS.glob("*.md"):
            rc, out = self.run_brief(p.stem, "T-" + p.stem, self.all_vars(p.stem)); self.assertEqual(rc, 0, out)
            text = (self.d / "briefs" / ("T-" + p.stem + ".md")).read_text()
            self.assertEqual(placeholders(text), [], p.name); self.assertIn("MYD-1", text); self.assertIn("reports/T-" + p.stem + ".md", text)
            self.assertIn("AGENT: turnstile:" + p.stem, out); self.assertIn("PROMPT: Read and execute", out)
        self.assertEqual(len(self.io.commits), 9); self.assertIn("brief T-tester for tester", (self.d / "ledger.md").read_text())
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
    def test_no_agent_but_the_investigator_starts_before_the_plan_is_approved(self):
        # round 2 R2-11 (spec §4.1 "no agent starts"): a brief is the start of an agent
        self.approve_plan(approved=False)
        for agent in ("tester", "implementer", "reviewer", "deployer", "comments-handler", "stack-step", "story-reviewer", "gate-runner"):
            rc, out = self.run_brief(agent, "X-" + agent, self.all_vars(agent))
            self.assertEqual(rc, 2, agent); self.assertIn("plan", out); self.assertFalse((self.d / "briefs" / ("X-%s.md" % agent)).exists())
        self.assertEqual(self.io.commits, [])
        self.assertEqual(self.run_brief("investigator", "I", self.all_vars("investigator"))[0], 0)
        self.approve_plan(); (self.d / "plan.md").write_text("# plan\nedited\n")  # an edited plan voids the approval
        rc, out = self.run_brief("tester", "T", self.all_vars("tester")); self.assertEqual(rc, 2); self.assertIn("changed", out)
        self.approve_plan(); self.assertEqual(self.run_brief("tester", "T", self.all_vars("tester"))[0], 0)
    def test_agent_line_carries_the_resolved_model_and_effort(self):
        # lead rules 2026-10-19 / 2026-10-26: the orchestrator passes model/effort from this line, never its own choice
        from turnstile_cli import state
        rc, out = self.run_brief("reviewer", "REVIEW-1", self.all_vars("reviewer")); self.assertEqual(rc, 0)
        self.assertIn("AGENT: turnstile:reviewer model=opus effort=xhigh\n", out)  # no epic.models in the fixture: defaults
        self.assertIn("Deep review skill: `/code-review xhigh` — invoke it as written", (self.d / "briefs" / "REVIEW-1.md").read_text())
        rc, out = self.run_brief("implementer", "MYD-10", self.all_vars("implementer")); self.assertIn("AGENT: turnstile:implementer model=sonnet\n", out)
        rc, out = self.run_brief("investigator", "I", self.all_vars("investigator")); self.assertIn("AGENT: turnstile:investigator model=haiku\n", out)
        rc, out = self.run_brief("story-reviewer", "STORY-S1-review", self.all_vars("story-reviewer")); self.assertIn("model=opus effort=xhigh\n", out)
        self.assertIn("Story review skill: `/code-review xhigh` — invoke it as written", (self.d / "briefs" / "STORY-S1-review.md").read_text())
        d = json.loads((self.d / "state.json").read_text()); d["epic"]["models"] = {"reviewer": {"model": "opus", "effort": "high"}, "implementer": {"model": "haiku", "effort": "low"}}
        (self.d / "state.json").write_text(state.dumps(d))
        rc, out = self.run_brief("reviewer", "REVIEW-1-r2", self.all_vars("reviewer")); self.assertIn("AGENT: turnstile:reviewer model=opus effort=high\n", out)
        text = (self.d / "briefs" / "REVIEW-1-r2.md").read_text(); self.assertIn("Deep review skill: `/code-review high`", text); self.assertNotIn("xhigh", text)
        rc, out = self.run_brief("implementer", "MYD-11", self.all_vars("implementer")); self.assertIn("AGENT: turnstile:implementer model=haiku effort=low\n", out)
        rc, out = self.run_brief("deployer", "DEPLOY-x", self.all_vars("deployer")); self.assertIn("AGENT: turnstile:deployer model=sonnet\n", out)
        rc, out = self.run_brief("gate-runner", "GATE-1", self.all_vars("gate-runner")); self.assertIn("AGENT: turnstile:gate-runner model=sonnet\n", out)
        rc, out = self.run_brief("reviewer", "REVIEW-9-r2", self.all_vars("reviewer")); self.assertEqual(rc, 0, out)
        self.assertIn("This brief: round 2 — delta review", (self.d / "briefs" / "REVIEW-9-r2.md").read_text())
    def test_tester_and_implementer_briefs_carry_the_epic_flag_and_the_arm(self):
        from turnstile_cli import state
        rc, out = self.run_brief("tester", "ENV-S1", self.all_vars("tester")); self.assertEqual(rc, 0, out)
        text = (self.d / "briefs" / "ENV-S1.md").read_text(); self.assertIn("Feature flag: `none` · arm: `treatment`", text)
        d = json.loads((self.d / "state.json").read_text()); d["epic"]["flag"] = "pwr-l2f-funnel"; (self.d / "state.json").write_text(state.dumps(d))
        rc, out = self.run_brief("tester", "ENV-S1-control", self.all_vars("tester") + ["arm=control"]); self.assertEqual(rc, 0, out)
        text = (self.d / "briefs" / "ENV-S1-control.md").read_text(); self.assertIn("Feature flag: `pwr-l2f-funnel` · arm: `control`", text); self.assertIn("--arm control", text)
        rc, out = self.run_brief("implementer", "MYD-10", self.all_vars("implementer")); self.assertIn("Feature flag: `pwr-l2f-funnel`", (self.d / "briefs" / "MYD-10.md").read_text())
    def test_review_briefs_carry_the_resolved_review_skill_user_layer_first(self):
        from turnstile_cli import config, state
        rc, out = self.run_brief("reviewer", "REVIEW-2", self.all_vars("reviewer")); self.assertEqual(rc, 0, out)
        text = (self.d / "briefs" / "REVIEW-2.md").read_text(); self.assertIn("Deep review skill: `/code-review xhigh`", text); self.assertIn("BLOCKED: review skill /code-review not available", text)
        d = json.loads((self.d / "state.json").read_text()); d["epic"]["review_skill"] = "/pdf-review:run"; d["epic"]["models"] = {"reviewer": {"model": "opus", "effort": "high"}}
        (self.d / "state.json").write_text(state.dumps(d))
        config.save_user({"review_skill": "/my-review", "story_review_skill": "/my-story-review", "models": {"reviewer": {"model": "sonnet", "effort": "low"}}})
        rc, out = self.run_brief("reviewer", "REVIEW-3", self.all_vars("reviewer")); self.assertEqual(rc, 0, out)
        text = (self.d / "briefs" / "REVIEW-3.md").read_text(); self.assertIn("Deep review skill: `/my-review` — invoke it as written", text); self.assertNotIn("/pdf-review:run", text)
        self.assertNotIn("/my-review low", text); self.assertIn("AGENT: turnstile:reviewer model=sonnet effort=low\n", out)
        rc, out = self.run_brief("story-reviewer", "STORY-S1-review-r2", self.all_vars("story-reviewer"))
        story = (self.d / "briefs" / "STORY-S1-review-r2.md").read_text(); self.assertIn("Story review skill: `/my-story-review` — invoke it as written", story); self.assertNotIn("xhigh", story)
        self.assertIn("AGENT: turnstile:story-reviewer model=opus effort=xhigh\n", out)
        config.save_user({"models": {"reviewer": {"model": "sonnet", "effort": None}}})
        rc, out = self.run_brief("reviewer", "REVIEW-4", self.all_vars("reviewer")); self.assertIn("AGENT: turnstile:reviewer model=sonnet effort=xhigh\n", out)
        self.assertIn("Deep review skill: `/pdf-review:run` — invoke it as written", (self.d / "briefs" / "REVIEW-4.md").read_text())
        config.save_user({"models": {"reviewer": {"model": "sonnet", "effort": None}}, "review_skill": "/code-review"})
        rc, out = self.run_brief("reviewer", "REVIEW-5", self.all_vars("reviewer")); self.assertIn("AGENT: turnstile:reviewer model=sonnet effort=xhigh\n", out)
        self.assertIn("Deep review skill: `/code-review xhigh` — invoke it as written", (self.d / "briefs" / "REVIEW-5.md").read_text())
        config.save_user({"models": {"story-reviewer": {"model": "opus", "effort": "high"}}})
        rc, out = self.run_brief("story-reviewer", "STORY-S1-review-r3", self.all_vars("story-reviewer"))
        self.assertIn("Story review skill: `/code-review high` — invoke", (self.d / "briefs" / "STORY-S1-review-r3.md").read_text()); self.assertIn("effort=high\n", out)
        self.assertFalse(any(p.name.endswith(".json") and p.name not in ("state.json", ".sync.json") for p in self.d.iterdir()))
    def test_pre_041_epic_models_render_the_current_reviewer_defaults(self):
        from turnstile_cli import state
        d = json.loads((self.d / "state.json").read_text())
        from turnstile_cli import models
        d["epic"]["models"] = dict(models.defaults(), reviewer={"model": "opus", "effort": "medium"}, **{"story-reviewer": {"model": "opus", "effort": "high"}})
        (self.d / "state.json").write_text(state.dumps(d))
        rc, out = self.run_brief("reviewer", "REVIEW-OLD", self.all_vars("reviewer")); self.assertEqual(rc, 0, out)
        self.assertIn("Deep review skill: `/code-review xhigh`", (self.d / "briefs" / "REVIEW-OLD.md").read_text()); self.assertIn("AGENT: turnstile:reviewer model=opus effort=xhigh\n", out)
        rc, out = self.run_brief("story-reviewer", "STORY-OLD", self.all_vars("story-reviewer")); self.assertEqual(rc, 0, out)
        self.assertIn("Story review skill: `/code-review xhigh`", (self.d / "briefs" / "STORY-OLD.md").read_text()); self.assertIn("AGENT: turnstile:story-reviewer model=opus effort=xhigh\n", out)
        d["epic"]["models"] = {"reviewer": {"model": "opus", "effort": "high"}}; (self.d / "state.json").write_text(state.dumps(d))
        rc, out = self.run_brief("reviewer", "REVIEW-EPIC", self.all_vars("reviewer")); self.assertIn("AGENT: turnstile:reviewer model=opus effort=high\n", out)
        self.assertIn("Deep review skill: `/code-review high`", (self.d / "briefs" / "REVIEW-EPIC.md").read_text())
    def test_var_cannot_override_the_review_skill_or_its_level(self):
        from turnstile_cli.errors import TurnstileError
        for key in ("review_skill", "story_review_skill", "review_effort"):
            with self.assertRaises(TurnstileError) as cm: brief_cmd.parse_vars(["%s=/evil" % key])
            self.assertIn("--var %s is not accepted" % key, str(cm.exception)); self.assertIn("turnstile config", str(cm.exception))
            rc, out = self.run_brief("reviewer", "REVIEW-VAR-" + key, self.all_vars("reviewer") + ["%s=/evil" % key])
            self.assertEqual(rc, 2); self.assertIn("MISSING --var %s is not accepted" % key, out); self.assertFalse((self.d / "briefs" / ("REVIEW-VAR-%s.md" % key)).exists())
        self.assertEqual(brief_cmd.parse_vars(["scope=x"]), {"scope": "x"})
    def test_tester_brief_requires_test_user(self):
        rc, out = self.run_brief("tester", "ENV-S1", [v for v in self.all_vars("tester") if not v.startswith("test_user=")])
        self.assertEqual(rc, 2); self.assertIn("MISSING placeholder test_user", out)
