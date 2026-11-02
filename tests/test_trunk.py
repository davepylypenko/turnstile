import contextlib, copy, io, json, pathlib, shutil, tempfile, unittest
from unittest import mock
from turnstile_cli import pass_cmd, reconcile, rules, state
from turnstile_cli import sync
from turnstile_cli.github import PrFacts
from tests.test_pass import FakeIO, opts, run_capture, READY_OPTS, H, LINK
from tests.test_rules_story import story, prs, DONE, FIX as FIXD

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"
M1, M2, BASE = "11111111aaaaaaaa", "22222222bbbbbbbb", "ba5eba5e00000000"

def trunk_story(st, **ev):
    s = story(st, **ev); s["mode"] = "trunk"; s["control_cases"] = ["CC-1", "CC-2"]; return s

def merged():
    out = prs("MERGED", "MERGED"); out["jsfiller#1"]["merged_sha"] = M1; out["docs-platform#2"]["merged_sha"] = M2; return out

def run(arm, full=True, fail=0, parity="pass", head=H):
    return {"report": "r", "cases": {"pass": (3 if arm == "treatment" else 2) - fail, "fail": fail, "not_testable_here": 0}, "failed_cases": ["TP-1"] if fail else [],
            "figma_parity": parity, "full": full, "build": "1", "head": head, "arm": arm}

def reviewed(**ev):
    return trunk_story("ENV_TESTING", deploy={"build": "1", "head": H, "heads": {"jsfiller#1": M1, "docs-platform#2": M2}, "head_verified": {"verified": True}},
                       integration_review={"report": "r", "head": H, "rounds": 1, "clean": True}, **ev)

