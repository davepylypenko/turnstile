# Turnstile skill, agents and workflow commands — implementation plan (plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the reviewed core (main `bc0fdc1`, 147 tests) into a usable plugin: `init` (knowledge worktree + `delivery/` skeleton + kick-off analysis + lead approval of `plan.md`), `dispatch` (standardised agent launch from brief templates), `story-gate` (integration review → env testing with recorded test runs), `plan` (re-plan), the eight role agents, the `turnstile` skill with its references (DoR/DoD, briefs, PR body, Slack, reports, evidence, the pdffiller dev env recipe), the bug-status overlay on the board, `epic.github_org` promoted to a required field, and the four rules the core review deferred to plan 2 (story-branch stacking at INTEGRATION_REVIEW, "replies posted" at REWORK → ON_HUMAN_REVIEW, "every failed test became a bug" with recorded env runs, trailer/footer evasion caught on GitHub).

**Architecture:** The CLI grows four writers next to `pass` (`init`, `plan-submitted`, `brief`, `bug add|set`); every writer takes `state.locked()`, validates, then goes through `pass_cmd._side_effects` (save → ledger → board → git commit, restored on failure), with `pass_cmd.IO` injectable so tests never touch git remotes or the network. New rules live in `rules.py` (pure) and `pass_cmd._facts_mismatches` (GitHub facts). Everything the orchestrator *reads* (procedures, templates, role rules) is Markdown under `skills/turnstile/` and `agents/`, validated by stdlib tests that parse frontmatter and cross-references. The skill commands `init`, `dispatch`, `story-gate`, `plan` are procedures in `SKILL.md` that chain CLI calls and agent launches; the CLI enforces, the skill sequences.

**Tech Stack:** Python 3.9 standard library (`json`, `re`, `argparse`, `subprocess`, `hashlib`, `datetime`, `unittest`), `git` worktrees, `gh api graphql`, Claude Code plugin layout (`agents/*.md` with YAML frontmatter, `skills/<name>/SKILL.md`, `hooks/`), the claude.ai artifact runtime (`claude.use('db')`, `claude.use('user')`) in `templates/board.html`.

**Spec:** `docs/superpowers/specs/2026-10-13-turnstile-design.md` (§2.1, §4.1, §5 "Skill commands", §7, §7.1, §8, §10). Core review with the plan-2 items: `docs/superpowers/reviews/2026-10-13-core-review.md` (Round 3 § "Spec rules still not enforced: decisions", R3-10). Plan 1 (implemented): `docs/superpowers/plans/2026-10-13-turnstile-core.md`. Plan 3 (not here): migration of MYD-16538 and vendoring into `pdffiller-knowledge`. README sections "How the lead approves" and "Threat model" are binding: the lead approves only by typing `! TURNSTILE_LEAD=1 turnstile approve <ah-id>` in the Claude Code prompt; nothing in this plan gives the model another way.

## Global Constraints

- Python 3.9 syntax only: no `match`, no `X | Y` types, no `list[str]` at runtime (use `typing.List`). No third-party packages. Tests: `python3 -m unittest discover -s tests -v` (147 green at the start of this plan; every task adds, none removes).
- State file: JSON via `state.dumps` (2-space indent, `sort_keys=True`, trailing newline), written through `state.write_atomic` under `state.locked(delivery)`. Writers after this plan: `pass`, `approve`, `jira-synced`, `init`, `plan-submitted`, `bug add|set`, `brief`, `post_slack.py`. Every writer except `init` calls `pass_cmd._side_effects(delivery, st, lines, io, no_commit)` (board rendered in memory first; on commit failure the three files are restored).
- CLI output: plain text; success ends with one `OK …` line; failure prints `MISSING …` lines, exits 2, writes nothing. `WARN` lines are allowed before them.
- Ids: PR `<repo>#<number>`; story `S<n>`; bug `b<nn>` (two digits, zero-padded); awaiting `ah-<n>` (`pass_cmd._next_ah_id`). Heads: `rules.valid_head` (`[0-9a-f]{8,40}`), stored lowercase, compared with `rules.same_head`. Timestamps from `pass_cmd._now()` (`%Y-%m-%dT%H:%MZ`, UTC).
- `awaiting_human` entries are opened only by `pass_cmd._open_entry(data, type_, **keys)`; they carry `approved_at`, `approved_via` (`"lead-terminal"`, set only by `approve`), `consumed_at`, `voided_at`, and for Slack entries `used_at`/`used_channel`/`message_ts` (set only by `post_slack.py`). Types after this plan: `send`, `reply`, `merge`, `start_story`, `story_done`, `plan`. Selection: `rules.latest_entry` (newest, not consumed, not voided), validation: `rules.check_approved_entry`.
- `epic.github_org` is required (no `"pdffiller"` fallback anywhere after Task 2). Per-repo keys as the code has them: `base`, `epic_branch`, `slack`, `gate` (name of the review skill/gate, e.g. `pdf-review`, `pr-review`, `review`, `run-lint`), `gate_check` (the GitHub StatusContext/CheckRun that must be `success`; **default = `gate`; `null` for a skill gate that posts no check**), `ci_ignore` (contexts excluded from CI when entering AI_REVIEW; default `[gate_check]`; jsfiller/docs-platform: `["pdf-review", "gate / gate"]`), `copilot` (bool), optional `branch_prefix`.
- Every new `turnstile` subcommand is added to `hooks/guard_bash.py` `TURNSTILE_SUBS` in the task that adds it, with a hook test, or the Bash guard refuses it (`lead-approve` rule).
- Agents: `agents/<name>.md`, YAML frontmatter `name` (= file stem), `description`, `model` (`sonnet` | `opus` | `fable`), optional `effort`, `tools` (comma-separated allowlist). Per spec §7: implementer sonnet; reviewer opus **xhigh**; story-reviewer fable; stack-step opus; comments-handler opus; investigator opus; tester opus; deployer sonnet. Launch name `turnstile:<name>`. No agent's allowlist contains `Agent`, a Slack send tool or a Jira transition tool; the hooks apply to them anyway.
- Skill: `skills/turnstile/SKILL.md` ≤ 170 lines, frontmatter `name: turnstile` + `description`; long text lives in `skills/turnstile/references/` and is linked by relative path.
- Brief templates: `skills/turnstile/references/briefs/<agent>.md`, placeholders `{{snake_case}}` only; `turnstile brief` refuses to write a brief with any unfilled placeholder.
- Personal items never enter the plugin: channel ids, logins and roles come from `state.json`; credentials come from the lead at dispatch time; the env recipe carries patterns only.
- Commit messages in this repo: conventional (`feat(init): …`), signed (global SSH signing; never `--no-gpg-sign`), **no `Co-Authored-By` trailer**. Tag `v0.2.0` at the end.

## Review Focus

1. **`init` run twice** (worktree present, or `delivery/state.json` already there) must reuse the worktree and refuse to overwrite the state. Test in Task 1 (`test_init_reuses_worktree_and_refuses_existing_state`).
2. **`plan.md` edited after the lead approved it**: `pass story S<n> IN_PROGRESS` from `PLANNED` must be refused until `plan-submitted` + a fresh approval, with no `--reason` override. Test in Task 3 (`test_edited_plan_voids_approval`).
3. **A failed env run recorded without bugs**: `pass story S ENV_TESTING … --cases-fail 2` with fewer than two bugs of that story created after the previous run must be refused, and `DONE` after a `rerun` (not `--full`) must be refused. Test in Task 6 (`test_failed_run_needs_bugs`, `test_done_needs_full_run`).
4. **REWORK → ON_HUMAN_REVIEW with a human thread the lead never answered** (thread opened before `rework_since.at`, no comment by `epic.roles.lead_github` after it) must be refused; a thread opened after the rework started is not required. Test in Task 7 (`test_rework_needs_lead_replies`).
5. **A brief template with a placeholder nobody filled** must not be written, and the missing names must be printed. Test in Task 10 (`test_brief_refuses_unfilled_placeholder`).

---

## File structure

```
turnstile/
  .claude-plugin/plugin.json                  # version 0.2.0 (Task 12); agents/ and skills/ are auto-discovered
  agents/{implementer,reviewer,story-reviewer,stack-step,comments-handler,investigator,tester,deployer}.md   # Task 9
  skills/turnstile/SKILL.md                   # Task 11 — short; states, commands, when what
  skills/turnstile/references/lifecycle.md    # Task 11 — DoR/DoD tables with the CLI call per transition
  skills/turnstile/references/kickoff.md      # Task 11 — §4.1 procedure
  skills/turnstile/references/plan.md         # Task 1  — plan.md template with the turnstile-stories block
  skills/turnstile/references/pr-body.md      # Task 11
  skills/turnstile/references/slack.md        # Task 11 — review request, locales pairing, monolith, replies, story report
  skills/turnstile/references/reports.md      # Task 11 — report templates per agent
  skills/turnstile/references/evidence.md     # Task 11 — evidence/ layout
  skills/turnstile/references/env/pdffiller-dev.md   # Task 11 — first env recipe
  skills/turnstile/references/briefs/<agent>.md      # Task 10 — eight brief templates
  templates/state.json                        # Task 1  — empty epic skeleton with every key the rules read
  templates/CLAUDE.md.workspace               # Task 1  — the shrunken workspace CLAUDE.md
  templates/board.html                        # Task 2 (no org fallback), Task 8 (bugs db overlay)
  turnstile_cli/init_cmd.py                   # Task 1
  turnstile_cli/plan_cmd.py                   # Task 3
  turnstile_cli/bug_cmd.py                    # Task 4
  turnstile_cli/brief_cmd.py                  # Task 10
  turnstile_cli/rules.py                      # Task 3 (plan gate), 5 (story branch), 6 (env runs)
  turnstile_cli/github.py                     # Task 7 — threads with replies, commit messages, PR body
  turnstile_cli/pass_cmd.py                   # Task 2 (org), 3, 6 (--full, env_runs), 7 (lead replies, trailer), 8 (BOARD line)
  turnstile_cli/reconcile.py                  # Task 2 (org), 3 (status: plan line), 7 (dry run passes lead login)
  turnstile_cli/main.py                       # wiring in Tasks 1, 3, 4, 6, 10
  hooks/guard_bash.py                         # TURNSTILE_SUBS += init (1), plan-submitted (3), bug (4), brief (10)
  tests/fixtures/state_min.json               # Task 5 — stories.S1.branch; Task 7 — roles.lead_github
  tests/fixtures/gh_pr_13222.json             # Task 7 — thread ids/createdAt, commit messages, body
  tests/test_init.py  tests/test_org.py  tests/test_plan_cmd.py  tests/test_bug.py  tests/test_story_branch.py
  tests/test_env_runs.py  tests/test_replies_trailer.py  tests/test_board_bugs.py  tests/test_agents.py
  tests/test_brief.py  tests/test_skill_files.py
```

---

### Task 1: `templates/state.json`, `templates/CLAUDE.md.workspace`, plan template, `turnstile init`

**Files:**
- Create: `templates/state.json`, `templates/CLAUDE.md.workspace`, `skills/turnstile/references/plan.md`, `turnstile_cli/init_cmd.py`, `tests/test_init.py`
- Modify: `turnstile_cli/main.py` (wire `init` before `find_delivery`), `hooks/guard_bash.py` (`TURNSTILE_SUBS` += `"init"`), `tests/test_hooks.py` (allow line)

**Interfaces:**
- Consumes: `state.dumps`, `ledger.append`, `pass_cmd._ensure_repo_files(delivery)` (creates `.gitattributes`, `.state.lock`, `.gitignore`), `errors.TurnstileError`.
- Produces:
  - `init_cmd.InitOptions` dataclass: `epic, workitem, knowledge, lead, lead_github, github_org, repos: List[str]` (each a JSON object string), `variant, desk, board_url, workspace=".", knowledge_base="main", pm, design, recipe="references/env/pdffiller-dev.md"`.
  - `init_cmd.InitIO.git(args: List[str], cwd: Path) -> str` (injectable).
  - `init_cmd.parse_repo(spec: str) -> Tuple[str, dict]` — JSON with required `name, base, epic_branch, slack`; `gate` default `None`; `gate_check` default `= gate` (pass `"gate_check": null` for a skill gate); `ci_ignore` default `[gate_check]` or `[]`; `copilot` default `False`; optional `branch_prefix`.
  - `init_cmd.epic_branch_name(key) -> "epic/<key lower>"`, `init_cmd.build_state(o) -> dict`, `init_cmd.run(o, io=None) -> int`.
  - CLI: `turnstile init --epic MYD-16538 --workitem pdfd-429-l2f-editor-funnel --knowledge ../pdffiller-knowledge --lead davyd.pylypenko --lead-github davepylypenko --github-org pdffiller --repo '{"name":"jsfiller","base":"develop","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CCGLRULNR","gate":"pdf-review","gate_check":"pdf-review","ci_ignore":["pdf-review","gate / gate"],"copilot":false}' --repo '{"name":"front-link2fill-app","base":"master","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CFZ7EC5BN","gate":"pr-review","gate_check":null,"copilot":true}' --variant l2f-funnel --desk desk05 [--board-url …] [--workspace .] [--knowledge-base main] [--pm …] [--design …]`.
  - Filesystem result: worktree `<workspace>/<knowledge basename>` on `epic/<key>`; `delivery/` = `<worktree>/context/workitems/<workitem>/delivery/` with `state.json`, `ledger.md`, `decisions.md`, `plan.md`, `briefs/.gitkeep`, `reports/.gitkeep`, `evidence/.gitkeep`, `.gitattributes`, `.state.lock`, `.gitignore`; `<workspace>/.turnstile` with the relative delivery path; `<workspace>/CLAUDE.md` from the template (or `CLAUDE.md.turnstile` when one exists); one commit `turnstile: init <key>` of `delivery/`.
  - `epic.plan = {"path": "plan.md", "submitted_at": null, "digest": null}` is what Task 3 fills.

- [ ] **Step 1: Write the templates**

`templates/state.json`:

```json
{
  "awaiting_human": [],
  "bugs": [],
  "epic": {
    "board": { "artifact_url": null, "capabilities": ["db", "user"] },
    "environment": { "desk": null, "recipe": "references/env/pdffiller-dev.md", "variant": null },
    "github_org": null,
    "key": null,
    "plan": { "digest": null, "path": "plan.md", "submitted_at": null },
    "repos": {},
    "roles": { "design": null, "lead": null, "lead_github": null, "pm": null },
    "workitem": null
  },
  "prs": {},
  "stories": {}
}
```

`templates/CLAUDE.md.workspace`:

```markdown
# {{epic_key}} — orchestrator workspace

You are the orchestrator of epic **{{epic_key}}**. The delivery state lives in `{{delivery}}/` (`state.json`,
`ledger.md`, `plan.md`, `decisions.md`, `briefs/`, `reports/`, `evidence/`, `board.html`) on the epic branch of the
knowledge worktree. Plugin: `turnstile` — invoke the `turnstile` skill first in every session; it starts with
`turnstile status`.

- `state.json` and `ledger.md` are written only by `turnstile` commands; briefs and reports go through the Write tool.
- The lead approves every send, reply, merge, story start and story completion by typing
  `! TURNSTILE_LEAD=1 turnstile approve <ah-id>` in the Claude Code prompt. You report what awaits the lead and ask;
  you never run that line, and no agent does.
- All implementation, review, testing and deployment is delegated to the `turnstile:*` agents; the orchestrator never
  reads diffs or runs suites itself.
- Chat with the lead in Ukrainian. Code, commits, PRs, tickets and docs in English.
```

`skills/turnstile/references/plan.md` (`init` copies it to `delivery/plan.md`):

````markdown
# {{epic_key}} — delivery plan

Status: DRAFT — not approved. Approval: `turnstile plan-submitted` prints the `ah-id`; the lead types
`! TURNSTILE_LEAD=1 turnstile approve <ah-id>`.

## 1. Inputs read

| Document | Path / link | Notes |
|---|---|---|
| Decomposition | | |
| PRD | | |
| Design | Figma file:node | |
| Test plan | | case ids referenced below |
| Repo guides | `<repo>/CLAUDE.md` for every repo in `epic.repos` | |

## 2. Stories

One story = one business slice that is testable and releasable on its own. If the decomposition is not by story,
define the slices here and give the rationale. `human_review: per_pr` is lead-set and exempts a legacy story from the
story gates (README "The lead's word").

| Story | Title | Tickets | Repos | Story branch | After | Parallel with | Env slot |
|---|---|---|---|---|---|---|---|
| S1 | | | | | — | | variant / desk |

## 3. Merge order and stack

Per story: the ticket PRs in merge order, the story branch they stack into (`stories.<S>.branch`; a PR's base is that
branch or another PR of the same story), file overlaps with parallel stories and which merge order resolves them.

## 4. Human-review units (~400 lines of logic each, tests and markup excluded)

| Story | Unit | PRs | Logic lines (est.) |
|---|---|---|---|

## 5. Test-case map and Figma frames

| Story | Test cases | Figma frames (`file:node`) | Parity tolerance |
|---|---|---|---|
| S1 | TP-… | | 1 px, exact colour |

## 6. Inputs needed from humans

| Who | What | Needed by | Blocks |
|---|---|---|---|

## 7. Machine-readable stories (read by `turnstile plan-submitted`; keep in sync with §2–§5)

```json turnstile-stories
{
  "S1": {
    "title": "",
    "tickets": [],
    "repos": [],
    "branch": "",
    "after": [],
    "parallel_with": [],
    "test_cases": [],
    "figma": [],
    "env_slot": { "variant": null, "desk": null },
    "human_review_units": []
  }
}
```
````

- [ ] **Step 2: Failing tests**

```python
# tests/test_init.py
import json, os, pathlib, subprocess, tempfile, unittest
from turnstile_cli import init_cmd
from turnstile_cli.errors import TurnstileError

JS = '{"name":"jsfiller","base":"develop","epic_branch":"epic_myd-1","slack":"C1","gate":"pdf-review","ci_ignore":["pdf-review","gate / gate"]}'
MONO = '{"name":"pdffiller","base":"master","epic_branch":"l2f","slack":"G1","gate":"run-lint","gate_check":null,"copilot":true,"branch_prefix":"l2f-myd-"}'

def opts(ws, knowledge, **kw):
    base = dict(epic="MYD-1", workitem="demo", knowledge=str(knowledge), lead="lead@example.com", lead_github="leadlogin",
                github_org="pdffiller", repos=[JS, MONO], variant="v1", desk="desk05", workspace=str(ws))
    base.update(kw); return init_cmd.InitOptions(**base)

class FakeGit(init_cmd.InitIO):
    def __init__(self): self.calls = []
    def git(self, args, cwd):
        self.calls.append((args, pathlib.Path(cwd)))
        if args[:2] == ["worktree", "add"]:
            pathlib.Path(args[4] if args[2] == "-b" else args[2]).mkdir(parents=True)
        return ""

class ParseRepo(unittest.TestCase):
    def test_defaults_and_required(self):
        name, cfg = init_cmd.parse_repo(JS)
        self.assertEqual(name, "jsfiller")
        self.assertEqual(cfg, {"base": "develop", "epic_branch": "epic_myd-1", "slack": "C1", "gate": "pdf-review",
                               "gate_check": "pdf-review", "ci_ignore": ["pdf-review", "gate / gate"], "copilot": False})
        name, cfg = init_cmd.parse_repo(MONO)
        self.assertEqual((cfg["gate_check"], cfg["ci_ignore"], cfg["copilot"], cfg["branch_prefix"]), (None, [], True, "l2f-myd-"))
        _, cfg = init_cmd.parse_repo('{"name":"locales","base":"main","epic_branch":"e","slack":"C2"}')
        self.assertEqual((cfg["gate"], cfg["gate_check"], cfg["ci_ignore"]), (None, None, []))
        for bad in ['{"name":"x"}', "not json", '["jsfiller"]', '{"name":"x","base":"b","epic_branch":"e","slack":"c","gate":"g","unknown":1}']:
            with self.assertRaises(TurnstileError, msg=bad):
                init_cmd.parse_repo(bad)
    def test_epic_branch_name(self):
        self.assertEqual(init_cmd.epic_branch_name("MYD-16538"), "epic/myd-16538")

class Init(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.ws = self.tmp / "ws"; self.ws.mkdir()
        self.knowledge = self.tmp / "pdffiller-knowledge"; (self.knowledge / ".git").mkdir(parents=True)

    def test_init_creates_worktree_delivery_marker_and_claude_md(self):
        io = FakeGit()
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), io), 0)
        wt = self.ws / "pdffiller-knowledge"; d = wt / "context" / "workitems" / "demo" / "delivery"
        self.assertEqual(io.calls[0][0], ["worktree", "add", "-b", "epic/myd-1", str(wt), "main"]); self.assertEqual(io.calls[0][1], self.knowledge)
        data = json.loads((d / "state.json").read_text())
        self.assertEqual((data["epic"]["key"], data["epic"]["github_org"], data["epic"]["roles"]["lead_github"]), ("MYD-1", "pdffiller", "leadlogin"))
        self.assertEqual(data["epic"]["repos"]["pdffiller"]["branch_prefix"], "l2f-myd-")
        self.assertEqual(data["epic"]["repos"]["jsfiller"]["ci_ignore"], ["pdf-review", "gate / gate"])
        self.assertEqual(data["epic"]["plan"], {"digest": None, "path": "plan.md", "submitted_at": None})
        self.assertEqual(data["epic"]["environment"], {"desk": "desk05", "recipe": "references/env/pdffiller-dev.md", "variant": "v1"})
        for name in ("ledger.md", "decisions.md", "plan.md", "briefs/.gitkeep", "reports/.gitkeep", "evidence/.gitkeep", ".gitattributes", ".state.lock", ".gitignore"):
            self.assertTrue((d / name).exists(), name)
        self.assertIn("MYD-1", (d / "plan.md").read_text()); self.assertIn("turnstile-stories", (d / "plan.md").read_text())
        self.assertEqual((self.ws / ".turnstile").read_text().strip(), "pdffiller-knowledge/context/workitems/demo/delivery")
        self.assertIn("MYD-1", (self.ws / "CLAUDE.md").read_text()); self.assertIn("TURNSTILE_LEAD=1", (self.ws / "CLAUDE.md").read_text())
        self.assertEqual(io.calls[-1][0][:3], ["commit", "-q", "-m"]); self.assertEqual(io.calls[-1][1], d)

    def test_init_keeps_existing_claude_md(self):
        (self.ws / "CLAUDE.md").write_text("mine\n")
        init_cmd.run(opts(self.ws, self.knowledge), FakeGit())
        self.assertEqual((self.ws / "CLAUDE.md").read_text(), "mine\n"); self.assertTrue((self.ws / "CLAUDE.md.turnstile").exists())

    def test_init_reuses_worktree_and_refuses_existing_state(self):
        io = FakeGit(); init_cmd.run(opts(self.ws, self.knowledge), io); n = len(io.calls)
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), io), 2)
        self.assertFalse(any(c[0][:2] == ["worktree", "add"] for c in io.calls[n:]))
        self.assertFalse(any(c[0][:1] == ["commit"] for c in io.calls[n:]))

    def test_init_validates_before_touching_disk(self):
        io = FakeGit()
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge, repos=["{bad"]), io), 2); self.assertEqual(io.calls, [])
        self.assertEqual(init_cmd.run(opts(self.ws, self.tmp / "nope"), io), 2); self.assertEqual(io.calls, [])

    def test_init_with_real_git(self):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.knowledge, check=True)
        (self.knowledge / "README.md").write_text("k\n")
        g = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
        subprocess.run(g + ["add", "."], cwd=self.knowledge, check=True); subprocess.run(g + ["commit", "-qm", "init"], cwd=self.knowledge, check=True)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        class RealGit(init_cmd.InitIO):
            def git(self, args, cwd):
                out = subprocess.run(["git", "-c", "commit.gpgsign=false"] + args, cwd=str(cwd), capture_output=True, text=True, env=env)
                if out.returncode != 0: raise TurnstileError(out.stderr)
                return out.stdout
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), RealGit()), 0)
        wt = self.ws / "pdffiller-knowledge"
        self.assertEqual(subprocess.run(["git", "branch", "--show-current"], cwd=wt, capture_output=True, text=True).stdout.strip(), "epic/myd-1")
        self.assertIn("turnstile: init MYD-1", subprocess.run(["git", "log", "--oneline"], cwd=wt, capture_output=True, text=True).stdout)
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True).stdout, "")
```

