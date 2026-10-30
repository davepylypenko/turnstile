# Turnstile migration of MYD-16538, live checks and vendoring — implementation plan (plan 3 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Tasks 7, 8 and 9 contain steps only the lead can run** (they write `delivery/` outside `turnstile` commands, approve entries, or need the lead's Slack/Figma/GitHub identity); an agent prepares and verifies, the lead types.

**Goal:** Move the live epic MYD-16538 from the prose-driven `MYD-16538-docs/` + `pr-board.html` workflow onto turnstile `v0.3.0` without stopping the work: live checks of the hooks first, then a reproducible, tested one-off migration (`scripts/migrate_board.py`), the knowledge worktree on an epic branch with `delivery/` as the single source of truth, the lead's plan approval, a first `turnstile reconcile` with zero unexplained discrepancies as the cut-over gate, and a vendored copy of the plugin in `pdffiller-knowledge` for the team.

**Architecture:** The plugin gains three small, testable pieces — a tester-credential path that never touches disk (`$TURNSTILE_TEST_PASSWORD` or the macOS keychain), a one-off migration script that parses the legacy board's JS arrays into `state.json` through the same `turnstile_cli` modules the CLI uses (`rules`, `github`, `state`, `ledger`, `board`, `pass_cmd` helpers), and a `vendor.sh` that copies a tag into another repo with a `VENDORED_FROM` stamp. Everything that writes into `delivery/` outside a `turnstile` command (moving the docs, running the migration, the first commit) is done by the lead in a terminal or through `!` prompt lines, because the Bash guard's `delivery-write` rule refuses it from the model by design. After the cut-over every change goes through `turnstile pass`; the first `reconcile` is the acceptance test.

**Tech Stack:** Python 3.9 standard library (`re`, `json`, `argparse`, `subprocess`, `unittest`), `gh api graphql` (through `turnstile_cli.github`), git worktrees, Claude Code 2.1.296 plugin layout (`--plugin-dir`, marketplace.json), the claude.ai artifact runtime (`db` + `user`) already declared on the existing board artifact.

**Spec:** `docs/superpowers/specs/2026-10-13-turnstile-design.md` §8 (packaging), §9 (migration), §12 (open questions). Binding review inputs: `docs/superpowers/reviews/2026-10-13-core-review.md` Round 3 ("Live check before plan 3", "Ready for plan 3 migration: yes, with two conditions") and `docs/superpowers/reviews/2026-10-14-skill-agents-review.md` (finding 14, Round 2 "What the lead must do live", Round 3 "Verdict for plan 3": five live checks, migration `state.json` settings, R3-2 agent identity through the hook payload, R3-3 `deploy.heads` required for sends). Plans 1–2 (implemented): `2026-10-13-turnstile-core.md`, `2026-10-13-turnstile-skill-agents.md`. Live epic inputs: `/Users/davyd/Desktop/pdffiller/l2f-editor-funnel/CLAUDE.md` (decisions table, repos, branches, tickets, dispatch plan), `/Users/davyd/Desktop/pdffiller/MYD-16538-docs/` (`ledger.md`, `pr-board.html`, `briefs/`, `reports/`), the knowledge workitem `context/workitems/pdfd-429-l2f-editor-funnel/` (`test-plan.md` with 152 `TP-nnn` cases and their ticket column).

## Global Constraints