class TrunkRules(unittest.TestCase):
    def test_pr_to_human_review_does_not_wait_for_the_story(self):
        stories = {"S1": dict(FIXD["stories"]["S1"], mode="trunk", state="IN_PROGRESS")}
        pr = {"_id": "jsfiller#1", "state": "READY", "story": "S1", "head": H, "evidence": {"head_verified": {"head": H, "verified": True}, "ci": {"head": H, "status": "success"},
              "deep_review": {"head": H, "clean": True}, "gate": {"name": "pdf-review", "head": H, "result": "pass"},
              "human": {"head": H, "slack_permalink": LINK, "sent_head": H, "approved": "ah-1"}}}
        aw = [{"id": "ah-1", "type": "send", "pr": "jsfiller#1", "approved_at": "x", "used_at": "x", "head": H}]
        out = rules.check_pr(pr, "ON_HUMAN_REVIEW", FIXD["epic"]["repos"]["jsfiller"], {}, awaiting=aw, stories=stories)
        self.assertEqual(out, [])
        stories["S1"]["mode"] = "stack"
        out = rules.check_pr(pr, "ON_HUMAN_REVIEW", FIXD["epic"]["repos"]["jsfiller"], {}, awaiting=aw, stories=stories)
        self.assertTrue(any("story S1 to be DONE" in m for m in out), out)

    def test_integration_review_needs_every_pr_merged_and_a_base_deploy(self):
        out = rules.check_story(trunk_story("IN_PROGRESS", deploy={"build": "1", "head": BASE}), "INTEGRATION_REVIEW", prs("READY", "MERGED"), FIXD["stories"])
        self.assertTrue(any("jsfiller#1 to be MERGED" in m for m in out), out); self.assertFalse(any("story branch" in m for m in out), out)
        p = merged(); p["docs-platform#2"].pop("merged_sha")
        out = rules.check_story(trunk_story("IN_PROGRESS", deploy={"build": "1", "head": BASE}), "INTEGRATION_REVIEW", p, FIXD["stories"])
        self.assertTrue(any("merged_sha of docs-platform#2" in m for m in out), out)
        out = rules.check_story(trunk_story("IN_PROGRESS"), "INTEGRATION_REVIEW", merged(), FIXD["stories"])
        self.assertTrue(any("deploy.build (repo base" in m for m in out), out)
        self.assertEqual(rules.check_story(trunk_story("IN_PROGRESS", deploy={"build": "1", "head": BASE}), "INTEGRATION_REVIEW", merged(), FIXD["stories"]), [])
        self.assertTrue(any("at least one PR" in m for m in rules.check_story(trunk_story("IN_PROGRESS", deploy={"build": "1", "head": BASE}), "INTEGRATION_REVIEW", {}, FIXD["stories"])))

    def test_full_runs_are_measured_per_arm(self):
        s = reviewed(env_runs=[run("control", fail=0)]); s["evidence"]["env_test"] = s["evidence"]["env_runs"][-1]
        self.assertEqual(rules.check_story(s, "ENV_TESTING", merged(), FIXD["stories"], recording_run=True), [])
        s["control_cases"] = ["CC-1"]
        out = rules.check_story(s, "ENV_TESTING", merged(), FIXD["stories"], recording_run=True)
        self.assertTrue(any("1 control case:" in m for m in out), out)
        s = reviewed(env_runs=[run("treatment", fail=1)]); s["evidence"]["env_test"] = s["evidence"]["env_runs"][-1]
        out = rules.check_story(s, "ENV_TESTING", merged(), FIXD["stories"], recording_run=True, bugs=[{"id": "b1", "story": "S1", "case": "TP-1", "state": "todo", "arm": "control"}])
        self.assertTrue(any("a bug for failed case TP-1" in m for m in out), out)
        out = rules.check_story(s, "ENV_TESTING", merged(), FIXD["stories"], recording_run=True, bugs=[{"id": "b1", "story": "S1", "case": "TP-1", "state": "todo"}])
        self.assertEqual(out, [])

    def test_done_needs_both_arms_full_and_clean_on_the_deploy_head(self):
        s = reviewed(env_runs=[run("treatment")]); s["evidence"]["env_test"] = run("treatment")
        out = rules.check_story(s, "DONE", merged(), FIXD["stories"], bugs=[], awaiting=[DONE], flag="pwr-x")
        self.assertEqual([m for m in out if "control" in m], ["MISSING a recorded control-arm run (pass story S1 ENV_TESTING --arm control --report … --cases-pass … --full)"])
        s = reviewed(env_runs=[run("treatment"), run("control", parity="not_testable_here")])
        self.assertEqual(rules.check_story(s, "DONE", merged(), FIXD["stories"], bugs=[], awaiting=[DONE], flag="pwr-x"), [])
        s = reviewed(env_runs=[run("treatment", parity="not_testable_here"), run("control")])
        out = rules.check_story(s, "DONE", merged(), FIXD["stories"], bugs=[], awaiting=[DONE], flag="pwr-x"); self.assertTrue(any("env_runs[treatment].figma_parity in pass" in m for m in out), out)
        s = reviewed(env_runs=[run("treatment"), run("control", full=False)])
        out = rules.check_story(s, "DONE", merged(), FIXD["stories"], bugs=[], awaiting=[DONE], flag="pwr-x"); self.assertTrue(any("env_runs[control].full" in m for m in out), out)
        s = reviewed(env_runs=[run("treatment"), run("control", head="ffffffff66666666")])
        out = rules.check_story(s, "DONE", merged(), FIXD["stories"], bugs=[], awaiting=[DONE], flag="pwr-x"); self.assertTrue(any("env_runs[control].head == evidence.deploy.head" in m for m in out), out)
        s = reviewed(env_runs=[run("treatment", fail=1), run("control"), run("treatment")])  # the latest run per arm counts
        self.assertEqual(rules.check_story(s, "DONE", merged(), FIXD["stories"], bugs=[], awaiting=[DONE], flag="pwr-x"), [])
        out = rules.check_story(s, "DONE", prs("MERGED", "APPROVED"), FIXD["stories"], bugs=[], awaiting=[DONE], flag="pwr-x"); self.assertTrue(any("docs-platform#2 to be MERGED" in m for m in out), out)
        out = rules.check_story(s, "DONE", merged(), FIXD["stories"], bugs=[{"id": "b1", "story": "S1", "state": "testing"}], awaiting=[DONE], flag="pwr-x"); self.assertIn("MISSING bug b1 to be done (is testing)", out)
        s["evidence"]["deploy"].pop("head_verified"); out = rules.check_story(s, "DONE", merged(), FIXD["stories"], bugs=[], awaiting=[DONE], flag="pwr-x"); self.assertTrue(any("head_verified" in m for m in out), out)

    def test_done_without_a_flag_needs_only_the_treatment_arm(self):
        # review P2-5: no flag, no control arm; with a flag both arms
        s = reviewed(env_runs=[run("treatment")]); s["control_cases"] = []
        self.assertEqual(rules.check_story(s, "DONE", merged(), FIXD["stories"], bugs=[], awaiting=[DONE]), [])
        out = rules.check_story(s, "DONE", merged(), FIXD["stories"], bugs=[], awaiting=[DONE], flag="pwr-x"); self.assertTrue(any("control-arm run" in m for m in out), out)
        s = reviewed(env_runs=[run("treatment"), run("control")])
        self.assertEqual(rules.check_story(s, "DONE", merged(), FIXD["stories"], bugs=[], awaiting=[DONE], flag="pwr-x"), [])
    def test_next_actions_and_stack_mode_untouched(self):
        self.assertIn("MERGED", rules.next_action_story(trunk_story("IN_PROGRESS"), {})); self.assertIn("both arms", rules.next_action_story(trunk_story("ENV_TESTING"), {}))
        self.assertIn("deploy the stack top", rules.next_action_story(story("IN_PROGRESS"), {}))
        self.assertEqual(rules.run_arm({}), "treatment"); self.assertEqual(rules.run_arm({"arm": "control"}), "control")

