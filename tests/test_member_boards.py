import contextlib, io, json, shutil, unittest
from turnstile_cli import board, members, pass_cmd, pr_cmd, reconcile, state, sync
from tests.test_members import Delivery, out_of
from tests.test_pass import FakeIO, opts, env
from unittest import mock

class BoardIO(FakeIO):
    render_boards = pass_cmd.IO.render_boards

class Owners(Delivery):
    def seed(self):
        d = self.with_members()
        d["stories"]["S2"] = dict(d["stories"]["S1"], title="Second story", owner="second")
        d["stories"]["S1"]["owner"] = "leadlogin"
        d["prs"]["jsfiller#1"]["owner"] = "leadlogin"
        d["prs"]["docs-platform#2"]["owner"] = "second"; d["prs"]["docs-platform#2"]["story"] = "S2"
        d["bugs"] = [{"id": "b01", "story": "S1", "title": "lead bug", "state": "todo"}, {"id": "b02", "story": "S2", "title": "second bug", "state": "todo"}]
        d["awaiting_human"] = [{"id": "ah-1", "owner": "lead", "type": "plan", "payload": "plan.md", "created_at": "x", "approved_at": None},
                               {"id": "ah-2", "owner": "lead", "type": "merge", "pr": "jsfiller#1", "created_at": "x", "approved_at": None},
                               {"id": "ah-3", "owner": "lead", "type": "merge", "pr": "docs-platform#2", "created_at": "x", "approved_at": None}]
        self.put(d); return d

    def test_migration_gives_every_pr_and_story_without_owner_the_lead(self):
        data = state.load(self.d / "state.json").data
        self.assertEqual({p["owner"] for p in data["prs"].values()} | {s["owner"] for s in data["stories"].values()}, {"leadlogin"})
        data["prs"]["jsfiller#1"]["owner"] = "second"; before = json.dumps(data, sort_keys=True)
        self.assertFalse(members.migrate_owners(data)); self.assertEqual(json.dumps(data, sort_keys=True), before)

    def test_pr_add_records_the_current_member_and_owner_overrides(self):
        from tests.test_pr_add import PrAdd
        t = PrAdd("test_add_records_dev_from_github_facts_and_the_pass_to_ai_review_accepts_it"); t.setUp(); self.addCleanup(shutil.rmtree, str(t.d.parent), True)
        d = t.data(); d["epic"]["members"] = {"leadlogin": members.new_entry("Lead", None, None, None), "second": members.new_entry("Second", None, None, None)}
        (t.d / "state.json").write_text(state.dumps(d))
        from turnstile_cli import workspace
        workspace.record(t.d, t.d.parent / "ws", t.d.parent, t.d.parent / "k", {}, member="second")
        rc, out = t.add(); self.assertEqual(rc, 0, out); self.assertEqual(t.data()["prs"]["jsfiller#7"]["owner"], "second")
        t.io.heads["jsfiller#8"] = "dddddddd44444444"; t.io.facts["jsfiller#8"] = {"base": "epic_myd-1", "branch": "feature/MYD-10x"}
        (t.d / "briefs" / "MYD-10.md").write_text("b\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = pr_cmd.add(t.d, "jsfiller#8", "S1", "MYD-10", io=t.io, owner="leadlogin")
        self.assertEqual(rc, 0, buf.getvalue()); self.assertEqual(t.data()["prs"]["jsfiller#8"]["owner"], "leadlogin")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = pr_cmd.add(t.d, "jsfiller#9", "S1", "MYD-10", io=t.io, owner="ghost")
        self.assertEqual(rc, 2); self.assertIn("--owner ghost is not in epic.members", buf.getvalue()); self.assertNotIn("jsfiller#9", t.data()["prs"])

    def test_story_start_records_the_current_member(self):
        d = self.with_members(); self.record_member("second")
        d["stories"]["S2"] = dict(d["stories"]["S1"], state="PLANNED", after=[], parallel_with=["S1"], title="Next")
        (self.d / "plan.md").write_text("plan"); d["epic"]["plan"] = {"path": "plan.md", "submitted_at": "x", "digest": state.digest("plan")}
        d["awaiting_human"] = [{"id": "ah-1", "owner": "lead", "type": "plan", "payload": "plan.md", "created_at": "x", "approved_at": "2026-10-13T09:00Z", "approved_via": "lead-terminal"},
                               {"id": "ah-2", "owner": "lead", "type": "start_story", "story": "S2", "created_at": "x", "approved_at": "2026-10-13T09:00Z", "approved_via": "lead-terminal"}]
        self.put(d); sync.record(self.d, True, "aaaaaaaa11111111")
        rc, out = out_of(pass_cmd.run, self.d, "story", "S2", "IN_PROGRESS", opts(approved="ah-2", owner="ghost"), self.io)
        self.assertEqual(rc, 2); self.assertIn("--owner ghost is not in epic.members", out); self.assertEqual(self.data()["stories"]["S2"]["state"], "PLANNED")
        rc, out = out_of(pass_cmd.run, self.d, "story", "S2", "IN_PROGRESS", opts(approved="ah-2"), self.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.data()["stories"]["S2"]["owner"], "second")
        self.assertIn("boards/second.html", out)

    def test_member_board_holds_only_that_members_rows_and_the_full_board_keeps_everything(self):
        self.seed(); data = state.load(self.d / "state.json").data
        mine = board.member_view(data, "second")
        self.assertEqual((list(mine["stories"]), list(mine["prs"]), [b["id"] for b in mine["bugs"]]), (["S2"], ["docs-platform#2"], ["b02"]))
        self.assertEqual([a["id"] for a in mine["awaiting_human"]], ["ah-1", "ah-3"])
        lead = board.member_view(data, "leadlogin")
        self.assertEqual((list(lead["stories"]), list(lead["prs"]), [b["id"] for b in lead["bugs"]], [a["id"] for a in lead["awaiting_human"]]), (["S1"], ["jsfiller#1"], ["b01"], ["ah-1", "ah-2"]))
        files = board.render_files(data)
        self.assertEqual(sorted(files), ["board.html", "boards/leadlogin.html", "boards/second.html"])
        second = files["boards/second.html"]
        self.assertIn('"docs-platform#2"', second); self.assertNotIn('"jsfiller#1": {', second); self.assertNotIn("lead bug", second); self.assertIn("second bug", second)
        self.assertIn('"view": {"login": "second", "name": "Second", "variant": "myd-1-second", "desk": null, "full": "board.html"}', second)
        full = files["board.html"]
        for needle in ('"jsfiller#1"', '"docs-platform#2"', "lead bug", "second bug"): self.assertIn(needle, full)
        self.assertNotIn('"view"', full)

    def test_pr_without_owner_follows_its_story_owner(self):
        data = self.seed(); del data["prs"]["docs-platform#2"]["owner"]
        self.assertEqual(list(board.member_view(data, "second")["prs"]), ["docs-platform#2"]); self.assertNotIn("docs-platform#2", board.member_view(data, "leadlogin")["prs"])

    def test_a_write_renders_every_member_file_and_the_board_line_names_the_current_one(self):
        self.seed(); self.record_member("second"); self.io = BoardIO(heads={})
        rc, out = out_of(pass_cmd.jira_synced, self.d, "docs-platform#2", "In progress", self.io, assignee="a1"); self.assertEqual(rc, 0, out)
        for rel in ("board.html", "boards/leadlogin.html", "boards/second.html"): self.assertTrue((self.d / rel).exists(), rel)
        data = self.data(); self.assertTrue(members.board_line(data, self.d).startswith("BOARD: publish %s" % (self.d / "boards" / "second.html")))
        self.assertIn("board file boards/second.html", members.member_line(state.load(self.d / "state.json").data, self.d))

    def test_render_board_command_prints_both_files(self):
        self.seed(); files = board.render_files(self.data()); board.write_files(self.d, files)
        self.assertEqual((self.d / "boards" / "leadlogin.html").read_text().count('"jsfiller#1"') > 0, True)

    def test_reconcile_lists_owner_unknown(self):
        d = self.seed(); d["prs"]["docs-platform#2"]["owner"] = "ghost"; d["stories"]["S2"]["owner"] = "ghost"; self.put(d)
        with mock.patch.object(reconcile.github, "fetch", side_effect=Exception("offline")):
            rc, out = out_of(reconcile.cli, self.d)
        self.assertIn("docs-platform#2 owner_unknown: pr owner ghost is not in epic.members", out)
        self.assertIn("S2 owner_unknown: story owner ghost", out); self.assertIn("--owner <login>", out)

if __name__ == "__main__":
    unittest.main()