Add to `tests/test_hooks.py`, in the test that asserts allowed turnstile commands (the `assertAllowed([... "turnstile status", ...])` list at line ~127): `"turnstile init --epic MYD-1 --workitem demo --knowledge ../k --lead a --lead-github b --github-org o"`.

- [ ] **Step 3: Run to verify they fail**

Run: `python3 -m unittest tests.test_init -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'turnstile_cli.init_cmd'`.

- [ ] **Step 4: Implement `init_cmd.py`**

```python
# turnstile_cli/init_cmd.py
import json, os, pathlib, subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from . import state as st_mod, ledger
from .errors import TurnstileError

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
PLAN_TEMPLATE = ROOT / "skills" / "turnstile" / "references" / "plan.md"
REPO_REQUIRED = ("name", "base", "epic_branch", "slack")
REPO_KEYS = REPO_REQUIRED + ("gate", "gate_check", "ci_ignore", "copilot", "branch_prefix")

@dataclass
class InitOptions:
    epic: str
    workitem: str
    knowledge: str
    lead: str
    lead_github: str
    github_org: str
    repos: List[str] = field(default_factory=list)
    variant: Optional[str] = None
    desk: Optional[str] = None
    board_url: Optional[str] = None
    workspace: str = "."
    knowledge_base: str = "main"
    pm: Optional[str] = None
    design: Optional[str] = None
    recipe: str = "references/env/pdffiller-dev.md"

class InitIO:
    def git(self, args: List[str], cwd: pathlib.Path) -> str:
        out = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True)
        if out.returncode != 0:
            raise TurnstileError("git %s failed: %s" % (" ".join(args), out.stderr.strip()[:200]))
        return out.stdout

def parse_repo(spec: str) -> Tuple[str, dict]:
    try:
        raw = json.loads(spec)
    except json.JSONDecodeError as e:
        raise TurnstileError("--repo must be a JSON object (%s): %r" % (e, spec))
    if not isinstance(raw, dict):
        raise TurnstileError("--repo must be a JSON object with %s" % ", ".join(REPO_REQUIRED))
    for k in REPO_REQUIRED:
        if not raw.get(k):
            raise TurnstileError("--repo lacks %r: %r" % (k, spec))
    unknown = sorted(set(raw) - set(REPO_KEYS))
    if unknown:
        raise TurnstileError("--repo has unknown key(s) %s (allowed: %s)" % (", ".join(unknown), ", ".join(REPO_KEYS)))
    gate = raw.get("gate") or None
    gate_check = raw["gate_check"] if "gate_check" in raw else gate
    cfg = {"base": raw["base"], "epic_branch": raw["epic_branch"], "slack": raw["slack"], "gate": gate, "gate_check": gate_check,
           "ci_ignore": list(raw["ci_ignore"]) if "ci_ignore" in raw else ([gate_check] if gate_check else []),
           "copilot": bool(raw.get("copilot", False))}
    if raw.get("branch_prefix"):
        cfg["branch_prefix"] = raw["branch_prefix"]
    return raw["name"], cfg

def epic_branch_name(key: str) -> str:
    return "epic/" + key.lower()

def build_state(o: InitOptions) -> dict:
    data = json.loads((TEMPLATES / "state.json").read_text())
    e = data["epic"]
    e["key"] = o.epic; e["workitem"] = o.workitem; e["github_org"] = o.github_org
    e["roles"] = {"lead": o.lead, "lead_github": o.lead_github, "pm": o.pm, "design": o.design}
    e["repos"] = dict(parse_repo(s) for s in o.repos)
    e["environment"] = {"variant": o.variant, "desk": o.desk, "recipe": o.recipe}
    e["board"] = {"artifact_url": o.board_url, "capabilities": ["db", "user"]}
    e["plan"] = {"path": "plan.md", "submitted_at": None, "digest": None}
    return data

def _ensure_worktree(o: InitOptions, io: InitIO, knowledge: pathlib.Path, wt: pathlib.Path) -> str:
    branch = epic_branch_name(o.epic)
    if wt.exists():
        return branch
    if io.git(["branch", "--list", branch], knowledge).strip():
        io.git(["worktree", "add", str(wt), branch], knowledge)
    else:
        io.git(["worktree", "add", "-b", branch, str(wt), o.knowledge_base], knowledge)
    return branch

def run(o: InitOptions, io: Optional[InitIO] = None) -> int:
    from .pass_cmd import _ensure_repo_files
    io = io or InitIO()
    try:
        ws = pathlib.Path(o.workspace).resolve()
        knowledge = pathlib.Path(o.knowledge).resolve()
        if not (knowledge / ".git").exists():
            raise TurnstileError("%s is not a git clone (no .git)" % knowledge)
        if not o.repos:
            raise TurnstileError("at least one --repo is required")
        data = build_state(o)  # validates every --repo before anything is created
        wt = ws / knowledge.name
        delivery = wt / "context" / "workitems" / o.workitem / "delivery"
        if (delivery / "state.json").exists():
            raise TurnstileError("already initialised: %s (state.json exists; run turnstile status)" % delivery)
        branch = _ensure_worktree(o, io, knowledge, wt)
        for sub in ("briefs", "reports", "evidence"):
            (delivery / sub).mkdir(parents=True, exist_ok=True); (delivery / sub / ".gitkeep").touch()
        st_mod.write_atomic(delivery / "state.json", st_mod.dumps(data))
        (delivery / "decisions.md").write_text(
            "# Decisions — %s\n\n| Date | Topic | Decision | Source |\n|---|---|---|---|\n\n## Open questions\n\n"
            "| # | Question | Owner | Asked | Answer |\n|---|---|---|---|---|\n" % o.epic)
        (delivery / "plan.md").write_text(PLAN_TEMPLATE.read_text().replace("{{epic_key}}", o.epic))
        _ensure_repo_files(delivery)
        ledger.append(delivery, "init %s (%s) on %s" % (o.epic, o.workitem, branch))
        rel = os.path.relpath(str(delivery), str(ws))
        (ws / ".turnstile").write_text(rel + "\n")
        text = (TEMPLATES / "CLAUDE.md.workspace").read_text().replace("{{epic_key}}", o.epic).replace("{{delivery}}", rel)
        target = ws / "CLAUDE.md"
        if target.exists():
            target = ws / "CLAUDE.md.turnstile"
        target.write_text(text)
        io.git(["add", "-A", "."], delivery)
        io.git(["commit", "-q", "-m", "turnstile: init %s" % o.epic, "--", "."], delivery)
        print("WORKTREE: %s (%s)" % (wt, branch)); print("DELIVERY: %s" % delivery); print("CLAUDE_MD: %s" % target)
        print("NEXT: write %s per references/kickoff.md, then: turnstile plan-submitted" % (delivery / "plan.md"))
        print("OK init %s" % o.epic)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
```

- [ ] **Step 5: Wire the subcommand and the hook allowlist**

`main.py`, in `build_parser()` after the `status` parser:

```python
    ini = sub.add_parser("init", help="create the knowledge worktree and the delivery/ skeleton for an epic")
    for flag, kw in [("--epic", {"required": True}), ("--workitem", {"required": True}), ("--knowledge", {"required": True}),
                     ("--lead", {"required": True}), ("--lead-github", {"required": True}), ("--github-org", {"required": True}),
                     ("--repo", {"action": "append", "default": [], "dest": "repos", "help": "JSON: {name, base, epic_branch, slack[, gate, gate_check, ci_ignore, copilot, branch_prefix]}; repeatable"}),
                     ("--variant", {}), ("--desk", {}), ("--board-url", {}), ("--workspace", {"default": "."}),
                     ("--knowledge-base", {"default": "main"}), ("--pm", {}), ("--design", {}),
                     ("--recipe", {"default": "references/env/pdffiller-dev.md"})]:
        ini.add_argument(flag, **kw)
```

In `main()`, as the first statement inside `try:` (before `delivery = paths.find_delivery(...)`, because no `.turnstile` exists yet):

```python
        if a.cmd == "init":
            from .init_cmd import run as init_run, InitOptions
            return init_run(InitOptions(**{k: v for k, v in vars(a).items() if k not in ("cmd", "delivery")}))
```

`hooks/guard_bash.py`: `TURNSTILE_SUBS = {"pass", "reconcile", "status", "render-board", "jira-synced", "init", "-h", "--help", "--version"}`.

- [ ] **Step 6: Run the tests**

Run: `python3 -m unittest tests.test_init tests.test_hooks -v 2>&1 | tail -3 && scripts/turnstile init --help | head -3`
Expected: PASS; usage shows `--epic --workitem --knowledge --lead --lead-github --github-org`.

- [ ] **Step 7: Commit**

```bash
git add templates/state.json templates/CLAUDE.md.workspace skills/turnstile/references/plan.md turnstile_cli/init_cmd.py turnstile_cli/main.py hooks/guard_bash.py tests/test_init.py tests/test_hooks.py
git commit -m "feat(init): knowledge worktree, delivery skeleton, workspace CLAUDE.md and plan template"
```

---

### Task 2: `epic.github_org` required everywhere

**Files:**
- Create: `tests/test_org.py`
- Modify: `turnstile_cli/pass_cmd.py:738` (`org = data["epic"].get("github_org", "pdffiller")`), `turnstile_cli/reconcile.py:177` (same), `templates/board.html` (`prUrl` fallback)

**Interfaces:**
- Produces: `rules.require_org(data: dict) -> str` — returns `epic.github_org` or raises `TurnstileError("epic.github_org is not set; add it to state.json (turnstile init sets it)")`. Used by `pass_cmd.run`, `reconcile.cli`.
- Board: `prUrl` returns `'#'` when the org is missing (no link), never a guessed organisation.

- [ ] **Step 1: Failing tests**

```python
# tests/test_org.py
import copy, json, pathlib, shutil, tempfile, unittest
from turnstile_cli import board, reconcile, rules, pass_cmd
from turnstile_cli.errors import TurnstileError
from tests.test_pass import FakeIO, opts, run_capture, READY_OPTS, H

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class OrgRequired(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        data = json.loads(FIX.read_text()); del data["epic"]["github_org"]
        (self.d / "state.json").write_text(json.dumps(data)); (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok")
        (self.d / ".state.lock").touch()
    def test_rule(self):
        self.assertEqual(rules.require_org(json.loads(FIX.read_text())), "pdffiller")
        with self.assertRaises(TurnstileError):
            rules.require_org(json.loads((self.d / "state.json").read_text()))
    def test_pass_refuses(self):
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), FakeIO(heads={"jsfiller#1": H}))
        self.assertEqual(rc, 2); self.assertIn("MISSING epic.github_org", out)
    def test_reconcile_refuses(self):
        with self.assertRaises(TurnstileError):
            reconcile.cli(self.d)
    def test_board_has_no_fallback(self):
        html = board.render_html(json.loads(FIX.read_text()))
        self.assertNotIn("'pdffiller'", html)
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_org -v`
Expected: FAIL — `AttributeError: module 'turnstile_cli.rules' has no attribute 'require_org'`.

- [ ] **Step 3: Implement**

`rules.py` (after `valid_head`):

```python
def require_org(data: dict) -> str:
    org = ((data.get("epic") or {}).get("github_org") or "").strip()
    if not org:
        raise TurnstileError("epic.github_org is not set; add it to state.json (turnstile init sets it)")
    return org
```

and `from .errors import TurnstileError` at the top of `rules.py`. In `pass_cmd.run` replace `org = data["epic"].get("github_org", "pdffiller")` with `org = rules.require_org(data)`. In `reconcile.cli` replace `org = st.data["epic"].get("github_org", "pdffiller")` with `org = rules.require_org(st.data)`. In `templates/board.html` replace the `prUrl` line with:

```js
const prUrl = id => { const [repo, n] = id.split('#'); const org = ((STATE || {}).epic || {}).github_org; return org ? 'https://github.com/' + org + '/' + repo + '/pull/' + n : '#'; };
```

- [ ] **Step 4: Run, commit**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -1` — Expected: `OK`.

```bash
git add turnstile_cli/rules.py turnstile_cli/pass_cmd.py turnstile_cli/reconcile.py templates/board.html tests/test_org.py
git commit -m "feat(state): epic.github_org is required; no organisation fallback"
```

---

### Task 3: `plan-submitted` and the lead-approval gate on story start

**Files:**
- Create: `turnstile_cli/plan_cmd.py`, `tests/test_plan_cmd.py`
- Modify: `turnstile_cli/rules.py` (`plan_approval_missing`, `check_story(..., plan_missing=None)`), `turnstile_cli/pass_cmd.py` (story branch computes `plan_missing`), `turnstile_cli/reconcile.py` (`status` prints the plan line), `turnstile_cli/main.py` (wire), `hooks/guard_bash.py` (`TURNSTILE_SUBS` += `"plan-submitted"`), `tests/test_hooks.py`

**Interfaces:**
- Consumes: `state.load/locked/digest`, `pass_cmd.IO`, `pass_cmd._side_effects`, `pass_cmd._open_entry`, `pass_cmd._ensure_start_story_entries`, `pass_cmd._recompute_next_actions`, `pass_cmd._now`, `rules.latest_entry`.
- Produces:
  - `plan_cmd.stories_from_plan(text) -> dict` — parses the fenced block that starts with ```` ```json turnstile-stories ````; raises `TurnstileError` when absent, not JSON, an id is not `S<n>`, a required key (`title`, `tickets`, `repos`, `branch`) is missing or empty, or `after`/`parallel_with` reference unknown ids. Defaults: `after, parallel_with, test_cases, figma, human_review_units = []`, `env_slot = {}`. Other keys (`human_review`) pass through.
  - `plan_cmd.merge_stories(existing, planned) -> dict` — new ids become `PLANNED` with `evidence: {}`, `next_action: ""`; existing ids keep `state`, `evidence`, `next_action`, `last_reason` and take the plan fields; ids missing from the plan are dropped only while `PLANNED`, otherwise `TurnstileError`.
  - `plan_cmd.run(delivery, io=None, no_commit=False) -> int` — under `state.locked`: merges stories, sets `epic.plan = {path, submitted_at, digest}` (digest of `plan.md` via `state.digest`), voids every open `plan` entry (`voided_at`) and opens a new one with `_open_entry(data, "plan", payload="plan.md", digest=<digest>)`, calls `_ensure_start_story_entries` and `_recompute_next_actions`, then `_side_effects`. Prints `PLAN: <n> stories (<new> new)`, `APPROVAL: the lead types: ! TURNSTILE_LEAD=1 turnstile approve <ah-id>`, `OK plan submitted …`.
  - `rules.plan_approval_missing(data, plan_digest) -> Optional[str]` — `None` when `epic.plan.digest` equals `plan_digest` and `latest_entry(awaiting, "plan", "payload", "plan.md")` has `approved_at`; else the `MISSING …` line. `rules.check_story(..., plan_missing=None)` appends it on `PLANNED → IN_PROGRESS` only; **the lead `--reason` override does not bypass it** (spec §4.1: without approval no story leaves PLANNED).
  - CLI: `turnstile plan-submitted [--no-commit]`; `turnstile status` prints `plan: approved <ah-id> | awaiting approval <ah-id> | not submitted | changed since submission`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_plan_cmd.py
import contextlib, io, json, pathlib, shutil, tempfile, unittest
from turnstile_cli import plan_cmd, pass_cmd, rules, state
from turnstile_cli.errors import TurnstileError
from tests.test_pass import FakeIO, opts, env

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"
PLAN = """# plan

```json turnstile-stories
{
  "S1": {"title": "Header", "tickets": ["MYD-10", "MYD-11"], "repos": ["jsfiller"], "branch": "epic_myd-1", "after": [], "parallel_with": [],
         "test_cases": ["TP-1"], "figma": ["F:1-2"], "env_slot": {"variant": "v1"}, "human_review_units": [], "human_review": "per_pr"},
  "S2": {"title": "Results", "tickets": ["MYD-12"], "repos": ["front-link2fill-app"], "branch": "story/s2", "after": ["S1"]}
}
```
"""

class Parse(unittest.TestCase):
    def test_parses_block_and_defaults(self):
        s = plan_cmd.stories_from_plan(PLAN)
        self.assertEqual(sorted(s), ["S1", "S2"]); self.assertEqual(s["S1"]["human_review"], "per_pr")
        self.assertEqual((s["S2"]["parallel_with"], s["S2"]["test_cases"], s["S2"]["env_slot"], s["S2"]["human_review_units"]), ([], [], {}, []))
    def test_rejects(self):
        for bad in ["# no block", PLAN.replace('"S2"', '"X2"'), PLAN.replace('"title": "Results", ', ""),
                    PLAN.replace('"branch": "story/s2", ', ""), PLAN.replace('"after": ["S1"]', '"after": ["S9"]'), PLAN.replace("}\n}\n```", "}\n```")]:
            with self.assertRaises(TurnstileError, msg=bad[:40]):
                plan_cmd.stories_from_plan(bad)

class Merge(unittest.TestCase):
    def test_keeps_state_of_existing_and_plans_new(self):
        existing = json.loads(FIX.read_text())["stories"]
        merged = plan_cmd.merge_stories(existing, plan_cmd.stories_from_plan(PLAN))
        self.assertEqual((merged["S1"]["state"], merged["S1"]["figma"]), ("IN_PROGRESS", ["F:1-2"]))
        self.assertEqual((merged["S2"]["state"], merged["S2"]["evidence"], merged["S2"]["next_action"]), ("PLANNED", {}, ""))
    def test_drop_only_planned(self):
        self.assertNotIn("S1", plan_cmd.merge_stories({"S1": {"state": "PLANNED"}}, {}))
        with self.assertRaises(TurnstileError):
            plan_cmd.merge_stories({"S1": {"state": "PLANNED"}, "S2": {"state": "IN_PROGRESS"}}, {})