class TrunkFlow(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir(); sync.record(self.d, True, "aaaaaaaa11111111"); shutil.copy(FIX, self.d / "state.json")
        (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok")
        d = json.loads((self.d / "state.json").read_text()); d["epic"]["flag"] = "pwr-x"; s = d["stories"]["S1"]; s["mode"] = "trunk"; s["control_cases"] = ["CC-1"]
        for pid, sha in (("jsfiller#1", M1), ("docs-platform#2", M2)):
            d["prs"][pid].update({"state": "MERGED", "merged_sha": sha})
        d["awaiting_human"] = [dict(DONE, id="ah-9")]
        (self.d / "state.json").write_text(state.dumps(d)); self.io = FakeIO(heads={"jsfiller#1": H, "docs-platform#2": "bbbbbbbb22222222"})
    def data(self): return json.loads((self.d / "state.json").read_text())
    def story(self): return self.data()["stories"]["S1"]

    def test_integration_review_verifies_the_merges_against_the_base_head(self):
        BH = "jsfiller=%s,docs-platform=cafecafe00000000" % BASE
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="7", head=BASE, base_heads=BH), self.io)
        self.assertEqual(rc, 0, out); self.assertEqual(sorted(self.io.compares), [("docs-platform", M2, "cafecafe00000000"), ("jsfiller", M1, BASE)])
        dp = self.story()["evidence"]["deploy"]
        self.assertEqual((dp["heads"], dp["head_verified"]["verified"], dp["base_heads"]), ({"jsfiller#1": M1, "docs-platform#2": M2}, True, {"jsfiller": BASE, "docs-platform": "cafecafe00000000"}))
        self.io.compare = {("jsfiller", M1): "diverged"}
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="8", head=BASE, base_heads=BH), self.io)
        self.assertEqual(rc, 2); self.assertIn("merge commit 11111111aaaa of jsfiller#1 contained in the deployed jsfiller head", out); self.assertEqual(self.story()["evidence"]["deploy"]["build"], "7")
        self.io.compare = {}; self.io.compare_fail = "gh down"
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="8", head=BASE, base_heads=BH), self.io); self.assertEqual(rc, 2); self.assertIn("GitHub compare for", out)
        self.io.compare_fail = None
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="8", head=BASE, base_heads=BH, offline=True), self.io)
        self.assertEqual(rc, 0, out); self.assertFalse(self.story()["evidence"]["deploy"]["head_verified"]["verified"]); self.assertIn("WARN --offline: merged PRs", out)

    def test_multi_repo_story_requires_base_heads(self):
        # review P3-13: --head alone cannot be the base of two repos
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="7", head=BASE), self.io)
        self.assertEqual(rc, 2); self.assertIn("MISSING --base-heads docs-platform=<sha>,jsfiller=<sha> (story S1 spans docs-platform, jsfiller", out); self.assertFalse(getattr(self.io, "compares", []))
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="7", head=BASE, base_heads="jsfiller=" + BASE), self.io)
        self.assertEqual(rc, 2); self.assertIn("--base-heads docs-platform=<sha>", out)
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="7", head=BASE, base_heads="jsfiller=%s,docs-platform=cafecafe00000000" % BASE), self.io)
        self.assertEqual(rc, 0, out)
    def test_open_pr_blocks_the_trunk_integration_review(self):
        d = self.data(); d["prs"]["docs-platform#2"].update({"state": "APPROVED"}); (self.d / "state.json").write_text(state.dumps(d))
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="7", head=BASE, base_heads="jsfiller=%s,docs-platform=%s" % (BASE, BASE)), self.io)
        self.assertEqual(rc, 2); self.assertIn("docs-platform#2 to be MERGED", out)

    def test_two_arms_then_done(self):
        self.assertEqual(run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="7", head=BASE, base_heads="jsfiller=%s,docs-platform=%s" % (BASE, BASE)), self.io)[0], 0)
        self.assertEqual(run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/R.md", head=BASE, rounds=1), self.io)[0], 0)
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-9"), self.io); self.assertEqual(rc, 2); self.assertIn("treatment-arm run", out); self.assertIn("control-arm run", out)
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/R.md", cases_pass=1, cases_fail=0, figma_parity="pass", build="7", head=BASE, full=True), self.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.story()["evidence"]["env_runs"][-1]["arm"], "treatment")
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/R.md", arm="control", cases_pass=1, cases_fail=0, figma_parity="not_testable_here", build="7", head=BASE, full=True), self.io)
        self.assertEqual(rc, 0, out); self.assertEqual([r["arm"] for r in self.story()["evidence"]["env_runs"]], ["treatment", "control"])
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-9"), self.io); self.assertEqual(rc, 0, out); self.assertEqual(self.story()["state"], "DONE")

    def test_arm_and_base_heads_are_refused_in_stack_mode(self):
        d = self.data(); d["stories"]["S1"]["mode"] = "stack"; (self.d / "state.json").write_text(state.dumps(d))
        rc, out = run_capture(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="7", head=BASE, base_heads="jsfiller=" + BASE), self.io)
        self.assertEqual(rc, 2); self.assertIn("--base-heads is a trunk-mode flag", out)
        d["stories"]["S1"].update({"state": "ENV_TESTING", "evidence": {"deploy": {"build": "7", "head": H}, "integration_review": {"report": "r", "head": H, "clean": True}}}); (self.d / "state.json").write_text(state.dumps(d))
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/R.md", arm="control", cases_pass=1, cases_fail=0, figma_parity="pass", build="7", head=H), self.io)
        self.assertEqual(rc, 2); self.assertIn("--arm is a trunk-mode flag", out)
        for bad in ("jsfiller", "jsfiller=xyz", "=abcdef12"):
            with self.assertRaises(pass_cmd.TurnstileError, msg=bad): pass_cmd._parse_base_heads(bad)
        self.assertEqual(pass_cmd._parse_base_heads("jsfiller=ABCDEF1234567890, docs-platform=cafecafe00000000"), {"jsfiller": "abcdef1234567890", "docs-platform": "cafecafe00000000"})

    def test_status_shows_flag_mode_and_the_trunk_proposal(self):
        d = self.data(); d["stories"]["S1"]["state"] = "IN_PROGRESS"; (self.d / "state.json").write_text(state.dumps(d))
        with mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf): reconcile.cli(self.d, status=True)
        out = buf.getvalue(); self.assertIn("flag: pwr-x · story_mode: stack (stories: trunk)", out); self.assertIn("story S1 [IN_PROGRESS] (trunk)", out)
        self.assertIn("S1 trunk_merged: every PR of S1 merged into the base", out); self.assertIn("turnstile pass story S1 INTEGRATION_REVIEW --build <build> --head <base sha>", out)
        self.assertEqual(reconcile.compare(json.loads(FIX.read_text()), {}), [])