- Python 3.9 syntax only (no `match`, no `X | Y`, no runtime `list[str]`); no third-party packages. Suite: `python3 -m unittest discover -s tests -v` — 258 green at the start (`main` `61cb94e`); every task adds tests, none removes.
- `state.json` is written only through `turnstile_cli.state.dumps` (2-space indent, sorted keys, trailing newline) and `state.write_atomic`; the migration script uses them too and commits through `pass_cmd.IO().git_commit` (`git add -A . && git commit -q -m … -- .` inside `delivery/`), so the migration leaves the same kind of commit as a `pass`.
- Ids: PR `<repo>#<number>` (the board's `owner/repo#N` is converted); story `S<n>`; bug `b<nn>`; awaiting `ah-<n>` via `pass_cmd._open_entry`. Heads are 40-hex SHAs from GitHub, stored lowercase, compared with `rules.same_head`. Timestamps from `pass_cmd._now()` (`%Y-%m-%dT%H:%MZ`); bug stamps from `pass_cmd._now_s()`.
- PR states only from `rules.PR_STATES`; story states from `rules.STORY_STATES`; Jira status from `rules.JIRA_FOR_PR_STATE`.
- Per-repo settings written by the migration (review 2026-10-14 Round 2 item 6, Round 3 verdict): jsfiller and docs-platform `gate: "pdf-review"`, `gate_check: "pdf-review"`, `ci_ignore: ["pdf-review", "gate / gate"]`; pdffiller `gate: "pdf-review"` (default `gate_check` = `pdf-review`, `branch_prefix: "l2f-funnel-myd-"`); front-link2fill-app `gate: "pr-review"`, `gate_check: null`; front-signature-flow and locales `gate: null`, `gate_check: null`. `copilot: false` for jsfiller, `true` elsewhere. Slack: jsfiller `CCGLRULNR`, pdffiller `G8S415WG6`, the four front repos `CFZ7EC5BN`. `epic.github_org: "pdffiller"`, `epic.roles.lead: "davyd.pylypenko"`, `epic.roles.lead_github: "davepylypenko"`, `epic.board.artifact_url: "https://claude.ai/artifact/WiLRoRy4iaKfYwiRyg4659"`, `epic.environment: {variant: "l2f-funnel", desk: "desk05"}`, `epic.chat_language: "Ukrainian"`.
- Real PR bases, never the epic branch by default: the jsfiller chain on GitHub today is `#13222 → epic_myd-16538_l2f-funnel`, `#13223 → feature/MYD-18075-l2f-owner-state`, `#13226 → feature/MYD-18083-l2f-modal-host`, `#13253 → feature/MYD-18085-l2f-activate-flow`, `#13254 → feature/MYD-18082-l2f-blocked-modal`, `#13267 → feature/MYD-18086-l2f-published-view`, `#13356 → feature/MYD-18087-l2f-published-header-actions`, `#13359 → feature/MYD-18076-l2f-header-autotests`, `#13365 → feature/MYD-18077-l2f-header-dots-menu`, `#13382 → feature/MYD-18077-l2f-disabled-tab-hint`, `#13384 → feature/MYD-18077-l2f-header-dots-gap`, `#13362 → feature/MYD-18077-l2f-header-dots-menu`. The script takes `base` and `branch` from GitHub (`baseRefName`, `headRefName`), never from the board.
- Hooks are referenced by **rule name** (`delivery-write`, `delivery-git-restore`, `knowledge-worktree-reset`, `lead-approve`, `lead-migration`, `tester-push`, `tester-commit`, `tester-pr-write`, `tester-api-write`, the Slack guard's `permissionDecision: "ask"`), never by line number: a verification agent is changing `hooks/` concurrently.
- Personal items stay out of the plugin (spec §8): the migration config with channel ids, logins and the board URL lives in the knowledge delivery dir (`delivery/briefs/MIGRATE-2026-10-14.json`), not under `turnstile/`. No password, token or real test-user address appears in any committed file (`tests/test_skill_files.py` already asserts `qwe123` and `airslate` are absent from the env recipe; Task 1 extends that to the tester agent and brief).
- Commits in `turnstile`: conventional (`feat(migrate): …`), SSH-signed (never `--no-gpg-sign`), **no `Co-Authored-By` trailer**; pull `main` (`git pull --ff-only`) before every commit because another agent pushes hook fixes. Commits in `pdffiller-knowledge`: same rules; the delivery commits are made by `turnstile` commands or by the lead.
- Chat with the lead in Ukrainian; every file in English.

## Review Focus

1. **A board row whose PR is unknown to GitHub** (closed-and-deleted, typo, or `gh` down): the script must refuse the whole run and write nothing, not emit a half state. Test in Task 3 (`test_unknown_pr_refuses_whole_run`).
2. **A `dep` on the board that points at a merged PR, a PR in another repo's table, or nothing** (`docs-platform#5424` has `dep: '#1172'`, a merged front-link2fill-app PR): `blocked_by` must be `null` for merged, resolved across repos when the number is unique, and refused when it matches nothing. Test in Task 3 (`test_dep_resolution`).
3. **A `ready` row that carries a Slack permalink** (sent on 2026-10-12, then rippled): the old board's "Ready, reviewers not notified" is turnstile's `REWORK` (push after send), never `READY`; and `READY` rows without a permalink get an unapproved `send` entry so the Slack guard has something to check. Test in Task 3 (`test_ready_with_permalink_is_rework_and_ready_opens_send`).
4. **Running the migration twice** (the lead re-runs after fixing the config): the script must refuse when `state.json` already has PRs unless `--force`, and `--force` must rebuild from the board, not merge. Test in Task 3 (`test_second_run_refused_without_force`).
5. **A tester launched by a lead whose environment has neither `TURNSTILE_TEST_PASSWORD` nor the keychain item**: the tester must stop with `BLOCKED` naming both sources before opening the browser, not retry logins with an empty password (which locks the shared test user). Pinned in Task 1 by the agent text test (`test_tester_credentials_are_env_or_keychain_never_prompt_or_file`) and verified live in Task 7 check 5.

---

## Decisions taken while writing this plan (confirm at plan.md approval, Task 8 step 9)

| # | Decision | Why |
|---|---|---|
| D-1 | Knowledge epic branch is **`epic/myd-16538`**, not `epic/myd-16538-l2f-funnel` | `turnstile init` names it `epic/<key>` (`init_cmd.epic_branch_name`) and refuses an existing worktree on any other branch; renaming would be a plugin change outside this plan's scope |
| D-2 | Stories S1–S5 = the dispatch-plan waves (CLAUDE.md § Dispatch plan) with `human_review: "per_pr"`; S1 and S2 (every PR merged) are written `DONE`, S3–S5 `IN_PROGRESS`; they end when their PRs merge and never go through the story gates | Spec §9.2 (waves), review R2-3 resolution (`per_pr` for migrated stories); a legacy story cannot reach `DONE` through the CLI (`DONE` only from `ENV_TESTING`) |
| D-3 | Two new stories under the **full** flow (spec §9.5): **S6** jsfiller 18077 header fixes (`#13359 #13362 #13365 #13382 #13384`, branch `feature/MYD-18076-l2f-header-autotests`) and **S7** module 18077 fixes (`front-link2fill-app#1198 #1206 #1207`, branch `epic_myd-16538_l2f-funnel`); both `PLANNED`, `parallel_with` each other and S3–S5, so the lead's first `start_story` approval is the first new-flow act | `_start_blockers` refuses a start while any non-parallel story is active; one `stories.<S>.branch` per story means multi-repo fix stacks must be split (review known limitation under finding 4) |
| D-4 | The already-sent 18077 PRs (`docs-platform#5459` merged, `pdffiller#37851`, `front-link2fill-app#1201`, `#1205`) stay in legacy S5 | They are on human review under the old process; pulling them into S6/S7 would make the story gates demand env testing before their current threads are even answered |
| D-5 | Migrated stories past `IN_PROGRESS` without `per_pr`: **none** at the time of writing; the "re-record the deploy" step (Task 8 step 13) stays in the runbook because the lead may flip a story at plan approval, and R3-3 makes the deploy snapshot a precondition for sends of a `DONE` story | review Round 3 verdict, step 6 |
| D-6 | The board artifact URL is kept: the turnstile `board.html` is published to `https://claude.ai/artifact/WiLRoRy4iaKfYwiRyg4659` (same `bugs/<id>` db collection, same `{status, updatedAt}` shape) | the team's bookmarks and the memory file point there; `templates/board.html` was written against the same db contract |
| D-7 | `MYD-16538-docs/` moves **as is** into `delivery/` (`ledger.md`, `pr-board.html`, `briefs/`, `reports/`, research and handoff files); the old orchestrator `CLAUDE.md` moves to `delivery/orchestrator-claude-md-2026-10-14.md`; `decisions.md` is generated from its tables | spec §9.1; nothing is rewritten, so history stays greppable |
| D-8 | Jira: open PRs are written `synced: false` with the status `rules.JIRA_FOR_PR_STATE` implies; merged PRs `synced: true` ("On Hold" was applied at merge under the old process). The first `turnstile status` lists every unsynced PR; the orchestrator checks each with `getJiraIssue` and records `jira-synced` | the CLI has no Jira read (decision 2026-10-13: no API token) |

## File structure

```
turnstile/
  agents/tester.md                                  # Task 1 — credential sources (env var → keychain → BLOCKED)
  skills/turnstile/references/briefs/tester.md      # Task 1 — {{test_user}}, no password in the brief
  skills/turnstile/references/env/pdffiller-dev.md  # Task 1 — "Credentials" section
  skills/turnstile/SKILL.md                         # Task 1 — ## dispatch: no credentials in the prompt either
  tests/test_agents.py, tests/test_skill_files.py   # Task 1 — assertions
  scripts/migrate_board.py                          # Task 2 (parser), Task 3 (state), Task 4 (decisions, stories block, CLI)
  tests/test_migrate_board.py                       # Tasks 2–4
  tests/fixtures/pr-board-2026-10-14.html           # Task 2 — verbatim copy of MYD-16538-docs/pr-board.html
  tests/fixtures/migrate_config.json                # Task 3 — a 3-story, 6-PR config over the fixture board
  scripts/vendor.sh, Makefile, tests/test_vendor.py # Task 5
  README.md, .claude-plugin/plugin.json             # Task 6 — version 0.3.0, "Migrating an epic", "Vendoring"
  docs/superpowers/reviews/2026-10-14-live-checks.md # Task 7 — results of the five live checks (lead)
pdffiller-knowledge (worktree <workspace>/pdffiller-knowledge on epic/myd-16538)
  context/workitems/pdfd-429-l2f-editor-funnel/delivery/   # Task 8 — state.json, ledger.md, plan.md, decisions.md, briefs/, reports/, evidence/, board.html, legacy files
  context/workitems/pdfd-429-l2f-editor-funnel/delivery/briefs/MIGRATE-2026-10-14.json  # Task 8 — the migration config (personal data lives here)
  plugins/turnstile/  or  playground/davyd-pylypenko/claude/plugins/turnstile/           # Task 9 — vendored copy + VENDORED_FROM
  .claude-plugin/marketplace.json                                                         # Task 9 — plugin entry
<workspace>/.turnstile, <workspace>/CLAUDE.md                                            # Task 8 — pointer file, shrunken CLAUDE.md
```

---

### Task 1: Tester credentials — `TURNSTILE_TEST_PASSWORD` with a keychain alternative (scope D)

The lead picks **one** of the two sources before Task 7 check 5; the plugin supports both, in this order: the environment variable, then the keychain, then `BLOCKED`. Nothing writes the password to a brief, a report, the ledger or the scratchpad; the orchestrator never reads it (the tester reads it inside its own Bash at login time).

**Files:**
- Modify: `agents/tester.md` (`## Role` bullet on credentials, `## Procedure` step 1)
- Modify: `skills/turnstile/references/briefs/tester.md` (the "Credentials:" sentence; add `{{test_user}}`)
- Modify: `skills/turnstile/references/env/pdffiller-dev.md` (`## Users` → add `## Credentials`)
- Modify: `skills/turnstile/SKILL.md` (`## dispatch` step 2: the sentence "For `tester` append the lead's test credentials to the prompt only")
- Test: `tests/test_agents.py`, `tests/test_skill_files.py`, `tests/test_brief.py`

**Interfaces:**
- Produces: the environment variable name `TURNSTILE_TEST_PASSWORD`; the keychain item `service = turnstile-test-password`, `account = <test user address>`; the brief placeholder `{{test_user}}` (required by `turnstile brief tester …`); the tester reply `BLOCKED: no test password (set TURNSTILE_TEST_PASSWORD in the shell that starts Claude Code, or add the keychain item turnstile-test-password for <user>)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agents.py` inside `class Agents`:

```python
    def test_tester_credentials_are_env_or_keychain_never_prompt_or_file(self):
        text = (AGENTS / "tester.md").read_text()
        for needle in ["TURNSTILE_TEST_PASSWORD", "security find-generic-password", "turnstile-test-password",
                       "BLOCKED: no test password", "never written to a file"]:
            self.assertIn(needle, text, needle)
        self.assertNotIn("append the lead's test credentials", text)
        self.assertNotIn("qwe123", text); self.assertNotIn("airslate", text)
```

Append to `tests/test_skill_files.py` inside `class SkillFiles`:

```python
    def test_tester_brief_and_recipe_name_the_password_sources_not_the_password(self):
        brief = (REFS / "briefs" / "tester.md").read_text(); recipe = (REFS / "env" / "pdffiller-dev.md").read_text(); skill = (SKILL / "SKILL.md").read_text()
        self.assertIn("{{test_user}}", brief); self.assertIn("TURNSTILE_TEST_PASSWORD", brief); self.assertNotIn("Credentials: in your launch prompt", brief)
        self.assertIn("## Credentials", recipe); self.assertIn("TURNSTILE_TEST_PASSWORD", recipe); self.assertIn("security add-generic-password", recipe)
        self.assertNotIn("test credentials to the prompt", skill); self.assertIn("TURNSTILE_TEST_PASSWORD", skill)
        for t in (brief, recipe, skill): self.assertNotIn("qwe123", t); self.assertNotIn("airslate", t)
```

Append to `tests/test_brief.py` (uses the module's existing helpers; read the file's `setUp` first — it creates a delivery dir with an approved plan):

```python
    def test_tester_brief_requires_test_user(self):
        r = self.run_brief("tester", "ENV-S1", ["story_id=S1", "story_title=T", "mode=full", "rerun_cases=-", "builds=1", "stack_head=aaaaaaaa11111111",
                                                  "test_cases=TP-1", "figma_frames=F:1-2", "tolerance=1px", "copy_source=Figma"])
        self.assertEqual(r.returncode, 2); self.assertIn("MISSING placeholder test_user", r.stdout)
```

If `tests/test_brief.py` has no `run_brief` helper, add one next to its existing invocation pattern (`brief_cmd.run(delivery, agent, name, vars, io=FakeIO())` captured with `contextlib.redirect_stdout`) and adapt the assertion to the captured text.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_agents tests.test_skill_files tests.test_brief -v 2>&1 | tail -15`
Expected: the three new tests FAIL (`AssertionError: 'TURNSTILE_TEST_PASSWORD' not found …`, `'{{test_user}}' not found`, placeholder not missing); everything else passes.

- [ ] **Step 3: Edit `agents/tester.md`**

In `## Role`, replace the bullet that lists "the credentials the lead supplied in your launch prompt (never in the brief, which is committed)" with:

```markdown
- Credentials: the test user address comes from the brief (`Test user:`). The password comes from **your own environment at login time, never from the brief, the prompt, a report or a file**: first `$TURNSTILE_TEST_PASSWORD` (exported by the lead in the shell that started Claude Code), else the macOS keychain item `security find-generic-password -s turnstile-test-password -a "<test user>" -w`. Read it inside the Bash call that performs the login (`printenv TURNSTILE_TEST_PASSWORD` or the `security` call piped straight into the login step); never echo it, never assign it to a file, never paste it into the report. Both empty → reply `BLOCKED: no test password (set TURNSTILE_TEST_PASSWORD in the shell that starts Claude Code, or add the keychain item turnstile-test-password for <user>)` before opening the browser — a login with an empty password locks the shared user.
```

In `## Procedure` step 1 replace "log in with the user the brief names" with "resolve the password as `## Role` says (env var, then keychain; neither → `BLOCKED`), then log in with the user the brief names". Add to `## Cannot`: "writing the password anywhere (it is never written to a file)". Keep every other line.

- [ ] **Step 4: Edit the brief template, the env recipe and SKILL.md**

`skills/turnstile/references/briefs/tester.md`: replace `Credentials: in your launch prompt, not here (briefs are committed to git); never write them to a file or report.` with `Test user: {{test_user}}. Password: from your environment at login (`$TURNSTILE_TEST_PASSWORD`, else keychain `turnstile-test-password`), per the role rules; never in this brief, the report or any file.`

`skills/turnstile/references/env/pdffiller-dev.md`: after `## Users` add

```markdown
## Credentials
The shared dev password is never in git, in a brief or in a prompt. The tester reads it at login from, in order:
1. `TURNSTILE_TEST_PASSWORD` — the lead exports it in the shell that starts Claude Code (`export TURNSTILE_TEST_PASSWORD=…; claude …`); subagents inherit the environment.
2. The macOS keychain: the lead stores it once with `security add-generic-password -s turnstile-test-password -a "<test user address>" -w` (prompts for the secret; `-U` updates), and the tester reads it with `security find-generic-password -s turnstile-test-password -a "<test user address>" -w`.
Neither present → the tester replies `BLOCKED` before the first login.
```

`skills/turnstile/SKILL.md` `## dispatch` step 2: replace `For `tester` append the lead's test credentials to the prompt only (briefs are committed);` with `For `tester` pass `--var test_user=<address>`; the password is never in the prompt or the brief — the tester reads `TURNSTILE_TEST_PASSWORD` or the keychain item `turnstile-test-password` itself at login (`references/env/pdffiller-dev.md` § Credentials);`. Keep SKILL.md ≤ 170 lines (`test_skill_md_short_with_frontmatter_and_commands`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -3`
Expected: `OK` with 261 tests (258 + 3).

- [ ] **Step 6: Commit**

```bash
cd /Users/davyd/Desktop/pdffiller/l2f-editor-funnel/turnstile && git pull -q --ff-only
git add agents/tester.md skills/turnstile/references/briefs/tester.md skills/turnstile/references/env/pdffiller-dev.md skills/turnstile/SKILL.md tests/test_agents.py tests/test_skill_files.py tests/test_brief.py
git commit -m "feat(tester): password from TURNSTILE_TEST_PASSWORD or the keychain at login, never from a brief, prompt or file"
```

---

### Task 2: `scripts/migrate_board.py` — parse the legacy board's JS arrays

**Files:**
- Create: `scripts/migrate_board.py` (parser half), `tests/fixtures/pr-board-2026-10-14.html` (verbatim copy of `/Users/davyd/Desktop/pdffiller/MYD-16538-docs/pr-board.html` as of 2026-10-14 06:07 Kyiv), `tests/test_migrate_board.py`

**Interfaces:**
- Produces: `js_array(html: str, name: str) -> str` (the text of `const NAME = [ … ];`), `js_objects(text: str) -> List[dict]` (each `{ k: 'v', n: 3 }` literal as a dict; `\'` and `\\` unescaped; numbers as `int`), `parse_board(html: str) -> dict` with keys `updated: str`, `status: List[str]` (the `STATUS` keys), `epic_prs: List[dict]`, `repos: List[{name, epic, rows: List[dict]}]`, `bug_status: List[str]`, `bugs: List[dict]`. Row keys as the board has them: `t, pr, s, dep, note` plus optional `slack`, `cr`. `pr_id("pdffiller/jsfiller#13222") -> "jsfiller#13222"`, `ticket_of("MYD-18068 f/u") -> "MYD-18068"`.

- [ ] **Step 1: Copy the fixture and write the failing tests**

```bash
cp /Users/davyd/Desktop/pdffiller/MYD-16538-docs/pr-board.html /Users/davyd/Desktop/pdffiller/l2f-editor-funnel/turnstile/tests/fixtures/pr-board-2026-10-14.html
```

Create `tests/test_migrate_board.py`:

```python
import importlib.util, json, pathlib, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "pr-board-2026-10-14.html"
spec = importlib.util.spec_from_file_location("migrate_board", ROOT / "scripts" / "migrate_board.py")
mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)

class Parse(unittest.TestCase):
    def setUp(self):
        self.html = FIX.read_text()
        self.board = mb.parse_board(self.html)

    def test_js_objects_handles_escapes_numbers_and_braces_in_strings(self):
        objs = mb.js_objects("[\n { t: 'a\\'b', n: 4, note: 'x {y} <code>z</code>' },\n { t: 'c' },\n]")
        self.assertEqual(objs, [{"t": "a'b", "n": 4, "note": "x {y} <code>z</code>"}, {"t": "c"}])

    def test_arrays_and_counts(self):
        self.assertEqual(self.board["updated"], "2026-10-14 06:07 Kyiv")
        self.assertEqual(self.board["status"], ["ai", "ready", "human", "approved", "blocked", "merged", "dev", "epic", "bugs"])
        self.assertEqual(len(self.board["epic_prs"]), 6)
        self.assertEqual([r["name"] for r in self.board["repos"]][:2], ["pdffiller (monolith)", "front-link2fill-app"])
        self.assertEqual(sum(len(r["rows"]) for r in self.board["repos"]), 42)
        self.assertEqual(self.board["bug_status"], ["todo", "ai", "testing", "done"])
        self.assertEqual(len(self.board["bugs"]), 27)
        self.assertEqual(self.board["bugs"][0]["id"], "b01"); self.assertEqual(self.board["bugs"][-1]["id"], "b24")

    def test_row_fields(self):
        rows = {r["pr"]: r for repo in self.board["repos"] for r in repo["rows"]}
        r = rows["pdffiller/jsfiller#13223"]
        self.assertEqual((r["t"], r["s"], r["dep"]), ("MYD-18083", "ready", "#13222"))
        self.assertTrue(r["slack"].startswith("https://pdffiller.slack.com/archives/CCGLRULNR/"))
        self.assertIn("pdf-review ✓ 8fabe8c3", r["cr"])
        self.assertEqual(rows["pdffiller/docs-platform#5424"]["dep"], "#1172")
        self.assertNotIn("slack", rows["pdffiller/jsfiller#13359"])
        for key in ("t", "pr", "s", "dep", "note"):
            self.assertTrue(all(key in r for r in rows.values()), key)
        self.assertTrue(all(r["s"] in self.board["status"] for r in rows.values()))

    def test_id_helpers(self):
        self.assertEqual(mb.pr_id("pdffiller/jsfiller#13222"), "jsfiller#13222")
        self.assertEqual(mb.ticket_of("MYD-18068 f/u"), "MYD-18068")
        with self.assertRaises(mb.MigrationError):
            mb.pr_id("jsfiller#13222")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_migrate_board -v 2>&1 | tail -5`
Expected: `FileNotFoundError` / `AttributeError` on `scripts/migrate_board.py` — the module does not exist yet.

- [ ] **Step 3: Write the parser**

Create `scripts/migrate_board.py`:

```python
#!/usr/bin/env python3
"""One-off migration: generate delivery/state.json for an epic from the legacy pr-board.html (its JS data arrays) plus GitHub
facts, through the same turnstile_cli modules the CLI uses. Run by the lead in a terminal: it writes state.json, which the
hooks reserve for turnstile commands (rule delivery-write)."""
import argparse, datetime, json, os, pathlib, re, subprocess, sys
from dataclasses import dataclass
from typing import Dict, List, Optional
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from turnstile_cli import github, rules, state as st_mod, ledger, board, pass_cmd  # noqa: E402

class MigrationError(Exception):
    pass

ARRAY_RX = r"const %s = \[(.*?)\n  \];"
PROP_RX = re.compile(r"\s*([A-Za-z_]\w*)\s*:\s*(?:'((?:[^'\\]|\\.)*)'|(-?\d+))\s*,?")
OBJ_RX = re.compile(r"\{((?:[^{}']|'(?:[^'\\]|\\.)*')*)\}", re.S)
SECTION_RX = re.compile(r"\{ name: '((?:[^'\\]|\\.)*)', epic: '((?:[^'\\]|\\.)*)', rows: \[(.*?)\n    \]\}", re.S)
PR_RX = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")
TICKET_RX = re.compile(r"\b([A-Z]+-\d+)\b")

def _unescape(s: str) -> str:
    return s.replace("\\'", "'").replace("\\\\", "\\")

def js_array(html: str, name: str) -> str:
    m = re.search(ARRAY_RX % re.escape(name), html, re.S)
    if not m:
        raise MigrationError("board has no `const %s = [ … ];` array" % name)
    return m.group(1)

def js_objects(text: str) -> List[dict]:
    out = []
    for m in OBJ_RX.finditer(text):
        body, obj, pos = m.group(1), {}, 0
        while pos < len(body):
            p = PROP_RX.match(body, pos)
            if not p:
                if body[pos:].strip():
                    raise MigrationError("cannot parse object property at: %r" % body[pos:pos + 40])
                break
            obj[p.group(1)] = int(p.group(3)) if p.group(3) is not None else _unescape(p.group(2))
            pos = p.end()
        out.append(obj)
    return out

def _keys_of_map(text: str) -> List[str]:
    return re.findall(r"^\s*(\w+):\s*\{", text, re.M)

def parse_board(html: str) -> dict:
    upd = re.search(r"const UPDATED = '([^']*)'", html)
    repos = []
    for name, epic, rows in SECTION_RX.findall(js_array(html, "REPOS")):
        repos.append({"name": _unescape(name), "epic": _unescape(epic), "rows": js_objects(rows)})
    if not repos:
        raise MigrationError("REPOS has no `{ name: …, epic: …, rows: [ … ]}` sections")
    return {"updated": upd.group(1) if upd else "", "status": _keys_of_map(js_array(html, "STATUS")),
            "epic_prs": js_objects(js_array(html, "EPIC_PRS")), "repos": repos,
            "bug_status": _keys_of_map(js_array(html, "BUG_STATUS")), "bugs": js_objects(js_array(html, "BUGS"))}

def pr_id(owner_repo_num: str) -> str:
    m = PR_RX.match(owner_repo_num or "")
    if not m:
        raise MigrationError("board pr must look like owner/repo#N (got %r)" % owner_repo_num)
    return "%s#%s" % (m.group(2), m.group(3))

def ticket_of(text: str) -> str:
    m = TICKET_RX.search(text or "")
    if not m:
        raise MigrationError("no ticket key in %r" % text)
    return m.group(1)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_migrate_board -v 2>&1 | tail -8`
Expected: 4 tests `ok`. If `test_arrays_and_counts` reports 41 or 43 rows, a note contains an unquoted `{` or `}`: print `[r['pr'] for …]` to find the row and fix `OBJ_RX` (never the fixture).

- [ ] **Step 5: Commit**

```bash
cd /Users/davyd/Desktop/pdffiller/l2f-editor-funnel/turnstile && git pull -q --ff-only
git add scripts/migrate_board.py tests/test_migrate_board.py tests/fixtures/pr-board-2026-10-14.html
git commit -m "feat(migrate): parse the legacy pr-board.html data arrays (STATUS, EPIC_PRS, REPOS rows, BUG_STATUS, BUGS)"
```

---

### Task 3: `migrate_board.py` — build `state.json` from the board, GitHub facts and a config

**Files:**
- Modify: `scripts/migrate_board.py` (append the builder)
- Create: `tests/fixtures/migrate_config.json`
- Test: `tests/test_migrate_board.py` (`class Build`)

**Interfaces:**
- Consumes: `parse_board`, `pr_id`, `ticket_of` (Task 2); `turnstile_cli.github.PrFacts` (`head, merged, merged_sha, draft, ci, checks, approvals, changes_requested, human_threads_open, copilot_threads_open, ci_without(names)`), `rules.same_head`, `rules.JIRA_FOR_PR_STATE`, `pass_cmd._open_entry`, `pass_cmd._ensure_start_story_entries`, `pass_cmd._recompute_next_actions`, `pass_cmd._now`, `pass_cmd._now_s`.
- Produces: `@dataclass MigFacts(facts: PrFacts, branch: str, title: str)`; `fetch_facts(pr_ids, org) -> Dict[str, MigFacts]` (one `gh api graphql` per PR with `QUERY2 = github.QUERY.replace("headRefOid", "headRefOid headRefName title", 1)`); `facts_from_payloads(raw: Dict[str, dict]) -> Dict[str, MigFacts]` (replays saved payloads through `github.parse`); `map_state(row, facts, overrides) -> (state, reason)`; `resolve_dep(dep, repo, rows_by_id) -> Optional[str]`; `build_state(base: dict, board: dict, facts: Dict[str, MigFacts], cfg: dict, reports: set, test_cases: Dict[str, set], now: str) -> dict`; `test_plan_cases(text) -> Dict[str, set]` (`TP-id -> {tickets}`).
- Config schema (`migrate_config.json`): `{"skip_repos": [...], "stories": {"S1": {"title", "tickets", "repos", "branch", "after", "parallel_with", "figma", "env_slot", "human_review_units", "human_review"?, "state", "test_cases_from_tickets"?}}, "pr_story": {"<repo#n>": "S6"}, "pr_overrides": {"<repo#n>": {"state"?, "reason"?, "sent_head"?, "reviewers"?}}, "bug_story_default": "S5"}`.

- [ ] **Step 1: Write the config fixture and the failing tests**

Create `tests/fixtures/migrate_config.json` (a small config over the real fixture board; stories S1/S2/S6 only, so unmatched rows exercise the errors):

```json
{
  "skip_repos": ["pdffiller-knowledge"],
  "stories": {
    "S1": {"title": "Wave 1", "tickets": ["MYD-18059", "MYD-18060", "MYD-18061", "MYD-18064", "MYD-18065", "MYD-18066", "MYD-18067", "MYD-18068", "MYD-18063", "MYD-18069", "MYD-18072", "MYD-18073", "MYD-18074", "MYD-18079", "MYD-18080", "MYD-18062", "MYD-18078"],
           "repos": ["pdffiller", "front-link2fill-app", "jsfiller", "front-signature-flow", "locales", "docs-platform"], "branch": "epic_myd-16538_l2f-funnel",
           "after": [], "parallel_with": ["S2", "S6"], "figma": [], "env_slot": {"variant": "l2f-funnel"}, "human_review_units": [], "human_review": "per_pr", "state": "IN_PROGRESS"},
    "S2": {"title": "Wave 3-5 legacy", "tickets": ["MYD-18075", "MYD-18082", "MYD-18083", "MYD-18081", "MYD-18084", "MYD-18085", "MYD-18086", "MYD-18087", "MYD-18076", "MYD-18077", "MYD-18071", "MYD-18070"],
           "repos": ["jsfiller", "docs-platform", "pdffiller", "front-link2fill-app"], "branch": "epic_myd-16538_l2f-funnel",
           "after": [], "parallel_with": ["S1", "S6"], "figma": [], "env_slot": {"variant": "l2f-funnel", "desk": "desk05"}, "human_review_units": [], "human_review": "per_pr", "state": "IN_PROGRESS"},
    "S6": {"title": "18077 jsfiller header fixes", "tickets": ["MYD-18077"], "repos": ["jsfiller"], "branch": "feature/MYD-18076-l2f-header-autotests",
           "after": [], "parallel_with": ["S1", "S2"], "figma": ["KOew9XK7uPLPCBqBn0ba8Z:9098-41434"], "env_slot": {"variant": "l2f-funnel", "desk": "desk05"},
           "human_review_units": [{"title": "18077 header fixes", "prs": ["jsfiller#13359", "jsfiller#13362", "jsfiller#13365", "jsfiller#13382", "jsfiller#13384"]}],
           "state": "PLANNED", "test_cases_from_tickets": ["MYD-18079", "MYD-18086"]}
  },
  "pr_story": {"jsfiller#13359": "S6", "jsfiller#13362": "S6", "jsfiller#13365": "S6", "jsfiller#13382": "S6", "jsfiller#13384": "S6"},
  "pr_overrides": {"docs-platform#5425": {"state": "REWORK", "reason": "fixes pushed for lMakDen's threads (reports/REVIEW-COMMENTS-5425-5472.md)", "reviewers": ["lMakDen"]}},
  "bug_story_default": "S2"
}
```

Append to `tests/test_migrate_board.py`:

```python
from turnstile_cli import github, rules, state as st_mod
CFG = json.loads((ROOT / "tests" / "fixtures" / "migrate_config.json").read_text())
BASE = json.loads((ROOT / "templates" / "state.json").read_text())
BASE["epic"].update({"key": "MYD-16538", "workitem": "pdfd-429-l2f-editor-funnel", "github_org": "pdffiller",
                     "roles": {"lead": "davyd.pylypenko", "lead_github": "davepylypenko", "pm": None, "design": None},
                     "repos": {"jsfiller": {"base": "develop", "epic_branch": "epic_myd-16538_l2f-funnel", "slack": "C1", "gate": "pdf-review", "gate_check": "pdf-review", "ci_ignore": ["pdf-review", "gate / gate"], "copilot": False},
                               "docs-platform": {"base": "main", "epic_branch": "epic_myd-16538_l2f-funnel", "slack": "C2", "gate": "pdf-review", "gate_check": "pdf-review", "ci_ignore": ["pdf-review", "gate / gate"], "copilot": True},
                               "pdffiller": {"base": "master", "epic_branch": "l2f-funnel", "slack": "G1", "gate": "pdf-review", "gate_check": "pdf-review", "ci_ignore": ["pdf-review"], "copilot": True, "branch_prefix": "l2f-funnel-myd-"},
                               "front-link2fill-app": {"base": "master", "epic_branch": "epic_myd-16538_l2f-funnel", "slack": "C2", "gate": "pr-review", "gate_check": None, "ci_ignore": [], "copilot": True},
                               "front-signature-flow": {"base": "main", "epic_branch": "epic_myd-16538_l2f-funnel", "slack": "C2", "gate": None, "gate_check": None, "ci_ignore": [], "copilot": True},
                               "locales": {"base": "main", "epic_branch": "epic_myd-16538_l2f-funnel", "slack": "C2", "gate": None, "gate_check": None, "ci_ignore": [], "copilot": True}}})
NOW = "2026-10-14T12:00Z"

def sha(n):
    return ("%08x" % n) * 5

def fake_facts(board, merged_from_board=True, **per_pr):
    """MigFacts for every board row: head = sha(number), base/branch synthetic, merged when the board says merged."""
    out = {}
    for repo in board["repos"]:
        for r in repo["rows"]:
            pid = mb.pr_id(r["pr"]); n = int(pid.split("#")[1])
            kw = dict(id=pid, head=sha(n), merged=(r["s"] == "merged"), merged_sha=sha(n + 1) if r["s"] == "merged" else None, draft=r["s"] in ("ai", "blocked"),
                      ci="success", checks={"pdf-review": "success", "gate / gate": "success", "build": "success"})
            kw.update(per_pr.get(pid, {}))
            out[pid] = mb.MigFacts(facts=github.PrFacts(**kw), branch="feature/%s" % r["t"].split()[0], title=r["t"])
    return out

class Build(unittest.TestCase):
    def setUp(self):
        self.board = mb.parse_board(FIX.read_text()); self.facts = fake_facts(self.board)
        self.cases = {"TP-001": {"MYD-18079"}, "TP-002": {"MYD-18079"}, "TP-060": {"MYD-18086"}, "TP-100": {"MYD-18081"}}

    def build(self, **kw):
        return mb.build_state(json.loads(json.dumps(BASE)), self.board, kw.pop("facts", self.facts), kw.pop("cfg", CFG), kw.pop("reports", {"PDF-REVIEW-13359.md", "PDF-REVIEW-13359-r2.md"}), self.cases, NOW)

    def test_state_shape_and_counts(self):
        data = self.build()
        self.assertEqual(sorted(data["stories"]), ["S1", "S2", "S6"]); self.assertEqual(len(data["prs"]), 41)  # 42 rows − pdffiller-knowledge
        self.assertNotIn("pdffiller-knowledge#1766", data["prs"])
        self.assertEqual(len(data["bugs"]), 27)
        json.loads(st_mod.dumps(data))  # serialisable through the CLI's writer
        for pid, pr in data["prs"].items():
            self.assertIn(pr["state"], rules.PR_STATES, pid); self.assertTrue(rules.valid_head(pr["head"]), pid)
            self.assertEqual(pr["jira"]["status"], rules.JIRA_FOR_PR_STATE[pr["state"]], pid)
            self.assertIn(pr["story"], data["stories"], pid); self.assertEqual(pr["branch"], self.facts[pid].branch)
        self.assertEqual(data["stories"]["S6"]["test_cases"], ["TP-001", "TP-002", "TP-060"])
        self.assertEqual(data["stories"]["S2"]["test_cases"], ["TP-001", "TP-002", "TP-060", "TP-100"])
        self.assertEqual(data["stories"]["S6"]["state"], "PLANNED"); self.assertEqual(data["stories"]["S1"]["state"], "IN_PROGRESS")
        self.assertTrue(any(a["type"] == "start_story" and a["story"] == "S6" for a in data["awaiting_human"]))

    def test_board_states_map_to_turnstile_states(self):
        data = self.build(); prs = data["prs"]
        self.assertEqual(prs["pdffiller#37651"]["state"], "MERGED"); self.assertEqual(prs["pdffiller#37651"]["merged_sha"], sha(37652))
        self.assertEqual(prs["pdffiller#37651"]["jira"], {"status": "On Hold", "synced": True})
        self.assertEqual(prs["front-link2fill-app#1198"]["state"], "AI_REVIEW")
        self.assertEqual(prs["jsfiller#13362"]["state"], "AI_REVIEW"); self.assertEqual(prs["jsfiller#13362"]["blocked_by"], "jsfiller#13359")
        self.assertEqual(prs["jsfiller#13359"]["state"], "READY")
        self.assertEqual(prs["docs-platform#5424"]["state"], "ON_HUMAN_REVIEW"); self.assertEqual(prs["docs-platform#5424"]["jira"], {"status": "On Review", "synced": False})

    def test_ready_with_permalink_is_rework_and_ready_opens_send(self):
        data = self.build(); prs = data["prs"]
        pr = prs["jsfiller#13223"]
        self.assertEqual(pr["state"], "REWORK"); self.assertEqual(pr["rework_since"]["head"], sha(13223)); self.assertIn("pushed after the send", pr["rework_since"]["reason"])
        self.assertEqual(pr["evidence"]["human"]["slack_permalink"], "https://pdffiller.slack.com/archives/CCGLRULNR/p1791806791768989")
        self.assertTrue(any(a["type"] == "reply" and a["pr"] == "jsfiller#13223" and not a.get("approved_at") for a in data["awaiting_human"]))
        self.assertTrue(any(a["type"] == "send" and a["pr"] == "jsfiller#13359" and a["head"] == sha(13359) and not a.get("approved_at") for a in data["awaiting_human"]))
        self.assertFalse(any(a["type"] == "send" and a["pr"] == "jsfiller#13223" for a in data["awaiting_human"]))

    def test_evidence_only_for_what_github_and_the_board_agree_on(self):
        facts = fake_facts(self.board, **{"jsfiller#13359": {"head": "ac6d2c03" + "0" * 32}, "jsfiller#13365": {"head": sha(13365)}})
        data = self.build(facts=facts); prs = data["prs"]
        ev = prs["jsfiller#13359"]["evidence"]  # board cr says pdf-review ✓ ac6d2c03 == live head → gate + deep review + ci + head_verified
        self.assertEqual(ev["gate"], {"name": "pdf-review", "head": "ac6d2c03" + "0" * 32, "result": "pass", "run": None})
        self.assertEqual(ev["deep_review"]["report"], "reports/PDF-REVIEW-13359-r2.md"); self.assertTrue(ev["deep_review"]["clean"])
        self.assertEqual(ev["ci"], {"head": "ac6d2c03" + "0" * 32, "status": "success"}); self.assertEqual(ev["head_verified"], {"head": "ac6d2c03" + "0" * 32, "verified": True, "at": NOW})
        self.assertNotIn("copilot", ev)  # jsfiller has copilot: false
        ev2 = prs["jsfiller#13365"]["evidence"]  # board cr names 45b41a66, live head differs → gate from GitHub check only, no deep review
        self.assertEqual(ev2["gate"]["result"], "pass"); self.assertNotIn("deep_review", ev2)
        self.assertEqual(prs["docs-platform#5424"]["evidence"]["copilot"], {"head": sha(5424), "open_threads": 0})
        self.assertNotIn("evidence", prs["pdffiller#37651"]) if "evidence" not in prs["pdffiller#37651"] else self.assertEqual(prs["pdffiller#37651"]["evidence"], {})

    def test_overrides_apply(self):
        data = self.build(); pr = data["prs"]["docs-platform#5425"]
        self.assertEqual(pr["state"], "REWORK"); self.assertEqual(pr["evidence"]["human"]["reviewers"], ["lMakDen"]); self.assertIn("lMakDen", pr["rework_since"]["reason"])

    def test_dep_resolution(self):
        rows = {mb.pr_id(r["pr"]): r for repo in self.board["repos"] for r in repo["rows"]}
        data = self.build(); prs = data["prs"]
        self.assertIsNone(prs["docs-platform#5424"]["blocked_by"])  # dep '#1172' is a merged front-link2fill-app PR
        self.assertEqual(mb.resolve_dep("#1172", "docs-platform", rows), "front-link2fill-app#1172")
        self.assertEqual(mb.resolve_dep("", "jsfiller", rows), None)
        with self.assertRaises(mb.MigrationError):
            mb.resolve_dep("#99999", "jsfiller", rows)

    def test_unknown_pr_refuses_whole_run(self):
        facts = dict(self.facts); del facts["jsfiller#13384"]
        with self.assertRaises(mb.MigrationError) as cm:
            self.build(facts=facts)
        self.assertIn("jsfiller#13384", str(cm.exception))

    def test_unassignable_pr_refuses(self):
        cfg = json.loads(json.dumps(CFG)); cfg["stories"]["S2"]["tickets"].remove("MYD-18081")
        with self.assertRaises(mb.MigrationError) as cm:
            self.build(cfg=cfg)
        self.assertIn("docs-platform#5424", str(cm.exception)); self.assertIn("MYD-18081", str(cm.exception))

    def test_bugs_follow_their_pr_story_else_default(self):
        data = self.build(); bugs = {b["id"]: b for b in data["bugs"]}
        self.assertEqual(bugs["b02"]["story"], "S6"); self.assertEqual(bugs["b02"]["pr"], "jsfiller#13384"); self.assertEqual(bugs["b02"]["state"], "testing")
        self.assertEqual(bugs["b16"]["story"], "S2"); self.assertIsNone(bugs["b16"]["pr"]); self.assertIsNone(bugs["b16"]["case"])
        self.assertEqual(bugs["b17"]["state"], "done"); self.assertEqual(bugs["b02"]["source"], "Давид, 08.10")
        self.assertTrue(all(b["runs"] == [] and b["created_at"] and b["updated_at"] for b in bugs.values()))

    def test_test_plan_cases(self):
        text = "| ID | Pre | Steps | Expected | Tickets | Arm | Pri |\n|---|---|---|---|---|---|---|\n| TP-001 | a | b | c | MYD-18079 | T | P1 |\n| TP-003 | a | b | c | MYD-18074, MYD-18076 | T | P2 |\n"
        self.assertEqual(mb.test_plan_cases(text), {"TP-001": {"MYD-18079"}, "TP-003": {"MYD-18074", "MYD-18076"}})

    def test_second_run_refused_without_force(self):
        base = json.loads(json.dumps(BASE)); base["prs"] = {"jsfiller#1": {"state": "DEV"}}
        with self.assertRaises(mb.MigrationError):
            mb.build_state(base, self.board, self.facts, CFG, set(), self.cases, NOW)
        data = mb.build_state(base, self.board, self.facts, CFG, set(), self.cases, NOW, force=True)
        self.assertNotIn("jsfiller#1", data["prs"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_migrate_board -v 2>&1 | tail -5`
Expected: `AttributeError: module 'migrate_board' has no attribute 'MigFacts'` (and friends) for every `Build` test; `Parse` still passes.

- [ ] **Step 3: Write the builder**

Append to `scripts/migrate_board.py`:

```python
BOARD_STATES = {"ai": "AI_REVIEW", "blocked": "AI_REVIEW", "ready": "READY", "human": "ON_HUMAN_REVIEW", "approved": "APPROVED",
                "merged": "MERGED", "dev": "DEV"}
CR_HEAD_RX = re.compile(r"pdf-review ✓ ([0-9a-f]{7,40})")
CR_ROUNDS_RX = re.compile(r"\((\d+) раунд|\(r(\d+)")
TP_RX = re.compile(r"^\| (TP-\d+) \|(?:[^|]*\|){3}([^|]*)\|", re.M)
QUERY2 = github.QUERY.replace("headRefOid", "headRefOid headRefName title", 1)

@dataclass
class MigFacts:
    facts: github.PrFacts
    branch: str
    title: str

def facts_from_payloads(raw: Dict[str, dict]) -> Dict[str, MigFacts]:
    return {pid: MigFacts(facts=github.parse(pid, p), branch=p.get("headRefName") or "", title=p.get("title") or "") for pid, p in raw.items()}

def fetch_payloads(pr_ids: List[str], org: str) -> Dict[str, dict]:
    out = {}
    for pid in sorted(pr_ids):
        repo, num = pid.split("#", 1)
        r = subprocess.run(["gh", "api", "graphql", "-f", "query=" + QUERY2, "-f", "o=" + org, "-f", "r=" + repo, "-F", "n=" + num], capture_output=True, text=True)
        if r.returncode != 0:
            raise MigrationError("gh api failed for %s: %s" % (pid, r.stderr.strip()[:200]))
        pr = json.loads(r.stdout)["data"]["repository"]["pullRequest"]
        if pr is None:
            raise MigrationError("%s does not exist on GitHub (org %s)" % (pid, org))
        out[pid] = pr
    return out

def fetch_facts(pr_ids: List[str], org: str) -> Dict[str, MigFacts]:
    return facts_from_payloads(fetch_payloads(pr_ids, org))

def test_plan_cases(text: str) -> Dict[str, set]:
    return {m.group(1): set(TICKET_RX.findall(m.group(2))) for m in TP_RX.finditer(text or "")}

def resolve_dep(dep: str, repo: str, rows_by_id: Dict[str, dict]) -> Optional[str]:
    dep = (dep or "").strip()
    if not dep:
        return None
    num = dep.lstrip("#")
    if "#" in dep and not dep.startswith("#"):
        cand = [pr_id(dep)] if PR_RX.match(dep) else [dep]
    else:
        cand = [pid for pid in rows_by_id if pid.endswith("#" + num)]
        same = [c for c in cand if c.startswith(repo + "#")]
        cand = same or cand
    if len(cand) != 1 or cand[0] not in rows_by_id:
        raise MigrationError("dep %r of a %s row matches %s board rows (need exactly one)" % (dep, repo, len(cand)))
    return cand[0]

def story_for(pid: str, ticket: str, cfg: dict) -> str:
    if pid in (cfg.get("pr_story") or {}):
        return cfg["pr_story"][pid]
    hits = [sid for sid, s in cfg["stories"].items() if ticket in s["tickets"]]
    if len(hits) != 1:
        raise MigrationError("%s (%s) matches %d stories by ticket (%s); add it to pr_story in the config" % (pid, ticket, len(hits), ", ".join(hits) or "none"))
    return hits[0]

def map_state(row: dict, f: MigFacts, override: dict):
    if override.get("state"):
        return override["state"], override.get("reason") or "migrated: config override"
    if f.facts.merged or row["s"] == "merged":
        return "MERGED", None
    if row["s"] not in BOARD_STATES:
        raise MigrationError("board status %r on %s has no turnstile state" % (row["s"], row["pr"]))
    st = BOARD_STATES[row["s"]]
    if st == "READY" and row.get("slack"):
        return "REWORK", "migrated: pushed after the send of %s (board: Ready, reviewers not notified)" % row["slack"]
    if st == "ON_HUMAN_REVIEW" and (f.facts.human_threads_open or f.facts.changes_requested):
        return "REWORK", "migrated: %d unresolved human thread(s)%s" % (f.facts.human_threads_open, ", changes requested by " + ", ".join(f.facts.changes_requested) if f.facts.changes_requested else "")
    return st, None

def _latest_report(reports: set, num: str) -> Optional[str]:
    names = sorted(n for n in reports if re.match(r"PDF-REVIEW-%s(-r\d+)?\.md$" % num, n))
    return "reports/" + names[-1] if names else None

def _evidence(pid: str, row: dict, f: MigFacts, st: str, repo_cfg: dict, reports: set, now: str) -> dict:
    head = f.facts.head.lower(); ev = {}
    if st == "MERGED":
        return ev
    ev["head_verified"] = {"head": head, "verified": True, "at": now}
    gate, gate_check = repo_cfg.get("gate"), repo_cfg.get("gate_check") if "gate_check" in repo_cfg else repo_cfg.get("gate")
    ci = f.facts.ci_without(repo_cfg.get("ci_ignore") or []) if st == "AI_REVIEW" else f.facts.ci
    if ci in ("success", "failure"):
        ev["ci"] = {"head": head, "status": ci}
    m = CR_HEAD_RX.search(row.get("cr") or "")
    board_claims = bool(m) and rules.same_head(m.group(1), head)
    if gate and (board_claims or (gate_check and f.facts.checks.get(gate_check) == "success")):
        ev["gate"] = {"name": gate, "head": head, "result": "pass", "run": None}
    report = _latest_report(reports, pid.split("#")[1])
    if board_claims and report:
        r = CR_ROUNDS_RX.search(row.get("cr") or "")
        ev["deep_review"] = {"head": head, "report": report, "rounds": int(r.group(1) or r.group(2)) if r else 1, "clean": True}
    if repo_cfg.get("copilot") and f.facts.copilot_threads_open == 0:
        ev["copilot"] = {"head": head, "open_threads": 0}
    return ev

def build_state(base: dict, board: dict, facts: Dict[str, MigFacts], cfg: dict, reports: set, test_cases: Dict[str, set], now: str, force: bool = False) -> dict:
    data = json.loads(json.dumps(base))
    if (data.get("prs") or data.get("stories") or data.get("bugs")) and not force:
        raise MigrationError("state.json already holds prs/stories/bugs; re-run with --force to rebuild it from the board")
    data["prs"], data["bugs"], data["awaiting_human"] = {}, [], []
    skip = set(cfg.get("skip_repos") or [])
    data["stories"] = {}
    for sid, s in cfg["stories"].items():
        story = {k: s.get(k, d) for k, d in (("title", ""), ("tickets", []), ("repos", []), ("branch", ""), ("after", []), ("parallel_with", []),
                                               ("figma", []), ("env_slot", {}), ("human_review_units", []))}
        if s.get("human_review"):
            story["human_review"] = s["human_review"]
        if s.get("state", "PLANNED") not in rules.STORY_STATES:
            raise MigrationError("story %s: state %r is not one of %s" % (sid, s.get("state"), ", ".join(rules.STORY_STATES)))
        tickets = set(s.get("test_cases_from_tickets") or s["tickets"])
        story["test_cases"] = sorted(c for c, t in test_cases.items() if t & tickets)
        story.update({"state": s.get("state", "PLANNED"), "evidence": {}, "next_action": "", "last_reason": "migrated from pr-board.html on %s" % now[:10]})
        data["stories"][sid] = story
    rows_by_id, row_repo = {}, {}
    for repo in board["repos"]:
        for row in repo["rows"]:
            pid = pr_id(row["pr"]); rows_by_id[pid] = row; row_repo[pid] = pid.split("#")[0]
    for pid, row in rows_by_id.items():
        repo = row_repo[pid]
        if repo in skip:
            continue
        if pid not in facts:
            raise MigrationError("no GitHub facts for %s (fetch failed or the PR is gone); nothing written" % pid)
        if repo not in data["epic"]["repos"]:
            raise MigrationError("repo %s of %s is not in epic.repos (add it at init or to skip_repos)" % (repo, pid))
        f, repo_cfg = facts[pid], data["epic"]["repos"][repo]
        override = (cfg.get("pr_overrides") or {}).get(pid) or {}
        ticket = ticket_of(row["t"]); st, reason = map_state(row, f, override)
        pr = {"ticket": ticket, "story": story_for(pid, ticket, cfg), "branch": f.branch, "base": f.facts.base, "state": st, "head": f.facts.head.lower(),
              "blocked_by": None, "evidence": _evidence(pid, row, f, st, repo_cfg, reports, now),
              "jira": {"status": rules.JIRA_FOR_PR_STATE[st], "synced": st == "MERGED"}, "next_action": "", "_dep": row.get("dep") or ""}
        if st == "MERGED":
            pr["merged_sha"] = f.facts.merged_sha
        if reason:
            pr["last_reason"] = reason
        if row.get("slack") and st != "MERGED":
            pr["evidence"]["human"] = {"head": pr["head"], "slack_permalink": row["slack"], "reviewers": list(override.get("reviewers") or []),
                                       "sent_head": override.get("sent_head") or (pr["head"] if st in ("ON_HUMAN_REVIEW", "APPROVED") else None),
                                       "approved": None, "open_threads": f.facts.human_threads_open, "approvals": list(f.facts.approvals), "sent_at": None}
        if st == "REWORK":
            pr["rework_since"] = {"head": pr["head"], "at": now, "reason": reason}
        data["prs"][pid] = pr
    for pid, pr in data["prs"].items():
        dep = resolve_dep(pr.pop("_dep"), pid.split("#")[0], rows_by_id)
        pr["blocked_by"] = dep if dep and dep in data["prs"] and data["prs"][dep]["state"] != "MERGED" else None
        if pr["state"] == "READY":
            pass_cmd._open_entry(data, "send", pr=pid, head=pr["head"])
        if pr["state"] == "REWORK":
            pass_cmd._open_entry(data, "reply", pr=pid, head=pr["head"])
    default_story = cfg.get("bug_story_default")
    for b in board["bugs"]:
        bpr = pr_id(b["pr"]) if b.get("pr") else None
        sid = data["prs"][bpr]["story"] if bpr and bpr in data["prs"] else default_story
        if sid not in data["stories"]:
            raise MigrationError("bug %s: story %r unknown (set bug_story_default)" % (b["id"], sid))
        if b["s"] not in ("todo", "ai", "testing", "done"):
            raise MigrationError("bug %s has board status %r" % (b["id"], b["s"]))
        stamp = now + ":00Z" if len(now) == 17 else now
        data["bugs"].append({"id": b["id"], "story": sid, "case": None, "title": b["t"], "source": b.get("src") or "", "pr": bpr, "figma": None,
                             "state": b["s"], "note": b.get("note") or "", "runs": [], "created_at": stamp, "updated_at": stamp})
    pass_cmd._ensure_start_story_entries(data)
    pass_cmd._recompute_next_actions(data)
    return data
```

Note on `stamp`: `pass_cmd._now()` yields `2026-10-14T12:00Z` (17 characters); bug stamps need seconds (`_now_s`), so the builder derives `…:00Z` from a minute-precision `now`, and the CLI entry point (Task 4) passes `_now()`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_migrate_board -v 2>&1 | tail -16`
Expected: all `Parse` and `Build` tests `ok`. If `test_state_shape_and_counts` fails on the S2 case list, the fixture's `TP-100` maps to `MYD-18081`, which is in S2's tickets: check `story["test_cases"]` sorts as strings.

- [ ] **Step 5: Commit**

```bash
cd /Users/davyd/Desktop/pdffiller/l2f-editor-funnel/turnstile && git pull -q --ff-only
git add scripts/migrate_board.py tests/test_migrate_board.py tests/fixtures/migrate_config.json
git commit -m "feat(migrate): build state.json from board rows, GitHub facts and a story config (states, evidence, deps, bugs, entries)"
```

---

### Task 4: `migrate_board.py` — decisions.md, the `turnstile-stories` block, the command line

**Files:**
- Modify: `scripts/migrate_board.py` (append `decisions_md`, `stories_block`, `main`)
- Test: `tests/test_migrate_board.py` (`class Decisions`, `class Cli`)

**Interfaces:**
- Produces: `decisions_md(claude_md: str, today: str) -> str` (the init template's two tables filled from the CLAUDE.md "Decisions already taken" and "Rulings" tables and the "Open inputs from humans" list); `stories_block(cfg) -> dict` (the JSON for plan.md § 7: keys `title, tickets, repos, branch, after, parallel_with, test_cases, figma, env_slot, human_review_units[, human_review]`, with `test_cases` taken from the built state); CLI:

```
python3 scripts/migrate_board.py --delivery <dir> --board <pr-board.html> --config <json> [--test-plan <test-plan.md>] [--claude-md <CLAUDE.md>]
                                 (--fetch | --facts <payloads.json>) [--facts-out <payloads.json>] [--force] [--no-commit] [--print-stories-block]
```
Exit 0 with `OK migrated …` as the last line; exit 2 with `MISSING …` and nothing written on any `MigrationError`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_migrate_board.py`:

```python
import os, shutil, subprocess, sys, tempfile
CLAUDE_MD = """# x
## Decisions already taken (do not reopen)

| Topic | Decision |
|---|---|
| Modal ownership | Reusable module `@pdffiller/front-l2f-modal-interface`. |
| CTA tabs (2026-09-22, Davyd) | Create form only. |

## Rulings from the gap / test-plan review (2026-09-18)

| Ruling | Decision (short) | Affects |
|---|---|---|
| R-1 | Five toggles. | 18064 |

## Open inputs from humans (do not block on them, note where they land)

- PM: AB Tower report (18061, 18063).
- Design (Vlad Grekov): spreadsheet copy.
"""

class Decisions(unittest.TestCase):
    def test_tables_become_decisions_and_open_questions(self):
        text = mb.decisions_md(CLAUDE_MD, "2026-10-14")
        self.assertTrue(text.startswith("# Decisions — MYD-16538\n\n| Date | Topic | Decision | Source |"))
        self.assertIn("| 2026-09-22 | CTA tabs | Create form only. | workspace CLAUDE.md (Davyd) |", text)
        self.assertIn("| ≤2026-10-14 | Modal ownership | Reusable module `@pdffiller/front-l2f-modal-interface`. | workspace CLAUDE.md |", text)
        self.assertIn("| 2026-09-18 | R-1 | Five toggles. (affects 18064) | gap / test-plan review ruling |", text)
        self.assertIn("## Open questions", text); self.assertIn("| 1 | AB Tower report (18061, 18063). | PM | ≤2026-10-14 | |", text)
        self.assertIn("| 2 | spreadsheet copy. | Design (Vlad Grekov) | ≤2026-10-14 | |", text)

class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve(); self.d = self.tmp / "delivery"; (self.d / "reports").mkdir(parents=True)
        base = json.loads(json.dumps(BASE)); (self.d / "state.json").write_text(st_mod.dumps(base)); (self.d / "ledger.md").write_text("# L\n")
        (self.d / "reports" / "PDF-REVIEW-13359.md").write_text("clean")
        board = mb.parse_board(FIX.read_text())
        payload = json.loads((ROOT / "tests" / "fixtures" / "gh_pr_13222.json").read_text())
        raw = {}
        for repo in board["repos"]:
            for r in repo["rows"]:
                pid = mb.pr_id(r["pr"]); n = int(pid.split("#")[1]); p = json.loads(json.dumps(payload))
                p.update({"headRefOid": sha(n), "headRefName": "feature/x-%d" % n, "title": r["t"], "merged": r["s"] == "merged", "isDraft": False,
                          "mergeCommit": {"oid": sha(n + 1)} if r["s"] == "merged" else None, "baseRefName": "epic"})
                raw[pid] = p
        self.facts = self.tmp / "facts.json"; self.facts.write_text(json.dumps(raw))
        (self.tmp / "CLAUDE.md").write_text(CLAUDE_MD)
        (self.tmp / "tp.md").write_text("| ID | a | b | c | Tickets | Arm | Pri |\n|---|---|---|---|---|---|---|\n| TP-001 | a | b | c | MYD-18079 | T | P1 |\n")
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "add", "."], cwd=self.tmp, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-qm", "init"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.tmp, check=True)

    def run_cli(self, *extra):
        args = [sys.executable, str(ROOT / "scripts" / "migrate_board.py"), "--delivery", str(self.d), "--board", str(FIX), "--config", str(ROOT / "tests" / "fixtures" / "migrate_config.json"),
                "--test-plan", str(self.tmp / "tp.md"), "--claude-md", str(self.tmp / "CLAUDE.md"), "--facts", str(self.facts)] + list(extra)
        return subprocess.run(args, capture_output=True, text=True, env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))

    def test_writes_state_ledger_decisions_board_and_commits(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertTrue(r.stdout.strip().splitlines()[-1].startswith("OK migrated 41 PRs, 3 stories, 27 bugs"))
        data = json.loads((self.d / "state.json").read_text()); self.assertEqual(len(data["prs"]), 41)
        self.assertIn("migrated from pr-board.html (updated 2026-10-14 06:07 Kyiv)", (self.d / "ledger.md").read_text())
        self.assertTrue((self.d / "decisions.md").read_text().startswith("# Decisions — MYD-16538")); self.assertTrue((self.d / "board.html").exists())
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.tmp, capture_output=True, text=True).stdout
        self.assertIn("turnstile: migrate MYD-16538 from pr-board.html", log)
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=self.tmp, capture_output=True, text=True).stdout, "")
        r2 = self.run_cli(); self.assertEqual(r2.returncode, 2); self.assertIn("MISSING state.json already holds", r2.stdout)
        r3 = self.run_cli("--force", "--print-stories-block"); self.assertEqual(r3.returncode, 0, r3.stdout)
        block = json.loads(r3.stdout.split("```json turnstile-stories\n", 1)[1].split("\n```", 1)[0])
        self.assertEqual(sorted(block), ["S1", "S2", "S6"]); self.assertEqual(block["S6"]["branch"], "feature/MYD-18076-l2f-header-autotests"); self.assertEqual(block["S6"]["test_cases"], ["TP-001"])
        self.assertNotIn("state", block["S6"])

    def test_refuses_without_facts_and_writes_nothing(self):
        before = (self.d / "state.json").read_text()
        raw = json.loads(self.facts.read_text()); del raw["jsfiller#13222"]; self.facts.write_text(json.dumps(raw))
        r = self.run_cli(); self.assertEqual(r.returncode, 2); self.assertIn("MISSING no GitHub facts for jsfiller#13222", r.stdout)
        self.assertEqual((self.d / "state.json").read_text(), before); self.assertFalse((self.d / "board.html").exists())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_migrate_board.Decisions tests.test_migrate_board.Cli -v 2>&1 | tail -5`
Expected: `AttributeError: … 'decisions_md'`; the CLI test fails with a non-zero exit (`argparse` unknown options) or an `AttributeError` traceback.

- [ ] **Step 3: Write decisions, the stories block and `main`**

Append to `scripts/migrate_board.py`:

```python
DATE_IN_TOPIC = re.compile(r"\((\d{4}-\d{2}-\d{2})(?:,\s*([^)]*))?\)")

def _table_rows(section: str) -> List[List[str]]:
    rows = []
    for line in section.splitlines():
        if line.startswith("|") and not re.match(r"^\|\s*-", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.append(cells)
    return rows[1:] if rows else []  # drop the header row

def _section(text: str, heading_start: str) -> str:
    m = re.search(r"^## %s.*?(?=^## |\Z)" % re.escape(heading_start), text, re.S | re.M)
    return m.group(0) if m else ""

def decisions_md(claude_md: str, today: str, epic: str = "MYD-16538") -> str:
    out = ["# Decisions — %s" % epic, "", "| Date | Topic | Decision | Source |", "|---|---|---|---|"]
    for cells in _table_rows(_section(claude_md, "Decisions already taken")):
        if len(cells) < 2:
            continue
        topic, decision = cells[0], cells[1]
        m = DATE_IN_TOPIC.search(topic)
        date = m.group(1) if m else "≤" + today
        who = (" (%s)" % m.group(2)) if m and m.group(2) else ""
        topic = DATE_IN_TOPIC.sub("", topic).strip()
        out.append("| %s | %s | %s | workspace CLAUDE.md%s |" % (date, topic, decision, who))
    sec = _section(claude_md, "Rulings from the gap / test-plan review")
    m = re.search(r"\((\d{4}-\d{2}-\d{2})\)", sec)
    rdate = m.group(1) if m else "≤" + today
    for cells in _table_rows(sec):
        if len(cells) >= 2 and cells[0].startswith("R-"):
            affects = (" (affects %s)" % cells[2]) if len(cells) > 2 and cells[2] not in ("", "—") else ""
            out.append("| %s | %s | %s%s | gap / test-plan review ruling |" % (rdate, cells[0], cells[1], affects))
    out += ["", "## Open questions", "", "| # | Question | Owner | Asked | Answer |", "|---|---|---|---|---|"]
    n = 0
    for line in _section(claude_md, "Open inputs from humans").splitlines():
        mm = re.match(r"^- ([^:]+): (.+)$", line.strip())
        if mm:
            n += 1; out.append("| %d | %s | %s | ≤%s | |" % (n, mm.group(2).strip(), mm.group(1).strip(), today))
    return "\n".join(out) + "\n"

def stories_block(cfg: dict, built: dict) -> dict:
    keys = ("title", "tickets", "repos", "branch", "after", "parallel_with", "figma", "env_slot", "human_review_units")
    out = {}
    for sid, s in cfg["stories"].items():
        o = {k: s.get(k, [] if k in ("tickets", "repos", "after", "parallel_with", "figma", "human_review_units") else ({} if k == "env_slot" else "")) for k in keys}
        o["test_cases"] = built["stories"][sid]["test_cases"]
        if s.get("human_review"):
            o["human_review"] = s["human_review"]
        out[sid] = o
    return out

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="migrate_board", description="one-off: legacy pr-board.html → delivery/state.json")
    p.add_argument("--delivery", required=True); p.add_argument("--board", required=True); p.add_argument("--config", required=True)
    p.add_argument("--test-plan"); p.add_argument("--claude-md")
    g = p.add_mutually_exclusive_group(required=True); g.add_argument("--fetch", action="store_true"); g.add_argument("--facts")
    p.add_argument("--facts-out"); p.add_argument("--force", action="store_true"); p.add_argument("--no-commit", action="store_true")
    p.add_argument("--print-stories-block", action="store_true")
    a = p.parse_args(argv)
    try:
        delivery = pathlib.Path(a.delivery).resolve()
        st = st_mod.load(delivery / "state.json")
        epic = st.data["epic"]; org = rules.require_org(st.data)
        board_data = parse_board(pathlib.Path(a.board).read_text())
        cfg = json.loads(pathlib.Path(a.config).read_text())
        skip = set(cfg.get("skip_repos") or [])
        ids = sorted({pr_id(r["pr"]) for repo in board_data["repos"] for r in repo["rows"] if pr_id(r["pr"]).split("#")[0] not in skip})
        if a.fetch:
            raw = fetch_payloads(ids, org)
            if a.facts_out:
                pathlib.Path(a.facts_out).write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
        else:
            raw = json.loads(pathlib.Path(a.facts).read_text())
        facts = facts_from_payloads(raw)
        cases = test_plan_cases(pathlib.Path(a.test_plan).read_text()) if a.test_plan else {}
        reports = {q.name for q in (delivery / "reports").glob("*.md")} if (delivery / "reports").exists() else set()
        now = pass_cmd._now()
        data = build_state(st.data, board_data, facts, cfg, reports, cases, now, force=a.force)
        if (epic.get("board") or {}).get("artifact_url") is None and cfg.get("board_url"):
            data["epic"].setdefault("board", {})["artifact_url"] = cfg["board_url"]
        with st_mod.locked(delivery):
            st.data = data; st_mod.save(st)
            if a.claude_md:
                (delivery / "decisions.md").write_text(decisions_md(pathlib.Path(a.claude_md).read_text(), now[:10], epic.get("key") or ""))
            summary = "migrated from pr-board.html (updated %s): %d PRs, %d stories, %d bugs; config %s" % (board_data["updated"], len(data["prs"]), len(data["stories"]), len(data["bugs"]), a.config)
            ledger.append(delivery, summary)
            board.render(data, delivery)
            pass_cmd._ensure_repo_files(delivery)
            if not a.no_commit:
                pass_cmd.IO().git_commit(delivery, "turnstile: migrate %s from pr-board.html" % (epic.get("key") or ""))
        if a.print_stories_block:
            print("```json turnstile-stories\n%s\n```" % json.dumps(stories_block(cfg, data), indent=2, ensure_ascii=False))
        print("NEXT: turnstile reconcile; write plan.md (stories block above); turnstile plan-submitted")
        print("OK migrated %d PRs, %d stories, %d bugs into %s" % (len(data["prs"]), len(data["stories"]), len(data["bugs"]), delivery / "state.json"))
        return 0
    except (MigrationError, Exception) as e:
        if isinstance(e, SystemExit):
            raise
        print("MISSING %s" % e); return 2

if __name__ == "__main__":
    sys.exit(main())
```

Also make the script executable: `chmod +x scripts/migrate_board.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_migrate_board -v 2>&1 | tail -20 && python3 -m unittest discover -s tests 2>&1 | tail -3`
Expected: all `test_migrate_board` tests `ok`; the whole suite `OK` (261 + 18 = 279 or close — count, do not guess, and write the number into the commit message).

- [ ] **Step 5: Commit**

```bash
cd /Users/davyd/Desktop/pdffiller/l2f-editor-funnel/turnstile && git pull -q --ff-only
git add scripts/migrate_board.py tests/test_migrate_board.py
git commit -m "feat(migrate): decisions.md from the workspace CLAUDE.md tables, turnstile-stories block, command line with --fetch/--facts and a guarded commit"
```

---

### Task 5: `scripts/vendor.sh`, `Makefile`, `VENDORED_FROM` (scope C, plugin side)

**Files:**
- Create: `scripts/vendor.sh`, `Makefile`, `tests/test_vendor.py`

**Interfaces:**
- Produces: `scripts/vendor.sh <tag> <dest-dir>` — exports the plugin files of `<tag>` from this repo's git into `<dest-dir>` (emptied first except `VENDORED_FROM`), writes `VENDORED_FROM` (`repo`, `tag`, `commit`, `date`, `command`), exit non-zero on an unknown tag or a dirty destination outside a git repo; `make vendor TAG=v0.3.0 DEST=/path` wraps it. Exported paths: `.claude-plugin agents hooks skills templates scripts turnstile_cli tests README.md LICENSE` (not `docs/`, not `.superpowers/`, not `.gitignore`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_vendor.py`:

```python
import pathlib, shutil, subprocess, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class Vendor(unittest.TestCase):
    def setUp(self):
        self.dest = pathlib.Path(tempfile.mkdtemp()) / "turnstile"
        self.tag = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    def test_vendor_copies_plugin_files_and_stamps_vendored_from(self):
        r = subprocess.run(["sh", str(ROOT / "scripts" / "vendor.sh"), self.tag, str(self.dest)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for rel in (".claude-plugin/plugin.json", "agents/tester.md", "hooks/hooks.json", "hooks/guard_bash.py", "skills/turnstile/SKILL.md",
                    "templates/board.html", "scripts/turnstile", "turnstile_cli/main.py", "tests/test_pass.py", "README.md", "LICENSE", "VENDORED_FROM"):
            self.assertTrue((self.dest / rel).exists(), rel)
        self.assertFalse((self.dest / "docs").exists()); self.assertFalse((self.dest / ".superpowers").exists())
        stamp = (self.dest / "VENDORED_FROM").read_text()
        self.assertIn("repo: https://github.com/davepylypenko/turnstile", stamp); self.assertIn("tag: %s" % self.tag, stamp)
        self.assertRegex(stamp, r"commit: [0-9a-f]{40}"); self.assertIn("command: scripts/vendor.sh %s" % self.tag, stamp)
        self.assertTrue((self.dest / "scripts" / "turnstile").stat().st_mode & 0o111, "scripts/turnstile must stay executable")
        (self.dest / "stale.txt").write_text("x")
        r = subprocess.run(["sh", str(ROOT / "scripts" / "vendor.sh"), self.tag, str(self.dest)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertFalse((self.dest / "stale.txt").exists(), "a re-vendor replaces the tree")

    def test_unknown_tag_fails(self):
        r = subprocess.run(["sh", str(ROOT / "scripts" / "vendor.sh"), "v0.0.0-nope", str(self.dest)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0); self.assertIn("v0.0.0-nope", r.stderr); self.assertFalse(self.dest.exists())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_vendor -v 2>&1 | tail -4`
Expected: FAIL — `sh: …/scripts/vendor.sh: No such file or directory` (non-zero exit).

- [ ] **Step 3: Write `scripts/vendor.sh` and the `Makefile`**

`scripts/vendor.sh`:

```sh
#!/bin/sh
# Vendor a tagged turnstile release into another repository: scripts/vendor.sh <tag> <dest-dir>
# Copies the plugin files of <tag> from this repo's git history (never the working tree), replaces <dest-dir>, stamps VENDORED_FROM.
set -eu
TAG="${1:?usage: vendor.sh <tag> <dest-dir>}"; DEST="${2:?usage: vendor.sh <tag> <dest-dir>}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO_URL="https://github.com/davepylypenko/turnstile"
PATHS=".claude-plugin agents hooks skills templates scripts turnstile_cli tests README.md LICENSE"
if ! COMMIT="$(git -C "$HERE" rev-list -n 1 "$TAG" 2>/dev/null)"; then
  echo "vendor.sh: unknown tag $TAG in $HERE" >&2; exit 2
fi
case "$DEST" in /*) ;; *) DEST="$(pwd)/$DEST" ;; esac
rm -rf "$DEST"; mkdir -p "$DEST"
# shellcheck disable=SC2086
git -C "$HERE" archive --format=tar "$TAG" -- $PATHS | tar -x -C "$DEST"
{
  echo "repo: $REPO_URL"; echo "tag: $TAG"; echo "commit: $COMMIT"
  echo "date: $(date -u +%Y-%m-%dT%H:%MZ)"; echo "command: scripts/vendor.sh $TAG <dest>"
  echo "note: do not edit here; change the canonical repo, tag, re-vendor"
} > "$DEST/VENDORED_FROM"
echo "vendored $TAG ($COMMIT) into $DEST"
```

`Makefile`:

```make
TAG ?= $(shell git describe --tags --abbrev=0)
DEST ?= ../pdffiller-knowledge/plugins/turnstile

.PHONY: test vendor
test:
	python3 -m unittest discover -s tests

vendor:
	sh scripts/vendor.sh $(TAG) $(DEST)
```

`chmod +x scripts/vendor.sh`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_vendor -v 2>&1 | tail -4 && make test 2>&1 | tail -2`
Expected: 2 tests `ok`; `make test` ends with `OK`. (`git archive` keeps file modes, so `scripts/turnstile` stays executable.)

- [ ] **Step 5: Commit**

```bash
cd /Users/davyd/Desktop/pdffiller/l2f-editor-funnel/turnstile && git pull -q --ff-only
git add scripts/vendor.sh Makefile tests/test_vendor.py
git commit -m "feat(vendor): vendor.sh exports a tag into another repo with a VENDORED_FROM stamp; make vendor/test"
```

---

### Task 6: README, plugin version 0.3.0, tag

**Files:**
- Modify: `README.md` (new sections "Migrating a running epic" and "Vendoring into a team repo"; the tester line in "What you get"), `.claude-plugin/plugin.json` (`"version": "0.3.0"`), `turnstile_cli/__init__.py` (`__version__ = "0.3.0"`)
- Test: `tests/test_cli_smoke.py` (version assertion, if it has one — read it first)

- [ ] **Step 1: Edit README.md**

After "## Usage" add:

```markdown
## Migrating a running epic

`scripts/migrate_board.py` turns a legacy board (`pr-board.html` with `STATUS`/`EPIC_PRS`/`REPOS`/`BUGS` JS arrays) into
`delivery/state.json`: states from the board, heads/bases/branches/threads/checks from GitHub, stories from a config file
kept in the delivery dir (`briefs/MIGRATE-<date>.json`), test cases from the test plan's ticket column, `decisions.md`
from the old workspace `CLAUDE.md`. It writes nothing on any error. The lead runs it from a terminal (the hooks' `delivery-write`
rule reserves `state.json` for `turnstile` commands), then `turnstile reconcile` must report zero unexplained
discrepancies before anything else happens. Full runbook: `docs/superpowers/plans/2026-10-14-turnstile-migration.md` Task 8.

## Vendoring into a team repo

`make vendor TAG=v0.3.0 DEST=/path/to/team-repo/plugins/turnstile` copies the tagged plugin files (never the working tree)
and writes `VENDORED_FROM` (repo, tag, commit, date). Edits go to this repo; the team copy is replaced by the next
`make vendor`. The team installs it from the team repo's marketplace (`claude plugin install turnstile@<marketplace>`) or
with `claude --plugin-dir <path>`.
```

In "## What you get" replace the role-agents bullet's tester mention (or add a bullet): "Tester credentials never touch a file: the tester reads `TURNSTILE_TEST_PASSWORD` or the keychain item `turnstile-test-password` at login."

- [ ] **Step 2: Bump the version**

`.claude-plugin/plugin.json`: `"version": "0.3.0"`. `turnstile_cli/__init__.py`: `__version__ = "0.3.0"`. If `tests/test_cli_smoke.py` asserts the version string, update it.

- [ ] **Step 3: Run the suite and the plugin validator**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -2 && claude plugin validate . && scripts/turnstile --version`
Expected: `OK`; `✔ Plugin manifest is valid` (or the validator's success line); `turnstile 0.3.0`.

- [ ] **Step 4: Commit, tag, push**

```bash
cd /Users/davyd/Desktop/pdffiller/l2f-editor-funnel/turnstile && git pull -q --ff-only
git add README.md .claude-plugin/plugin.json turnstile_cli/__init__.py tests/test_cli_smoke.py
git commit -m "docs(readme): migrating a running epic, vendoring; version 0.3.0"
git tag -s v0.3.0 -m "turnstile 0.3.0: tester credentials, migrate_board, vendor"   # signed tag; the lead's SSH key signs it
git push && git push origin v0.3.0
gh api repos/davepylypenko/turnstile/commits/v0.3.0 --jq '.commit.verification.verified'
```
Expected last line: `true`.

---

### Task 7: Pre-cut-over live checks (scope A) — the lead runs these; an agent prepares the sandbox and records the results

**Files:**
- Create: `docs/superpowers/reviews/2026-10-14-live-checks.md` (results table, filled by the lead's words; the agent only writes what the lead reports)

**Setup (lead, terminal — not through Claude):** a throwaway workspace with the plugin loaded from the tag.

```bash
export TS=/Users/davyd/Desktop/pdffiller/l2f-editor-funnel/turnstile
rm -rf /tmp/ts-live && mkdir -p /tmp/ts-live/delivery/reports && cd /tmp/ts-live
python3 - <<'EOF'
import json
s = json.load(open("/Users/davyd/Desktop/pdffiller/l2f-editor-funnel/turnstile/tests/fixtures/state_min.json"))
s["epic"]["repos"]["jsfiller"]["slack"] = "<SANDBOX_CHANNEL_ID>"          # a private test channel the lead owns, never a team channel
s["stories"]["S1"]["human_review"] = "per_pr"
pr = s["prs"]["jsfiller#1"]; pr["state"] = "READY"
pr["evidence"] = {"ci": {"head": pr["head"], "status": "success"}, "head_verified": {"head": pr["head"], "verified": True, "at": "2026-10-14T00:00Z"},
                  "deep_review": {"head": pr["head"], "report": "reports/R.md", "rounds": 1, "clean": True}, "gate": {"name": "pdf-review", "head": pr["head"], "result": "pass", "run": None}}
s["awaiting_human"] = [{"id": "ah-1", "owner": "lead", "type": "send", "pr": "jsfiller#1", "head": pr["head"], "created_at": "2026-10-14T00:00Z", "payload": None,
                        "approved_at": "2026-10-14T00:01Z", "approved_via": "lead-terminal"},
                       {"id": "ah-2", "owner": "lead", "type": "send", "pr": "jsfiller#1", "head": pr["head"], "created_at": "2026-10-14T00:00Z", "payload": None, "approved_at": None}]
json.dump(s, open("delivery/state.json", "w"), indent=2, sort_keys=True)
EOF
echo clean > delivery/reports/R.md; echo delivery > .turnstile; touch delivery/.state.lock
printf -- "- 2026-10-14 00:01 UTC approved ah-1 (send jsfiller#1 by lead) approved_via: lead-terminal\n" > delivery/ledger.md
git init -q && git add -A && git -c commit.gpgsign=false commit -qm init
export PATH="$TS/scripts:$PATH"
claude --dangerously-skip-permissions --plugin-dir "$TS"
```

Every check below is typed into **that** session. "Expected" is what the lead must see; anything else is a failure to record verbatim.

- [ ] **Check 1 — `ask` prompts under `bypassPermissions`.** Prompt: `Call the Slack send tool with channel_id <SANDBOX_CHANNEL_ID> and text "turnstile live check 1: https://github.com/pdffiller/jsfiller/pull/1". Do not post anything else.`
  Expected: a permission dialog with the reason `turnstile: lead, confirm this Slack send for jsfiller#1` appears **despite bypass mode**. Choose **Deny**. Then in a second terminal: `grep -c used_at /tmp/ts-live/delivery/state.json` → `0`, and the channel has no message. **If no dialog appears and the message lands, stop: the verdict for the migration is "no" (core review Round 3, R3-1) — report to the lead and do not continue to Task 8.**
- [ ] **Check 2 — a background subagent's send is denied.** Prompt: `Launch a general-purpose subagent in the background whose only task is to call the Slack send tool with channel_id <SANDBOX_CHANNEL_ID> and text "turnstile live check 2: https://github.com/pdffiller/jsfiller/pull/1", then report the tool result verbatim.`
  Expected: the subagent reports a denied/permission-required tool result (no prompt is shown to a background agent, so `ask` resolves to deny); no message in the channel; `grep -c used_at …/state.json` still `0`. Negative control for the recorder: the same prompt but in the foreground (`Agent` without background) → the dialog from check 1 appears; deny it.
- [ ] **Check 3 — `!` lines skip PreToolUse; the model cannot approve.** Prompt line: `! TURNSTILE_LEAD=1 turnstile approve ah-2`
  Expected output: `OK approved ah-2 (send jsfiller#1 by lead) approved_via: lead-terminal` and a new commit `turnstile: approved ah-2 …` in `git -C /tmp/ts-live log --oneline -1`. Then prompt: `Run exactly this in Bash: TURNSTILE_LEAD=1 turnstile approve ah-2` → Expected: the tool call is refused with `blocked by rule lead-approve`. If the `!` line itself is blocked, the lead approves from a separate terminal (`cd /tmp/ts-live && TURNSTILE_LEAD=1 turnstile approve ah-2`) and the README "How the lead approves" gets that sentence in Task 8 step 16's follow-up commit.
- [ ] **Check 4 — one dry run per agent on a sandbox branch; the repo gate skill runs without the `Agent` tool.** Sandbox: `gh repo create davepylypenko/turnstile-sandbox --private --clone` with a 10-line Node package (`package.json` with `"test": "node --test"`, one `sum.js`, one failing-then-passing test), a `CLAUDE.md` saying "run `npm test`", pushed to `main`. In `/tmp/ts-live`: `turnstile init --epic MYD-0 --workitem sandbox --knowledge <a clone of turnstile-sandbox outside /tmp/ts-live> --lead davyd.pylypenko --lead-github davepylypenko --github-org davepylypenko --repo '{"name":"turnstile-sandbox","base":"main","epic_branch":"main","slack":"<SANDBOX_CHANNEL_ID>","gate":null,"gate_check":null}' --workspace /tmp/ts-live-sandbox --chat-language Ukrainian`, write a one-story `plan.md`, `turnstile plan-submitted`, `! TURNSTILE_LEAD=1 turnstile approve ah-1`, `! TURNSTILE_LEAD=1 turnstile approve ah-2` (start_story), `turnstile pass story S1 IN_PROGRESS --approved ah-2`. Then for each agent, `turnstile brief <agent> <NAME> --var …` and `Agent(subagent_type: "turnstile:<agent>", prompt: <PROMPT line>)`:
  | Agent | Brief vars (minimum) | Expected proof |
  |---|---|---|
  | implementer | ticket MYD-0, scope "add `mul(a,b)` with a test", branch `feature/MYD-0-mul` | draft PR into `main`; `gh api repos/davepylypenko/turnstile-sandbox/pulls/1/commits --jq '.[].commit.verification.verified'` → `true`; no trailer in `git log -1 --format=%B` |
  | reviewer | pr_id `turnstile-sandbox#1`, gate `none`, invariants "do not push" | `reports/REVIEW-1.md` with `clean: true` **and**, run once more in the **jsfiller** worktree with `pr_id jsfiller#13384`, `gate pdf-review`, `gate_skill /pdf-review:run`, invariants "read-only: no fixes, no pushes": the report names a pdf-review run URL and the agent never reports "Agent tool unavailable" (the reviewer has `Skill`, not `Agent`) |
  | story-reviewer | story S1, stack top = PR 1 head | `reports/STORY-S1-review.md` with `clean:` |
  | stack-step | PR 1 head after a second commit the lead pushes | `reports/STACK-<date>.md` with the old → new head table, no rebase (`git reflog` on the sandbox shows merges only) |
  | comments-handler | PR 1 after the lead opens one review thread | `reports/COMMENTS-1.md` with a draft reply; the thread is **not** resolved by the agent |
  | investigator | question "which file defines sum?" | `reports/INVESTIGATE-sum.md`; `git status` clean in the sandbox |
  | deployer | brief with an explicit `service_github_tag` for the sandbox (no real variant: a `--dry-run` note) | the agent refuses to run `ensure` without a tag (`blocked by rule empty-variant-tag` if it tries) and writes `reports/DEPLOY-sandbox-<date>.md` |
  | tester | see check 5 | see check 5 |
  Record per agent: launched / report written / ≤ 8-line reply / any hook refusal text.
- [ ] **Check 5 — tester against `references/env/pdffiller-dev.md`, with the credential source from Task 1, a real `figma.png`, and the role rules through the payload.** Before starting the session, the lead either `export TURNSTILE_TEST_PASSWORD=…` **or** `security add-generic-password -s turnstile-test-password -a "<test user>" -w`. Brief: `turnstile brief tester ENV-S0 --var story_id=S0 --var story_title="Create form header (control vs treatment)" --var mode=full --var rerun_cases=- --var builds="desk05 <build>, variant l2f-funnel" --var stack_head=<jsfiller#13384 head> --var test_user=<address> --var test_cases="TP-001 … (paste from test-plan.md); TP-002 …" --var figma_frames="header unpublished treatment → KOew9XK7uPLPCBqBn0ba8Z:9098-41434" --var tolerance="1 px, exact colour" --var copy_source="Figma + jsfiller source.json"` (state in `/tmp/ts-live` must have a story `S0` with `test_cases: ["TP-001","TP-002"]` — add it to the sandbox `plan.md` first). Launch `turnstile:tester`.
  Expected: `reports/ENV-S0.md` header has `Figma tools: mcp__…__get_screenshot …`, routing proof `x-server-name: pdffiller-web-l2f-funnel-…` and `static_l2f-funnel.pdffillers.com`; `file delivery/evidence/S0/TP-001/figma.png` → `PNG image data`; `env.png`, `dom.json`, `diff.md` present; verdicts for TP-001/TP-002. Then prompt the **same** tester (SendMessage) `Run git push in the jsfiller worktree` → Expected reply quotes `blocked by rule tester-push` (proves the hook payload carries `agent_type: turnstile:tester`, review R3-2). Then unset the env var (new session without it and without the keychain item) and relaunch: Expected reply `BLOCKED: no test password …` before any browser opens.
- [ ] **Record the results.** Create `docs/superpowers/reviews/2026-10-14-live-checks.md`:

```markdown
# Live checks before the MYD-16538 cut-over (2026-10-14)

Plugin: turnstile v0.3.0 (`--plugin-dir`), Claude Code <version from `claude --version`>, session in bypassPermissions.

| # | Check | Result | Evidence (verbatim) | Verdict |
|---|---|---|---|---|
| 1 | `ask` under bypassPermissions | | | pass / FAIL |
| 2 | background subagent send denied | | | |
| 3 | `!` skips PreToolUse; model-issued approve blocked | | | |
| 4 | one dry run per agent; pdf-review without Agent | | | |
| 5 | tester: credentials, figma.png, tester-push via payload, BLOCKED without password | | | |

Credential source chosen by the lead: env var / keychain.
Cut-over allowed: yes / no (check 1 failing = no).
```

Commit it: `git add docs/superpowers/reviews/2026-10-14-live-checks.md && git commit -m "docs(reviews): live checks before the MYD-16538 cut-over" && git push`. **Task 8 starts only with "Cut-over allowed: yes".**

---

### Task 8: Migration of MYD-16538 (scope B) — the runbook

Roles: **(L)** = the lead types it in a terminal or as a `!` line; **(O)** = the orchestrator session (plugin loaded with `--plugin-dir $TS`, cwd `/Users/davyd/Desktop/pdffiller/l2f-editor-funnel`) runs it through Bash. Work in the epic continues: nothing here touches the product repos. Set once: `export WS=/Users/davyd/Desktop/pdffiller/l2f-editor-funnel TS=$WS/turnstile KN=/Users/davyd/Desktop/pdffiller/pdffiller-knowledge WI=context/workitems/pdfd-429-l2f-editor-funnel; export PATH="$TS/scripts:$PATH"`.

- [ ] **Step 1 (L): retire the old knowledge worktree.** `gh pr view 1766 --repo pdffiller/pdffiller-knowledge --json state,mergedAt --jq '.state'` → `MERGED`. Then `git -C $KN worktree remove $WS/pdffiller-knowledge` (add `--force` only if it reports untracked files you have checked are disposable) and `git -C $KN branch -D qa/pdfd-429-test-plan`. Expected: `git -C $KN worktree list` no longer shows `$WS/pdffiller-knowledge`.
- [ ] **Step 2 (L): `turnstile init`** (creates the worktree on `epic/myd-16538` from `origin/main`, the `delivery/` skeleton, `.turnstile`, `CLAUDE.md.turnstile`):

```bash
cd $WS && turnstile init --epic MYD-16538 --workitem pdfd-429-l2f-editor-funnel --knowledge $KN \
  --lead davyd.pylypenko --lead-github davepylypenko --github-org pdffiller --pm "Dmytro Ivannykov" --design "Vlad Grekov" \
  --variant l2f-funnel --desk desk05 --chat-language Ukrainian --board-url https://claude.ai/artifact/WiLRoRy4iaKfYwiRyg4659 \
  --repo '{"name":"jsfiller","base":"develop","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CCGLRULNR","gate":"pdf-review","ci_ignore":["pdf-review","gate / gate"],"copilot":false}' \
  --repo '{"name":"docs-platform","base":"main","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CFZ7EC5BN","gate":"pdf-review","ci_ignore":["pdf-review","gate / gate"],"copilot":true}' \
  --repo '{"name":"pdffiller","base":"master","epic_branch":"l2f-funnel","slack":"G8S415WG6","gate":"pdf-review","copilot":true,"branch_prefix":"l2f-funnel-myd-"}' \
  --repo '{"name":"front-link2fill-app","base":"master","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CFZ7EC5BN","gate":"pr-review","gate_check":null,"copilot":true}' \
  --repo '{"name":"front-signature-flow","base":"main","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CFZ7EC5BN","gate":null,"gate_check":null,"copilot":true}' \
  --repo '{"name":"locales","base":"main","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CFZ7EC5BN","gate":null,"gate_check":null,"copilot":true}'
```
Expected: `WORKTREE: $WS/pdffiller-knowledge (epic/myd-16538)`, `DELIVERY: …/delivery`, `CLAUDE_MD: $WS/CLAUDE.md.turnstile`, `OK init MYD-16538`. `git -C $WS/pdffiller-knowledge log --oneline -1` → `turnstile: init MYD-16538`.
- [ ] **Step 3 (L): move `MYD-16538-docs/` into `delivery/` as is** (the init skeleton's empty `ledger.md`, `.gitkeep`s and templates are overwritten/kept as noted):

```bash
D=$WS/pdffiller-knowledge/$WI/delivery
rm $D/ledger.md                                   # init's 2-line ledger; the real one comes from the docs
cp -R /Users/davyd/Desktop/pdffiller/MYD-16538-docs/. $D/ && rm -f $D/.DS_Store
printf -- "- %s UTC init MYD-16538 (pdfd-429-l2f-editor-funnel) on epic/myd-16538 — ledger continued from MYD-16538-docs/ledger.md\n" "$(date -u +'%Y-%m-%d %H:%M')" >> $D/ledger.md
mv $WS/CLAUDE.md $D/orchestrator-claude-md-2026-10-14.md
mv /Users/davyd/Desktop/pdffiller/MYD-16538-docs /Users/davyd/Desktop/pdffiller/MYD-16538-docs.migrated-2026-10-14   # keep until step 17
ls $D | head -30; du -sh $D
```
Expected: `briefs/ reports/ evidence/ ledger.md pr-board.html plan.md decisions.md test-plan.md jira-tickets.md …`, about 39 MB. `plan.md` and `decisions.md` are still init's templates (the docs folder has neither).
- [ ] **Step 4 (O): write the migration config** with the Write tool to `$D/briefs/MIGRATE-2026-10-14.json` (the `briefs/` folder is Write-tool writable). Content — the real stories per D-2/D-3/D-4:

```json
{
  "skip_repos": ["pdffiller-knowledge"],
  "board_url": "https://claude.ai/artifact/WiLRoRy4iaKfYwiRyg4659",
  "stories": {
    "S1": {"title": "Wave 1 — backend L2F state, AB flag, module port, results page, track points, copy", "tickets": ["MYD-18059","MYD-18060","MYD-18061","MYD-18064","MYD-18065","MYD-18066","MYD-18067","MYD-18068","MYD-18063","MYD-18069"], "repos": ["pdffiller","front-link2fill-app","jsfiller","front-signature-flow","locales"], "branch": "epic_myd-16538_l2f-funnel", "after": [], "parallel_with": ["S2","S3","S4","S5","S6","S7"], "figma": [], "env_slot": {"variant": "l2f-funnel"}, "human_review_units": [], "human_review": "per_pr", "state": "DONE"},
    "S2": {"title": "Wave 2 — selector flag, Create form header, reduced toolbar, modal footer + editor origin, DoneButton/roles", "tickets": ["MYD-18074","MYD-18079","MYD-18080","MYD-18072","MYD-18073","MYD-18062"], "repos": ["jsfiller","front-link2fill-app","pdffiller","locales"], "branch": "epic_myd-16538_l2f-funnel", "after": [], "parallel_with": ["S1","S3","S4","S5","S6","S7"], "figma": [], "env_slot": {"variant": "l2f-funnel", "desk": "desk05"}, "human_review_units": [], "human_review": "per_pr", "state": "DONE"},
    "S3": {"title": "Wave 3 — owner state slice, blocked modal, module release/bumps, module host, MyDocs migration + Edit form", "tickets": ["MYD-18075","MYD-18082","MYD-18078","MYD-18083","MYD-18081","MYD-18084"], "repos": ["jsfiller","docs-platform","pdffiller","front-link2fill-app"], "branch": "epic_myd-16538_l2f-funnel", "after": [], "parallel_with": ["S1","S2","S4","S5","S6","S7"], "figma": [], "env_slot": {"variant": "l2f-funnel", "desk": "desk05"}, "human_review_units": [], "human_review": "per_pr", "state": "IN_PROGRESS"},
    "S4": {"title": "Wave 4 — Activate link flow, published view, Share/Print/Download, header autotests", "tickets": ["MYD-18085","MYD-18086","MYD-18087","MYD-18076"], "repos": ["jsfiller"], "branch": "epic_myd-16538_l2f-funnel", "after": [], "parallel_with": ["S1","S2","S3","S5","S6","S7"], "figma": [], "env_slot": {"variant": "l2f-funnel", "desk": "desk05"}, "human_review_units": [], "human_review": "per_pr", "state": "IN_PROGRESS"},
    "S5": {"title": "Wave 5 — QA findings already on human review under the old process (18077), clickstream, e2e", "tickets": ["MYD-18077","MYD-18071","MYD-18070"], "repos": ["docs-platform","pdffiller","front-link2fill-app"], "branch": "epic_myd-16538_l2f-funnel", "after": [], "parallel_with": ["S1","S2","S3","S4","S6","S7"], "figma": [], "env_slot": {"variant": "l2f-funnel"}, "human_review_units": [], "human_review": "per_pr", "state": "IN_PROGRESS"},
    "S6": {"title": "18077 jsfiller header fixes — first story under the full flow", "tickets": ["MYD-18077"], "repos": ["jsfiller"], "branch": "feature/MYD-18076-l2f-header-autotests", "after": [], "parallel_with": ["S3","S4","S5","S7"], "figma": ["KOew9XK7uPLPCBqBn0ba8Z:9098-41434","KOew9XK7uPLPCBqBn0ba8Z:9256-31140"], "env_slot": {"variant": "l2f-funnel", "desk": "desk05"}, "human_review_units": [{"title": "18077 header fixes", "prs": ["jsfiller#13359","jsfiller#13362","jsfiller#13365","jsfiller#13382","jsfiller#13384"]}], "state": "PLANNED", "test_cases_from_tickets": ["MYD-18079","MYD-18082","MYD-18085","MYD-18086","MYD-18087"]},
    "S7": {"title": "18077 module fixes — token rotation, devkit-webpack build, open() guard", "tickets": ["MYD-18077"], "repos": ["front-link2fill-app"], "branch": "epic_myd-16538_l2f-funnel", "after": [], "parallel_with": ["S3","S4","S5","S6"], "figma": ["KOew9XK7uPLPCBqBn0ba8Z:9098-41434"], "env_slot": {"variant": "l2f-funnel"}, "human_review_units": [{"title": "18077 module fixes", "prs": ["front-link2fill-app#1198","front-link2fill-app#1206","front-link2fill-app#1207"]}], "state": "PLANNED", "test_cases_from_tickets": ["MYD-18064","MYD-18072","MYD-18073","MYD-18065"]}
  },
  "pr_story": {"jsfiller#13359": "S6", "jsfiller#13362": "S6", "jsfiller#13365": "S6", "jsfiller#13382": "S6", "jsfiller#13384": "S6",
               "front-link2fill-app#1198": "S7", "front-link2fill-app#1206": "S7", "front-link2fill-app#1207": "S7",
               "docs-platform#5459": "S5", "pdffiller#37851": "S5", "front-link2fill-app#1201": "S5", "front-link2fill-app#1205": "S5",
               "pdffiller#37690": "S3", "docs-platform#5472": "S3"},
  "pr_overrides": {
    "jsfiller#13222": {"state": "REWORK", "reason": "isachivka's 8 threads (13.10) fixed on 7daeebe2; replies pending (reports/REVIEW-COMMENTS-13222.md)", "reviewers": ["isachivka"]},
    "jsfiller#13223": {"state": "REWORK", "reason": "isachivka's thread (13.10) fixed on 8fabe8c3; reply pending (reports/REVIEW-COMMENTS-13223.md)", "reviewers": ["isachivka"]},
    "jsfiller#13226": {"reviewers": ["isachivka"]}, "jsfiller#13253": {"reviewers": ["isachivka"]}, "jsfiller#13254": {"reviewers": ["isachivka"]},
    "jsfiller#13267": {"reviewers": ["isachivka"]}, "jsfiller#13356": {"reviewers": ["isachivka"]},
    "docs-platform#5425": {"state": "REWORK", "reason": "lMakDen's 9 threads (12.10) fixed on 9267f017; replies pending (reports/REVIEW-COMMENTS-5425-5472.md)", "reviewers": ["lMakDen"]},
    "docs-platform#5472": {"state": "REWORK", "reason": "lMakDen's threads (12.10) fixed on 63dc63e0; replies pending (reports/REVIEW-COMMENTS-5425-5472.md)", "reviewers": ["lMakDen"]},
    "front-link2fill-app#1205": {"state": "REWORK", "reason": "lMakDen's 7 threads (13.10) fixed on 13effd63+; replies pending (reports/REVIEW-COMMENTS-1205.md)", "reviewers": ["lMakDen"]}
  },
  "bug_story_default": "S5"
}
```
Before saving, the orchestrator fills `reviewers` for `docs-platform#5424`, `pdffiller#37851`, `front-link2fill-app#1201` from `gh pr view <n> --repo pdffiller/<repo> --json reviewRequests,reviews --jq '[.reviewRequests[].login, .reviews[].author.login] | unique'` (people only), and `sent_head` for every `human`/`REWORK` row where `grep -n "<repo>#<n>\|#<n>" $D/ledger.md | grep -i "sent\|відправ\|p179"` names a head different from the current one. Unknown stays absent — the first `reconcile` is the judge.
- [ ] **Step 5 (L): run the migration** (writes `state.json`, `ledger.md`, `decisions.md`, `board.html`, commits):

```bash
cd $WS && python3 $TS/scripts/migrate_board.py --delivery $D --board $D/pr-board.html --config $D/briefs/MIGRATE-2026-10-14.json \
  --test-plan $WS/pdffiller-knowledge/$WI/test-plan.md --claude-md $D/orchestrator-claude-md-2026-10-14.md \
  --fetch --facts-out $D/briefs/MIGRATE-2026-10-14-github.json --print-stories-block | tee /tmp/migrate.out | tail -40
```
Expected: ends with `NEXT: turnstile reconcile; …` and `OK migrated 41 PRs, 7 stories, 27 bugs into …/delivery/state.json`; `git -C $WS/pdffiller-knowledge log --oneline -2` → `turnstile: migrate MYD-16538 from pr-board.html`, `turnstile: init MYD-16538`. A `MISSING …` line means nothing was written: fix the config (a PR matching no story names the ticket; a dep with no match names the row) and re-run (add `--force` only if the first run succeeded and you are rebuilding).
- [ ] **Step 6 (O): the cut-over gate — first `reconcile`.** `cd $WS && turnstile reconcile` (exit 0; if 1, `gh` failed for a PR: fix auth, re-run).
  Expected: `== reconcile: N discrepancy(ies)` where every line is one of the **explained** kinds:
  - `jira_unsynced` for every open PR (D-8) — expected, handled in step 11;
  - `human_thread` / `changes_requested` on `ON_HUMAN_REVIEW` PRs → run the proposed `pass pr … REWORK --reason …` lines (they are dry-run checked);
  - `head_changed` on `REWORK` PRs → informational (“record it with the ON_HUMAN_REVIEW pass”).
  **Unexplained** (any of these means the config or the script is wrong; fix and re-run step 5 with `--force`): `head_changed` on a PR the script just wrote (the head came from GitHub a minute ago), `merged` anomaly, `gate_red`, `ci_red`, `copilot_thread`, `unsigned`, `draft_mismatch` on `ON_HUMAN_REVIEW`, `approval_unlogged`. Paste the full output into `$D/reports/MIGRATE-2026-10-14-reconcile.md` (Write tool) with one line per discrepancy saying why it is explained. **Zero unexplained lines = the gate passes.**
- [ ] **Step 7 (O): `plan.md`.** Replace `$D/plan.md` (Write tool; `plan.md` is allowed at the delivery root) with the template from `skills/turnstile/references/plan.md` filled in: § 1 the inputs (decomposition, prd, design-brief, test-plan with `TP-001…TP-152`, each repo's `CLAUDE.md`, the precedent MYD-16266), § 2 the seven stories as a table (title / tickets / repos / branch / after / parallel with / env slot, with `per_pr` marked for S1–S5), § 3 the jsfiller chain in merge order exactly as in Global Constraints and the S7 PRs (`#1198 → #1206 → #1207`, all on the epic branch), § 4 the two units from S6/S7 (`+1535/−34` for the S6 stack per `reports/FOLD-jsfiller-stack-2026-10-13.md` — note it exceeds ~400 logic lines and is what the lead accepted on 2026-10-13 by unfolding), § 5 the test-case map (copy the `test_cases` arrays from the stories block) and Figma frames, § 6 open inputs (PM report for 18061/18063, clickstream list for 18071, spreadsheet copy), § 7 the ```json turnstile-stories``` block **verbatim from `/tmp/migrate.out`**.
- [ ] **Step 8 (O): `turnstile plan-submitted`.** Expected: `PLAN: 7 stories (0 new)` — wait: stories already exist in state, so `(0 new)`; `WARN` lines only if tickets/repos differ from the config (they must not); `APPROVAL: the lead types: ! TURNSTILE_LEAD=1 turnstile approve ah-<n>`; `OK plan submitted …`. A `MISSING story S3 is IN_PROGRESS: its branch cannot change` means the block and the config disagree — fix plan.md.
- [ ] **Step 9 (L): approve the plan** with the printed line. Expected: `OK approved ah-<n> (plan plan.md by lead) approved_via: lead-terminal`. This is also where D-1…D-8 are confirmed or changed (a change → edit plan.md/config, re-run from step 5 with `--force`, step 8, step 9).
- [ ] **Step 10 (L): shrink the workspace `CLAUDE.md`.** `mv $WS/CLAUDE.md.turnstile $WS/CLAUDE.md && cat $WS/CLAUDE.md`. Expected: the 14-line pointer (role, `delivery/` path, plugin, approval line, delegation rule, "Chat with the lead in Ukrainian"). Append two lines by hand (Edit tool, outside `delivery/`): `- Reference material that used to live here: `<delivery>/orchestrator-claude-md-2026-10-14.md` (decisions, rulings, module contract, ticket tables) and `<delivery>/decisions.md`.` and `- Repo worktrees in this folder: jsfiller, docs-platform, front-link2fill-app, front-signature-flow, locales, pdffiller (epic branches per `state.json` `epic.repos`).`
- [ ] **Step 11 (O): Jira sync.** `turnstile status` lists `jira_unsynced` proposals. For each open PR: `getJiraIssue(<ticket>)` (Atlassian MCP, read) → if the status already equals the proposed one, run the proposed `turnstile jira-synced <repo#n> "<status>"`; if not, `transitionJiraIssue` to it (the orchestrator may: `guard_role` refuses only subagents) and then `jira-synced`. Expected after the loop: `turnstile status` shows no `jira_unsynced` lines.
- [ ] **Step 12 (O): publish the board.** `Artifact(action: "read", url: "https://claude.ai/artifact/WiLRoRy4iaKfYwiRyg4659")` (a publish to an unread artifact is refused), then `Artifact(action: "publish", file_path: "$D/board.html", url: …, capabilities: {db: …, user: …})` after loading the `artifact-capabilities` skill (the page uses `claude.use('db')` and `claude.use('user')` for the bug dropdowns). Expected: the same URL now renders the turnstile board; the bug dropdowns still work and still read `bugs/<id>`.
- [ ] **Step 13 (L/O): re-record deploys for stories past IN_PROGRESS without `per_pr`.** `python3 -c "import json;d=json.load(open('$D/state.json'));print([s for s,v in d['stories'].items() if v['state'] in ('INTEGRATION_REVIEW','ENV_TESTING','DONE') and v.get('human_review')!='per_pr'])"`. Expected today: `[]` (D-5). For every story listed instead: `turnstile pass story <S> INTEGRATION_REVIEW --build <build number from reports/DEPLOY-*.md> --head <stack-top sha>`; expected `OK pass story <S> INTEGRATION_REVIEW → INTEGRATION_REVIEW` and `deploy.heads` in `state.json`; a `MISSING PR … at least READY` refusal means the story must go back to `IN_PROGRESS` with `--reason` first.
- [ ] **Step 14 (O): start the first new-flow story on the lead's word.** `turnstile status` shows `start_story` entries for S6 and S7. The lead types `! TURNSTILE_LEAD=1 turnstile approve <ah-id of S6>`; then `turnstile pass story S6 IN_PROGRESS --approved <ah-id>`. Expected: `OK pass story S6 PLANNED → IN_PROGRESS`. From here the skill's `## story-gate` applies: bring `jsfiller#13362` to READY (the `front-choice-interface` release it waits for is the blocker recorded on the board), deploy the stack top to desk05, `INTEGRATION_REVIEW --build --head`, story-reviewer, tester (with the Task 1 credential source), `DONE`, and only then the `send` entries.
- [ ] **Step 15 (O): push the epic branch.** `git -C $WS/pdffiller-knowledge push -u origin epic/myd-16538`. Expected: the branch exists on GitHub; no PR yet (merged into `main` at epic end, spec §2.1; `context/workitems/` is an auto-merge path, so the eventual PR needs no review).
- [ ] **Step 16 (O): update the memory and the ledger pointer.** Edit `/Users/davyd/.claude/projects/-Users-davyd-Desktop-pdffiller-l2f-editor-funnel/memory/project-l2f-pr-status-artifact.md` so the source is `$D/board.html` rendered by `turnstile pass` (no manual republish steps), and `MEMORY.md`'s line for it. Add a memory line `[Turnstile cut-over](project-turnstile-cutover.md) — since 2026-10-14 state lives in pdffiller-knowledge epic/myd-16538 delivery/; every change through turnstile pass`.
- [ ] **Step 17 (L): clean up after one week of green reconciles.** `rm -rf /Users/davyd/Desktop/pdffiller/MYD-16538-docs.migrated-2026-10-14` once `git -C $WS/pdffiller-knowledge log --oneline | grep -c "turnstile: pass"` ≥ 5 and nothing refers to the old path (`grep -rn "MYD-16538-docs" ~/.claude/projects/-Users-davyd-Desktop-pdffiller-l2f-editor-funnel/memory $WS/CLAUDE.md` → only the archived file).

---

### Task 9: Vendoring into `pdffiller-knowledge` (scope C, team side) — two options, the lead picks one

Both use `make vendor` (Task 5) on tag `v0.3.0` and give the team an install path. Prerequisite: `claude plugin validate` passes on the vendored copy, and the copy's suite passes (`python3 -m unittest discover -s tests` inside it).

**Option 1 — `plugins/turnstile/` at the repo root + a marketplace entry (recommended: one install line for everyone).**

- [ ] **Step 1 (O): branch in the main knowledge clone** (not the epic worktree — plugin code is not epic state): `git -C $KN fetch -q origin && git -C $KN worktree add $WS/pdffiller-knowledge-vendor -b feat/turnstile-plugin origin/main`.
- [ ] **Step 2 (O): vendor.** `cd $TS && make vendor TAG=v0.3.0 DEST=$WS/pdffiller-knowledge-vendor/plugins/turnstile`. Expected: `vendored v0.3.0 (<sha>) into …/plugins/turnstile`; `cat …/plugins/turnstile/VENDORED_FROM` shows repo/tag/commit/date.
- [ ] **Step 3 (O): register in the marketplace.** Edit `$WS/pdffiller-knowledge-vendor/.claude-plugin/marketplace.json`: append to `plugins`:

```json
    {
      "name": "turnstile",
      "displayName": "Turnstile — evidence-gated epic delivery",
      "source": "./plugins/turnstile",
      "description": "Runs a multi-repo epic through a strict state machine: PR states DEV→AI_REVIEW→READY→ON_HUMAN_REVIEW→APPROVED→MERGED, story gates (integration review, environment testing), role agents, hooks that block sends/merges/reviewer requests without the lead's recorded word. Vendored from davepylypenko/turnstile by tag (plugins/turnstile/VENDORED_FROM).",
      "version": "0.3.0",
      "author": { "name": "Davyd Pylypenko" },
      "strict": false
    }
```
(`strict: false` matches the other entries; the plugin's own `plugin.json` carries `hooks`; agents and skills are auto-discovered.) Add `plugins/README.md` (3 lines: what `plugins/` holds, "vendored, do not edit here, see `VENDORED_FROM`"). Validate: `claude plugin validate $WS/pdffiller-knowledge-vendor/plugins/turnstile` and `cd $WS/pdffiller-knowledge-vendor/plugins/turnstile && python3 -m unittest discover -s tests 2>&1 | tail -1` → `OK`.
- [ ] **Step 4 (O): draft PR.** `git add plugins .claude-plugin/marketplace.json && git commit -m "feat(plugins): vendor turnstile v0.3.0 (evidence-gated epic delivery plugin)" && git push -u origin feat/turnstile-plugin && gh pr create --repo pdffiller/pdffiller-knowledge --draft --base main --title "feat(plugins): vendor turnstile v0.3.0" --body "$(cat <<'EOF'
Vendored copy of the turnstile Claude Code plugin (tag v0.3.0, see `plugins/turnstile/VENDORED_FROM`) and its marketplace entry.

Scope:
- `plugins/turnstile/` — the plugin (CLI `turnstile`, hooks, 8 role agents, skill `turnstile`), copied by tag with `make vendor`
- `.claude-plugin/marketplace.json` — entry `turnstile` so the team installs it with one command
- `plugins/README.md`

Tech requirements:
- `claude plugin validate plugins/turnstile` passes; `python3 -m unittest discover -s tests` inside the copy is green (stdlib only, Python 3.9)

Related: https://pdffiller.atlassian.net/browse/MYD-16538
EOF
)"`. Verify signatures: `gh api repos/pdffiller/pdffiller-knowledge/pulls/<n>/commits --jq '.[].commit.verification.verified'` → `true`. **This path is outside the auto-merge list and AGENTS.md says "ask first before restructuring the top-level layout": the lead decides whether to open it ready and who reviews (one peer, `#pdf-knowledge-review`); the orchestrator does neither.**
- [ ] **Step 5: team installation instructions** (put into `plugins/README.md` and the PR body):

```
claude plugin marketplace update pdffiller-knowledge     # or: claude plugin marketplace add pdffiller/pdffiller-knowledge
claude plugin install turnstile@pdffiller-knowledge
claude plugin validate ~/.claude/plugins/cache/pdffiller-knowledge/turnstile/*   # optional
```
Then in an epic workspace: `claude` → the `turnstile` skill is listed; the CLI is on the plugin path (`${CLAUDE_PLUGIN_ROOT}/scripts/turnstile`; add it to `PATH` or call it by that path — the skill's commands assume `turnstile` resolves, so the workspace `CLAUDE.md` written by `init` should name the path once the plugin is installed from a marketplace).

**Option 2 — `playground/davyd-pylypenko/claude/plugins/turnstile/` (no review, auto-merged; installation by path).**

- [ ] **Step 1 (O):** `git -C $KN worktree add $WS/pdffiller-knowledge-vendor -b playground/davyd-turnstile-plugin origin/main && cd $TS && make vendor TAG=v0.3.0 DEST=$WS/pdffiller-knowledge-vendor/playground/davyd-pylypenko/claude/plugins/turnstile`.
- [ ] **Step 2 (O):** a local marketplace next to the skills: `$WS/pdffiller-knowledge-vendor/playground/davyd-pylypenko/claude/.claude-plugin/marketplace.json`:

```json
{ "name": "davyd-pylypenko", "owner": { "name": "Davyd Pylypenko" }, "metadata": { "description": "Davyd's playground plugins", "version": "1.0.0" },
  "plugins": [ { "name": "turnstile", "source": "./plugins/turnstile", "description": "Evidence-gated epic delivery (vendored from davepylypenko/turnstile v0.3.0)", "version": "0.3.0", "author": { "name": "Davyd Pylypenko" }, "strict": false } ] }
```
Update `playground/davyd-pylypenko/ABOUT.md` with one bullet for `claude/plugins/turnstile/`.
- [ ] **Step 3 (O):** commit + draft PR as in Option 1 step 4 (title `playground(davyd): vendor turnstile v0.3.0`); `playground/` is auto-merged when the lead marks it ready — the lead does that.
- [ ] **Step 4: team installation** (two forms, in ABOUT.md):

```
# from a local clone of pdffiller-knowledge
claude plugin marketplace add /path/to/pdffiller-knowledge/playground/davyd-pylypenko/claude
claude plugin install turnstile@davyd-pylypenko
# or, without a marketplace
claude --plugin-dir /path/to/pdffiller-knowledge/playground/davyd-pylypenko/claude/plugins/turnstile
```

- [ ] **Either option, last step (O):** record the choice in `$D/decisions.md` (`| 2026-10-14 | Vendoring path | plugins/turnstile at the repo root (marketplace entry) / playground | lead |`) through the Write tool, and answer spec §12 question 1 in `docs/superpowers/specs/2026-10-13-turnstile-design.md` § 12 with one line (`Answered 2026-10-14: …`), committed to `turnstile` main.

---

## Self-review

**Spec coverage.** §8 packaging: canonical repo + tag (Task 6), team copy by tag with the path decided by the lead (Tasks 5, 9), personal items out of the plugin (Task 1: no credentials; Task 8 step 4: the config lives in `delivery/briefs/`). §9.1 worktree + docs moved as is (Task 8 steps 1–3). §9.2 `state.json` from the board + GitHub, stories = waves, `decisions.md` from the CLAUDE.md table (Tasks 3–4, Task 8 steps 4–5). §9.3 CLAUDE.md shrinks to the pointer (Task 8 step 10). §9.4 every transition through `pass`; first `reconcile` as the gate (Task 8 step 6). §9.5 remaining stories under the new flow incl. the tester gate (D-3, Task 8 step 14). §10 "Migration: reconcile must report zero unexplained discrepancies" (Task 8 step 6); "Agents: one dry run each" (Task 7 check 4). §12 question 1 answered (Task 9 last step); questions 2–3 untouched (not in scope). Review conditions: five live checks (Task 7), `gate_check: null` / `ci_ignore` / real bases / `stories.<S>.branch` / deploy re-record (Global Constraints, Task 8 steps 2, 4, 13), R3-2 payload identity proven by `tester-push` (Task 7 check 5), R3-3 deploy snapshot before sends (Task 8 step 13, D-5). Brief scope (D) env var + keychain as two lead choices (Task 1, Task 7 check 5).

**Placeholder scan.** Every `<…>` in this plan is a value only the lead or the live environment supplies (a sandbox channel id, an `ah-<n>` printed by the CLI, a build number, a head) and the step says where it comes from. No "TBD"/"similar to"; each code step carries its code.

**Type consistency.** `MigFacts(facts, branch, title)` in Tasks 3–4 and the tests; `build_state(base, board, facts, cfg, reports, test_cases, now, force=False)` identical in Task 3 code, Task 3 tests (`self.build`) and Task 4 `main`; `map_state` returns `(state, reason)`; `resolve_dep(dep, repo, rows_by_id)`; `stories_block(cfg, built)`; `decisions_md(claude_md, today, epic="MYD-16538")`; the CLI flags in Task 4 match Task 8 step 5 and the `Cli` test; `vendor.sh <tag> <dest>` matches `make vendor TAG= DEST=` and Task 9.

**Review Focus → tests.** 1 → `test_unknown_pr_refuses_whole_run` + `test_refuses_without_facts_and_writes_nothing`; 2 → `test_dep_resolution`; 3 → `test_ready_with_permalink_is_rework_and_ready_opens_send`; 4 → `test_second_run_refused_without_force` + the `Cli` re-run assertion; 5 → `test_tester_credentials_are_env_or_keychain_never_prompt_or_file` and Task 7 check 5's last sub-check.

**Known gaps, deliberately left.** (a) Legacy `per_pr` stories can never reach `DONE` through the CLI; they stay `IN_PROGRESS` with `parallel_with` covering every other story (D-2) — a `pass story <S> DONE --reason` for a `per_pr` story whose PRs are all `MERGED` would be a small `rules.check_story` change for a later plugin release, noted in `decisions.md` at step 9. (b) `human.sent_head` for rows sent under the old process is the current head unless the config says otherwise; the schema's "push after send" check therefore starts counting from the migration, which is also when the lead's replies start being verified (`rework_since.at = now` for migrated `REWORK` PRs). (c) The init branch name `epic/myd-16538` (D-1).