class Run(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / "plan.md").write_text(PLAN); (self.d / ".state.lock").touch()
        self.io = FakeIO(heads={"jsfiller#1": "aaaaaaaa11111111"})
    def submit(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = plan_cmd.run(self.d, self.io)
        return rc, buf.getvalue()
    def data(self): return json.loads((self.d / "state.json").read_text())
    def write(self, d): (self.d / "state.json").write_text(state.dumps(d))
    def approve(self, ah):
        with env(TURNSTILE_LEAD="1"):
            self.assertEqual(pass_cmd.approve(self.d, ah, self.io), 0)
    def plan_entry(self):
        return rules.latest_entry(self.data()["awaiting_human"], "plan", "payload", "plan.md")

    def test_submit_records_stories_digest_and_awaiting(self):
        rc, out = self.submit()
        self.assertEqual(rc, 0); self.assertIn("TURNSTILE_LEAD=1 turnstile approve ah-1", out); self.assertIn("OK plan submitted", out)
        d = self.data()
        self.assertEqual(d["stories"]["S2"]["state"], "PLANNED"); self.assertEqual(d["epic"]["plan"]["digest"], state.digest(PLAN))
        e = self.plan_entry(); self.assertEqual((e["id"], e["type"], e["payload"], e["approved_at"]), ("ah-1", "plan", "plan.md", None))
        self.assertEqual(len(self.io.commits), 1); self.assertEqual(self.io.renders, 1); self.assertIn("plan submitted", (self.d / "ledger.md").read_text())
    def test_resubmit_voids_previous_entry(self):
        self.submit(); self.approve("ah-1"); (self.d / "plan.md").write_text(PLAN + "\nmore\n"); self.submit()
        entries = [a for a in self.data()["awaiting_human"] if a["type"] == "plan"]
        self.assertEqual(len(entries), 2); self.assertTrue(entries[0]["voided_at"]); self.assertIsNone(entries[1]["approved_at"])
    def test_story_start_needs_plan_approval_even_with_lead_reason(self):
        d = self.data(); d["stories"]["S1"]["state"] = "DONE"; self.write(d)  # S2 is after S1: plan-submitted opens its start_story entry
        self.submit()
        start = rules.latest_entry(self.data()["awaiting_human"], "start_story", "story", "S2"); self.assertIsNotNone(start)
        self.approve(start["id"])
        self.assertEqual(pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(), self.io), 2)
        self.assertEqual(pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(reason="lead 2026-10-13: go"), self.io), 2)
        self.approve("ah-1")
        self.assertEqual(pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(), self.io), 0)
    def test_edited_plan_voids_approval(self):
        self.submit(); self.approve("ah-1")
        d = self.data(); d["stories"]["S1"]["state"] = "DONE"; self.write(d)
        (self.d / "plan.md").write_text(PLAN + "\nedited after approval\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(reason="lead: go"), self.io)
        self.assertEqual(rc, 2); self.assertIn("plan.md changed", buf.getvalue())
    def test_messages(self):
        d = json.loads(FIX.read_text())
        self.assertIn("plan-submitted", rules.plan_approval_missing(d, state.digest(PLAN)))
        d["epic"]["plan"] = {"path": "plan.md", "submitted_at": "x", "digest": state.digest(PLAN)}
        d["awaiting_human"] = [{"id": "ah-1", "type": "plan", "payload": "plan.md", "approved_at": None}]
        self.assertIn("approve ah-1", rules.plan_approval_missing(d, state.digest(PLAN)))
        d["awaiting_human"][0]["approved_at"] = "x"
        self.assertIsNone(rules.plan_approval_missing(d, state.digest(PLAN)))
```

(`env` is the `TURNSTILE_LEAD` context manager `tests/test_pass.py` already defines and uses in `to_human`.) In `tests/test_hooks.py` add `"turnstile plan-submitted"` to the allowed list used in Task 1.

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_plan_cmd -v`
Expected: FAIL — `No module named 'turnstile_cli.plan_cmd'`.

- [ ] **Step 3: Implement `plan_cmd.py`**

```python
# turnstile_cli/plan_cmd.py
import copy, json, pathlib, re
from typing import Optional
from . import state as st_mod
from .errors import TurnstileError

BLOCK_RX = re.compile(r"```json[ \t]+turnstile-stories[ \t]*\n(.*?)\n```", re.S)
ID_RX = re.compile(r"^S\d+$")
REQUIRED = ("title", "tickets", "repos", "branch")
DEFAULTS = {"after": [], "parallel_with": [], "test_cases": [], "figma": [], "env_slot": {}, "human_review_units": []}
KEEP = ("state", "evidence", "next_action", "last_reason")

def stories_from_plan(text: str) -> dict:
    m = BLOCK_RX.search(text or "")
    if not m:
        raise TurnstileError("plan.md has no ```json turnstile-stories block")
    try:
        raw = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise TurnstileError("turnstile-stories block is not valid JSON: %s" % e)
    if not isinstance(raw, dict) or not raw:
        raise TurnstileError("turnstile-stories must be a non-empty object keyed by story id")
    out = {}
    for sid, s in raw.items():
        if not ID_RX.match(sid):
            raise TurnstileError("story id %r must look like S1" % sid)
        if not isinstance(s, dict):
            raise TurnstileError("story %s must be an object" % sid)
        for k in REQUIRED:
            if not s.get(k):
                raise TurnstileError("story %s lacks %r" % (sid, k))
        full = copy.deepcopy(DEFAULTS); full.update(copy.deepcopy(s))
        out[sid] = full
    for sid, s in out.items():
        for key in ("after", "parallel_with"):
            for ref in s[key]:
                if ref not in out:
                    raise TurnstileError("story %s.%s references unknown story %s" % (sid, key, ref))
    return out

def merge_stories(existing: dict, planned: dict) -> dict:
    merged = {}
    for sid, s in planned.items():
        cur = existing.get(sid)
        merged[sid] = dict(s)
        if cur:
            merged[sid].update({k: cur[k] for k in KEEP if k in cur})
        else:
            merged[sid].update({"state": "PLANNED", "evidence": {}, "next_action": ""})
    for sid, cur in existing.items():
        if sid not in planned and cur.get("state") != "PLANNED":
            raise TurnstileError("cannot drop story %s in state %s; keep it in plan.md" % (sid, cur.get("state")))
    return merged

def run(delivery, io=None, no_commit: bool = False) -> int:
    from .pass_cmd import IO, _side_effects, _open_entry, _ensure_start_story_entries, _recompute_next_actions, _now
    io = io or IO()
    delivery = pathlib.Path(delivery)
    try:
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json"); data = st.data
            plan_path = delivery / "plan.md"
            if not plan_path.exists():
                raise TurnstileError("no plan.md in %s" % delivery)
            text = plan_path.read_text()
            planned = stories_from_plan(text)
            before = set(data.get("stories") or {})
            data["stories"] = merge_stories(data.get("stories") or {}, planned)
            digest = st_mod.digest(text)
            data["epic"]["plan"] = {"path": "plan.md", "submitted_at": _now(), "digest": digest}
            extra = []
            for a in data.setdefault("awaiting_human", []):
                if a.get("type") == "plan" and not a.get("voided_at"):
                    a["voided_at"] = _now(); extra.append("voided %s (plan: superseded by a new submission)" % a["id"])
            entry = _open_entry(data, "plan", payload="plan.md", digest=digest)
            _ensure_start_story_entries(data)
            _recompute_next_actions(data)
            new = sorted(set(planned) - before)
            summary = "plan submitted: %d stories (%d new%s), approval %s" % (len(planned), len(new), ": " + ", ".join(new) if new else "", entry["id"])
            _side_effects(delivery, st, [summary] + extra, io, no_commit)
        print("PLAN: %d stories (%d new)" % (len(planned), len(new)))
        print("APPROVAL: the lead types: ! TURNSTILE_LEAD=1 turnstile approve %s" % entry["id"])
        print("OK " + summary)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
```

- [ ] **Step 4: Rule, pass gate, status line, wiring**

`rules.py`, after `latest_entry`:

```python
def plan_approval_missing(data: dict, plan_digest: Optional[str]) -> Optional[str]:
    plan = (data.get("epic") or {}).get("plan") or {}
    if not plan.get("digest"):
        return "MISSING plan.md submitted and approved (turnstile plan-submitted; the lead approves the printed ah-id)"
    if plan_digest != plan.get("digest"):
        return "MISSING plan.md changed since it was submitted; run turnstile plan-submitted and get the lead's approval again"
    e = latest_entry(data.get("awaiting_human"), "plan", "payload", "plan.md")
    if e is None or not e.get("approved_at"):
        return "MISSING lead approval of plan.md (the lead types: ! TURNSTILE_LEAD=1 turnstile approve %s)" % ((e or {}).get("id") or "<ah-id from turnstile status>")
    return None
```

`check_story` signature gains `plan_missing: Optional[str] = None`; in the `target == "IN_PROGRESS"` branch, right after `if src != "PLANNED": … return out`, insert as the first statement for the PLANNED case:

```python
        if plan_missing:
            out.append(plan_missing)
```

(placed before `override = is_lead_override(reason)`, so the override never clears it).

`pass_cmd.run`, story branch, replace the `missing = rules.check_story(...)` call with:

```python
                plan_missing = None
                if target == "IN_PROGRESS" and story.get("state") == "PLANNED":
                    plan_path = delivery / "plan.md"
                    plan_missing = rules.plan_approval_missing(data, st_mod.digest(plan_path.read_text()) if plan_path.exists() else None)
                missing = rules.check_story(trial, target, data["prs"], data["stories"], reason=o.reason,
                                            bugs=data.get("bugs"), awaiting=awaiting, approved=o.approved, plan_missing=plan_missing)
```

`reconcile.cli`, inside `if status:` right after `print("== %s" % …)`:

```python
        plan = st.data["epic"].get("plan") or {}
        plan_path = pathlib.Path(delivery) / "plan.md"
        e = rules.latest_entry(st.data.get("awaiting_human"), "plan", "payload", "plan.md")
        if not plan.get("digest"):
            print("plan: not submitted (turnstile plan-submitted)")
        elif plan_path.exists() and st_mod.digest(plan_path.read_text()) != plan.get("digest"):
            print("plan: changed since submission (turnstile plan-submitted)")
        elif e and e.get("approved_at"):
            print("plan: approved %s" % e["id"])
        else:
            print("plan: awaiting approval %s" % ((e or {}).get("id") or "?"))
```

`main.py`: `pl = sub.add_parser("plan-submitted", help="read stories from plan.md into state and open the lead's plan approval"); pl.add_argument("--no-commit", action="store_true")` and in `main()`:

```python
        if a.cmd == "plan-submitted":
            from .plan_cmd import run as plan_run
            return plan_run(delivery, no_commit=a.no_commit)
```

`hooks/guard_bash.py`: add `"plan-submitted"` to `TURNSTILE_SUBS`.

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest tests.test_plan_cmd tests.test_rules_story tests.test_pass tests.test_e2e tests.test_hooks 2>&1 | tail -3`
Expected: `OK` (`test_planned_needs_start_story_entry_or_lead_override` passes unchanged: it never passes `plan_missing`).

- [ ] **Step 6: Commit**

```bash
git add turnstile_cli/plan_cmd.py turnstile_cli/rules.py turnstile_cli/pass_cmd.py turnstile_cli/reconcile.py turnstile_cli/main.py hooks/guard_bash.py tests/test_plan_cmd.py tests/test_hooks.py
git commit -m "feat(plan): plan-submitted reads stories from plan.md; story start gated on the lead's plan approval"
```

---

### Task 4: `turnstile bug add | set`

**Files:**
- Create: `turnstile_cli/bug_cmd.py`, `tests/test_bug.py`
- Modify: `turnstile_cli/main.py` (wire), `hooks/guard_bash.py` (`TURNSTILE_SUBS` += `"bug"`), `tests/test_hooks.py`

**Interfaces:**
- Consumes: `state.load/locked`, `pass_cmd.IO`, `pass_cmd._side_effects`, `pass_cmd._now`, `pass_cmd._recompute_next_actions`.
- Produces:
  - `bug_cmd.STATES = ["todo", "ai", "testing", "done"]`, `bug_cmd.PR_RX = re.compile(r"^[A-Za-z0-9_.-]+#\d+$")`.
  - `bug_cmd.next_id(bugs) -> str` → `b01`, `b02`, … (max existing + 1).
  - `bug_cmd.add(delivery, story, title, source, pr=None, figma=None, note="", io=None) -> int` — appends `{id, story, title, source, pr, figma, state: "todo", note, created_at}`; story must exist; `pr` must match `PR_RX` (any repo; the PR may be outside the epic); prints `OK bug b03 added (S1): <title>`.
  - `bug_cmd.set_(delivery, bug_id, state=None, pr=None, note=None, io=None) -> int` — at least one field; prints `OK bug b03 → testing`.
  - CLI: `turnstile bug add --story S1 --title "…" --source "tester 2026-10-13" [--pr jsfiller#13384] [--figma file:node] [--note …]`; `turnstile bug set b03 [--state testing] [--pr …] [--note …]`. Both go through `_side_effects` (ledger line, board, commit `turnstile: bug …`).
  - `created_at` is what Task 6's "every fail became a bug" rule compares with the previous env run.

- [ ] **Step 1: Failing tests**

```python
# tests/test_bug.py
import contextlib, io, json, pathlib, shutil, tempfile, unittest
from turnstile_cli import bug_cmd
from tests.test_pass import FakeIO

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class Bugs(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch(); self.io = FakeIO()
    def data(self): return json.loads((self.d / "state.json").read_text())

    def test_next_id(self):
        self.assertEqual(bug_cmd.next_id([]), "b01"); self.assertEqual(bug_cmd.next_id([{"id": "b03"}, {"id": "b11"}, {"id": "x"}]), "b12")

    def test_add_and_set(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bug_cmd.add(self.d, "S1", "Share visible", "tester 2026-10-13", pr="jsfiller#13384", figma="F:1-2", io=self.io)
        self.assertEqual(rc, 0); self.assertIn("OK bug b01 added (S1)", buf.getvalue())
        b = self.data()["bugs"][0]
        self.assertEqual((b["id"], b["story"], b["state"], b["pr"], b["figma"]), ("b01", "S1", "todo", "jsfiller#13384", "F:1-2")); self.assertTrue(b["created_at"])
        self.assertEqual(bug_cmd.set_(self.d, "b01", state="testing", note="on desk05", io=self.io), 0)
        b = self.data()["bugs"][0]; self.assertEqual((b["state"], b["note"]), ("testing", "on desk05"))
        self.assertEqual(len(self.io.commits), 2); self.assertEqual(self.io.renders, 2)
        self.assertIn("bug b01 → testing", (self.d / "ledger.md").read_text()); self.assertTrue((self.d / "board.html").exists())

    def test_bug_add_validates_story_and_pr(self):
        before = (self.d / "state.json").read_text()
        self.assertEqual(bug_cmd.add(self.d, "S9", "x", "s", io=self.io), 2)
        self.assertEqual(bug_cmd.add(self.d, "S1", "x", "s", pr="jsfiller-13222", io=self.io), 2)
        self.assertEqual(bug_cmd.add(self.d, "S1", "  ", "s", io=self.io), 2)
        self.assertEqual((self.d / "state.json").read_text(), before); self.assertEqual(self.io.commits, [])

    def test_set_validates(self):
        bug_cmd.add(self.d, "S1", "x", "s", io=self.io)
        self.assertEqual(bug_cmd.set_(self.d, "b01", state="fixed", io=self.io), 2)
        self.assertEqual(bug_cmd.set_(self.d, "b02", state="done", io=self.io), 2)
        self.assertEqual(bug_cmd.set_(self.d, "b01", io=self.io), 2)
```

`tests/test_hooks.py`: add `"turnstile bug add --story S1 --title x --source y"` and `"turnstile bug set b01 --state done"` to the allowed list.

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_bug -v` — Expected: FAIL, `No module named 'turnstile_cli.bug_cmd'`.

- [ ] **Step 3: Implement**

```python
# turnstile_cli/bug_cmd.py
import pathlib, re
from typing import List, Optional
from . import state as st_mod
from .errors import TurnstileError

STATES = ["todo", "ai", "testing", "done"]
PR_RX = re.compile(r"^[A-Za-z0-9_.-]+#\d+$")

def next_id(bugs: List[dict]) -> str:
    nums = [int(b["id"][1:]) for b in bugs if re.match(r"^b\d+$", str(b.get("id", "")))]
    return "b%02d" % (max(nums or [0]) + 1)

def _check_pr(pr: Optional[str]) -> None:
    if pr and not PR_RX.match(pr):
        raise TurnstileError("pr must look like repo#123 (got %r)" % pr)

def _commit(delivery: pathlib.Path, st, summary: str, io) -> int:
    from .pass_cmd import _side_effects, _recompute_next_actions
    _recompute_next_actions(st.data)
    _side_effects(delivery, st, [summary], io, False)
    print("OK " + summary); return 0

def add(delivery, story: str, title: str, source: str, pr: Optional[str] = None, figma: Optional[str] = None, note: str = "", io=None) -> int:
    from .pass_cmd import IO, _now
    io = io or IO(); delivery = pathlib.Path(delivery)
    try:
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            if story not in (st.data.get("stories") or {}):
                raise TurnstileError("unknown story %s" % story)
            if not (title or "").strip():
                raise TurnstileError("--title is required")
            _check_pr(pr)
            bugs = st.data.setdefault("bugs", [])
            bug = {"id": next_id(bugs), "story": story, "title": title.strip(), "source": source, "pr": pr, "figma": figma,
                   "state": "todo", "note": note or "", "created_at": _now()}
            bugs.append(bug)
            return _commit(delivery, st, "bug %s added (%s): %s" % (bug["id"], story, bug["title"]), io)
    except TurnstileError as e:
        print("MISSING %s" % e); return 2

def set_(delivery, bug_id: str, state: Optional[str] = None, pr: Optional[str] = None, note: Optional[str] = None, io=None) -> int:
    from .pass_cmd import IO
    io = io or IO(); delivery = pathlib.Path(delivery)
    try:
        if state is None and pr is None and note is None:
            raise TurnstileError("nothing to set: pass --state, --pr or --note")
        if state is not None and state not in STATES:
            raise TurnstileError("state must be one of %s" % ", ".join(STATES))
        _check_pr(pr)
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            bug = next((b for b in st.data.get("bugs", []) if b.get("id") == bug_id), None)
            if bug is None:
                raise TurnstileError("unknown bug %s" % bug_id)
            changes = []
            if state is not None and state != bug.get("state"):
                bug["state"] = state; changes.append("→ %s" % state)
            if pr is not None:
                bug["pr"] = pr; changes.append("pr %s" % pr)
            if note is not None:
                bug["note"] = note; changes.append("note")
            return _commit(delivery, st, "bug %s %s" % (bug_id, ", ".join(changes) or "unchanged"), io)
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
```

`main.py` parser:

```python
    bg = sub.add_parser("bug", help="record or update a bug found by the tester or the lead"); bsub = bg.add_subparsers(dest="bug_cmd")
    ba = bsub.add_parser("add"); ba.add_argument("--story", required=True); ba.add_argument("--title", required=True)
    ba.add_argument("--source", required=True); ba.add_argument("--pr"); ba.add_argument("--figma"); ba.add_argument("--note", default="")
    bs = bsub.add_parser("set"); bs.add_argument("bug_id"); bs.add_argument("--state", choices=["todo", "ai", "testing", "done"]); bs.add_argument("--pr"); bs.add_argument("--note")
```

and in `main()`:

```python
        if a.cmd == "bug":
            from . import bug_cmd
            if a.bug_cmd == "add":
                return bug_cmd.add(delivery, a.story, a.title, a.source, pr=a.pr, figma=a.figma, note=a.note)
            if a.bug_cmd == "set":
                return bug_cmd.set_(delivery, a.bug_id, state=a.state, pr=a.pr, note=a.note)
            parser.parse_args(["bug", "--help"]); return 2
```

`hooks/guard_bash.py`: add `"bug"` to `TURNSTILE_SUBS`.

- [ ] **Step 4: Run, commit**

Run: `python3 -m unittest tests.test_bug tests.test_hooks 2>&1 | tail -1` — Expected: `OK`.

```bash
git add turnstile_cli/bug_cmd.py turnstile_cli/main.py hooks/guard_bash.py tests/test_bug.py tests/test_hooks.py
git commit -m "feat(bug): bug add/set writers for tester and lead findings"
```

---

### Task 5: Story branch — "stacked or merged into the story branch" at INTEGRATION_REVIEW

Review item (Round 3): *add `stories.<S>.branch` and require at INTEGRATION_REVIEW that every PR of the story has `base ∈ {story.branch} ∪ {…the story's other PRs}` (a stack) or is MERGED.* Decision taken here: the set is `{story.branch} ∪ {branch of every other PR of the story}` — a stacked PR's base is the branch **below** it. (Reading "bases of the other PRs" literally would let two PRs both based on the epic branch vouch for each other, which is the case the rule exists to refuse.)

**Files:**
- Create: `tests/test_story_branch.py`
- Modify: `turnstile_cli/rules.py` (`_stacked_into_story_branch`, called from `check_story` for `INTEGRATION_REVIEW`), `tests/fixtures/state_min.json` (`stories.S1.branch`)

**Interfaces:**
- Consumes: `stories.<S>.branch` (required by `plan_cmd.stories_from_plan` since Task 3; the migration sets it to the epic branch for legacy stories), `prs.<id>.base`, `prs.<id>.branch`.
- Produces: `rules._stacked_into_story_branch(story, prs, out)` — appends `MISSING stories.<S>.branch …` when unset, and `MISSING PR <id> based on the story branch <b> or on another PR of the story (base is <x>)` for every non-MERGED PR of the story whose `base` is outside the allowed set.

- [ ] **Step 1: Fixture and failing tests**

In `tests/fixtures/state_min.json` add `"branch": "epic_myd-1",` to `stories.S1` (after `"repos": ["jsfiller"],`). Both fixture PRs have `base: epic_myd-1`, so every existing story test keeps passing.

```python
# tests/test_story_branch.py
import copy, json, pathlib, unittest
from turnstile_cli import rules

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())
H = "aaaaaaaa11111111"

def story(**over):
    s = copy.deepcopy(FIX["stories"]["S1"]); s["_id"] = "S1"; s["state"] = "IN_PROGRESS"
    s["evidence"] = {"deploy": {"build": "1", "head": H}}; s.update(over); return s

def prs(**over):
    out = copy.deepcopy(FIX["prs"])
    for pid in out: out[pid]["state"] = "READY"
    for pid, fields in over.items(): out[pid].update(fields)
    return out

class StoryBranch(unittest.TestCase):
    def check(self, s, p):
        return rules.check_story(s, "INTEGRATION_REVIEW", p, FIX["stories"])
    def test_prs_on_the_story_branch_pass(self):
        self.assertEqual(self.check(story(), prs()), [])
    def test_stacked_pr_passes(self):
        self.assertEqual(self.check(story(), prs(**{"docs-platform#2": {"base": "feature/MYD-10"}})), [])
    def test_pr_based_elsewhere_is_refused_unless_merged(self):
        out = self.check(story(branch="story/s1"), prs(**{"jsfiller#1": {"base": "epic_myd-1"}, "docs-platform#2": {"base": "feature/MYD-10"}}))
        self.assertEqual([m for m in out if "jsfiller#1" in m], ["MISSING PR jsfiller#1 based on the story branch story/s1 or on another PR of the story (base is epic_myd-1)"])
        self.assertEqual([m for m in out if "docs-platform#2" in m], [])
        self.assertEqual(self.check(story(branch="story/s1"), prs(**{"jsfiller#1": {"base": "epic_myd-1", "state": "MERGED"}, "docs-platform#2": {"base": "feature/MYD-10"}})), [])
    def test_two_prs_on_the_epic_branch_do_not_vouch_for_each_other(self):
        out = self.check(story(branch="story/s1"), prs(**{"jsfiller#1": {"base": "epic_myd-1"}, "docs-platform#2": {"base": "epic_myd-1"}}))
        self.assertEqual(len([m for m in out if "based on the story branch" in m]), 2)
    def test_missing_story_branch_fails_closed(self):
        s = story(); del s["branch"]
        self.assertTrue(any("stories.S1.branch" in m for m in self.check(s, prs())))
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_story_branch -v` — Expected: `test_pr_based_elsewhere_is_refused_unless_merged`, `test_two_prs…`, `test_missing_story_branch…` FAIL (no such rule yet).

- [ ] **Step 3: Implement**

`rules.py`, after `_prs_at_least_ready`:

```python
def _stacked_into_story_branch(story: dict, prs: Dict[str, dict], out: List[str]) -> None:
    """Spec §4.2 IN_PROGRESS DoD: every ticket PR of the story is stacked or merged into the story branch. A PR's base is
    the story branch or the branch of another PR of the same story (a stack); MERGED PRs are exempt."""
    sid = story.get("_id"); sb = story.get("branch")
    if not sb:
        out.append("MISSING stories.%s.branch (the story branch the ticket PRs stack into; set it in plan.md and re-run plan-submitted)" % sid)
        return
    mine = {pid: p for pid, p in prs.items() if p.get("story") == sid}
    for pid, p in mine.items():
        if p.get("state") == "MERGED":
            continue
        allowed = {sb} | {q.get("branch") for qid, q in mine.items() if qid != pid and q.get("branch")}
        if p.get("base") not in allowed:
            out.append("MISSING PR %s based on the story branch %s or on another PR of the story (base is %s)" % (pid, sb, p.get("base")))
```

In `check_story`, `target == "INTEGRATION_REVIEW"` branch, after `_prs_at_least_ready(story, prs, out)` add `_stacked_into_story_branch(story, prs, out)`.

- [ ] **Step 4: Run, commit**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -1` — Expected: `OK`.

```bash
git add turnstile_cli/rules.py tests/fixtures/state_min.json tests/test_story_branch.py
git commit -m "feat(rules): INTEGRATION_REVIEW requires every story PR stacked or merged into the story branch"
```

---

### Task 6: Recorded env runs — "every fail became a bug", `--full`, DONE needs a full clean run

Review item (Round 3): *`turnstile pass story S ENV_TESTING --report R --cases-fail N` records a run while staying in ENV_TESTING; with N > 0 it requires at least N bugs of the story created after the previous run; DONE requires that the last recorded run is full (`--full`) with `fail == 0`.*

**Files:**
- Create: `tests/test_env_runs.py`
- Modify: `turnstile_cli/pass_cmd.py` (`Options.full`, `_apply_story_evidence` appends to `evidence.env_runs`, ENV_TESTING self re-entry requires a run, no voiding on re-entry), `turnstile_cli/rules.py` (`STORY_FROM["ENV_TESTING"]` += `"ENV_TESTING"`, `_fails_became_bugs`, DONE requires `full`), `turnstile_cli/main.py` (`--full`), `tests/test_rules_story.py` (`CLEAN_ENV` gets `"full": True`), `tests/test_pass.py:338-359` (the three `opts(... cases_fail=0 ...)` of the DONE tests get `full=True`)

**Interfaces:**
- `Options.full: bool = False`; CLI `--full` on `pass story`.
- `evidence.env_runs: [ {report, cases: {pass, fail}, figma_parity, full, at, bug_ids}, … ]` appended whenever env flags are given (any ENV_TESTING or DONE pass); `bug_ids` = ids of the story's bugs that existed when the run was recorded (set by `pass_cmd.run`, so the rule never depends on minute-resolution timestamps); `evidence.env_test` = the last run (the board and the DONE checks keep reading it).
- `rules.last_env_run(story) -> Optional[dict]` — `env_runs[-1]` if any, else `env_test` (migrated state).
- `rules._fails_became_bugs(story, bugs, out)` — for the last run with `cases.fail = N > 0`: the number of bugs with `bug.story == story._id` whose id is not in the previous run's `bug_ids` (every bug of the story when there is no previous run) must be ≥ N, else `MISSING every failed case became a bug: N fail(s) in the last run, M bug(s) of <S> created after the previous run (turnstile bug add …)`.
- `ENV_TESTING → ENV_TESTING` re-entry: allowed, requires the env flags (`MISSING --report/--cases-pass/--cases-fail/--figma-parity to record a test run`), does not void the open `story_done`, runs `_fails_became_bugs`.
- `DONE`: `last_env_run` must have `full == true`, `cases.fail == 0`, `figma_parity == pass`; `_fails_became_bugs` is not re-run (fail is 0).

- [ ] **Step 1: Failing tests**

```python
# tests/test_env_runs.py
import json, pathlib, shutil, tempfile, unittest
from turnstile_cli import pass_cmd, rules, bug_cmd, state
from tests.test_pass import FakeIO, opts, run_capture, env, H

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class EnvRuns(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / ".state.lock").touch(); (self.d / "reports").mkdir()
        (self.d / "reports" / "ENV.md").write_text("ok"); self.io = FakeIO()
        data = json.loads((self.d / "state.json").read_text())
        for pid in data["prs"]: data["prs"][pid]["state"] = "MERGED"
        data["stories"]["S1"]["state"] = "ENV_TESTING"
        data["stories"]["S1"]["evidence"] = {"deploy": {"build": "1", "head": H}, "integration_review": {"report": "r", "head": H, "clean": True}}
        data["awaiting_human"] = [{"id": "ah-7", "owner": "lead", "type": "story_done", "story": "S1", "created_at": "x", "payload": None,
                                   "approved_at": "2026-10-13T10:00Z", "approved_via": "lead-terminal"}]
        (self.d / "state.json").write_text(state.dumps(data))
    def data(self): return json.loads((self.d / "state.json").read_text())
    def run_env(self, fail, full=False, **kw):
        return run_capture(self.d, "story", "S1", "ENV_TESTING", opts(report="reports/ENV.md", figma_parity="pass", cases_pass=5 - fail, cases_fail=fail, full=full, **kw), self.io)

    def test_reentry_needs_a_run_and_keeps_story_done(self):
        rc, out = run_capture(self.d, "story", "S1", "ENV_TESTING", opts(), self.io)
        self.assertEqual(rc, 2); self.assertIn("record a test run", out)
        rc, out = self.run_env(0, full=True); self.assertEqual(rc, 0, out)
        d = self.data(); self.assertEqual(len(d["stories"]["S1"]["evidence"]["env_runs"]), 1); self.assertTrue(d["stories"]["S1"]["evidence"]["env_runs"][0]["full"])
        self.assertFalse(d["awaiting_human"][0].get("voided_at"))
        self.assertEqual(d["stories"]["S1"]["evidence"]["env_test"]["cases"], {"pass": 5, "fail": 0})

    def test_failed_run_needs_bugs(self):
        rc, out = self.run_env(2, full=True)
        self.assertEqual(rc, 2); self.assertIn("every failed case became a bug: 2 fail(s)", out); self.assertNotIn("env_runs", json.dumps(self.data()))
        bug_cmd.add(self.d, "S1", "a", "tester", io=self.io)
        self.assertEqual(self.run_env(2, full=True)[0], 2)
        bug_cmd.add(self.d, "S1", "b", "tester", io=self.io)
        self.assertEqual(self.run_env(2, full=True)[0], 0)
        # the next failing run counts only bugs created after this run
        rc, out = self.run_env(1); self.assertEqual(rc, 2); self.assertIn("1 fail(s)", out)
        bug_cmd.add(self.d, "S1", "c", "tester", io=self.io)
        self.assertEqual(self.run_env(1)[0], 0)
        self.assertEqual(len(self.data()["stories"]["S1"]["evidence"]["env_runs"]), 2)

    def test_done_needs_full_run(self):
        self.assertEqual(self.run_env(0, full=False)[0], 0)
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)
        self.assertEqual(rc, 2); self.assertIn("full", out)
        self.assertEqual(self.run_env(0, full=True)[0], 0)
        self.assertEqual(run_capture(self.d, "story", "S1", "DONE", opts(approved="ah-7"), self.io)[0], 0)

    def test_done_with_flags_records_a_full_run(self):
        rc, out = run_capture(self.d, "story", "S1", "DONE", opts(report="reports/ENV.md", figma_parity="pass", cases_pass=3, cases_fail=0, full=True, approved="ah-7"), self.io)
        self.assertEqual(rc, 0, out); self.assertEqual(self.data()["stories"]["S1"]["evidence"]["env_runs"][-1]["full"], True)

    def test_rule_reads_env_test_when_no_runs(self):
        s = {"_id": "S1", "state": "ENV_TESTING", "evidence": {"env_test": {"report": "r", "cases": {"pass": 1, "fail": 0}, "figma_parity": "pass", "full": True}}}
        self.assertEqual(rules.last_env_run(s)["full"], True)
```

Update existing tests: in `tests/test_rules_story.py` set `CLEAN_ENV = {"report": "reports/ENV-S1.md", "cases": {"pass": 3, "fail": 0, "not_testable_here": 0}, "figma_parity": "pass", "full": True}`; in `tests/test_pass.py` add `full=True` to the three `opts(report="reports/ENV.md", figma_parity="pass", cases_pass=3, cases_fail=0, …)` calls in `test_story_done_needs_both_case_counts_and_lead_word` and `test_reopen_voids_the_open_story_done_and_done_uses_the_newest_entry` (the `done = opts(...)` literal).

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_env_runs -v` — Expected: FAIL (`Options` has no field `full`).

- [ ] **Step 3: Implement**

`pass_cmd.Options`: add `full: bool = False` (after `offline`). `main.py`: `ps.add_argument("--full", action="store_true", help="the recorded env run covered every case of the story (DONE needs a full clean run)")`.

`pass_cmd._apply_story_evidence`, replace the `ev["env_test"] = {...}` line with:

```python
        run = {"report": o.report, "cases": {"pass": o.cases_pass, "fail": o.cases_fail}, "figma_parity": o.figma_parity, "full": bool(o.full), "at": _now()}
        ev.setdefault("env_runs", []).append(run)
        ev["env_test"] = run
```

`pass_cmd.run`, story branch: before `missing = rules.check_story(...)` add

```python
                if target == "ENV_TESTING" and story.get("state") == "ENV_TESTING" and o.cases_fail is None:
                    raise TurnstileError("--report, --cases-pass, --cases-fail and --figma-parity to record a test run (ENV_TESTING re-entry records a run)")
                if o.cases_fail is not None:
                    trial["evidence"]["env_runs"][-1]["bug_ids"] = sorted(b.get("id") for b in data.get("bugs") or [] if b.get("story") == ident)
```

(placed after `_apply_story_evidence(trial, o)`, which is what appends the run).

and change the voiding condition `if src == "ENV_TESTING" and target != "DONE":` to `if src == "ENV_TESTING" and target not in ("DONE", "ENV_TESTING"):`.

`rules.py`: `STORY_FROM["ENV_TESTING"] = ["INTEGRATION_REVIEW", "ENV_TESTING"]`; add after `_review_head_bound`:

```python
def last_env_run(story: dict) -> Optional[dict]:
    ev = story.get("evidence") or {}
    runs = ev.get("env_runs") or []
    return runs[-1] if runs else (ev.get("env_test") or None)

def _fails_became_bugs(story: dict, bugs: Optional[List[dict]], out: List[str]) -> None:
    """Spec §4.2 ENV_TESTING DoD: every fail became a bug. The last run's fail count needs that many bugs of the story
    created after the previous run (any bug of the story when it is the first run)."""
    runs = (story.get("evidence") or {}).get("env_runs") or []
    if not runs:
        return
    last, prev_ids = runs[-1], set((runs[-2].get("bug_ids") if len(runs) > 1 else None) or [])
    n = (last.get("cases") or {}).get("fail") or 0
    if n <= 0:
        return
    mine = [b for b in bugs or [] if b.get("story") == story.get("_id") and b.get("id") not in prev_ids]
    if len(mine) < n:
        out.append("MISSING every failed case became a bug: %d fail(s) in the last run, %d bug(s) of %s created after the previous run "
                   "(turnstile bug add --story %s --title … --source … before recording the run)" % (n, len(mine), story.get("_id"), story.get("_id")))
```

In `check_story`, `target == "ENV_TESTING"` branch: after `_review_head_bound(story, out)` add `_fails_became_bugs(story, bugs, out)`. In the `target == "DONE"` branch replace `et = (story.get("evidence") or {}).get("env_test") or {}` with `et = last_env_run(story) or {}` and add, after the `figma_parity` check:

```python
        if not et.get("full"):
            out.append("MISSING evidence.env_runs[-1].full (DONE needs one full final run: pass story %s ENV_TESTING … --full)" % sid)
```

- [ ] **Step 4: Run, commit**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -1` — Expected: `OK`.

```bash
git add turnstile_cli/pass_cmd.py turnstile_cli/rules.py turnstile_cli/main.py tests/test_env_runs.py tests/test_rules_story.py tests/test_pass.py
git commit -m "feat(story): recorded env runs; failed cases need bugs; DONE needs a full clean run"
```

---

### Task 7: GitHub facts — "replies posted" at REWORK → ON_HUMAN_REVIEW, trailer/footer caught on GitHub

Review items (Round 3): *REWORK → ON_HUMAN_REVIEW requires that every human review thread open at `rework_since.at` has a reply comment by the lead's login created after `rework_since.at`* (needs thread-level GraphQL) and R3-10 *trailer evasion by escape (`printf 'Co-Authored\x2dBy'`)* — caught here on the commit messages and PR body GitHub returns, not in the Bash guard.

**Files:**
- Create: `tests/test_replies_trailer.py`
- Modify: `turnstile_cli/github.py` (`QUERY`, `PrFacts.threads/trailered/body_footer`, `parse`), `turnstile_cli/pass_cmd.py` (`_facts_mismatches(..., lead_login=None)`, `_verify_against_github` passes it), `turnstile_cli/reconcile.py` (`_dry_run` passes it), `tests/fixtures/gh_pr_13222.json` (thread ids + `createdAt`, commit `message`, `body`), `tests/fixtures/state_min.json` (`roles.lead_github`)

**Interfaces:**
- `github.QUERY` adds: top-level `body`; `allCommits … nodes{commit{oid message signature{isValid}}}`; `reviewThreads(first:100){nodes{id isResolved comments(first:50){nodes{author{__typename login} createdAt}}}}`.
- `PrFacts.threads: List[dict]` — one per review thread: `{"id", "resolved": bool, "human": bool (first author not a bot), "opened_at": str, "replies": [{"login", "at"}, …] (every comment after the first)}`. `human_threads_open`/`copilot_threads_open` are unchanged.
- `PrFacts.trailered: List[str]` — short oids of commits whose message matches `github.TRAILER_RX = re.compile(r"Co-Authored-By|Generated with \[Claude Code\]", re.I)`; `PrFacts.body_footer: bool` — the PR body matches `Generated with \[Claude Code\]`.
- `github.ts(s: Optional[str]) -> Optional[datetime]` — parses `%Y-%m-%dT%H:%M:%SZ` and `%Y-%m-%dT%H:%MZ`; `None` otherwise.
- `pass_cmd._facts_mismatches(pr, target, facts, repo_cfg, lead_login=None)`:
  - for `AI_REVIEW`, `READY`, `ON_HUMAN_REVIEW`: `MISSING no Co-Authored-By trailer / generated-with footer in commit messages (has: <oids>)` when `facts.trailered`; `MISSING PR body without the generated-with footer` when `facts.body_footer`.
  - for `ON_HUMAN_REVIEW` when `pr.rework_since` is set: for every `facts.threads` entry with `human` and `ts(opened_at) <= ts(rework_since.at)`, require a reply with `login == lead_login` and `ts(at) > ts(rework_since.at)`; else `MISSING reply by the lead (<login>) after <since> on human thread <id> (opened <at>): REWORK DoD "replies posted"`. If such threads exist and `lead_login` is empty: `MISSING epic.roles.lead_github (the lead's GitHub login) to verify the replies`.
- `pass_cmd.run` passes `lead_login=data["epic"].get("roles", {}).get("lead_github")`; `reconcile._dry_run` does the same from `data`.

- [ ] **Step 1: Fixture changes**

`tests/fixtures/gh_pr_13222.json`: add `"body": "Scope:\n- x\n\nRelated: https://j/MYD-1"` at the top level; give every `allCommits.nodes[].commit` a `"message": "feat(x): [MYD-10] y"`; give every `reviewThreads.nodes[]` an `"id"` (`"PRRT_1"` … `"PRRT_4"` in order) and every comment a `"createdAt": "2026-10-12T09:00:00Z"`. `tests/fixtures/state_min.json`: `"roles": { "lead": "lead@example.com", "lead_github": "leadlogin" }`.

- [ ] **Step 2: Failing tests**

```python
# tests/test_replies_trailer.py
import copy, json, pathlib, shutil, tempfile, unittest
from turnstile_cli import github, pass_cmd, state
from tests.test_pass import FakeIO, opts, run_capture, env, H, LINK, READY_OPTS

D = pathlib.Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((D / "gh_pr_13222.json").read_text())
SINCE = "2026-10-13T10:00Z"
def thread(tid, opened, replies=(), human_login="lMakDen"):
    return {"id": tid, "resolved": False, "human": True, "opened_at": opened, "replies": [{"login": l, "at": a} for l, a in replies]}

class Parse(unittest.TestCase):
    def test_threads_trailer_body(self):
        f = github.parse("jsfiller#1", PAYLOAD)
        self.assertEqual(len(f.threads), 4); self.assertEqual(f.threads[0]["id"], "PRRT_1"); self.assertTrue(f.threads[0]["human"]); self.assertFalse(f.threads[1]["human"])
        self.assertEqual(f.threads[0]["opened_at"], "2026-10-12T09:00:00Z"); self.assertEqual(f.threads[0]["replies"], [])
        self.assertEqual(f.trailered, []); self.assertFalse(f.body_footer)
        p = copy.deepcopy(PAYLOAD); p["allCommits"]["nodes"][0]["commit"]["message"] = "x\n\nCo-Authored-By: a"; p["body"] += "\n\n🤖 Generated with [Claude Code](https://x)"
        f = github.parse("jsfiller#1", p); self.assertEqual(len(f.trailered), 1); self.assertTrue(f.body_footer)
    def test_ts(self):
        self.assertLess(github.ts("2026-10-13T10:00Z"), github.ts("2026-10-13T10:00:30Z")); self.assertIsNone(github.ts("nope"))

class Rework(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(D / "state_min.json", self.d / "state.json"); (self.d / ".state.lock").touch()
        (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok")
        self.io = FakeIO(heads={"jsfiller#1": H})
        # a PR on human review that went to REWORK at SINCE with one human thread opened before it
        data = json.loads((self.d / "state.json").read_text()); pr = data["prs"]["jsfiller#1"]
        pr["state"] = "REWORK"; pr["rework_since"] = {"head": H, "at": SINCE, "reason": "human thread PRRT_1"}
        pr["evidence"].update({"head_verified": {"head": H, "verified": True}, "deep_review": {"head": H, "report": "reports/R.md", "rounds": 1, "clean": True},
                               "gate": {"name": "pdf-review", "head": H, "result": "pass"}, "human": {"head": H, "sent_head": H, "slack_permalink": LINK, "approved": "ah-1", "open_threads": 1, "approvals": []}})
        data["stories"]["S1"]["state"] = "DONE"
        data["awaiting_human"] = [{"id": "ah-2", "owner": "lead", "type": "reply", "pr": "jsfiller#1", "head": H, "created_at": SINCE, "payload": None,
                                   "approved_at": "2026-10-13T10:30Z", "approved_via": "lead-terminal", "used_at": "2026-10-13T10:40Z", "message_ts": "1.2"}]
        (self.d / "state.json").write_text(state.dumps(data))
    def go(self):
        return run_capture(self.d, "pr", "jsfiller#1", "ON_HUMAN_REVIEW", opts(head=H, ci="success", gate="pdf-review:pass", slack=LINK, approved="ah-2"), self.io)
    def test_rework_needs_lead_replies(self):
        self.io.facts["jsfiller#1"] = {"threads": [thread("PRRT_1", "2026-10-13T09:00:00Z")]}
        rc, out = self.go(); self.assertEqual(rc, 2); self.assertIn("reply by the lead (leadlogin)", out); self.assertIn("PRRT_1", out)
        self.io.facts["jsfiller#1"] = {"threads": [thread("PRRT_1", "2026-10-13T09:00:00Z", [("someoneelse", "2026-10-13T11:00:00Z")])]}
        self.assertEqual(self.go()[0], 2)
        self.io.facts["jsfiller#1"] = {"threads": [thread("PRRT_1", "2026-10-13T09:00:00Z", [("leadlogin", "2026-10-13T09:30:00Z")])]}
        self.assertEqual(self.go()[0], 2)  # the lead's reply predates the rework
        self.io.facts["jsfiller#1"] = {"threads": [thread("PRRT_1", "2026-10-13T09:00:00Z", [("leadlogin", "2026-10-13T11:00:00Z")]),
                                                   thread("PRRT_9", "2026-10-13T12:00:00Z")]}  # opened after the rework: not required
        rc, out = self.go(); self.assertEqual(rc, 0, out)
    def test_lead_login_required_when_threads_exist(self):
        data = json.loads((self.d / "state.json").read_text()); data["epic"]["roles"]["lead_github"] = None; (self.d / "state.json").write_text(state.dumps(data))
        self.io.facts["jsfiller#1"] = {"threads": [thread("PRRT_1", "2026-10-13T09:00:00Z")]}
        rc, out = self.go(); self.assertEqual(rc, 2); self.assertIn("lead_github", out)
    def test_bot_threads_ignored(self):
        t = thread("PRRT_2", "2026-10-13T09:00:00Z"); t["human"] = False
        self.io.facts["jsfiller#1"] = {"threads": [t]}
        self.assertEqual(self.go()[0], 0)

class Trailer(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(D / "state_min.json", self.d / "state.json"); (self.d / ".state.lock").touch()
        (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok"); self.io = FakeIO(heads={"jsfiller#1": H})
    def test_trailer_and_footer_refused(self):
        self.io.facts["jsfiller#1"] = {"trailered": ["abc12345"]}
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("Co-Authored-By", out); self.assertIn("abc12345", out)
        self.io.facts["jsfiller#1"] = {"body_footer": True}
        rc, out = run_capture(self.d, "pr", "jsfiller#1", "READY", opts(**READY_OPTS), self.io)
        self.assertEqual(rc, 2); self.assertIn("generated-with footer", out)
```

- [ ] **Step 3: Run, expect failure**

Run: `python3 -m unittest tests.test_replies_trailer -v` — Expected: FAIL (`PrFacts` has no `threads`; `github.ts` missing).

- [ ] **Step 4: Implement `github.py`**

Replace `QUERY` with:

```python
QUERY = """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ pullRequest(number:$n){
  isDraft merged mergeCommit{oid} headRefOid baseRefName reviewDecision body
  allCommits: commits(last:100){totalCount nodes{commit{oid message signature{isValid}}}}
  latestReviews(first:30){nodes{author{__typename login} state commit{oid}}}
  reviewThreads(first:100){nodes{id isResolved comments(first:50){nodes{author{__typename login} createdAt}}}}
  commits(last:1){nodes{commit{oid signature{isValid} statusCheckRollup{state contexts(first:100){totalCount nodes{
    ... on CheckRun{name conclusion status} ... on StatusContext{context state}}}}}}} } } }"""
TRAILER_RX = re.compile(r"Co-Authored-By|Generated with \[Claude Code\]", re.I)
FOOTER_RX = re.compile(r"Generated with \[Claude Code\]", re.I)
```

(add `import re, datetime` at the top). Add to `PrFacts`:

```python
    threads: List[dict] = field(default_factory=list)   # {id, resolved, human, opened_at, replies: [{login, at}]}
    trailered: List[str] = field(default_factory=list)  # commits whose message carries a trailer or the generated-with footer
    body_footer: bool = False
```

Add the helper:

```python
def ts(s: Optional[str]) -> Optional[datetime.datetime]:
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ"):
        try:
            return datetime.datetime.strptime(s or "", fmt)
        except ValueError:
            continue
    return None
```

In `parse`, replace the thread loop with:

```python
    human_open = copilot_open = 0
    threads = []
    for t in (pr.get("reviewThreads") or {}).get("nodes") or []:
        comments = (t.get("comments") or {}).get("nodes") or [{}]
        first = comments[0]; author = first.get("author") or {}
        human = author.get("login") != BOT and not is_bot(author)
        threads.append({"id": t.get("id"), "resolved": bool(t.get("isResolved")), "human": human, "opened_at": first.get("createdAt") or "",
                        "replies": [{"login": (c.get("author") or {}).get("login") or "", "at": c.get("createdAt") or ""} for c in comments[1:]]})
        if t.get("isResolved"):
            continue
        if author.get("login") == BOT:
            copilot_open += 1
        elif human:
            human_open += 1
```

and compute, before the `return PrFacts(...)`:

```python
    trailered = [((n.get("commit") or {}).get("oid") or "")[:8] for n in (pr.get("allCommits") or {}).get("nodes") or []
                 if TRAILER_RX.search((n.get("commit") or {}).get("message") or "")]
```

then pass `threads=threads, trailered=trailered, body_footer=bool(FOOTER_RX.search(pr.get("body") or ""))` to the constructor.

- [ ] **Step 5: Implement the checks in `pass_cmd.py` and the dry run**

`_facts_mismatches` signature → `def _facts_mismatches(pr: dict, target: str, facts, repo_cfg: dict, lead_login: Optional[str] = None) -> List[str]:`. Inside the `if target in ("AI_REVIEW", "READY", "ON_HUMAN_REVIEW"):` block, after the `facts.unsigned` check:

```python
        if facts.trailered:
            out.append("MISSING no Co-Authored-By trailer / generated-with footer in commit messages (has: %s)" % ", ".join(facts.trailered))
        if facts.body_footer:
            out.append("MISSING PR body without the generated-with footer")
```

After the `if target in ("READY", "ON_HUMAN_REVIEW"):` block add:

```python
    if target == "ON_HUMAN_REVIEW" and pr.get("rework_since"):
        from . import github
        since = github.ts((pr.get("rework_since") or {}).get("at"))
        pending = [t for t in facts.threads if t.get("human") and since and (github.ts(t.get("opened_at")) or datetime.datetime.min) <= since]
        if pending and not lead_login:
            out.append("MISSING epic.roles.lead_github (the lead's GitHub login) to verify the replies on %d human thread(s)" % len(pending))
        for t in pending:
            if lead_login and not any(r.get("login") == lead_login and (github.ts(r.get("at")) or datetime.datetime.min) > since for r in t.get("replies") or []):
                out.append("MISSING reply by the lead (%s) after %s on human thread %s (opened %s): REWORK DoD \"replies posted\""
                           % (lead_login, pr["rework_since"].get("at"), t.get("id"), t.get("opened_at")))
```

`_verify_against_github` signature gains `lead_login: Optional[str] = None` and its last line becomes `return _facts_mismatches(pr, target, facts, repo_cfg, lead_login)`. In `run`: `missing = _verify_against_github(trial, ident, target, repo, org, o, io, notes, lead_login=(data["epic"].get("roles") or {}).get("lead_github"))`. In `reconcile._dry_run`: `missing = pass_cmd._facts_mismatches(pr, target, facts, repo, lead_login=(data["epic"].get("roles") or {}).get("lead_github")) if facts is not None else []`.

- [ ] **Step 6: Run, commit**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -1` — Expected: `OK` (`test_reconcile.Parse.test_parse` still sees `human_threads_open == 1`, `copilot_threads_open == 0`; the existing REWORK tests use `FakeIO` facts with `threads == []`, so no reply is required there).

```bash
git add turnstile_cli/github.py turnstile_cli/pass_cmd.py turnstile_cli/reconcile.py tests/fixtures/gh_pr_13222.json tests/fixtures/state_min.json tests/test_replies_trailer.py
git commit -m "feat(github): REWORK needs the lead's replies on open threads; trailer and footer caught on GitHub"
```

---

### Task 8: Board — bug-status overlay through the artifact `db`, artifact url in the `BOARD:` line

Ported from `/Users/davyd/Desktop/pdffiller/MYD-16538-docs/pr-board.html` (`connectBugsDb`, `renderBugs`): the dropdown writes `bugs/<id>` = `{status, updatedAt}` into the artifact's db; viewers see the overlay; the orchestrator folds it back into `state.json` with `turnstile bug set` (Task 11, SKILL.md "Bugs on the board").

**Files:**
- Create: `tests/test_board_bugs.py`
- Modify: `templates/board.html` (replace `function bugs()`, add the overlay, extend `legend()`), `turnstile_cli/pass_cmd.py` (`BOARD:` line)

**Interfaces:**
- Board JS: `BUG_STATES = ['todo', 'ai', 'testing', 'done']`; `bugOverrides` (db docs); `bugState(b)` = override `status` when it is a known state, else `b.state`; `<select class="bug" data-bug="<id>">` per bug, `disabled` unless `bugsCanWrite`; change → `bugsDb.doc('bugs/' + id).set({status, updatedAt: ISO})`, revert on error; `connectBugsDb()` = `claude.use('db')` → `claude.use('user')` → `user.can('data.write')` (`null`/`undefined` ⇒ writable: the owner's own view) → `db.collection('bugs').onSnapshot(...)` re-renders bugs and tiles; runs only when `window.claude.use` is a function (a plain file open stays static).
- `pass_cmd.run` prints `BOARD: publish <path> → <epic.board.artifact_url | new artifact (capabilities: db, user)>`.

- [ ] **Step 1: Failing test**

```python
# tests/test_board_bugs.py
import json, pathlib, unittest
from turnstile_cli import board

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())

class BoardBugs(unittest.TestCase):
    def html(self):
        data = json.loads(json.dumps(FIX))
        data["bugs"] = [{"id": "b01", "story": "S1", "title": "Share visible", "source": "tester", "pr": "jsfiller#13384", "figma": "F:1", "state": "todo", "note": "", "created_at": "x"}]
        return board.render_html(data)
    def test_overlay_wiring(self):
        html = self.html()
        for needle in ["claude.use('db')", "claude.use('user')", "user.can('data.write')", "db.collection('bugs').onSnapshot(",
                       "bugsDb.doc('bugs/' + id).set({", 'data-bug="', "const BUG_STATES = ['todo', 'ai', 'testing', 'done']",
                       "BUG_STATES.includes(", "typeof window.claude.use === 'function'", "<th>Figma</th>"]:
            self.assertIn(needle, html, needle)
    def test_select_disabled_without_write(self):
        self.assertIn("(bugsCanWrite ? '' : ' disabled title=\"Status changes are saved by the board owner\"')", self.html())
    def test_legend_mentions_bug_states_and_fold_back(self):
        html = self.html(); self.assertIn("turnstile bug set", html); self.assertIn("todo → ai", html)
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_board_bugs -v` — Expected: FAIL on `claude.use('db')`.

- [ ] **Step 3: Implement in `templates/board.html`**

Add to the `<style>` block:

```css
select.bug { font:inherit; font-size:12px; padding:2px 6px; border-radius:6px; border:1px solid var(--line); background:var(--card); color:var(--ink) }
select.bug:disabled { opacity:.7 } .manual { display:block; color:var(--muted); font-size:11px }
```

Replace `function bugs() { … }` with:

```js
const BUG_STATES = ['todo', 'ai', 'testing', 'done'];
let bugOverrides = {}, bugsDb = null, bugsCanWrite = false;
const bugState = b => (bugOverrides[b.id] && BUG_STATES.includes(bugOverrides[b.id].status)) ? bugOverrides[b.id].status : b.state;
const openBugs = () => (STATE.bugs || []).filter(b => bugState(b) !== 'done').length;
function bugs() {
  const counts = {}; (STATE.bugs || []).forEach(b => { const k = bugState(b); counts[k] = (counts[k] || 0) + 1; });
  document.getElementById('bugs').innerHTML =
    '<div class="tiles">' + BUG_STATES.map(k => '<div class="tile"><b>' + (counts[k] || 0) + '</b><span>' + k + '</span></div>').join('') + '</div>' +
    '<div class="scroll"><table><thead><tr><th>#</th><th>Story</th><th>Bug</th><th>Source</th><th>PR</th><th>Figma</th><th>State</th><th>Note</th></tr></thead><tbody>' +
    (STATE.bugs || []).map(b => {
      const cur = bugState(b);
      const manual = bugOverrides[b.id] ? '<span class="manual">changed ' + esc(String(bugOverrides[b.id].updatedAt || '').slice(0, 16).replace('T', ' ')) + '</span>' : '';
      return '<tr><td class="k">' + esc(b.id) + '</td><td>' + esc(b.story) + '</td><td>' + esc(b.title) + '</td><td class="muted">' + esc(b.source) + '</td><td class="k">' +
        (b.pr ? '<a href="' + esc(prUrl(b.pr)) + '" target="_blank" rel="noopener">' + esc(b.pr) + '</a>' : '—') + '</td><td class="k">' + esc(b.figma || '—') + '</td>' +
        '<td>' + badge(cur) + ' <select class="bug" data-bug="' + esc(b.id) + '"' + (bugsCanWrite ? '' : ' disabled title="Status changes are saved by the board owner"') + '>' +
        BUG_STATES.map(k => '<option value="' + k + '"' + (k === cur ? ' selected' : '') + '>' + k + '</option>').join('') + '</select>' + manual + '</td>' +
        '<td>' + esc(b.note) + '</td></tr>';
    }).join('') + '</tbody></table></div>';
  document.querySelectorAll('select[data-bug]').forEach(sel => sel.addEventListener('change', async () => {
    if (!bugsDb) return;
    const id = sel.getAttribute('data-bug'), status = sel.value; sel.disabled = true;
    try { await bugsDb.doc('bugs/' + id).set({ status: status, updatedAt: new Date().toISOString() }); }
    catch (e) { sel.value = bugState((STATE.bugs || []).find(b => b.id === id) || { state: 'todo' }); }
    finally { sel.disabled = !bugsCanWrite; }
  }));
}
async function connectBugsDb() {
  try {
    const db = await claude.use('db'); if (!db) return; bugsDb = db;
    const user = await claude.use('user'); const w = user ? await user.can('data.write') : null;
    bugsCanWrite = (w === null || w === undefined) ? true : !!w; bugs();
    db.collection('bugs').onSnapshot(snap => { const next = {}; for (const d of snap.docs) { if (d.exists) next[d.id] = d.data(); } bugOverrides = next; bugs(); tiles(); }, () => {});
  } catch (e) { /* no db in this view */ }
}
```

In `tiles()` replace `(STATE.bugs || []).filter(b => b.state !== 'done').length` with `openBugs()`. In `legend()` append to the innerHTML string:

```js
    '<br><b>Bugs:</b> todo → ai (an agent is fixing) → testing (deployed, waiting for a re-test) → done. The dropdown writes to the board database; the orchestrator folds it back with <span class="k">turnstile bug set</span>.'
```

Replace the last script line with:

```js
if (STATE) { document.getElementById('title').textContent = 'Turnstile — ' + (STATE.epic || {}).key; tiles(); prs(); stories(); bugs(); awaiting(); legend();
  if (window.claude && typeof window.claude.use === 'function') { connectBugsDb(); } else { window.addEventListener('load', () => { if (window.claude && typeof window.claude.use === 'function') connectBugsDb(); }); } }
```

In `pass_cmd.run` replace `print("BOARD: publish %s" % (delivery / "board.html"))` with:

```python
        url = ((data.get("epic") or {}).get("board") or {}).get("artifact_url")
        print("BOARD: publish %s → %s" % (delivery / "board.html", url or "new artifact (capabilities: db, user; then record the url in state.json at migration or init --board-url)"))
```

- [ ] **Step 4: Run, commit**

Run: `python3 -m unittest tests.test_board_bugs tests.test_board tests.test_pass 2>&1 | tail -1` — Expected: `OK` (`test_board` still finds `(e.env_test.cases || {}).fail`, `<th>Note</th>`, `--merged:#4b5563`).

Run: `python3 -c "import json,pathlib;from turnstile_cli import board;h=board.render_html(json.loads(pathlib.Path('tests/fixtures/state_min.json').read_text()));print(h.count('<script>'),h.count('</script>'))"` — Expected: `1 1`.

```bash
git add templates/board.html turnstile_cli/pass_cmd.py tests/test_board_bugs.py
git commit -m "feat(board): bug-status overlay via the artifact db; BOARD line names the artifact url"
```

---

### Task 9: The eight role agents

**Files:**
- Create: `agents/implementer.md`, `agents/reviewer.md`, `agents/story-reviewer.md`, `agents/stack-step.md`, `agents/comments-handler.md`, `agents/investigator.md`, `agents/tester.md`, `agents/deployer.md`, `tests/test_agents.py`

**Interfaces:**
- Produces: eight agent definitions launchable as `turnstile:<name>`; each has frontmatter per Global Constraints and the sections `## Role`, `## Procedure`, `## Cannot`, `## Report`, `## Common rules`. Brief templates (Task 10) address them by these names; report names per `references/reports.md` (Task 11).

- [ ] **Step 1: Failing test**

```python
# tests/test_agents.py
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
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_agents -v` — Expected: FAIL (`agents/` does not exist).

- [ ] **Step 3: The common block (paste verbatim as the last section of every agent file)**

```markdown
## Common rules

- Read the brief file named in your prompt first, then every file it lists; the brief wins on specifics. Verify every anchor (file:line, symbol) before editing; a wrong anchor means stop and report `NEEDS_CONTEXT` with what you found instead. Never guess.
- Poll every 2 minutes or less when waiting on CI, Copilot, a workflow or a build; never silent for more than 5 minutes — print one line of progress. Keep your working state in the report file as you go so a restart after a limit or a watchdog resumes cheaply.
- Write the full report to the path the brief gives under `reports/` using the template in `references/reports.md` (the Write tool; never Bash redirects into the delivery dir); reply to the orchestrator with at most 8 lines: status (`DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`), the head SHA(s), the PR URL(s), one-line result, concerns.
- Never claim a pass you did not observe: paste the real summary lines of every command you ran.
- Signed commits only (never `--no-gpg-sign`), conventional message with the ticket key, no `Co-Authored-By` trailer in any spelling (the gate reads the messages on GitHub). PR bodies per `references/pr-body.md`, no generated-with footer. Never comment on a PR; the repo gate's own outputs are the only allowed PR comments.
- No Slack, no Jira, no reviewer requests, no "ready for review", no merges, no force-push, no rebase of shared branches, no subagents, never `turnstile approve` or `TURNSTILE_LEAD` (the lead's own prompt line). The hooks block most of this; the rule covers the rest.
- Code, commits, PRs and reports in English.
```

- [ ] **Step 4: Write the eight files**

`agents/implementer.md`:

```markdown
---
name: implementer
description: Implements one ticket from a turnstile brief on a branch cut from the epic or story branch — code, tests, lint/types, a draft PR per template, signed commits, Copilot loop where the repo has it. Launched by the turnstile skill's dispatch; not for reviews, deployments, Slack or Jira.
model: sonnet
tools: Read, Edit, Write, Bash, Grep, Glob
---

You implement exactly one ticket per brief inside one repository. You follow the brief literally and report what it did not foresee.

## Role

- One ticket = one branch = one draft PR into the base the brief names (the story branch, or the branch of the PR below you in the stack). Branch name per the brief (`feature/<KEY>-<slug>` or the repo's `branch_prefix`).
- Change only the files the brief lists plus the tests it asks for. No refactors, no reformatting of untouched lines, no new dependencies, no CI changes, no code comments unless asked.
- Control arm untouched: a flagged feature ships with a test that has the flag off and asserts today's behaviour.

## Procedure

1. Read the target repo's `CLAUDE.md` / `AGENTS.md` / testing guide, then the brief, then every anchor it names.
2. `git fetch`; cut the branch from the base the brief names, or check out the existing one and merge the base in (never rebase).
3. Tests first where the brief lists them; implement; run exactly the verify commands from the brief and keep the summary lines.
4. Commit (signed, conventional, ticket key), push normally. On a rejected push stop and report.
5. `gh pr create --draft --base <base>` with the body from `references/pr-body.md`. Never request human reviewers, never mark ready, never add labels unless the brief says so.
6. When the brief says the repo has Copilot: request it via REST (`gh api -X POST repos/<org>/<repo>/pulls/<n>/requested_reviewers -f 'reviewers[]=copilot-pull-request-reviewer[bot]'`), wait, verify each thread against the code, fix the valid ones with a test, resolve every thread silently with the verdict in your report, re-request, repeat until a pass has no findings on the current head.
7. Verify every commit is signed: `gh api repos/<org>/<repo>/pulls/<n>/commits --jq '.[].commit.verification.verified'` — all `true`.

## Cannot

Slack, Jira, replying to or resolving human threads, `gh pr ready`, other repositories, subagents, merges, force-push, `turnstile approve`.

## Report

`reports/<KEY>.md` per `references/reports.md` § Ticket: files changed, per-command summary lines, PR URL, head, Copilot verdicts, deviations from the brief, open questions, backlog notes. The orchestrator records the PR with `turnstile pass pr <id> AI_REVIEW --head <sha> --ci success`.
```

`agents/reviewer.md`:

```markdown
---
name: reviewer
description: Deep review of one PR against its ticket and the epic invariants, then the repository's own review gate; recursive until the head is clean. Applies one-line fixes itself. Launched by turnstile dispatch for AI_REVIEW; never for human-review replies, merges or Slack.
model: opus
effort: xhigh
tools: Read, Edit, Bash, Grep, Glob, Skill
---

You are the most important step of the flow. You read the whole diff, not a summary, and you look for what would embarrass the team in human review.

## Role

- Scope: `git diff <base>...<head>`, every scope bullet of the ticket, the control arm, every test's assertions (does it bite? would a mutation pass?), the invariants listed in the brief, fidelity to the source when the PR ports code, design fidelity when the brief names Figma frames.
- Output: a numbered findings list with severity (`blocker` / `major` / `minor` / `nit`): what, where (`file:line`), why, proposed fix. One-line fixes you apply yourself (signed commit on the PR branch, noted in the report); everything else goes back through the orchestrator.
- Recursive: after fixes land you review the new head again until a round has zero `blocker`/`major` findings. Record the rounds.

## Procedure

1. Read the repo's `CLAUDE.md`, the brief, the ticket text in the brief, the PR body.
2. Check out the PR head in the worktree the brief names; confirm `gh pr view <n> --json headRefOid` matches the brief's head.
3. Deep review as above. Write the findings before running the gate so the gate does not anchor you.
4. Run the repo gate the brief names (`pdf-review` via its skill, or `pr-review` / `review` / `run-lint` + `run-unit-tests`) on the same head; its own PR comments and labels are allowed, yours are not.
5. Merge the two lists; mark duplicates; verify every gate finding against the code before accepting it.
6. Report `clean: true` only when both your review and the gate have no open `blocker`/`major` on the current head.

## Cannot

Merge, mark ready, reply to humans, Slack, Jira, subagents, rebase, force-push, multi-line fixes (those go to an implementer brief), `turnstile approve`.

## Report

`reports/REVIEW-<pr-number>.md` per `references/reports.md` § Review: head, base, rounds, findings table, gate run URL, what you fixed yourself, `clean`. The orchestrator records it with `turnstile pass pr <id> READY --head <sha> --deep-review reports/REVIEW-<n>.md --rounds <r> --gate <gate>:pass:<run> [--copilot 0]`.
```

`agents/story-reviewer.md`:

```markdown
---
name: story-reviewer
description: Whole-story integration review of the story branch (stack top) against the epic branch, recursive until clean; findings routed to the ticket PRs they belong to. Launched by turnstile story-gate; never replies to humans, merges or posts.
model: fable
tools: Read, Edit, Bash, Grep, Glob, Skill
---

You review a business slice as one change, the way a human reviewer will see it, after the ticket PRs have each passed their own review.

## Role

- Scope: `git diff <epic-branch>...<stack-top>` for the story's repos; the story's tickets as a whole; cross-ticket seams (state shapes, selectors, API contracts, copy keys); the test plan cases mapped to the story; the Figma frames named in the brief; the epic invariants.
- Findings carry the ticket PR they belong to, so fixes land in that PR and its gates re-run.
- Recursive: re-review the new stack top after fixes until a round has no `blocker`/`major`.

## Procedure

1. Read the brief, `plan.md` § the story, the repos' `CLAUDE.md`, the previous `REVIEW-<n>.md` reports of the story's PRs (do not repeat what they fixed; check that it is fixed).
2. Check out the stack top; verify its SHA with `gh pr view` of the top PR; it must equal `evidence.deploy.head` in the brief.
3. Review the whole diff; then run the repo gate on the stack top if the brief asks for it.
4. One-line fixes: apply on the ticket PR branch they belong to (signed); report for a stack-step agent to ripple them up.

## Cannot

Merge, ready, replies to humans, Slack, Jira, subagents, rebase, force-push, `turnstile approve`.

## Report

`reports/STORY-<S>-review.md` per `references/reports.md` § Story review: stack top SHA, rounds, findings with target PR, `clean`. Recorded with `turnstile pass story <S> ENV_TESTING --report reports/STORY-<S>-review.md --head <sha> --rounds <r>`.
```

`agents/stack-step.md`:

```markdown
---
name: stack-step
description: Ripples a fix up a PR stack by merge commits only (never rebase or force-push), re-runs the gates above the change, reports the new heads. Launched by turnstile dispatch after a fix lands low in a stack.
model: opus
tools: Read, Bash, Grep, Glob, Skill
---

You keep a stack of PRs consistent after one of them changed, without rewriting history.

## Role

- Input: the stack order from the brief (bottom → top), the PR whose head changed, the gate to re-run.
- For each PR above the change, in order: `git fetch`, check out its branch, `git merge --no-ff --no-edit origin/<branch-below>`, resolve conflicts only when the brief tells you how (else stop and report `BLOCKED` with the conflicting files), push normally.
- After every push: CI, then the repo gate (`pdf-review` run or the gate the brief names), then Copilot where the repo has it (request via REST, loop until clean).
- Signed merge commits; the default merge message is fine (no trailer).

## Procedure

1. Record the starting heads of every PR in the stack (`gh pr view <n> --json headRefOid`).
2. Ripple as above; keep a table PR → old head → new head → CI → gate → Copilot.
3. Verify signatures on every new commit.

## Cannot

Rebase, force-push, `gh pr ready`, Slack, Jira, replies to humans, subagents, code changes beyond the conflict resolution the brief authorised, `turnstile approve`.

## Report

`reports/STACK-<date>.md` per `references/reports.md` § Stack: the table above and the `turnstile pass` lines the orchestrator must run (`AI_REVIEW --head <new> --ci success`, then `READY` once the gate evidence exists).
```

`agents/comments-handler.md`:

```markdown
---
name: comments-handler
description: Handles review threads on one PR — verifies each human and Copilot comment against the code, fixes or justifies, loops Copilot to clean, drafts replies for human threads for the lead to post. Resolves Copilot threads only; never touches human threads, never posts.
model: opus
tools: Read, Edit, Write, Bash, Grep, Glob
---

You turn review comments into verified fixes and honest replies. Agreement is not a verdict; the code is.

## Role

- Every thread gets a verdict: `VALID` → fix + test + signed commit + push; `NOT VALID` → a concrete code-level reason in the report. High-priority Copilot findings are never declined without such a reason.
- Copilot threads: after the fix or justification, resolve the thread silently, re-request Copilot via REST, repeat until a pass on the current head has no findings.
- Human threads: do not reply, do not resolve. Draft the reply text per `references/slack.md` § Reply drafts (one per thread, with the commit that addresses it) in the report; the lead posts the GitHub replies themself — the REWORK gate checks for the lead's login on every thread that was open when the rework started.

## Procedure

1. `gh api graphql` the PR's review threads (id, resolved, author, path, line, body, createdAt); separate human and Copilot.
2. For each: locate the code, decide, act, record.
3. After pushes: CI green, repo gate re-run per brief; verify signatures.

## Cannot

Replying to or resolving human threads, Slack, Jira, `gh pr ready`, merges, rebase, force-push, subagents, `turnstile approve`.

## Report

`reports/COMMENTS-<pr-number>.md` per `references/reports.md` § Comments: thread table (id, author, verdict, commit, resolved?), Copilot loop rounds, draft replies, new head, gate state.
```

`agents/investigator.md`:

```markdown
---
name: investigator
description: Read-only investigation of a question in one or more repositories or environments — facts with file:line evidence and a recommendation. Launched by turnstile dispatch when the orchestrator needs an answer, not a change. Never pushes, never comments.
model: opus
tools: Read, Grep, Glob, Bash
---

You answer a precise question with evidence and stop. You change nothing.

## Role

- Input: the question, the repos/worktrees, the hypotheses the orchestrator already has, what a good answer looks like (the brief lists all four).
- Output: facts first (each with `file:line` or a command and its output), then the answer, then a recommendation with its cost if wrong, then what you could not verify.
- Bash is for reading: `git log/show/grep/diff`, `gh pr view/api` reads, running existing tests. No commits, no pushes, no PR or issue comments, no workflow runs.

## Procedure

1. Restate the question in one line; list the hypotheses.
2. Gather evidence per hypothesis; stop when the answer is unambiguous or the brief's time box ends.
3. Write the report; reply with the answer in one line plus the report path.

## Cannot

Any push, commit, comment, workflow run, deploy, Slack, Jira, edits, subagents, `turnstile approve`.

## Report

`reports/INVESTIGATE-<slug>.md` per `references/reports.md` § Investigation.
```

`agents/tester.md`:

```markdown
---
name: tester
description: Runs a story's test cases on the deployed environment and checks every screen against its Figma frame pixel-level (screenshots side by side plus numeric DOM checks) in an isolated headless browser. Writes ENV-<story>.md and the evidence folder; fails become bugs through the orchestrator. Never changes code.
model: opus
tools: Read, Write, Bash, Grep, Glob, mcp__claude_ai_Figma__get_screenshot, mcp__claude_ai_Figma__get_design_context, mcp__claude_ai_Figma__get_variable_defs, mcp__claude_ai_Figma__get_metadata
---

You are the gate between "it works on my branch" and a human reviewer's time. You test what the plan says, on the environment the plan names, against the design the plan links, and you write down what you saw.

## Role

- Input (from the brief): story id, its test cases (id, preconditions, steps, expected), Figma frames per screen/state (`file:node`), the environment slot (variant, desk, build numbers), the environment recipe (`references/env/<product>.md`), the credentials the lead supplied in the brief, the parity tolerance (default 1 px, exact colour), the mode (`full` or `rerun` with the case list).
- Browser: an isolated headless Playwright (or the product's headless runner) with its own profile and user-data dir under the scratchpad — never the user's Chrome, never a shared chrome-devtools MCP session. Route to the environment exactly as the recipe says (cookies on the recipe's domain, never as request headers) and prove the routing on the first request (`x-server-name`, static host) before any case.
- Design parity per screen/state: `evidence/<story>/<case>/env.png` next to `figma.png` (from `get_screenshot`), `dom.json` with measured spacing/sizes/fonts/colours against the Figma variables (`get_variable_defs`, `get_design_context`), `diff.md` with every deviation beyond tolerance; copy compared verbatim against Figma / the locale source the brief names.
- Verdict per case: `pass` / `fail` / `not_testable_here` (with the reason). A fail names the screen, the Figma node, the expected and the observed, in the `turnstile bug add` form.

## Procedure

1. Read the recipe and the brief; prepare the browser profile; log in with the user the brief names (register `+testerN` variants if sessions collide, per the recipe).
2. Prove routing; record build numbers (`static.version`, backend `x-server-name`) in the report header.
3. Run every case in order; save evidence immediately after each; never retry a failed case silently — record the retry.
4. Figma parity for every screen/state listed in the brief, including states reached mid-case.
5. Mode `rerun`: only the cases listed; say in the report that it is partial. Mode `full`: every case (the orchestrator records it with `--full`).

## Cannot

Code changes, pushes, Slack, Jira, PR comments, using the user's visible browser, subagents, inventing a case that is not in the brief (propose it in the report instead), `turnstile approve`.

## Report

`reports/ENV-<story>.md` per `references/reports.md` § Env test: header (environment, builds, routing proof, mode), case table (case → verdict → evidence path), parity table (screen → node → max deviation → verdict), fails as `turnstile bug add` lines, `not_testable_here` reasons, totals. Recorded with `turnstile pass story <S> ENV_TESTING --report reports/ENV-<S>.md --cases-pass <n> --cases-fail <n> --figma-parity pass|fail [--full]`.
```

`agents/deployer.md`:

```markdown
---
name: deployer
description: Deploys branches, PR builds and monolith images to a Prometey variant or an editor desk through the prometey-variant skill and the repos' delivery workflows, always with explicit image tags, and health-checks the result. Launched by turnstile dispatch; never prod, never Slack.
model: sonnet
tools: Read, Bash, Grep, Glob, Skill
---

You put the right build on the right environment and prove it is there.

## Role

- Follow the `prometey-variant` skill for variants (ensure, front deploys, monolith image build + ensure with tag) and the repo's documented desk workflow for editor desks (the brief names the label or workflow).
- Every `ensure` carries the monolith tag the variant must keep (`service_github_tag=<tag>`); the hook blocks an empty one. After every run confirm an XHR shows `x-server-name: …-<variant>-…` and the static host is the variant's.
- Record run ids, build numbers (`static.version` per app) and image tags as you learn them; the stack-top SHA you deployed is what the orchestrator passes as `--head`.

## Procedure

1. Read the brief (repos, branches/PRs, variant/desk, tag to keep, health checks).
2. Trigger the workflows; poll `gh run view` every ≤ 2 min; on failure collect the failing step's log tail.
3. Health check per the brief (an endpoint, a bundle url, a page). Never report "deployed" without it.

## Cannot

Production or RC environments, `ensure` without a tag, Slack, Jira, code changes, subagents, deleting variants, `turnstile approve`.

## Report

`reports/DEPLOY-<slug>-<date>.md` per `references/reports.md` § Deploy: table repo → ref → run → build/tag → health check. Recorded with `turnstile pass story <S> INTEGRATION_REVIEW --build <build> --head <stack-top sha>`.
```

- [ ] **Step 5: Run the tests and the manifest check**

Run: `python3 -m unittest tests.test_agents -v && claude plugin validate . 2>&1 | tail -3` — Expected: PASS; no error about `agents/`.

- [ ] **Step 6: Commit**

```bash
git add agents tests/test_agents.py
git commit -m "feat(agents): eight role agents with model, effort, tool allowlists and role rules"
```

---

### Task 10: Brief templates and `turnstile brief` (the `dispatch` helper)

**Files:**
- Create: `skills/turnstile/references/briefs/{implementer,reviewer,story-reviewer,stack-step,comments-handler,investigator,tester,deployer}.md`, `turnstile_cli/brief_cmd.py`, `tests/test_brief.py`
- Modify: `turnstile_cli/main.py` (wire), `hooks/guard_bash.py` (`TURNSTILE_SUBS` += `"brief"`), `tests/test_hooks.py`

**Interfaces:**
- `brief_cmd.PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")`; `brief_cmd.render(template, vars) -> Tuple[str, List[str]]` (text, sorted unfilled names).
- `brief_cmd.builtins(data, delivery, agent, name) -> dict`: `epic_key, github_org, delivery` (absolute), `variant, desk, env_recipe` (from `epic.environment`, `""` when null), `agent, brief_name, brief_path` (`briefs/<name>.md`), `report_path` (`reports/<name>.md`), `today` (UTC `YYYY-MM-DD`).
- `brief_cmd.run(delivery, agent, name, var_list, force=False, io=None, no_commit=False) -> int` — agent must exist in `agents/`, template in `references/briefs/`; `--var k=v` overrides builtins; unfilled placeholders → `MISSING placeholder <name> (pass --var <name>=...)` per name, exit 2, nothing written; existing brief → `MISSING briefs/<name>.md exists (use --force)`; success writes the brief under `state.locked`, then `_side_effects` with the line `brief <name> for <agent>`; prints `AGENT: turnstile:<agent>`, `BRIEF: <abs>`, `REPORT: <abs>`, `PROMPT: Read and execute <abs brief>. Write your report to <abs report>. Reply with at most 8 lines.`, `OK brief <name> for <agent>`.
- CLI: `turnstile brief <agent> <name> [--var k=v]... [--force] [--no-commit]`.
- Every template contains `{{report_path}}` and `{{epic_key}}`; the agent-specific placeholders are the ones listed in each template and are what SKILL.md's `dispatch` tells the orchestrator to pass.

- [ ] **Step 1: Failing tests**

```python
# tests/test_brief.py
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
```

`tests/test_hooks.py`: add `"turnstile brief tester ENV-S1 --var story_id=S1"` to the allowed list.

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_brief -v` — Expected: FAIL, `No module named 'turnstile_cli.brief_cmd'`.

- [ ] **Step 3: Write the eight templates**

Every template starts with this head:

```markdown
# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.
```

and ends with this tail:

```markdown
## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Poll ≤ 2 min, never silent > 5 min. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
```

Middles:

`briefs/implementer.md`

```markdown
## Ticket
{{ticket_key}} — {{ticket_title}}
Repo `{{repo}}` (org `{{github_org}}`), worktree `{{worktree}}`, base branch `{{base_branch}}`, branch `{{branch}}`.
Read the repo's `CLAUDE.md` and {{repo_guides}} first.

## Scope (implement exactly this)
{{scope}}

## Anchors (verify before editing)
{{anchors}}

## Tests required
{{tests}}

## Verify commands (paste the summary lines)
{{verify_commands}}

## Commit and PR
Commit `{{commit_message}}` (signed, no trailer). Draft PR into `{{base_branch}}`, title `{{pr_title}}`, body per
`references/pr-body.md` with `Related: {{jira_url}}`. Copilot loop: {{copilot}} (`true` → REST request + loop until clean).
```

`briefs/reviewer.md`

```markdown
## PR
{{pr_id}} — {{ticket_key}} {{ticket_title}} · head `{{head}}` · base `{{base_branch}}` · worktree `{{worktree}}` · repo gate `{{gate}}` via `{{gate_skill}}`.

## Ticket scope to check against
{{scope}}

## Invariants
{{invariants}}

## Design
{{figma_frames}}

## Earlier rounds
{{previous_reports}}

Report → `{{report_path}}` § Review; include the gate run URL and `clean: true|false`.
```

`briefs/story-reviewer.md`

```markdown
## Story
{{story_id}} — {{story_title}} · epic branch `{{epic_branch}}` · story branch `{{story_branch}}` · stack top {{stack_top_pr}} @ `{{head}}` · worktree `{{worktree}}`.
Tickets: {{tickets}}. PRs in merge order: {{prs}}.

## What the story must deliver (plan.md § story)
{{scope}}

## Test cases mapped to the story
{{test_cases}}

## Figma frames
{{figma_frames}}

## Invariants
{{invariants}}

## Earlier reviews of the ticket PRs (do not repeat; verify)
{{previous_reports}}

Report → `{{report_path}}` § Story review, findings tagged with the ticket PR they belong to.
```

`briefs/stack-step.md`

```markdown
## Stack (bottom → top)
{{stack}}

Changed PR: {{changed_pr}} (new head `{{head}}`). Repo `{{repo}}`, worktree `{{worktree}}`, gate `{{gate}}` via `{{gate_skill}}`, Copilot: {{copilot}}.

## Conflict policy
{{conflict_policy}}

Report → `{{report_path}}` § Stack with the table PR → old head → new head → CI → gate → Copilot and the `turnstile pass` lines.
```

`briefs/comments-handler.md`

```markdown
## PR
{{pr_id}} — {{ticket_key}} · head `{{head}}` · worktree `{{worktree}}` · gate `{{gate}}` via `{{gate_skill}}` · Copilot: {{copilot}}.
Rework started at {{rework_since}} (threads open at that time need the lead's reply before the PR goes back to humans).

## Threads to handle
{{threads}}

## Context the reviewers may lack
{{context}}

Human threads: verdict + fix + draft reply only (per `references/slack.md` § Reply drafts). Copilot threads: fix or justify, resolve, re-request, loop.
Report → `{{report_path}}` § Comments.
```

`briefs/investigator.md`

```markdown
## Question
{{question}}

## Where to look
{{where}}

## Hypotheses already on the table
{{hypotheses}}

## What a good answer looks like
{{answer_shape}}

Time box: {{time_box}}. Read-only. Report → `{{report_path}}` § Investigation.
```

`briefs/tester.md`

```markdown
## Story and environment
{{story_id}} — {{story_title}}. Mode: {{mode}} (`full` or `rerun`; rerun cases: {{rerun_cases}}).
Environment: variant `{{variant}}`, desk `{{desk}}`, builds {{builds}}. Recipe: `{{env_recipe}}`. Credentials: {{credentials}} (from the lead; never written anywhere else).

## Test cases
{{test_cases}}

## Screens and states → Figma frames
{{figma_frames}}
Parity tolerance: {{tolerance}}. Copy source: {{copy_source}}.

## Evidence
`evidence/{{story_id}}/<case>/` per `references/evidence.md`.

Report → `{{report_path}}` § Env test; list every fail in the `turnstile bug add --story {{story_id}} …` form.
```

`briefs/deployer.md`

```markdown
## Targets
{{targets}}

Variant `{{variant}}` must keep monolith tag `{{monolith_tag}}` on every `ensure`. Desk `{{desk}}` via {{desk_workflow}}. Stack top to deploy: `{{head}}`.

## Health checks
{{health_checks}}

Report → `{{report_path}}` § Deploy with run ids, build numbers and tags.
```

- [ ] **Step 4: Implement `brief_cmd.py`**

```python
# turnstile_cli/brief_cmd.py
import datetime, pathlib, re
from typing import List, Tuple
from . import state as st_mod
from .errors import TurnstileError

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"
BRIEFS = ROOT / "skills" / "turnstile" / "references" / "briefs"
PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

def render(template: str, vars: dict) -> Tuple[str, List[str]]:
    missing = set()
    def sub(m):
        k = m.group(1)
        if k in vars and vars[k] is not None:
            return str(vars[k])
        missing.add(k); return m.group(0)
    return PLACEHOLDER.sub(sub, template), sorted(missing)

def builtins(data: dict, delivery: pathlib.Path, agent: str, name: str) -> dict:
    epic = data.get("epic") or {}; env = epic.get("environment") or {}
    return {"epic_key": epic.get("key") or "", "github_org": epic.get("github_org") or "", "delivery": str(pathlib.Path(delivery).resolve()),
            "variant": env.get("variant") or "", "desk": env.get("desk") or "", "env_recipe": env.get("recipe") or "", "agent": agent,
            "brief_name": name, "brief_path": "briefs/%s.md" % name, "report_path": "reports/%s.md" % name,
            "today": datetime.datetime.utcnow().strftime("%Y-%m-%d")}

def parse_vars(var_list: List[str]) -> dict:
    out = {}
    for item in var_list or []:
        if "=" not in item:
            raise TurnstileError("--var needs key=value (got %r)" % item)
        k, v = item.split("=", 1)
        if not PLACEHOLDER.match("{{%s}}" % k):
            raise TurnstileError("bad placeholder name %r" % k)
        out[k] = v
    return out

def run(delivery, agent: str, name: str, var_list: List[str], force: bool = False, io=None, no_commit: bool = False) -> int:
    from .pass_cmd import IO, _side_effects
    io = io or IO(); delivery = pathlib.Path(delivery)
    try:
        if not (AGENTS / (agent + ".md")).exists():
            raise TurnstileError("unknown agent %s (no agents/%s.md)" % (agent, agent))
        tpl = BRIEFS / (agent + ".md")
        if not tpl.exists():
            raise TurnstileError("no brief template for %s (%s)" % (agent, tpl))
        if not NAME_RX.match(name):
            raise TurnstileError("brief name must be a file stem like FIX-13223-token (got %r)" % name)
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            vars = builtins(st.data, delivery, agent, name); vars.update(parse_vars(var_list))
            text, missing = render(tpl.read_text(), vars)
            if missing:
                for m in missing:
                    print("MISSING placeholder %s (pass --var %s=...)" % (m, m))
                return 2
            out = delivery / "briefs" / (name + ".md")
            if out.exists() and not force:
                raise TurnstileError("briefs/%s.md exists (use --force to overwrite)" % name)
            out.parent.mkdir(parents=True, exist_ok=True); out.write_text(text)
            _side_effects(delivery, st, ["brief %s for %s" % (name, agent)], io, no_commit)
        report = delivery / "reports" / (name + ".md")
        print("AGENT: turnstile:%s" % agent); print("BRIEF: %s" % out.resolve()); print("REPORT: %s" % report.resolve())
        print("PROMPT: Read and execute %s. Write your report to %s. Reply with at most 8 lines." % (out.resolve(), report.resolve()))
        print("OK brief %s for %s" % (name, agent))
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
```

`main.py`: `br = sub.add_parser("brief", help="render an agent brief from its template (the dispatch helper)"); br.add_argument("agent"); br.add_argument("name"); br.add_argument("--var", action="append", default=[], dest="vars"); br.add_argument("--force", action="store_true"); br.add_argument("--no-commit", action="store_true")` and in `main()`:

```python
        if a.cmd == "brief":
            from .brief_cmd import run as brief_run
            return brief_run(delivery, a.agent, a.name, a.vars, force=a.force, no_commit=a.no_commit)
```

`hooks/guard_bash.py`: add `"brief"` to `TURNSTILE_SUBS`.

- [ ] **Step 5: Run, commit**

Run: `python3 -m unittest tests.test_brief tests.test_hooks 2>&1 | tail -1` — Expected: `OK`.

```bash
git add skills/turnstile/references/briefs turnstile_cli/brief_cmd.py turnstile_cli/main.py hooks/guard_bash.py tests/test_brief.py tests/test_hooks.py
git commit -m "feat(brief): brief templates per agent and the turnstile brief renderer for dispatch"
```

---

### Task 11: The skill — `SKILL.md` and references (lifecycle, kickoff, PR body, Slack, reports, evidence, env recipe)

**Files:**
- Create: `skills/turnstile/SKILL.md`, `skills/turnstile/references/lifecycle.md`, `skills/turnstile/references/kickoff.md`, `skills/turnstile/references/pr-body.md`, `skills/turnstile/references/slack.md`, `skills/turnstile/references/reports.md`, `skills/turnstile/references/evidence.md`, `skills/turnstile/references/env/pdffiller-dev.md`, `tests/test_skill_files.py`

**Interfaces:**
- Consumes: every CLI command of this plan and of the core (`init`, `plan-submitted`, `status`, `pass`, `approve` (lead only), `jira-synced`, `brief`, `bug add|set`, `render-board`, `reconcile`), agent names (Task 9), brief placeholders (Task 10).
- Produces: the orchestrator's procedures `init`, `status`, `pass`, `dispatch`, `story-gate`, `plan`; the reference texts the agents and briefs cite by path.

- [ ] **Step 1: Failing test**

```python
# tests/test_skill_files.py
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
    def test_every_reference_link_exists(self):
        for md in [SKILL / "SKILL.md"] + list(REFS.glob("*.md")) + list((REFS / "env").glob("*.md")) + list((REFS / "briefs").glob("*.md")):
            for rel in re.findall(r"`(references/[A-Za-z0-9_./-]+\.md)`", md.read_text()):
                self.assertTrue((SKILL / rel).exists(), "%s links missing %s" % (md.name, rel))
    def test_reference_files_present(self):
        for name in ["lifecycle.md", "kickoff.md", "plan.md", "pr-body.md", "slack.md", "reports.md", "evidence.md", "env/pdffiller-dev.md"]:
            self.assertTrue((REFS / name).exists(), name)
    def test_lifecycle_tables_cover_every_state(self):
        text = (REFS / "lifecycle.md").read_text()
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
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_skill_files -v` — Expected: FAIL, `FileNotFoundError` on `SKILL.md`.

- [ ] **Step 3: Write `skills/turnstile/SKILL.md`**

````markdown
---
name: turnstile
description: Run or resume the delivery of a multi-repo epic through turnstile's evidence-gated flow — PR states DEV→AI_REVIEW→READY→ON_HUMAN_REVIEW→APPROVED→MERGED, story gates (integration review, environment testing), role agents, the lead's approvals. Use at the start of every orchestrator session and whenever a PR, story, review, deploy or bug changes state; also on "status", "send for review", "start story", "re-plan", "init epic".
---

# Turnstile

The state is `delivery/state.json` in the knowledge worktree (found through `.turnstile` in the workspace). Only
`turnstile` commands write it. You sequence; the CLI enforces. Every state change is one command whose side effects
(ledger, board, commit, Jira instruction) happen inside it — never "later". Read once per session:
`references/lifecycle.md` (DoR/DoD per state with the exact `turnstile pass` call). Templates: `references/pr-body.md`,
`references/slack.md`, `references/reports.md`, `references/evidence.md`; env recipes in `references/env/`.

## Rules that never bend

- The lead's word is an `awaiting_human` entry approved **by the lead typing** `! TURNSTILE_LEAD=1 turnstile approve <ah-id>`
  in the Claude Code prompt (the `!` runs outside the model). You report the pending ids (`turnstile status`) and ask
  for that line; you never run it, no agent runs it, and the Bash guard refuses any spelling of it.
- Send, reply, merge, story start, story completion, plan approval: all go through such an entry. A Slack send also
  gets a UI confirmation from the lead (the Slack guard answers `ask`), and must go through the real send tool so the
  PostToolUse hook records `used_at` — drafts and scheduled sends never count.
- A question from the lead is a question: answer and propose, act on a command.
- Delegate all implementation, review, testing and deployment to the `turnstile:*` agents (`## dispatch`). Never read
  a diff or run a suite yourself; your context is for coordination.
- After every agent report, record its facts (`pass`, `bug`, `jira-synced`) before you reply to the lead.

## status

`turnstile status` → reconcile against GitHub + plan state + next actions + what awaits the lead (exit 1 when `gh`
facts are missing). Run it first in every session and after every batch of agent reports. Run the proposed
`turnstile pass` lines it prints (they are dry-run checked); show the lead the anomalies. `turnstile reconcile --json`
for the raw list.

## pass (one transition)

`turnstile pass pr <repo#n> <STATE> --head <sha> [evidence flags]` / `turnstile pass story <S> <STATE> [flags]`; flags per
`references/lifecycle.md`. Every PR pass verifies the head and the evidence against GitHub; `--offline` only records.
On `OK` it prints `JIRA: <ticket> → <status>` (perform it through the Atlassian MCP `transitionJiraIssue`, then
`turnstile jira-synced <repo#n> "<status>"`) and `BOARD: publish <path> → <url>` (publish the file with the Artifact tool
and that `url`; a first publish loads the `artifact-capabilities` skill, declares `db` + `user`, and the url is recorded
at `init --board-url` or by the migration). On `MISSING …` nothing was written: get the evidence, do not argue with the gate.
READY with a paired PR outside the epic (locales): `--companions locales#5` so one Slack message may mention both.

## init (once per epic)

1. `turnstile init --epic <KEY> --workitem <slug> --knowledge <pdffiller-knowledge clone> --lead <login> --lead-github
   <GitHub login> --github-org <org> --repo '<json>'… --variant <v> --desk <d>` — creates the knowledge worktree on
   `epic/<key>`, `delivery/`, `.turnstile`, the workspace `CLAUDE.md`. Repo JSON keys: `name, base, epic_branch, slack,
   gate, gate_check (null for a skill gate), ci_ignore, copilot, branch_prefix`.
2. Kick-off analysis per `references/kickoff.md`: read decomposition, PRD, design, test plan, every repo's `CLAUDE.md`;
   write `delivery/plan.md` from its template (stories with a story branch each, merge order, human-review units ≈ 400
   logic lines, test-case map, Figma frames, human inputs, env slots) including the `turnstile-stories` JSON block.
3. `turnstile plan-submitted` → stories enter `PLANNED`, a `plan` entry opens; show the lead the plan summary and the
   approve line; wait. Without the approval no story leaves `PLANNED` (no `--reason` override).
4. After the lead approved the plan and the first `start_story` entry: `turnstile pass story S1 IN_PROGRESS --approved <ah-id>`,
   then dispatch implementers per the merge order.

## dispatch <agent> <brief>

1. `turnstile brief <agent> <NAME> --var k=v …` renders `references/briefs/<agent>.md`; it refuses unfilled
   placeholders, so pass every agent-specific variable listed in the template. Names: `<KEY>` for tickets,
   `REVIEW-<n>`, `STORY-<S>-review`, `ENV-<S>`, `FIX-<n>-<slug>`, `STACK-<date>`, `COMMENTS-<n>`,
   `INVESTIGATE-<slug>`, `DEPLOY-<slug>-<date>`.
2. Launch with the Agent tool: `subagent_type: "turnstile:<agent>"`, prompt = the `PROMPT:` line the command printed.
   Agents: implementer (sonnet), reviewer (opus xhigh), story-reviewer (fable), stack-step, comments-handler,
   investigator, tester, deployer (opus unless said). One agent per task; parallel agents only across different
   repos or stories.
3. On return read the ≤ 8-line reply (the report is in `reports/`), record the facts with `turnstile pass` / `bug`,
   then reply to the lead. Never paste agent output into the chat.

## story-gate <S>

Pre-condition: every PR of `S` is ≥ `READY`, each based on the story branch or on the PR below it, and the stack top
is deployed to the story's slot (dispatch `deployer`).
1. `turnstile pass story S INTEGRATION_REVIEW --build <build> --head <stack-top sha>`.
2. dispatch `story-reviewer` (`STORY-S-review`); findings → `implementer` briefs on the ticket PRs → `stack-step` →
   their gates re-run (`pass pr … AI_REVIEW --head <new> --ci success`, `reviewer`, `pass pr … READY …`); loop until
   the report says `clean: true`.
3. `turnstile pass story S ENV_TESTING --report reports/STORY-S-review.md --head <stack top> --rounds <r>` (opens the
   lead's `story_done` entry).
4. dispatch `tester` (`ENV-S`, mode `full`). For every fail first `turnstile bug add --story S --title … --source
   "tester <date>" --figma <node>`, then record the run: `turnstile pass story S ENV_TESTING --report reports/ENV-S.md
   --cases-pass <n> --cases-fail <n> --figma-parity pass|fail --full` (a run with fails needs that many new bugs).
   Fixes via `implementer`; `turnstile bug set bNN --state testing` after the deploy; `tester` in mode `rerun` for the
   failed cases (recorded without `--full`); `bug set bNN --state done`; then one full run.
5. `turnstile pass story S DONE --approved <story_done ah-id>` — needs the last run `--full` with 0 fails, parity pass,
   every bug of the story `done`, every PR ≥ READY.
6. Report to the lead per `references/slack.md` § Story report and **stop**: the next story and the sends of this
   story's units wait for the lead's words (`start_story` / `send` entries; then `pass pr … ON_HUMAN_REVIEW --head …
   --slack <permalink> --reviewers a,b --approved <ah-id>` after the message went out).

## plan (re-plan after a scope change)

Edit `delivery/plan.md` (stories, branches, units, map) with the rationale in `decisions.md`; `turnstile plan-submitted`
(voids the old plan entry, opens a new one); the lead approves again. Stories past `PLANNED` keep their state and
evidence; a started story cannot be dropped.

## REWORK (a human thread, changes requested, or a push after the send)

`turnstile status` proposes `pass pr … REWORK --reason …` (opens a `reply` entry). dispatch `comments-handler`; the lead
posts the GitHub replies themself (the gate requires the lead's login on every thread open at `rework_since`); gate and
Copilot re-run on the new head (no new deep review); the lead approves the `reply` entry; the Slack reply goes out through
the guarded tool; then `pass pr … ON_HUMAN_REVIEW --head <new> --ci success --gate … --slack <reply permalink> --approved <ah-id>`.

## Bugs on the board

Viewers with write access change a bug's status in the board's dropdown; it lands in the artifact db (`bugs/<id>`),
not in `state.json`. At `status` time read the `bugs` collection with `ArtifactData` and fold changes back with
`turnstile bug set <id> --state <s>` so git stays the source of truth.
````

- [ ] **Step 4: Write `references/lifecycle.md`**

```markdown
# Lifecycle — DoR / DoD and the command per transition

Evidence carries the head it was produced for; a push voids it (`turnstile status` shows the drop). Every PR pass checks
the head and the evidence against GitHub (`IO.github_facts`): CI rollup, the gate's `gate_check` context, Copilot threads,
approvals for the head, signed commits, no trailer in commit messages, no generated-with footer in the body, the PR base.

## PR states

| State | DoR (entry) | DoD (exit) | Command that enters it |
|---|---|---|---|
| **DEV** | ticket in the approved `plan.md`; brief exists; branch from the story branch (or the PR below in the stack) | draft PR into that base; CI green (contexts minus `ci_ignore`); every commit signed, no trailer; body per `references/pr-body.md` | `turnstile pass pr <id> DEV --reason "<why back>"` (from AI_REVIEW/REWORK; drops `rework_since`) |
| **AI_REVIEW** | DEV done | **loop until clean on one head**: `deep_review.clean` + `gate.result = pass` (and `gate_check` green on GitHub) + `copilot.open_threads = 0` where `repo.copilot`; all for `head == pr.head` | `turnstile pass pr <id> AI_REVIEW --head <sha> --ci success` (re-enters itself after a push; voids an open `send`) |
| **READY** | AI_REVIEW done, head verified online | head unchanged; `blocked_by` null or MERGED for sending; story DONE (or `human_review: per_pr`) | `turnstile pass pr <id> READY --head <sha> --deep-review reports/REVIEW-<n>.md --rounds <r> --gate <gate>:pass:<run-url> [--copilot 0] [--companions locales#5]` → opens `send` |
| **ON_HUMAN_REVIEW** | lead approved the `send` (bound to the head); message went out through the guarded tool (`used_at`) | ≥ 1 approval for the head; 0 unresolved human threads; no changes requested | `turnstile pass pr <id> ON_HUMAN_REVIEW --head <sha> --slack <permalink> --reviewers a,b --approved <ah-id>` → Jira On Review |
| **REWORK** | push after send, new human thread, or changes requested | fixes pushed; gate + Copilot green on the new head (deep review is **not** repeated: `rework_since` is set); the lead replied on every human thread open at `rework_since.at`; the lead approved the `reply` entry and the reply went out | `turnstile pass pr <id> REWORK --head <sha> --reason "<thread id or push>"` (opens `reply`); back with `ON_HUMAN_REVIEW --head <new> --ci success --gate … --slack <reply permalink> --approved <ah-id>` |
| **APPROVED** | ON_HUMAN_REVIEW done | lead merged | `turnstile pass pr <id> APPROVED --approvals a,b --open-threads 0` → opens `merge` |
| **MERGED** | squash-merged by the lead | — | `turnstile pass pr <id> MERGED --merged-sha <sha>` → Jira On Hold; unblocks dependants; notes the story |

AI review order on one head: deep review (`reviewer` agent) → repo gate (`pdf-review`, `pr-review`, `review`, `run-lint` +
`run-unit-tests`; a skill gate has `gate_check: null` and the report is the evidence) → Copilot where connected. Any finding
→ fix → re-run deep review **and** gate.

## Story states

| State | DoD | Command |
|---|---|---|
| **PLANNED** | listed in the approved `plan.md` (`plan` entry approved, digest unchanged) | `turnstile plan-submitted` + the lead's approve line |
| **IN_PROGRESS** | every ticket PR ≥ READY, each based on `stories.<S>.branch` or on another PR of the story (a stack) or MERGED; stack top deployed to the slot | `turnstile pass story <S> IN_PROGRESS --approved <start_story ah-id>` (also needs the plan approved and `after` stories DONE, or a `--reason` naming the lead for the dependency only) |
| **INTEGRATION_REVIEW** | whole-story diff reviewed by `story-reviewer` until clean; fixes in the ticket PRs with gates re-run | `turnstile pass story <S> INTEGRATION_REVIEW --build <build> --head <stack-top sha>` |
| **ENV_TESTING** | `tester` ran every case + Figma parity; every fail became a bug; fixed; re-run; one full final run | enter: `turnstile pass story <S> ENV_TESTING --report reports/STORY-<S>-review.md --head <sha> --rounds <r>`; record a run (re-entry): `turnstile pass story <S> ENV_TESTING --report reports/ENV-<S>.md --cases-pass <n> --cases-fail <n> --figma-parity pass|fail [--full]` |
| **DONE** | last run `--full` with 0 fails and parity pass; every bug of the story `done`; PRs ≥ READY; the lead's `story_done` word | `turnstile pass story <S> DONE --approved <ah-id>` |

Stop rule: after DONE nothing starts until the lead says so; parallel stories (`parallel_with` or the lead's word) each
have their own branch, stack, slot and tester run. Human review receives a story's units only after DONE (or with
`human_review: per_pr` set by the lead in `plan.md` for a legacy story).

## Jira mapping (printed by `pass`, performed through the Atlassian MCP, recorded with `jira-synced`)

DEV / AI_REVIEW / READY → In progress · ON_HUMAN_REVIEW / REWORK / APPROVED → On Review · MERGED → On Hold.
```

- [ ] **Step 5: Write `references/kickoff.md`**

```markdown
# Kick-off analysis (once, before any code)

Output: `delivery/plan.md` from `references/plan.md`. Approval gate: `turnstile plan-submitted` → the lead's approve line.

1. Read, in this order, and list each in plan.md § 1: the decomposition (ticket map, decisions), the PRD, the design
   brief + Figma file (collect `file:node` per screen and state), the test plan (case ids, preconditions), every target
   repo's `CLAUDE.md` / `AGENTS.md` / testing guide, the precedent epic if the decomposition names one.
2. Stories: business slices testable and releasable on their own. If the decomposition is by repo or by wave, define
   the slices yourself and write the rationale. For each: tickets, repos, **story branch** (`stories.<S>.branch`, the
   branch the ticket PRs stack into; the epic branch for a single-story epic or a legacy story), `after` (must be DONE
   first), `parallel_with` (explicitly allowed), env slot (variant / desk), Figma frames, test cases.
3. Merge order per story and the stack; file overlaps between parallel stories and which merge order resolves them.
4. Human-review units: ~400 lines of logic each (tests and markup excluded). A story goes to humans as its story PR or
   2–3 PRs split by subsystem (state + API / UI / tests). Estimate from the ticket scopes; refine after the PRs exist.
5. Inputs from humans (PM report, design copy, credentials) with the date each is needed and which story it blocks.
6. Fill the `turnstile-stories` JSON block (§ 7 of the template) — ids `S1…`, keys `title, tickets, repos, branch,
   after, parallel_with, test_cases, figma, env_slot, human_review_units`, optional `human_review: "per_pr"` (lead-set).
   `plan-submitted` validates it.
7. Show the lead: the story table, the unit table, the open inputs, the approve line. Wait. Record the answer in `decisions.md`.

Re-plan (`## plan` in SKILL.md): same steps on the delta; never drop a started story.
```

- [ ] **Step 6: Write `references/pr-body.md`, `references/slack.md`, `references/reports.md`, `references/evidence.md`**

`references/pr-body.md`:

```markdown
# PR body template

Title: `<type>(<scope>): [<KEY>] <summary>` (conventional type, Jira key). Draft, base = the story branch or the PR below.

```
<one-line intro: what the PR adds and for whom>

Scope:
- `<identifier>` — <what changed>

Tech requirements:
- <tests added / commands green>

Related: <Jira url>
```

Rules: no generated-with footer (the pass reads the body on GitHub and refuses it); no checklist boilerplate; the body
ends with the `Related:` line. Update `Scope:` when a later fix changes behaviour. Never comment on the PR.
```

`references/slack.md`:

```markdown
# Slack messages

Channels come from `state.json` (`epic.repos.<repo>.slack`); the guard refuses any other channel. Reviewer logins come
from the PR (`gh pr view <n> --repo <org>/<repo> --json reviewRequests --jq '.reviewRequests[].login'`, people only — skip
team entries); resolve a login to a Slack user through the Slack MCP user search by name/email; never guess. Every message
is composed, shown to the lead, and sent only through the real send tool after the lead approved the entry
(`! TURNSTILE_LEAD=1 turnstile approve <ah-id>`) and confirmed the send in the UI. One approval = one message.

## Review request (front repos)

```
Reviewers: <@USER_ID_1> <@USER_ID_2>
PR: <https://github.com/<org>/<repo>/pull/<n>>
Task description: <PR title with the conventional prefix stripped>
Estimate review: +<additions>-<deletions>
```

- Wrap every URL in angle brackets (Slack's auto-linker otherwise swallows the newline).
- A front PR and its paired locales PR go in **one** message with a `Locales: <url>` line under `PR:`; the estimate sums
  both; the locales PR is a `--companions` entry of the main PR's `send`.
- One repo per message; several repos → consecutive messages, each with its own approved entry.
- Search the channel for the PR URL first; if a request exists, reply in that thread instead.

## Review request (backend / bare link channels)

```
<https://github.com/<org>/<repo>/pull/<n>>
```

## Reply drafts (human threads; written by comments-handler, posted on GitHub by the lead, announced in Slack with the `reply` entry)

```
<thread id> — <reviewer>: <one-line restatement of the point>
→ <what was done / why not>, commit `<sha>` (or: declined because <code-level reason>)
```

## Story report to the lead (after `pass story <S> DONE`)

```
Story <S> "<title>": integration review clean (<r> rounds, reports/STORY-<S>-review.md), env test <pass>/<total> cases
in the final full run, Figma parity pass (reports/ENV-<S>.md), bugs: <n> found, all done. Units ready to send:
<unit → PRs>. Pending your word: <ah-ids>.
```
```

`references/reports.md`:

```markdown
# Report templates (one file per agent run under `delivery/reports/`)

Every report starts with `# <TYPE> — <subject> — <date>` and a `Status:` line (`DONE` / `DONE_WITH_CONCERNS` /
`NEEDS_CONTEXT` / `BLOCKED`), then the sections below. Paste real command output summary lines, never paraphrase them.

## Ticket
`reports/<KEY>.md` — PR URL · branch · head · base · files changed · commands run → summary lines · Copilot threads
(id → verdict → commit) · signatures verified · deviations from the brief · open questions · backlog notes.

## Review
`reports/REVIEW-<n>.md` — PR · head · base · worktree · rounds (round → head → findings count) · findings table
(# · severity · file:line · claim · verification · fix · status) · gate run URL + verdict · fixes applied by the reviewer
(commits) · `clean: true|false`.

## Story review
`reports/STORY-<S>-review.md` — stack top SHA (= `evidence.deploy.head`) · PRs in order · rounds · findings table with a
`target PR` column · cross-ticket seams checked · test cases traced · `clean: true|false`.

## Stack
`reports/STACK-<date>.md` — table PR → old head → new head → CI → gate → Copilot · conflicts (files, how resolved) ·
`turnstile pass` lines to run.

## Comments
`reports/COMMENTS-<n>.md` — thread table (id · author · human/Copilot · opened at · verdict · commit · resolved?) · Copilot
loop rounds · draft replies (per `references/slack.md`) for the lead to post · new head · gate state.

## Investigation
`reports/INVESTIGATE-<slug>.md` — question · hypotheses · evidence per hypothesis (file:line / command → output) ·
answer · recommendation + cost if wrong · not verified.

## Env test
`reports/ENV-<S>.md` — environment (variant, desk, builds, routing proof: `x-server-name`, static host) · mode (`full` /
`rerun` + cases) · case table (case · verdict · evidence path · note) · parity table (screen/state · Figma node · max
deviation px / colour · verdict) · fails as `turnstile bug add --story <S> --title "…" --source "tester <date>" --figma
<node>` lines · `not_testable_here` reasons · totals (pass / fail / not_testable_here).

## Deploy
`reports/DEPLOY-<slug>-<date>.md` — table repo → ref → workflow run → build / image tag → health check result ·
variant tag kept · stack-top SHA deployed · traps hit.
```

`references/evidence.md`:

```markdown
# Evidence layout (tester)

```
delivery/evidence/<story>/<case>/
  env.png        # environment screenshot, viewport per the Figma frame, full state reached by the case
  figma.png      # Figma get_screenshot of the frame/node named in plan.md
  dom.json       # measured values: {selector: {x, y, w, h, font, size, lineHeight, color, bg, gap, padding}} + Figma expected
  diff.md        # deviations beyond tolerance (element · property · expected · observed · delta) and copy mismatches
```

One folder per case; a case with several states uses `<case>/<state>/`. Keep images under 1 MB. Paths in `ENV-<S>.md`
are relative to `delivery/`. Evidence is committed by the next `turnstile pass` of the story.
```

- [ ] **Step 7: Write `references/env/pdffiller-dev.md`**

```markdown
# Environment recipe — pdffiller dev (variants + editor desks)

Domain: `https://www.pdffillers.com`. All cookies are set on `.pdffillers.com`.

## Users
Pattern `<mailbox>+tester<N>@<company domain>` with the shared dev password the lead supplies in the brief (never in
git). Parallel sessions on one user log each other out: register `+tester1`, `+tester2`, … for each parallel agent.
Login answers "we can't recognize you" → set the user agent to `pdffiller-autotests` for the login request only, then
restore the default.

## Routing
- Editor build on a desk: cookie `jsfillerEnv=deskNN` (`path=/`). Desk builds reset every morning — redeliver first.
- Backend on a Prometey variant: cookies `Forward-Variant-pdffiller=<variant>` **and** `developer_access=md5(<UTC date
  'Y-m-d'>)` (expires daily; without it requests silently hit the default backend). Set both as cookies on
  `.pdffillers.com`; **never as a request header** from a browser (`Forward-Variant-pdffiller` as a header breaks CORS
  preflights).
- Proof before the first case: an XHR response carries `x-server-name: pdffiller-web-<variant>-…` and the app bundle
  is served from `static_<variant>.pdffillers.com`. A tab opened before the cookies existed keeps the default bundle;
  reload. Negative control when in doubt: a nonsense variant name must change the response.

## Browser
Use an isolated headless browser (Playwright) with its own profile / user-data dir under the scratchpad. Never the user's
visible Chrome, never a shared devtools MCP session. Viewport per the Figma frame; device scale factor 1 unless the
frame is retina.

## Builds
Front: `static.version` of each app on the variant (deployer records it). Monolith: variant image tag (`DEV_ECR_TAG`).
Record both in the `ENV-<S>.md` header.
```

- [ ] **Step 8: Run, commit**

Run: `python3 -m unittest tests.test_skill_files -v && python3 -m unittest discover -s tests 2>&1 | tail -1` — Expected: PASS; suite `OK`. If the line-count test fails, move prose to a reference; never drop a command section.

```bash
git add skills/turnstile/SKILL.md skills/turnstile/references tests/test_skill_files.py
git commit -m "feat(skill): turnstile SKILL.md with init/status/pass/dispatch/story-gate/plan and the references"
```

---

### Task 12: README, version 0.2.0, tag

**Files:**
- Modify: `README.md` (install line; usage grows with the new commands; agents + skill; the four new rules), `turnstile_cli/__init__.py` (`0.2.0`), `.claude-plugin/plugin.json` (`0.2.0`), `tests/test_cli_smoke.py` (`turnstile 0.2.0`)

- [ ] **Step 1: Smoke test first**

Replace both `"turnstile 0.1.0"` in `tests/test_cli_smoke.py` with `"turnstile 0.2.0"`. Run `python3 -m unittest tests.test_cli_smoke` — Expected: FAIL.

- [ ] **Step 2: Bump**

`turnstile_cli/__init__.py`: `__version__ = "0.2.0"`. `.claude-plugin/plugin.json`: `"version": "0.2.0"`.

- [ ] **Step 3: README**

Insert after the "Why it exists" paragraph:

````markdown
## Install

```
claude plugin marketplace add davepylypenko/turnstile
claude plugin install turnstile
```

(Without a marketplace entry: clone the repo and start Claude Code with `--plugin-dir <path>`.)
````

In "What you get" add the bullets:

```markdown
- `turnstile init` / `plan-submitted` / `brief` / `bug add|set` — the epic skeleton, the lead-approved plan, agent briefs
  and the bug list, all written through the same guarded path as `pass`.
- Skill `turnstile` (`skills/turnstile/SKILL.md`): `init`, `status`, `pass`, `dispatch <agent> <brief>`, `story-gate <S>`,
  `plan`; references for DoR/DoD, kick-off, briefs, PR body, Slack, reports, evidence and env recipes.
```

Prepend to the "Usage (core)" block (rename it "Usage"):

```
turnstile init --epic MYD-16538 --workitem pdfd-429-l2f-editor-funnel --knowledge ../pdffiller-knowledge \
  --lead davyd.pylypenko --lead-github <login> --github-org pdffiller \
  --repo '{"name":"jsfiller","base":"develop","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CCGLRULNR","gate":"pdf-review","ci_ignore":["pdf-review","gate / gate"]}' \
  --repo '{"name":"front-link2fill-app","base":"master","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CFZ7EC5BN","gate":"pr-review","gate_check":null,"copilot":true}' \
  --variant l2f-funnel --desk desk05
# write delivery/plan.md (skill: references/kickoff.md), then
turnstile plan-submitted                                   # the lead: ! TURNSTILE_LEAD=1 turnstile approve ah-1
turnstile brief implementer MYD-18075 --var ticket_key=MYD-18075 --var ...   # then Agent(turnstile:implementer, PROMPT line)
turnstile bug add --story S1 --title "Share visible on published Create form" --source "tester 2026-10-13" --figma KOew:9098-41434
turnstile pass story S1 ENV_TESTING --report reports/ENV-S1.md --cases-pass 30 --cases-fail 1 --figma-parity pass   # a run; fails need bugs
turnstile bug set b01 --state done
turnstile pass story S1 ENV_TESTING --report reports/ENV-S1.md --cases-pass 31 --cases-fail 0 --figma-parity pass --full
```

Replace the "Commands" paragraph's first sentence with: `init`, `plan-submitted`, `pass` (the writer of transitions), `approve` (lead only), `jira-synced` (validated against the PR's state), `brief` (renders an agent brief; refuses unfilled placeholders), `bug add|set`, `reconcile` (read-only, `--json`), `status`, `render-board`. Add to "Heads and GitHub": *Every commit message is checked for a `Co-Authored-By` trailer or the generated-with footer and the PR body for the footer (R3-10). From REWORK, ON_HUMAN_REVIEW requires a reply by `epic.roles.lead_github` after `rework_since.at` on every human thread that was open then.* Add to "The lead's word": *`plan` entries are opened by `plan-submitted`; no story leaves PLANNED until the newest one is approved and `plan.md` is unchanged.* Add a paragraph "Stories" after it: *`stories.<S>.branch` is the story branch; INTEGRATION_REVIEW requires every PR of the story to be based on it or on another PR of the story (a stack), or MERGED. ENV_TESTING re-enters itself to record a test run (`--cases-pass/--cases-fail/--figma-parity`, `--full` for a complete run); a run with N fails needs N bugs of the story added since the previous run (`turnstile bug add`); DONE needs the last run full and clean and every bug of the story done.* Add a line "Agents (`agents/`): implementer (sonnet), reviewer (opus, xhigh), story-reviewer (fable), stack-step, comments-handler, investigator, tester (opus, Figma parity), deployer (sonnet); launched as `turnstile:<name>` with a brief from `turnstile brief`."

- [ ] **Step 4: Verify everything**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -3 && claude plugin validate . 2>&1 | tail -3 && scripts/turnstile --version`
Expected: `OK` with ≥ 190 tests (147 + the ~45 added here); validate without errors; `turnstile 0.2.0`.

- [ ] **Step 5: Commit and tag**

```bash
git add README.md turnstile_cli/__init__.py .claude-plugin/plugin.json tests/test_cli_smoke.py
git commit -m "docs: usage for init, plan-submitted, brief, bug, skill and agents; version 0.2.0"
git tag v0.2.0
```

---

## Self-review

- **Spec coverage.** §2.1 artefacts (`plan.md`, `decisions.md`, `briefs/`, `reports/`, `evidence/`, the shrunken workspace `CLAUDE.md`) → Task 1. §2.2 `github_org` → Task 2; `roles.lead_github`, `stories.<S>.branch`, `evidence.env_runs` → Tasks 1, 5, 6. §4.1 kick-off + lead approval of `plan.md` → Task 1 (template), Task 3 (`plan` entry + digest gate, approved only through `turnstile approve` from the lead's prompt), Task 11 (`kickoff.md`, `## init`). §4.2 story DoDs: "stacked or merged into the story branch" → Task 5; "every fail became a bug → fixed → re-run (failed cases only, then one full final run)" → Task 6; the sequencing → Task 11 `## story-gate`. §3 REWORK DoD "replies posted" → Task 7; R3-10 trailer evasion → Task 7 (GitHub commit messages + body). §5 skill commands `init / status / pass / dispatch / story-gate / plan` → Task 11; their CLI helpers → Tasks 1, 3, 4, 10. §5 `render-board` "bugs tab with the db-backed status dropdowns" → Task 8 (the legend with the Jira mapping already exists in the core). §7 agents (models, efforts, does/cannot, common rules) → Task 9; §7.1 tester → Task 9 `tester.md` + Task 11 `evidence.md`, `env/pdffiller-dev.md`. §8 packaging (`skills/turnstile/SKILL.md`, `references/`, `agents/`, `templates/state.json`, `templates/CLAUDE.md.workspace`, personal items out of the plugin) → Tasks 1, 9, 11, 12. §10 "agents: one dry run each on a throwaway branch" stays a manual step before plan 3's cut-over. §12 open question 3 (create Jira story issues at `init`): decided **no** — `plan.md` references tickets only.
- **Placeholders.** None of the forbidden phrases; the eight agent files and eight brief templates are written in full (the common block is defined once in Task 9 Step 3 and pasted into each file; the test pins its sentinel lines). The README edits in Task 12 are given as exact text.
- **Type consistency.** New writers use the core's names: `state.locked`, `state.load`, `state.digest`, `state.write_atomic`, `pass_cmd.IO` (`git_commit`, `render_board`, `github_facts`), `pass_cmd._side_effects(delivery, st, lines, io, no_commit)`, `_open_entry`, `_ensure_start_story_entries`, `_recompute_next_actions`, `_ensure_repo_files`, `_now`, `rules.latest_entry`, `rules.check_approved_entry`, `rules.is_lead_override`, `rework_since`, `used_at`, `approved_via`, `human_review: per_pr`, `gate` / `gate_check` / `ci_ignore`. `check_story` keeps its signature and gains `plan_missing=None` (Task 3) — the `pass_cmd` call site is updated once in Task 3 and left untouched by Tasks 5–6 (they add rules inside `check_story`). `_facts_mismatches` gains `lead_login=None` (Task 7) and both callers (`pass_cmd._verify_against_github`, `reconcile._dry_run`) are updated there. Agent names (Task 9) = brief template stems (Task 10) = `turnstile:<name>` launch names (Task 11); `tests/test_brief.py` pins the equality. Bug states in Task 4 (`STATES`) = `BUG_STATES` in Task 8 = the `--state` choices. `tests/test_pass.py` exports used across new tests exist today: `FakeIO`, `opts`, `run_capture`, `env`, `READY_OPTS`, `LINK`, `H`.
- **Review Focus.** 1 → Task 1 `test_init_reuses_worktree_and_refuses_existing_state`; 2 → Task 3 `test_edited_plan_voids_approval` (+ `test_story_start_needs_plan_approval_even_with_lead_reason`); 3 → Task 6 `test_failed_run_needs_bugs`, `test_done_needs_full_run`; 4 → Task 7 `test_rework_needs_lead_replies`; 5 → Task 10 `test_brief_refuses_unfilled_placeholder`.

## Decisions taken while planning (not in the spec or the review)

- Plan approval is an `awaiting_human` entry of `type: plan` (`payload: plan.md`, `digest`), approved like every other entry by the lead's prompt line; the gate also pins the digest of `plan.md`, so an edited plan needs a new submission and approval. The lead `--reason` override that bypasses `start_story`/`after` does **not** bypass the plan gate.
- Stories enter `state.json` from a ```` ```json turnstile-stories ```` block in `plan.md` (`branch` required per story); the prose tables stay for humans.
- `--repo` for `init` is a JSON object (the state's own format) rather than a positional mini-language, so `gate_check: null` and `ci_ignore` lists need no custom syntax.
- Story-branch rule: allowed bases are `{story.branch} ∪ {branches of the story's other PRs}` (the review text says "bases of the other PRs"; read literally that would let two PRs on the epic branch vouch for each other).
- "Every fail became a bug" counts bugs by id against the previous run's `bug_ids` snapshot, not by `created_at`, because `_now()` has minute resolution.
- "Replies posted" is verified on GitHub (`reviewThreads.comments.createdAt`, `epic.roles.lead_github`), so the lead posts GitHub replies themself; `comments-handler` only drafts them. The trailer check is on GitHub commit messages and the PR body (the review's alternative to a `commit-msg` hook), which also catches `printf`-escaped spellings.
- Credentials for the tester are a `--var credentials=…` at dispatch time; the brief file is committed, so the lead decides what goes there (flag for plan 3: a `TURNSTILE_TEST_PASSWORD` env read by the tester would keep it out of git).

## Deviations

Recorded while executing the plan on 2026-10-14 (inline, single implementer; every task committed, suite green, pushed).

1. **Task 1 — `test_init_creates_worktree_delivery_marker_and_claude_md`.** The plan's `_ensure_worktree` probes `git branch --list` before `worktree add`, so the test's `io.calls[0]` assertion could not hold. Kept the probe (a deleted worktree with a surviving branch is re-attached, not re-created with `-b`); the test locates the first `worktree add` call instead.
2. **Task 1 — test setUp.** The temp dir is `.resolve()`d because `init` resolves the workspace and knowledge paths; on macOS `/var` is a symlink to `/private/var`, which made the path assertions differ. No code change.
3. **Task 3 — `tests/test_pass.py::test_start_story_entries_are_opened_for_startable_stories`.** The plan listed only `test_rules_story` as unaffected; this test goes through `pass_cmd.run` and now hits the plan gate (the fixture has no approved plan). The gate is spec §4.1, so the test seeds `epic.plan` + an approved `plan` entry and indexes the `start_story` entry at `[1]`.
4. **Task 7 — fixture.** `tests/fixtures/gh_pr_13222.json` had no `allCommits` block (the core's parse tolerated its absence); the plan's step edits `allCommits.nodes[].commit.message`, so the block was added with one signed node at the head and a clean message.
5. **Task 12 — tag.** Tagged `v0.2.0-skill` (the caller's instruction) rather than `v0.2.0`.
6. **Task 12 — README.** "Usage (core)" became "Usage" with the new commands prepended as planned; the `echo delivery > .turnstile` line was kept at the end of the block with a note that `init` writes it.
7. **Final review (self-review, no subagent per the caller).** One finding fixed: `_facts_mismatches` let an unparsable `rework_since.at` skip the "replies posted" check (fail-open); it now refuses with `MISSING a parsable rework_since.at …` (test `test_unparsable_rework_since_fails_closed`). Deferred minors: `approve`/`status` print `plan None` for plan entries (no pr/story); a brief file written before a failed commit stays on disk (the next pass commits it, `status` reports it); `turnstile bug` without a subcommand prints help and exits 0; `init` overwrites an existing `.turnstile` in the workspace.
