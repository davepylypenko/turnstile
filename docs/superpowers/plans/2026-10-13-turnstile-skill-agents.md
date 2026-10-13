# Turnstile skill, agents and workflow commands — implementation plan (plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the core CLI from plan 1 into a usable plugin: `init` (knowledge worktree + `delivery/` skeleton + kick-off analysis + lead approval gate), `dispatch` (standardised agent launch from brief templates), `story-gate` (integration review → env testing), `plan` (re-plan), the eight role agents, the `turnstile` skill with its references (DoR/DoD, briefs, PR body, Slack, reports, evidence, env recipe), the bug-status overlay on the board, and two schema promotions (`epic.github_org`, `epic.repos.*.gate` + `gate_check`).

**Architecture:** The CLI grows four small writers next to `pass` (`init`, `plan-submitted`, `brief`, `bug`), each going through the same side-effect path (save → ledger → board → git commit) with injectable IO so tests never touch git remotes or the network. Everything the orchestrator *reads* (procedures, templates, role rules) is Markdown under `skills/turnstile/` and `agents/`, validated by stdlib tests that parse frontmatter and check cross-references. The skill commands `init`, `dispatch`, `story-gate`, `plan` are procedures in `SKILL.md` that chain CLI calls and agent launches; the CLI enforces the gates (plan approval, evidence heads), the skill only sequences.

**Tech Stack:** Python 3.9 standard library (`json`, `re`, `argparse`, `subprocess`, `hashlib`, `unittest`), `git` worktrees, Claude Code plugin layout (`agents/*.md` with YAML frontmatter, `skills/<name>/SKILL.md`), the claude.ai artifact runtime (`claude.use('db')`, `claude.use('user')`) in `templates/board.html`.

**Spec:** `docs/superpowers/specs/2026-10-13-turnstile-design.md` (sections 2.1, 4.1, 5 "Skill commands", 7, 7.1, 8, 10). Plan 1 (implemented, read its `## Deviations`): `docs/superpowers/plans/2026-10-13-turnstile-core.md`. Plan 3 (not here): migration of MYD-16538 and vendoring into `pdffiller-knowledge`.

## Global Constraints

- Python 3.9 syntax only: no `match`, no `X | Y` types, no `list[str]` at runtime (use `typing.List`). No third-party packages. Tests: `python3 -m unittest discover -s tests -v` (52 green at the start of this plan; every task adds to that number, none removes).
- State file is JSON, 2-space indent, `sort_keys=True`, trailing newline (`state.dumps`). Writers of `state.json` after this plan: `pass`, `approve`, `jira-synced`, `init`, `plan-submitted`, `bug add|set`. Every writer: `state.save` (stale-file guard) → `ledger.append` → `board.render` → `git commit` of `delivery/`, exactly like `pass_cmd._side_effects`; `--no-commit` where the plan says so.
- CLI output: plain text; success ends with one `OK …` line; failure prints `MISSING …` lines, exits 2, writes nothing.
- PR ids `<repo>#<number>`; story ids `S<n>`; bug ids `b<nn>` (two digits, zero-padded, e.g. `b03`); awaiting ids `ah-<n>`. Head comparison is `rules.same_head` (prefix-safe, ≥ 8 chars).
- `epic.github_org` is required (no silent `pdffiller` default anywhere after Task 3). `epic.repos.<repo>.gate` names the GitHub **StatusContext** (`pdf-review`); `epic.repos.<repo>.gate_check` (optional) names the **CheckRun** that must also be green (`gate / gate`). Both must be `success` for the gate to count.
- Agents: `agents/<name>.md`, YAML frontmatter keys `name` (= file stem), `description`, `model` (`sonnet` | `opus` | `fable`), optional `effort`, `tools` (comma-separated allowlist). Models/efforts per spec §7: implementer sonnet; reviewer opus **xhigh**; story-reviewer fable; stack-step opus; comments-handler opus; investigator opus; tester opus; deployer sonnet. Launch name from the orchestrator: `turnstile:<name>`.
- Skill: `skills/turnstile/SKILL.md` ≤ 160 lines, frontmatter `name: turnstile` + `description`; everything longer lives in `skills/turnstile/references/` and is linked by relative path.
- Brief templates: `skills/turnstile/references/briefs/<agent>.md`, placeholders `{{snake_case}}` only; `turnstile brief` refuses to write a brief with any unfilled placeholder.
- Personal items (names, channel ids, reviewer logins, passwords) never go into the plugin: channels and roles come from `state.json`, credentials from the lead at dispatch time (brief variable), the env recipe carries patterns only.
- Commit messages in this repo: conventional (`feat(init): …`), signed (global SSH signing is on; never `--no-gpg-sign`), **no `Co-Authored-By` trailer**. Tag `v0.2.0` at the end.

## Review Focus

1. **`init` run twice** (worktree already exists, or `delivery/state.json` already there): the second run must reuse the worktree and refuse to overwrite the state rather than clobber a live epic. Test in Task 1 (`test_init_reuses_worktree_and_refuses_existing_state`).
2. **`plan.md` edited after the lead approved it**: `pass story S<n> IN_PROGRESS` from `PLANNED` must be refused until `plan-submitted` + a fresh approval, because the approval was for a different text. Test in Task 2 (`test_edited_plan_voids_approval`).
3. **Gate StatusContext green while the `gate / gate` CheckRun is pending or failed**: the gate must not count as passed; `reconcile` must flag recorded `pass` evidence as red. Test in Task 3 (`test_gate_status_needs_both`, `test_gate_red_when_check_run_fails`).
4. **A brief template with a placeholder nobody filled** (`{{figma_frames}}` for a tester brief): the brief must not be written, the missing names must be printed, because an agent launched on a half-filled brief hallucinates the rest. Test in Task 7 (`test_brief_refuses_unfilled_placeholder`).
5. **`bug add` for a story that does not exist** or a malformed PR id (`jsfiller-13222`): refused, nothing written, so the board never shows a bug nobody can route. Test in Task 4 (`test_bug_add_validates_story_and_pr`).

---

## File structure

```
turnstile/
  .claude-plugin/plugin.json                  # version 0.2.0 (Task 9); agents/ and skills/ are auto-discovered
  agents/implementer.md                       # Task 6 — eight role agents, frontmatter + role rules
  agents/reviewer.md
  agents/story-reviewer.md
  agents/stack-step.md
  agents/comments-handler.md
  agents/investigator.md
  agents/tester.md
  agents/deployer.md
  skills/turnstile/SKILL.md                   # Task 8 — short; states, commands, when what
  skills/turnstile/references/lifecycle.md    # Task 8 — DoR/DoD tables with the CLI call per transition
  skills/turnstile/references/kickoff.md      # Task 8 — §4.1 procedure
  skills/turnstile/references/plan.md         # Task 1 — plan.md template (init copies it), carries the turnstile-stories block
  skills/turnstile/references/pr-body.md      # Task 8
  skills/turnstile/references/slack.md        # Task 8 — review request, locales pairing, monolith, replies, story report
  skills/turnstile/references/reports.md      # Task 8 — report templates per agent
  skills/turnstile/references/evidence.md     # Task 8 — evidence/ layout
  skills/turnstile/references/env/pdffiller-dev.md   # Task 8 — first env recipe
  skills/turnstile/references/briefs/<agent>.md      # Task 7 — eight brief templates
  templates/state.json                        # Task 1 — empty epic skeleton with every key the rules read
  templates/CLAUDE.md.workspace               # Task 1 — the shrunken workspace CLAUDE.md
  templates/board.html                        # Task 5 — bugs db overlay + legend
  turnstile_cli/init_cmd.py                   # Task 1
  turnstile_cli/plan_cmd.py                   # Task 2
  turnstile_cli/brief_cmd.py                  # Task 7
  turnstile_cli/bug_cmd.py                    # Task 4
  turnstile_cli/rules.py                      # Task 2 (plan approval), Task 3 (nothing; gate logic lives in github.py)
  turnstile_cli/github.py                     # Task 3 — gate_status()
  turnstile_cli/reconcile.py                  # Task 2 (status shows plan), Task 3 (gate_status, github_org required)
  turnstile_cli/pass_cmd.py                   # Task 2 (plan gate on PLANNED→IN_PROGRESS), Task 5 (BOARD line carries the artifact url)
  turnstile_cli/main.py                       # wiring in Tasks 1, 2, 4, 7
  tests/test_init.py  tests/test_plan_cmd.py  tests/test_gate.py  tests/test_bug.py
  tests/test_board_bugs.py  tests/test_agents.py  tests/test_brief.py  tests/test_skill_files.py
  tests/fixtures/gh_pr_13222.json             # Task 3 — the pdf-review CheckRun becomes a StatusContext again
```

---

### Task 1: `templates/state.json`, `templates/CLAUDE.md.workspace`, plan template, `turnstile init`

**Files:**
- Create: `templates/state.json`, `templates/CLAUDE.md.workspace`, `skills/turnstile/references/plan.md`, `turnstile_cli/init_cmd.py`, `tests/test_init.py`
- Modify: `turnstile_cli/main.py` (wire `init`)

**Interfaces:**
- Consumes: `state.dumps`, `ledger.append`, `errors.TurnstileError`.
- Produces:
  - `init_cmd.InitOptions` dataclass: `epic, workitem, knowledge, lead, github_org, repos: List[str], variant, desk, board_url, workspace=".", knowledge_base="main", pm, design, recipe="references/env/pdffiller-dev.md"`.
  - `init_cmd.InitIO.git(args: List[str], cwd: Path) -> str` (injectable).
  - `init_cmd.parse_repo(spec: str) -> Tuple[str, dict]` for `name:base:epic_branch:slack:gate:copilot[:branch_prefix]` (empty `gate` → `None`; `gate == "pdf-review"` adds `gate_check: "gate / gate"`).
  - `init_cmd.epic_branch_name(key: str) -> str` → `epic/<key lower-cased>`.
  - `init_cmd.build_state(o: InitOptions) -> dict`.
  - `init_cmd.run(o: InitOptions, io: Optional[InitIO] = None) -> int`.
  - CLI: `turnstile init --epic MYD-16538 --workitem pdfd-429-l2f-editor-funnel --knowledge /path/pdffiller-knowledge --lead davyd.pylypenko --github-org pdffiller --repo jsfiller:develop:epic_myd-16538_l2f-funnel:CCGLRULNR:pdf-review:false --repo pdffiller:master:l2f-funnel:G8S415WG6:pdf-review:true:l2f-funnel-myd- --variant l2f-funnel --desk desk05 [--board-url …] [--workspace .] [--knowledge-base main] [--pm …] [--design …]`.
  - Filesystem result: worktree `<workspace>/<knowledge basename>` on branch `epic/<key>`; `delivery/` = `<worktree>/context/workitems/<workitem>/delivery/` with `state.json`, `ledger.md`, `decisions.md`, `plan.md`, `briefs/.gitkeep`, `reports/.gitkeep`, `evidence/.gitkeep`; `<workspace>/.turnstile` with the relative delivery path; `<workspace>/CLAUDE.md` from the template, or `CLAUDE.md.turnstile` when a `CLAUDE.md` already exists; one git commit `turnstile: init <key>` in the worktree.
  - `epic.plan = {"path": "plan.md", "submitted_at": null, "digest": null}` is the hook Task 2 uses for the approval gate.

- [ ] **Step 1: Write the templates**

`templates/state.json` (every key the rules and the board read; `null`/empty where `init` fills it):

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
    "roles": { "design": null, "lead": null, "pm": null },
    "workitem": null
  },
  "prs": {},
  "stories": {}
}
```

`templates/CLAUDE.md.workspace`:

```markdown
# {{epic_key}} — orchestrator workspace

You are the orchestrator of epic **{{epic_key}}**. The delivery state lives in `{{delivery}}/`
(`state.json`, `ledger.md`, `plan.md`, `decisions.md`, `briefs/`, `reports/`, `evidence/`, `board.html`),
on the epic branch of the knowledge worktree. Plugin: `turnstile` — invoke the `turnstile` skill first in every
session; it starts with `turnstile status`.

- `state.json` is written only by `turnstile` commands (`pass`, `approve`, `jira-synced`, `plan-submitted`, `bug`).
- Every send, reply, merge, "ready", reviewer request and story start waits for the lead's word; the hooks block the rest.
- All implementation, review, testing and deployment is delegated to the `turnstile:*` agents; the orchestrator never reads diffs or runs suites itself.
- Chat with the lead in Ukrainian. Code, commits, PRs, tickets and docs in English.
```

`skills/turnstile/references/plan.md` (the kick-off output template; `init` copies it to `delivery/plan.md`):

````markdown
# {{epic_key}} — delivery plan

Status: DRAFT — not approved. (Approval: `turnstile approve <ah-id>` after the lead's word; the id is printed by `turnstile plan-submitted`.)

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
define the slices here and give the rationale.

| Story | Title | Tickets | Repos | After | Parallel with | Env slot |
|---|---|---|---|---|---|---|
| S1 | | | | — | | variant / desk |

## 3. Merge order and stack

Per story: the ticket PRs in merge order, the story branch they stack into, file overlaps with parallel stories and
how merge order resolves them.

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

def opts(ws, knowledge, **kw):
    base = dict(epic="MYD-1", workitem="demo", knowledge=str(knowledge), lead="lead@example.com", github_org="pdffiller",
                repos=["jsfiller:develop:epic_myd-1:C1:pdf-review:false", "pdffiller:master:l2f:G1:pdf-review:true:l2f-myd-"],
                variant="v1", desk="desk05", workspace=str(ws))
    base.update(kw); return init_cmd.InitOptions(**base)

class FakeGit(init_cmd.InitIO):
    def __init__(self): self.calls = []
    def git(self, args, cwd):
        self.calls.append((args, pathlib.Path(cwd)))
        if args[0] == "worktree" and args[1] == "add":
            pathlib.Path(args[-2] if args[2] == "-b" else args[2]).mkdir(parents=True)
        if args[:2] == ["branch", "--list"]:
            return ""
        return ""

class ParseRepo(unittest.TestCase):
    def test_repo_spec(self):
        name, cfg = init_cmd.parse_repo("pdffiller:master:l2f:G1:pdf-review:true:l2f-myd-")
        self.assertEqual(name, "pdffiller")
        self.assertEqual(cfg, {"base": "master", "epic_branch": "l2f", "slack": "G1", "gate": "pdf-review",
                               "gate_check": "gate / gate", "copilot": True, "branch_prefix": "l2f-myd-"})
        self.assertEqual(init_cmd.parse_repo("locales:main:epic:C2::false")[1]["gate"], None)
        with self.assertRaises(TurnstileError):
            init_cmd.parse_repo("jsfiller:develop")
    def test_epic_branch_name(self):
        self.assertEqual(init_cmd.epic_branch_name("MYD-16538"), "epic/myd-16538")

class Init(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.ws = self.tmp / "ws"; self.ws.mkdir()
        self.knowledge = self.tmp / "pdffiller-knowledge"; (self.knowledge / ".git").mkdir(parents=True)

    def test_init_creates_worktree_delivery_marker_and_claude_md(self):
        io = FakeGit()
        rc = init_cmd.run(opts(self.ws, self.knowledge), io)
        self.assertEqual(rc, 0)
        wt = self.ws / "pdffiller-knowledge"
        d = wt / "context" / "workitems" / "demo" / "delivery"
        self.assertEqual(io.calls[1][0], ["worktree", "add", "-b", "epic/myd-1", str(wt), "main"])
        data = json.loads((d / "state.json").read_text())
        self.assertEqual(data["epic"]["key"], "MYD-1"); self.assertEqual(data["epic"]["github_org"], "pdffiller")
        self.assertEqual(data["epic"]["repos"]["pdffiller"]["branch_prefix"], "l2f-myd-")
        self.assertEqual(data["epic"]["plan"], {"digest": None, "path": "plan.md", "submitted_at": None})
        self.assertEqual(data["epic"]["environment"], {"desk": "desk05", "recipe": "references/env/pdffiller-dev.md", "variant": "v1"})
        for name in ("ledger.md", "decisions.md", "plan.md", "briefs/.gitkeep", "reports/.gitkeep", "evidence/.gitkeep"):
            self.assertTrue((d / name).exists(), name)
        self.assertIn("MYD-1", (d / "plan.md").read_text()); self.assertIn("turnstile-stories", (d / "plan.md").read_text())
        self.assertEqual((self.ws / ".turnstile").read_text().strip(), "pdffiller-knowledge/context/workitems/demo/delivery")
        self.assertIn("MYD-1", (self.ws / "CLAUDE.md").read_text())
        self.assertEqual(io.calls[-1][0][:2], ["commit", "-q"]); self.assertEqual(io.calls[-1][1], d)

    def test_init_keeps_existing_claude_md(self):
        (self.ws / "CLAUDE.md").write_text("mine\n")
        init_cmd.run(opts(self.ws, self.knowledge), FakeGit())
        self.assertEqual((self.ws / "CLAUDE.md").read_text(), "mine\n")
        self.assertTrue((self.ws / "CLAUDE.md.turnstile").exists())

    def test_init_reuses_worktree_and_refuses_existing_state(self):
        io = FakeGit(); init_cmd.run(opts(self.ws, self.knowledge), io)
        n = len(io.calls)
        rc = init_cmd.run(opts(self.ws, self.knowledge), io)
        self.assertEqual(rc, 2)
        self.assertFalse(any(c[0][:2] == ["worktree", "add"] for c in io.calls[n:]))

    def test_init_requires_a_git_clone(self):
        rc = init_cmd.run(opts(self.ws, self.tmp / "nope"), FakeGit())
        self.assertEqual(rc, 2)

    def test_init_with_real_git(self):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.knowledge, check=True)
        (self.knowledge / "README.md").write_text("k\n")
        g = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
        subprocess.run(g + ["add", "."], cwd=self.knowledge, check=True)
        subprocess.run(g + ["commit", "-qm", "init"], cwd=self.knowledge, check=True)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        class RealGit(init_cmd.InitIO):
            def git(self, args, cwd):
                out = subprocess.run(["git", "-c", "commit.gpgsign=false"] + args, cwd=str(cwd), capture_output=True, text=True, env=env)
                if out.returncode != 0: raise TurnstileError(out.stderr)
                return out.stdout
        self.assertEqual(init_cmd.run(opts(self.ws, self.knowledge), RealGit()), 0)
        wt = self.ws / "pdffiller-knowledge"
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=wt, capture_output=True, text=True).stdout.strip()
        self.assertEqual(branch, "epic/myd-1")
        log = subprocess.run(["git", "log", "--oneline"], cwd=wt, capture_output=True, text=True).stdout
        self.assertIn("turnstile: init MYD-1", log)
```

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

@dataclass
class InitOptions:
    epic: str
    workitem: str
    knowledge: str
    lead: str
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
    parts = spec.split(":")
    if len(parts) < 6 or not parts[0]:
        raise TurnstileError("--repo needs name:base:epic_branch:slack:gate:copilot[:branch_prefix] (got %r)" % spec)
    name, base, epic_branch, slack, gate, copilot = parts[:6]
    cfg = {"base": base, "epic_branch": epic_branch, "slack": slack or None, "gate": gate or None,
           "copilot": copilot.strip().lower() == "true"}
    if gate == "pdf-review":
        cfg["gate_check"] = "gate / gate"
    if len(parts) > 6 and parts[6]:
        cfg["branch_prefix"] = parts[6]
    return name, cfg

def epic_branch_name(key: str) -> str:
    return "epic/" + key.lower()

def build_state(o: InitOptions) -> dict:
    data = json.loads((TEMPLATES / "state.json").read_text())
    e = data["epic"]
    e["key"] = o.epic; e["workitem"] = o.workitem; e["github_org"] = o.github_org
    e["roles"] = {"lead": o.lead, "pm": o.pm, "design": o.design}
    e["repos"] = dict(parse_repo(s) for s in o.repos)
    e["environment"] = {"variant": o.variant, "desk": o.desk, "recipe": o.recipe}
    e["board"] = {"artifact_url": o.board_url, "capabilities": ["db", "user"]}
    e["plan"] = {"path": "plan.md", "submitted_at": None, "digest": None}
    return data

def _ensure_worktree(o: InitOptions, io: InitIO, knowledge: pathlib.Path, wt: pathlib.Path) -> str:
    branch = epic_branch_name(o.epic)
    if wt.exists():
        return branch
    existing = io.git(["branch", "--list", branch], knowledge).strip()
    if existing:
        io.git(["worktree", "add", str(wt), branch], knowledge)
    else:
        io.git(["worktree", "add", "-b", branch, str(wt), o.knowledge_base], knowledge)
    return branch

def run(o: InitOptions, io: Optional[InitIO] = None) -> int:
    io = io or InitIO()
    try:
        ws = pathlib.Path(o.workspace).resolve()
        knowledge = pathlib.Path(o.knowledge).resolve()
        if not (knowledge / ".git").exists():
            raise TurnstileError("%s is not a git clone (no .git)" % knowledge)
        data = build_state(o)  # validates --repo specs before touching the filesystem
        wt = ws / knowledge.name
        branch = _ensure_worktree(o, io, knowledge, wt)
        delivery = wt / "context" / "workitems" / o.workitem / "delivery"
        if (delivery / "state.json").exists():
            raise TurnstileError("already initialised: %s (state.json exists; use turnstile status)" % delivery)
        for sub in ("briefs", "reports", "evidence"):
            (delivery / sub).mkdir(parents=True, exist_ok=True)
            (delivery / sub / ".gitkeep").touch()
        (delivery / "state.json").write_text(st_mod.dumps(data))
        (delivery / "decisions.md").write_text(
            "# Decisions — %s\n\n| Date | Topic | Decision | Source |\n|---|---|---|---|\n\n## Open questions\n\n| # | Question | Owner | Asked | Answer |\n|---|---|---|---|---|\n" % o.epic)
        (delivery / "plan.md").write_text(PLAN_TEMPLATE.read_text().replace("{{epic_key}}", o.epic))
        ledger.append(delivery, "init %s (%s) on %s" % (o.epic, o.workitem, branch))
        rel = os.path.relpath(str(delivery), str(ws))
        (ws / ".turnstile").write_text(rel + "\n")
        text = (TEMPLATES / "CLAUDE.md.workspace").read_text().replace("{{epic_key}}", o.epic).replace("{{delivery}}", rel)
        target = ws / "CLAUDE.md"
        if target.exists():
            target = ws / "CLAUDE.md.turnstile"
        target.write_text(text)
        io.git(["add", "-A", "."], delivery)
        io.git(["commit", "-q", "-m", "turnstile: init %s" % o.epic], delivery)
        print("WORKTREE: %s (%s)" % (wt, branch))
        print("DELIVERY: %s" % delivery)
        print("CLAUDE_MD: %s" % target)
        print("NEXT: write %s per the turnstile skill (references/kickoff.md), then: turnstile plan-submitted" % (delivery / "plan.md"))
        print("OK init %s" % o.epic)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
```

- [ ] **Step 5: Wire the subcommand in `main.py`**

Add to `build_parser()` after the `status` parser:

```python
    ini = sub.add_parser("init", help="create the knowledge worktree and the delivery/ skeleton for an epic")
    for flag, kw in [("--epic", {"required": True}), ("--workitem", {"required": True}), ("--knowledge", {"required": True}),
                     ("--lead", {"required": True}), ("--github-org", {"required": True}),
                     ("--repo", {"action": "append", "default": [], "dest": "repos",
                                 "help": "name:base:epic_branch:slack:gate:copilot[:branch_prefix]; repeatable"}),
                     ("--variant", {}), ("--desk", {}), ("--board-url", {}), ("--workspace", {"default": "."}),
                     ("--knowledge-base", {"default": "main"}), ("--pm", {}), ("--design", {}),
                     ("--recipe", {"default": "references/env/pdffiller-dev.md"})]:
        ini.add_argument(flag, **kw)
```

And in `main()`, **before** `delivery = paths.find_delivery(...)` (init runs where no `.turnstile` exists yet):

```python
        if a.cmd == "init":
            from .init_cmd import run as init_run, InitOptions
            return init_run(InitOptions(**{k: v for k, v in vars(a).items() if k not in ("cmd", "delivery")}))
```

- [ ] **Step 6: Run the tests**

Run: `python3 -m unittest tests.test_init -v && python3 -m unittest discover -s tests 2>&1 | tail -3`
Expected: all `test_init` tests PASS; whole suite `OK` (52 + 7).

- [ ] **Step 7: Smoke the CLI help**

Run: `scripts/turnstile init --help | head -5`
Expected: usage line listing `--epic --workitem --knowledge --lead --github-org`.

- [ ] **Step 8: Commit**

```bash
git add templates/state.json templates/CLAUDE.md.workspace skills/turnstile/references/plan.md turnstile_cli/init_cmd.py turnstile_cli/main.py tests/test_init.py
git commit -m "feat(init): knowledge worktree, delivery skeleton, workspace CLAUDE.md and plan template"
```

---

### Task 2: `plan-submitted` and the lead-approval gate on story start

**Files:**
- Create: `turnstile_cli/plan_cmd.py`, `tests/test_plan_cmd.py`
- Modify: `turnstile_cli/rules.py` (add `plan_approval_missing`, extend `check_story`), `turnstile_cli/pass_cmd.py:209-220` (story branch computes the plan gate), `turnstile_cli/reconcile.py:358-367` (status prints the plan line), `turnstile_cli/main.py` (wire)

**Interfaces:**
- Consumes: `state.load/save/dumps`, `ledger.append`, `pass_cmd.IO`, `pass_cmd._recompute_next_actions`, `pass_cmd._next_ah_id`, `pass_cmd._now`, `state.digest`.
- Produces:
  - `plan_cmd.stories_from_plan(text: str) -> dict` — parses the fenced block that starts with ```` ```json turnstile-stories ````; raises `TurnstileError` when absent, not JSON, an id is not `S<n>`, a required key (`title`, `tickets`, `repos`) is missing, or `after`/`parallel_with` reference unknown ids.
  - `plan_cmd.merge_stories(existing: dict, planned: dict) -> dict` — new ids become `PLANNED` with `evidence: {}`, `next_action: ""`; existing ids keep `state`, `evidence`, `next_action` and take the plan fields; ids missing from the plan are dropped only while `PLANNED`, otherwise `TurnstileError`.
  - `plan_cmd.run(delivery: Path, io: Optional[IO] = None) -> int` — writes `stories`, `epic.plan = {path, submitted_at, digest}` (digest = `state.digest` of `plan.md`), replaces any unapproved `awaiting_human` entry of `type: "decision", payload: "plan.md"` with a fresh one, then the side-effect chain; prints `PLAN: <n> stories (<new> new)`, `APPROVAL: turnstile approve <ah-id>`, `OK plan submitted …`.
  - `rules.plan_approval_missing(data: dict, plan_digest: Optional[str]) -> Optional[str]` — `None` when the latest plan decision is approved and the digest matches; otherwise the `MISSING …` line.
  - `rules.check_story(..., plan_missing: Optional[str] = None)` — appended only on `PLANNED → IN_PROGRESS`; **no `--reason` override** (spec §4.1: without approval no story leaves PLANNED).
  - CLI: `turnstile plan-submitted [--no-commit]`; `turnstile status` prints `plan: approved <ah-id> | awaiting approval <ah-id> | not submitted | changed since approval`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_plan_cmd.py
import copy, io, json, contextlib, pathlib, shutil, tempfile, unittest
from turnstile_cli import plan_cmd, pass_cmd, rules, state
from turnstile_cli.errors import TurnstileError

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"
PLAN = """# plan

```json turnstile-stories
{
  "S1": {"title": "Header", "tickets": ["MYD-10", "MYD-11"], "repos": ["jsfiller"], "after": [], "parallel_with": [],
         "test_cases": ["TP-1"], "figma": ["F:1-2"], "env_slot": {"variant": "v1"}, "human_review_units": []},
  "S2": {"title": "Results", "tickets": ["MYD-12"], "repos": ["front-link2fill-app"], "after": ["S1"]}
}
```
"""

class FakeIO(pass_cmd.IO):
    def __init__(self): self.commits = []; self.renders = 0
    def git_commit(self, delivery, message): self.commits.append(message)
    def renderer(self, data, delivery): self.renders += 1

def opts(**kw):
    o = pass_cmd.Options(); [setattr(o, k, v) for k, v in kw.items()]; return o

class Parse(unittest.TestCase):
    def test_parses_block_and_defaults(self):
        s = plan_cmd.stories_from_plan(PLAN)
        self.assertEqual(sorted(s), ["S1", "S2"])
        self.assertEqual(s["S2"]["parallel_with"], []); self.assertEqual(s["S2"]["test_cases"], [])
        self.assertEqual(s["S2"]["env_slot"], {}); self.assertEqual(s["S2"]["human_review_units"], [])
    def test_rejects_missing_block_bad_id_missing_key_unknown_ref(self):
        with self.assertRaises(TurnstileError): plan_cmd.stories_from_plan("# no block")
        with self.assertRaises(TurnstileError): plan_cmd.stories_from_plan(PLAN.replace('"S2"', '"X2"'))
        with self.assertRaises(TurnstileError): plan_cmd.stories_from_plan(PLAN.replace('"title": "Results", ', ""))
        with self.assertRaises(TurnstileError): plan_cmd.stories_from_plan(PLAN.replace('"after": ["S1"]', '"after": ["S9"]'))

class Merge(unittest.TestCase):
    def test_keeps_state_of_existing_and_plans_new(self):
        existing = json.loads(FIX.read_text())["stories"]
        merged = plan_cmd.merge_stories(existing, plan_cmd.stories_from_plan(PLAN))
        self.assertEqual(merged["S1"]["state"], "IN_PROGRESS"); self.assertEqual(merged["S1"]["figma"], ["F:1-2"])
        self.assertEqual(merged["S2"]["state"], "PLANNED"); self.assertEqual(merged["S2"]["evidence"], {})
    def test_drop_only_planned(self):
        self.assertNotIn("S1", plan_cmd.merge_stories({"S1": {"state": "PLANNED"}}, {}))
        with self.assertRaises(TurnstileError):
            plan_cmd.merge_stories({"S1": {"state": "PLANNED"}, "S2": {"state": "IN_PROGRESS"}}, {})

class Run(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); (self.d / "plan.md").write_text(PLAN); self.io = FakeIO()
    def submit(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = plan_cmd.run(self.d, self.io)
        return rc, buf.getvalue()
    def data(self): return json.loads((self.d / "state.json").read_text())

    def test_submit_records_stories_digest_and_awaiting(self):
        rc, out = self.submit()
        self.assertEqual(rc, 0); self.assertIn("APPROVAL: turnstile approve ah-1", out); self.assertIn("OK plan submitted", out)
        d = self.data()
        self.assertEqual(d["stories"]["S2"]["state"], "PLANNED")
        self.assertEqual(d["epic"]["plan"]["digest"], state.digest(PLAN))
        self.assertEqual(d["awaiting_human"][0]["type"], "decision"); self.assertEqual(d["awaiting_human"][0]["payload"], "plan.md")
        self.assertIsNone(d["awaiting_human"][0]["approved_at"])
        self.assertEqual(len(self.io.commits), 1); self.assertEqual(self.io.renders, 1)
    def test_resubmit_replaces_unapproved_entry(self):
        self.submit(); self.submit()
        self.assertEqual(len([a for a in self.data()["awaiting_human"] if a["payload"] == "plan.md"]), 1)
    def test_story_start_needs_approval(self):
        self.submit()
        rc = pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(), self.io)
        self.assertEqual(rc, 2)
        d = self.data(); d["stories"]["S1"]["state"] = "DONE"; (self.d / "state.json").write_text(state.dumps(d))  # S2 is after S1
        pass_cmd.approve(self.d, "ah-1", self.io)
        rc = pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(), self.io)
        self.assertEqual(rc, 0)
    def test_edited_plan_voids_approval(self):
        self.submit(); pass_cmd.approve(self.d, "ah-1", self.io)
        d = self.data(); d["stories"]["S1"]["state"] = "DONE"; (self.d / "state.json").write_text(state.dumps(d))
        (self.d / "plan.md").write_text(PLAN + "\nedited after approval\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = pass_cmd.run(self.d, "story", "S2", "IN_PROGRESS", opts(), self.io)
        self.assertEqual(rc, 2); self.assertIn("plan.md changed", buf.getvalue())
    def test_not_submitted_message(self):
        d = self.data(); d["stories"]["S1"]["state"] = "PLANNED"; (self.d / "state.json").write_text(state.dumps(d))
        self.assertIn("plan-submitted", rules.plan_approval_missing(d, state.digest(PLAN)))
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_plan_cmd -v`
Expected: FAIL — `No module named 'turnstile_cli.plan_cmd'`.

- [ ] **Step 3: Implement `plan_cmd.py`**

```python
# turnstile_cli/plan_cmd.py
import copy, json, pathlib, re
from typing import Optional
from . import state as st_mod, ledger
from .errors import TurnstileError

BLOCK_RX = re.compile(r"```json[ \t]+turnstile-stories[ \t]*\n(.*?)\n```", re.S)
ID_RX = re.compile(r"^S\d+$")
REQUIRED = ("title", "tickets", "repos")
DEFAULTS = {"after": [], "parallel_with": [], "test_cases": [], "figma": [], "env_slot": {}, "human_review_units": []}

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
        for k in REQUIRED:
            if k not in s:
                raise TurnstileError("story %s lacks %r" % (sid, k))
        full = dict(DEFAULTS); full.update({k: copy.deepcopy(v) for k, v in s.items()})
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
        if cur:
            keep = {k: cur.get(k) for k in ("state", "evidence", "next_action")}
            merged[sid] = dict(s); merged[sid].update({k: v for k, v in keep.items() if v is not None})
        else:
            merged[sid] = dict(s); merged[sid].update({"state": "PLANNED", "evidence": {}, "next_action": ""})
    for sid, cur in existing.items():
        if sid not in planned and cur.get("state") != "PLANNED":
            raise TurnstileError("cannot drop story %s in state %s; keep it in plan.md" % (sid, cur.get("state")))
    return merged

def run(delivery: pathlib.Path, io=None) -> int:
    from .pass_cmd import IO, _recompute_next_actions, _next_ah_id, _now
    io = io or IO()
    try:
        delivery = pathlib.Path(delivery)
        st = st_mod.load(delivery / "state.json")
        plan_path = delivery / "plan.md"
        if not plan_path.exists():
            raise TurnstileError("no plan.md in %s" % delivery)
        text = plan_path.read_text()
        planned = stories_from_plan(text)
        before = set(st.data.get("stories", {}))
        st.data["stories"] = merge_stories(st.data.get("stories", {}), planned)
        st.data["epic"]["plan"] = {"path": "plan.md", "submitted_at": _now(), "digest": st_mod.digest(text)}
        ah = [a for a in st.data.setdefault("awaiting_human", [])
              if not (a.get("type") == "decision" and a.get("payload") == "plan.md" and not a.get("approved_at"))]
        st.data["awaiting_human"] = ah
        entry = {"id": _next_ah_id(st.data), "owner": "lead", "type": "decision", "pr": None, "story": None,
                 "created_at": _now(), "payload": "plan.md", "approved_at": None}
        ah.append(entry)
        _recompute_next_actions(st.data)
        new = sorted(set(planned) - before)
        summary = "plan submitted: %d stories (%d new%s)" % (len(planned), len(new), ": " + ", ".join(new) if new else "")
        st_mod.save(st); ledger.append(delivery, summary); io.renderer(st.data, delivery)
        io.git_commit(delivery, "turnstile: " + summary)
        print("PLAN: %d stories (%d new)" % (len(planned), len(new)))
        print("APPROVAL: turnstile approve %s   # after the lead's word" % entry["id"])
        print("OK " + summary)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
```

- [ ] **Step 4: The rule and the gate in `rules.py` / `pass_cmd.py` / `reconcile.py`**

In `rules.py` add after `STORY_FROM`/`PR_AT_LEAST_READY`:

```python
def plan_approval_missing(data: dict, plan_digest: Optional[str]) -> Optional[str]:
    plan = (data.get("epic") or {}).get("plan") or {}
    if not plan.get("digest"):
        return "MISSING plan.md submitted and approved (turnstile plan-submitted, then turnstile approve <ah-id>)"
    if plan_digest != plan.get("digest"):
        return "MISSING plan.md changed since it was submitted; re-run turnstile plan-submitted and get the lead's approval again"
    decisions = [a for a in data.get("awaiting_human", []) if a.get("type") == "decision" and a.get("payload") == "plan.md"]
    if not decisions or not decisions[-1].get("approved_at"):
        ah = decisions[-1]["id"] if decisions else "<ah-id>"
        return "MISSING lead approval of plan.md (turnstile approve %s)" % ah
    return None
```

Change the `check_story` signature to `def check_story(story, target, prs, stories, reason=None, plan_missing: Optional[str] = None)` and inside the `target == "IN_PROGRESS"` branch, as the first statement:

```python
        if src == "PLANNED" and plan_missing:
            out.append(plan_missing)
```

In `pass_cmd.run`, story branch, replace the `missing = rules.check_story(...)` line with:

```python
            plan_missing = None
            if target == "IN_PROGRESS" and story.get("state") == "PLANNED":
                plan_path = pathlib.Path(delivery) / "plan.md"
                plan_missing = rules.plan_approval_missing(data, st_mod.digest(plan_path.read_text()) if plan_path.exists() else None)
            missing = rules.check_story(trial, target, data["prs"], data["stories"], reason=o.reason, plan_missing=plan_missing)
```

In `reconcile.cli`, inside `if status:` right after the `== <key>` line:

```python
        plan = st.data["epic"].get("plan") or {}
        decisions = [a for a in st.data.get("awaiting_human", []) if a.get("type") == "decision" and a.get("payload") == "plan.md"]
        plan_path = pathlib.Path(delivery) / "plan.md"
        if not plan.get("digest"):
            print("plan: not submitted")
        elif plan_path.exists() and st_mod.digest(plan_path.read_text()) != plan.get("digest"):
            print("plan: changed since submission (turnstile plan-submitted)")
        elif decisions and decisions[-1].get("approved_at"):
            print("plan: approved %s" % decisions[-1]["id"])
        else:
            print("plan: awaiting approval %s" % (decisions[-1]["id"] if decisions else "?"))
```

In `main.py`: `sub.add_parser("plan-submitted", help="read stories from plan.md into state and ask the lead for approval")` and in `main()`:

```python
        if a.cmd == "plan-submitted":
            from .plan_cmd import run as plan_run
            return plan_run(delivery)
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest tests.test_plan_cmd tests.test_rules_story tests.test_pass tests.test_e2e -v 2>&1 | tail -5`
Expected: all PASS (`test_planned_waits_for_after_unless_reason` still passes: it calls `check_story` without `plan_missing`). `test_status_without_network` still passes and its output now has a `plan:` line.

- [ ] **Step 6: Commit**

```bash
git add turnstile_cli/plan_cmd.py turnstile_cli/rules.py turnstile_cli/pass_cmd.py turnstile_cli/reconcile.py turnstile_cli/main.py tests/test_plan_cmd.py
git commit -m "feat(plan): plan-submitted reads stories from plan.md; story start gated on the lead's approval"
```

---

### Task 3: Gate = StatusContext + secondary CheckRun; `github_org` required

**Files:**
- Create: `tests/test_gate.py`
- Modify: `turnstile_cli/github.py` (add `gate_status`), `turnstile_cli/reconcile.py:330-333` (use it) and `:346` (org required), `tests/fixtures/gh_pr_13222.json:84-88` (CheckRun `pdf-review` → StatusContext), `templates/board.html` (`prUrl` has no `'pdffiller'` fallback)

**Interfaces:**
- Produces: `github.gate_status(f: PrFacts, repo_cfg: dict) -> Optional[str]` — `None` when the repo has no `gate`; `"success"` only when `checks[gate] == "success"` and (`gate_check` unset or `checks[gate_check] == "success"`); `"missing"` when either configured name is absent from the rollup; `"failure"` when any is in `failure | error | cancelled | timed_out | action_required | startup_failure`; otherwise `"pending"`.
- `reconcile.compare` proposal `gate_red` message becomes `gate <name> is <status> on GitHub but evidence says pass`.
- `reconcile.cli` raises `TurnstileError("epic.github_org is not set; add it to state.json (turnstile init sets it)")` when absent → `main` prints `MISSING …`, exit 2.

- [ ] **Step 1: Fixture — make `pdf-review` a StatusContext again**

In `tests/fixtures/gh_pr_13222.json` replace the node

```json
                {
                  "name": "pdf-review",
                  "conclusion": "SUCCESS",
                  "status": "COMPLETED"
                }
```

with

```json
                {
                  "context": "pdf-review",
                  "state": "SUCCESS"
                }
```

(The `gate / gate` CheckRun node at line 60 stays.)

- [ ] **Step 2: Failing tests**

```python
# tests/test_gate.py
import copy, io, json, contextlib, pathlib, shutil, tempfile, unittest
from turnstile_cli import github, reconcile, board
from turnstile_cli.errors import TurnstileError

D = pathlib.Path(__file__).parent / "fixtures"
FIX = json.loads((D / "state_min.json").read_text())
PAYLOAD = json.loads((D / "gh_pr_13222.json").read_text())
CFG = {"gate": "pdf-review", "gate_check": "gate / gate"}

def facts(**checks):
    f = github.parse("jsfiller#1", PAYLOAD); f.checks.update(checks); return f

class GateStatus(unittest.TestCase):
    def test_fixture_has_context_and_check_run(self):
        f = github.parse("jsfiller#1", PAYLOAD)
        self.assertEqual(f.checks["pdf-review"], "success"); self.assertEqual(f.checks["gate / gate"], "success")
    def test_success_needs_both(self):
        self.assertEqual(github.gate_status(facts(), CFG), "success")
        self.assertEqual(github.gate_status(facts(**{"gate / gate": "in_progress"}), CFG), "pending")
        self.assertEqual(github.gate_status(facts(**{"gate / gate": "failure"}), CFG), "failure")
        self.assertEqual(github.gate_status(facts(**{"pdf-review": "failure"}), CFG), "failure")
    def test_missing_and_no_gate(self):
        f = facts(); del f.checks["gate / gate"]
        self.assertEqual(github.gate_status(f, CFG), "missing")
        self.assertEqual(github.gate_status(facts(), {"gate": "pdf-review"}), "success")
        self.assertIsNone(github.gate_status(facts(), {"gate": None}))

class ReconcileGate(unittest.TestCase):
    def data(self):
        d = copy.deepcopy(FIX); p = d["prs"]["jsfiller#1"]; p["state"] = "READY"
        p["evidence"]["gate"] = {"name": "pdf-review", "head": "aaaaaaaa11111111", "result": "pass"}
        d["epic"]["repos"]["jsfiller"]["gate_check"] = "gate / gate"
        return d
    def test_gate_red_when_check_run_fails(self):
        f = facts(**{"gate / gate": "failure"}); f.human_threads_open = 0
        props = reconcile.compare(self.data(), {"jsfiller#1": f})
        self.assertEqual([p.kind for p in props], ["gate_red"]); self.assertIn("failure", props[0].message)
    def test_gate_green_when_both_pass(self):
        f = facts(); f.human_threads_open = 0
        self.assertEqual([p.kind for p in reconcile.compare(self.data(), {"jsfiller#1": f})], [])

class OrgRequired(unittest.TestCase):
    def test_reconcile_cli_refuses_without_org(self):
        d = pathlib.Path(tempfile.mkdtemp()); data = copy.deepcopy(FIX); del data["epic"]["github_org"]
        (d / "state.json").write_text(json.dumps(data))
        with self.assertRaises(TurnstileError):
            reconcile.cli(d)
    def test_board_has_no_org_fallback(self):
        html = board.render(FIX, pathlib.Path(tempfile.mkdtemp())).read_text()
        self.assertNotIn("|| 'pdffiller'", html)
```

- [ ] **Step 3: Run, expect failure**

Run: `python3 -m unittest tests.test_gate -v`
Expected: FAIL — `AttributeError: module 'turnstile_cli.github' has no attribute 'gate_status'`; `test_board_has_no_org_fallback` fails on the fallback string.

- [ ] **Step 4: Implement**

Append to `turnstile_cli/github.py`:

```python
RED = ("failure", "error", "cancelled", "timed_out", "action_required", "startup_failure")

def gate_status(f: PrFacts, repo_cfg: dict) -> Optional[str]:
    name = repo_cfg.get("gate")
    if not name:
        return None
    names = [name] + ([repo_cfg["gate_check"]] if repo_cfg.get("gate_check") else [])
    vals = [f.checks.get(n) for n in names]
    if any(v is None for v in vals):
        return "missing"
    if all(v == "success" for v in vals):
        return "success"
    if any(v in RED for v in vals):
        return "failure"
    return "pending"
```

In `reconcile.compare` replace the three `g = _ev_for_head(pr, "gate") … gate_red` lines with:

```python
        g = _ev_for_head(pr, "gate")
        gs = github.gate_status(f, repo)
        if g and gs and gs != "success" and g.get("result") == "pass":
            out.append(Proposal(pid, "gate_red", "gate %s is %s on GitHub but evidence says pass" % (repo.get("gate"), gs), None))
```

In `reconcile.cli` replace `org = st.data["epic"].get("github_org", "pdffiller")` with:

```python
    org = st.data["epic"].get("github_org")
    if not org:
        raise TurnstileError("epic.github_org is not set; add it to state.json (turnstile init sets it)")
```

and add `from .errors import TurnstileError` to the imports of `reconcile.py`.

In `templates/board.html` change the `prUrl` line to:

```js
const prUrl = id => { const [repo, n] = id.split('#'); const org = ((STATE || {}).epic || {}).github_org; return org ? 'https://github.com/' + org + '/' + repo + '/pull/' + n : '#'; };
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -3`
Expected: `OK`; `tests.test_reconcile.Parse.test_parse` still asserts `checks["pdf-review"] == "success"` (now from the StatusContext) and `test_gate_red_against_recorded_pass` still proposes `gate_red`.

- [ ] **Step 6: Commit**

```bash
git add turnstile_cli/github.py turnstile_cli/reconcile.py templates/board.html tests/fixtures/gh_pr_13222.json tests/test_gate.py
git commit -m "feat(github): gate = StatusContext plus secondary gate/gate check run; github_org required"
```

---

### Task 4: `turnstile bug add | set`

**Files:**
- Create: `turnstile_cli/bug_cmd.py`, `tests/test_bug.py`
- Modify: `turnstile_cli/main.py` (wire)

**Interfaces:**
- Consumes: `state.*`, `ledger.append`, `pass_cmd.IO`, `pass_cmd._now`.
- Produces:
  - `bug_cmd.STATES = ["todo", "ai", "testing", "done"]`, `bug_cmd.PR_RX = r"^[A-Za-z0-9_.-]+#\d+$"`.
  - `bug_cmd.next_id(bugs: List[dict]) -> str` → `b01`, `b02`, … (max existing + 1).
  - `bug_cmd.add(delivery, story, title, source, pr=None, figma=None, note="", io=None) -> int` — bug `{id, story, title, source, pr, figma, state: "todo", note, created_at}`; story must exist; `pr` must match `PR_RX` (any repo, the PR may be outside the epic); prints `OK bug b03 added (S1)`.
  - `bug_cmd.set_(delivery, bug_id, state=None, pr=None, note=None, io=None) -> int` — at least one of the three; prints `OK bug b03 → testing`.
  - CLI: `turnstile bug add --story S1 --title "…" --source "tester 2026-10-13" [--pr jsfiller#13384] [--figma file:node] [--note …]`; `turnstile bug set b03 [--state testing] [--pr …] [--note …]`.
  - Both run the side-effect chain (`save`, ledger line, board render, commit `turnstile: bug …`).

- [ ] **Step 1: Failing tests**

```python
# tests/test_bug.py
import io, json, contextlib, pathlib, shutil, tempfile, unittest
from turnstile_cli import bug_cmd, pass_cmd

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class FakeIO(pass_cmd.IO):
    def __init__(self): self.commits = []; self.renders = 0
    def git_commit(self, delivery, message): self.commits.append(message)
    def renderer(self, data, delivery): self.renders += 1

class Bugs(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); self.io = FakeIO()
    def data(self): return json.loads((self.d / "state.json").read_text())

    def test_next_id(self):
        self.assertEqual(bug_cmd.next_id([]), "b01")
        self.assertEqual(bug_cmd.next_id([{"id": "b03"}, {"id": "b11"}]), "b12")

    def test_add_and_set(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = bug_cmd.add(self.d, "S1", "Share visible", "tester 2026-10-13", pr="jsfiller#13384", figma="F:1-2", io=self.io)
        self.assertEqual(rc, 0); self.assertIn("OK bug b01 added (S1)", buf.getvalue())
        b = self.data()["bugs"][0]
        self.assertEqual((b["id"], b["story"], b["state"], b["pr"], b["figma"]), ("b01", "S1", "todo", "jsfiller#13384", "F:1-2"))
        rc = bug_cmd.set_(self.d, "b01", state="testing", note="on desk05", io=self.io)
        self.assertEqual(rc, 0)
        b = self.data()["bugs"][0]; self.assertEqual((b["state"], b["note"]), ("testing", "on desk05"))
        self.assertEqual(len(self.io.commits), 2); self.assertEqual(self.io.renders, 2)
        self.assertIn("bug b01 → testing", (self.d / "ledger.md").read_text())

    def test_bug_add_validates_story_and_pr(self):
        before = (self.d / "state.json").read_text()
        self.assertEqual(bug_cmd.add(self.d, "S9", "x", "s", io=self.io), 2)
        self.assertEqual(bug_cmd.add(self.d, "S1", "x", "s", pr="jsfiller-13222", io=self.io), 2)
        self.assertEqual(bug_cmd.add(self.d, "S1", "", "s", io=self.io), 2)
        self.assertEqual((self.d / "state.json").read_text(), before); self.assertEqual(self.io.commits, [])

    def test_set_validates(self):
        bug_cmd.add(self.d, "S1", "x", "s", io=self.io)
        self.assertEqual(bug_cmd.set_(self.d, "b01", state="fixed", io=self.io), 2)
        self.assertEqual(bug_cmd.set_(self.d, "b02", state="done", io=self.io), 2)
        self.assertEqual(bug_cmd.set_(self.d, "b01", io=self.io), 2)
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_bug -v`
Expected: FAIL — `No module named 'turnstile_cli.bug_cmd'`.

- [ ] **Step 3: Implement**

```python
# turnstile_cli/bug_cmd.py
import pathlib, re
from typing import List, Optional
from . import state as st_mod, ledger
from .errors import TurnstileError

STATES = ["todo", "ai", "testing", "done"]
PR_RX = re.compile(r"^[A-Za-z0-9_.-]+#\d+$")

def next_id(bugs: List[dict]) -> str:
    nums = [int(b["id"][1:]) for b in bugs if re.match(r"^b\d+$", b.get("id", ""))]
    return "b%02d" % (max(nums or [0]) + 1)

def _check_pr(pr: Optional[str]) -> None:
    if pr and not PR_RX.match(pr):
        raise TurnstileError("pr must look like repo#123 (got %r)" % pr)

def _finish(delivery: pathlib.Path, st, summary: str, io) -> int:
    st_mod.save(st); ledger.append(delivery, summary); io.renderer(st.data, delivery)
    io.git_commit(delivery, "turnstile: " + summary)
    print("OK " + summary); return 0

def add(delivery, story: str, title: str, source: str, pr: Optional[str] = None, figma: Optional[str] = None,
        note: str = "", io=None) -> int:
    from .pass_cmd import IO, _now
    io = io or IO()
    try:
        delivery = pathlib.Path(delivery); st = st_mod.load(delivery / "state.json")
        if story not in st.data.get("stories", {}):
            raise TurnstileError("unknown story %s" % story)
        if not (title or "").strip():
            raise TurnstileError("--title is required")
        _check_pr(pr)
        bugs = st.data.setdefault("bugs", [])
        bug = {"id": next_id(bugs), "story": story, "title": title.strip(), "source": source, "pr": pr, "figma": figma,
               "state": "todo", "note": note or "", "created_at": _now()}
        bugs.append(bug)
        return _finish(delivery, st, "bug %s added (%s): %s" % (bug["id"], story, bug["title"]), io)
    except TurnstileError as e:
        print("MISSING %s" % e); return 2

def set_(delivery, bug_id: str, state: Optional[str] = None, pr: Optional[str] = None, note: Optional[str] = None, io=None) -> int:
    from .pass_cmd import IO
    io = io or IO()
    try:
        delivery = pathlib.Path(delivery); st = st_mod.load(delivery / "state.json")
        if state is None and pr is None and note is None:
            raise TurnstileError("nothing to set: pass --state, --pr or --note")
        if state is not None and state not in STATES:
            raise TurnstileError("state must be one of %s" % ", ".join(STATES))
        _check_pr(pr)
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
        return _finish(delivery, st, "bug %s %s" % (bug_id, ", ".join(changes) or "unchanged"), io)
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
```

`main.py` — parser:

```python
    bg = sub.add_parser("bug", help="record or update a bug found by the tester or the lead"); bsub = bg.add_subparsers(dest="bug_cmd")
    ba = bsub.add_parser("add"); ba.add_argument("--story", required=True); ba.add_argument("--title", required=True)
    ba.add_argument("--source", required=True); ba.add_argument("--pr"); ba.add_argument("--figma"); ba.add_argument("--note", default="")
    bs = bsub.add_parser("set"); bs.add_argument("bug_id"); bs.add_argument("--state", choices=["todo", "ai", "testing", "done"])
    bs.add_argument("--pr"); bs.add_argument("--note")
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

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tests.test_bug -v && python3 -m unittest discover -s tests 2>&1 | tail -1`
Expected: PASS; suite `OK`.

- [ ] **Step 5: Commit**

```bash
git add turnstile_cli/bug_cmd.py turnstile_cli/main.py tests/test_bug.py
git commit -m "feat(bug): bug add/set writers for tester and lead findings"
```

---

### Task 5: Board — bug-status overlay through the artifact `db`, legend, artifact url in the `BOARD:` line

**Files:**
- Create: `tests/test_board_bugs.py`
- Modify: `templates/board.html` (replace `function bugs()`, add overlay code and legend), `turnstile_cli/pass_cmd.py:224` (BOARD line), `turnstile_cli/bug_cmd.py` (nothing — it already renders)

**Interfaces:**
- Board JS (ported from `MYD-16538-docs/pr-board.html` `connectBugsDb`/`renderBugs`): `BUG_STATES`, `bugOverrides` (db docs `bugs/<id>` → `{status, updatedAt}`), `bugState(b)` = override when its `status` is a known state, else `b.state`; `<select data-bug="<id>">` per bug, disabled unless `bugsCanWrite`; on change → `bugsDb.doc('bugs/' + id).set({status, updatedAt: ISO})`, revert on error; `connectBugsDb()` = `claude.use('db')` → `claude.use('user')` → `user.can('data.write')` (null/undefined ⇒ writable, i.e. the owner's own view) → `db.collection('bugs').onSnapshot(...)` re-renders bugs and tiles. The orchestrator folds overrides back into `state.json` with `turnstile bug set` (Task 8 skill text).
- `pass_cmd` prints `BOARD: publish <path> → <artifact_url | new artifact (capabilities: db, user)>`.

- [ ] **Step 1: Failing test**

```python
# tests/test_board_bugs.py
import json, pathlib, re, tempfile, unittest
from turnstile_cli import board

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())

class BoardBugs(unittest.TestCase):
    def html(self):
        data = json.loads(json.dumps(FIX))
        data["bugs"] = [{"id": "b01", "story": "S1", "title": "Share visible", "source": "tester", "pr": "jsfiller#13384",
                         "figma": "F:1", "state": "todo", "note": "", "created_at": "x"}]
        return board.render(data, pathlib.Path(tempfile.mkdtemp())).read_text()
    def test_overlay_wiring(self):
        html = self.html()
        for needle in ["claude.use('db')", "claude.use('user')", "user.can('data.write')", "db.collection('bugs').onSnapshot",
                       "bugsDb.doc('bugs/' + id).set(", 'data-bug="', "const BUG_STATES = ['todo', 'ai', 'testing', 'done']",
                       "BUG_STATES.includes(", "typeof window.claude.use === 'function'"]:
            self.assertIn(needle, html, needle)
    def test_select_disabled_without_write(self):
        html = self.html()
        self.assertIn("(bugsCanWrite ? '' : ' disabled title=\"Status changes are saved by the board owner\"')", html)
    def test_legend_with_jira_mapping(self):
        html = self.html()
        self.assertIn('id="legend"', html)
        for s in ["DEV", "AI_REVIEW", "READY", "ON_HUMAN_REVIEW", "REWORK", "APPROVED", "MERGED", "In progress", "On Review", "On Hold"]:
            self.assertIn(s, html)
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_board_bugs -v`
Expected: FAIL on the first `assertIn` (`claude.use('db')`).

- [ ] **Step 3: Implement in `templates/board.html`**

Add to the `<style>` block:

```css
select.bug { font:inherit; font-size:12px; padding:2px 6px; border-radius:6px; border:1px solid var(--line); background:var(--card); color:var(--ink) }
select.bug:disabled { opacity:.7 } .manual { display:block; color:var(--muted); font-size:11px }
#legend { color:var(--muted); font-size:12px; margin-top:16px } #legend .badge { margin-right:4px }
```

After the four tab panes `<div id="prs">…<div id="awaiting" class="hidden"></div>` add `<div id="legend"></div>`.

Replace `function bugs() { … }` with:

```js
const BUG_STATES = ['todo', 'ai', 'testing', 'done'];
const BUG_COLORS = { todo:'var(--dev)', ai:'var(--ai)', testing:'var(--human)', done:'var(--merged)' };
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
        (b.pr ? '<a href="' + prUrl(b.pr) + '" target="_blank" rel="noopener">' + esc(b.pr) + '</a>' : '—') + '</td><td class="k">' + esc(b.figma || '—') + '</td>' +
        '<td><select class="bug" data-bug="' + esc(b.id) + '"' + (bugsCanWrite ? '' : ' disabled title="Status changes are saved by the board owner"') + '>' +
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
function legend() {
  const jira = { DEV:'In progress', AI_REVIEW:'In progress', READY:'In progress', ON_HUMAN_REVIEW:'On Review', REWORK:'On Review', APPROVED:'On Review', MERGED:'On Hold' };
  document.getElementById('legend').innerHTML = 'Jira mapping: ' + PR_STATES.map(s => badge(s) + ' ' + esc(jira[s])).join(' · ') +
    ' · Bug states: todo → ai (an agent is fixing) → testing (deployed, waiting for a re-test) → done. The dropdown writes to the board database; the orchestrator folds it back with <span class="k">turnstile bug set</span>.';
}
```

In `tiles()` replace the `'Open bugs'` count expression `(STATE.bugs || []).filter(b => b.state !== 'done').length` with `openBugs()`.

Change the last line of the script to:

```js
if (STATE) { document.getElementById('title').textContent = 'Turnstile — ' + (STATE.epic || {}).key; tiles(); prs(); stories(); bugs(); awaiting(); legend();
  if (window.claude && typeof window.claude.use === 'function') { connectBugsDb(); } else { window.addEventListener('load', () => { if (window.claude && typeof window.claude.use === 'function') connectBugsDb(); }); } }
```

In `pass_cmd.run`, replace `print("BOARD: publish %s" % (pathlib.Path(delivery) / "board.html"))` with:

```python
        url = ((data.get("epic") or {}).get("board") or {}).get("artifact_url")
        print("BOARD: publish %s → %s" % (pathlib.Path(delivery) / "board.html", url or "new artifact (capabilities: db, user)"))
```

- [ ] **Step 4: Run the tests and a DOM sanity check**

Run: `python3 -m unittest tests.test_board_bugs tests.test_board -v && python3 -m unittest discover -s tests 2>&1 | tail -1`
Expected: PASS; suite `OK`.

Run: `python3 - <<'EOF'
import json, pathlib, tempfile
from turnstile_cli import board
html = board.render(json.loads(pathlib.Path("tests/fixtures/state_min.json").read_text()), pathlib.Path(tempfile.mkdtemp())).read_text()
print(html.count("<script>"), html.count("</script>"), "legend" in html)
EOF`
Expected: `1 1 True`.

- [ ] **Step 5: Commit**

```bash
git add templates/board.html turnstile_cli/pass_cmd.py tests/test_board_bugs.py
git commit -m "feat(board): bug-status overlay via the artifact db, legend with the Jira mapping"
```

---

### Task 6: The eight role agents

**Files:**
- Create: `agents/implementer.md`, `agents/reviewer.md`, `agents/story-reviewer.md`, `agents/stack-step.md`, `agents/comments-handler.md`, `agents/investigator.md`, `agents/tester.md`, `agents/deployer.md`, `tests/test_agents.py`

**Interfaces:**
- Produces: eight agent definitions launchable as `turnstile:<name>`; each has frontmatter per Global Constraints and the sections `## Role`, `## Procedure`, `## Cannot`, `## Report`, `## Common rules`. Brief templates (Task 7) address them by these names and the report conventions below.
- `tests/test_agents.py` exposes `parse_frontmatter(text) -> dict` (reused by Task 8's test).

- [ ] **Step 1: Failing test**

```python
# tests/test_agents.py
import pathlib, re, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"
EXPECTED = {"implementer": ("sonnet", None), "reviewer": ("opus", "xhigh"), "story-reviewer": ("fable", None),
            "stack-step": ("opus", None), "comments-handler": ("opus", None), "investigator": ("opus", None),
            "tester": ("opus", None), "deployer": ("sonnet", None)}
SECTIONS = ["## Role", "## Procedure", "## Cannot", "## Report", "## Common rules"]
COMMON = ["Poll every 2 minutes or less", "never silent for more than 5 minutes", "reports/", "8 lines", "no subagents"]
FORBIDDEN_TOOLS = ["slack_send_message", "transitionJiraIssue", "Agent"]

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
            self.assertEqual(fm["name"], name); self.assertEqual(fm["model"], model, name)
            self.assertEqual(fm.get("effort"), effort, name)
            self.assertTrue(len(fm["description"]) > 40, name); self.assertIn("tools", fm, name)
    def test_sections_and_common_rules(self):
        for p in AGENTS.glob("*.md"):
            text = p.read_text()
            for s in SECTIONS: self.assertIn(s, text, "%s lacks %s" % (p.name, s))
            for c in COMMON: self.assertIn(c, text, "%s lacks common rule %r" % (p.name, c))
    def test_no_forbidden_tools(self):
        for p in AGENTS.glob("*.md"):
            tools = parse_frontmatter(p.read_text())["tools"]
            for t in FORBIDDEN_TOOLS:
                self.assertNotIn(t, [x.strip() for x in tools.split(",")], "%s allows %s" % (p.name, t))
    def test_role_specific_tools(self):
        fm = parse_frontmatter((AGENTS / "investigator.md").read_text())
        self.assertNotIn("Edit", fm["tools"]); self.assertNotIn("Write", fm["tools"])
        fm = parse_frontmatter((AGENTS / "tester.md").read_text())
        for t in ["mcp__claude_ai_Figma__get_screenshot", "mcp__claude_ai_Figma__get_design_context", "mcp__claude_ai_Figma__get_variable_defs"]:
            self.assertIn(t, fm["tools"])
        self.assertNotIn("Edit", fm["tools"])
        fm = parse_frontmatter((AGENTS / "deployer.md").read_text()); self.assertIn("Skill", fm["tools"])
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_agents -v`
Expected: FAIL — `agents/` does not exist (empty glob ≠ eight names).

- [ ] **Step 3: Write the common block once, paste it verbatim into every agent under `## Common rules`**

```markdown
## Common rules

- Read the brief file named in your prompt first, then every file it lists; the brief wins on specifics. Verify every anchor (file:line, symbol) before editing; a wrong anchor means stop and report `NEEDS_CONTEXT` with what you found instead. Never guess.
- Poll every 2 minutes or less when waiting on CI, Copilot, a workflow or a build; never silent for more than 5 minutes — print one line of progress. Keep your working state in the report file as you go so a restart after a limit or a watchdog resumes cheaply.
- Write the full report to the path the brief gives under `reports/` using the template in `references/reports.md`; reply to the orchestrator with at most 8 lines: status (`DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`), the head SHA(s), the PR URL(s), one-line result, concerns.
- Never claim a pass you did not observe: paste the real summary lines of every command you ran.
- Signed commits only (never `--no-gpg-sign`), conventional message with the ticket key, no `Co-Authored-By` trailer. PR bodies per `references/pr-body.md`, no generated-with footer. Never comment on a PR; the repo gate's own outputs are the only allowed PR comments.
- No Slack, no Jira, no reviewer requests, no "ready for review", no merges, no force-push, no rebase of shared branches, no subagents. The hooks block most of this; the rule covers the rest.
- Code, commits, PRs and reports in English.
```

- [ ] **Step 4: Write the eight files**

`agents/implementer.md`:

```markdown
---
name: implementer
description: Implements one ticket from a turnstile brief on a branch cut from the epic or story branch — code, tests, lint/types, a draft PR per template, signed commits. Launched by the turnstile skill's dispatch; not for reviews, deployments, Slack or Jira.
model: sonnet
tools: Read, Edit, Write, Bash, Grep, Glob
---

You implement exactly one ticket per brief inside one repository. You are a careful engineer who knows the toolchain poorly and the brief well: you follow it literally and report what it did not foresee.

## Role

- One ticket = one branch = one draft PR into the epic or story branch the brief names. Branch name per the repo rule in the brief (template `feature/<KEY>-<slug>` or the repo's `branch_prefix`).
- Change only the files the brief lists plus the tests it asks for. No refactors, no reformatting of untouched lines, no new dependencies, no CI changes, no code comments unless asked.
- Control arm untouched: a flagged feature ships with a test that has the flag off and asserts today's behaviour.

## Procedure

1. Read the target repo's `CLAUDE.md` / `AGENTS.md` / testing guide, then the brief, then every anchor it names.
2. `git fetch`; cut the branch from the base the brief names (or check out the existing one and merge the base in — never rebase).
3. Tests first where the brief lists them; implement; run exactly the verify commands from the brief (lint, types, unit tests for the touched packages) and keep the summary lines.
4. Commit (signed, conventional, ticket key), push normally. On a rejected push stop and report.
5. `gh pr create --draft --base <base>` with the body from `references/pr-body.md`. Never request reviewers, never mark ready, never add labels unless the brief says so.
6. When the brief says the repo has Copilot: request it via REST (`gh api -X POST repos/<org>/<repo>/pulls/<n>/requested_reviewers -f 'reviewers[]=copilot-pull-request-reviewer[bot]'`), wait, verify each thread against the code, fix the valid ones with a test, resolve every thread silently with the verdict in your report, re-request, repeat until a pass has no findings on the current head.
7. Verify every commit is signed: `gh api repos/<org>/<repo>/pulls/<n>/commits --jq '.[].commit.verification.verified'` — all `true`.

## Cannot

Slack, Jira, replying to or resolving human threads, `gh pr ready`, touching other repositories, subagents, merges, force-push.

## Report

`reports/<KEY>.md` per `references/reports.md` § Ticket: files changed, per-command summary lines, PR URL, head, Copilot verdicts, deviations from the brief, open questions, anything for the backlog.

<paste the common block here>
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

- Scope: the diff of the PR head against its base (`git diff <base>...<head>`), every scope bullet of the ticket, the control arm, every test's assertions (does it bite? would a mutation pass?), the invariants listed in the brief, fidelity to the source when the PR ports code, design fidelity when the brief names Figma frames.
- Output: a numbered findings list with severity (`blocker` / `major` / `minor` / `nit`) and a verdict for each: what, where (`file:line`), why, proposed fix. One-line fixes you apply yourself (signed commit on the PR branch, note it in the report); everything else goes back through the orchestrator.
- Recursive: after fixes land (yours or the implementer's) you review the new head again until a round has zero `blocker`/`major` findings. Record the rounds.

## Procedure

1. Read the repo's `CLAUDE.md`, the brief, the ticket text in the brief, the PR body.
2. Check out the PR head in the worktree the brief names; confirm `gh pr view <n> --json headRefOid` matches.
3. Deep review as above. Write the findings before running any tool-based review so the gate does not anchor you.
4. Run the repo gate the brief names (`pdf-review` via its skill, or `pr-review` / `review` / `run-lint` + `run-unit-tests`) on the same head; its own PR comments and labels are allowed, yours are not.
5. Merge the two lists; mark duplicates; verify every gate finding against the code before accepting it.
6. Report `clean: true` only when both your review and the gate have no open `blocker`/`major` on the current head.

## Cannot

Merge, mark ready, reply to humans, Slack, Jira, subagents, rebase, force-push, multi-line fixes (those go to an implementer brief).

## Report

`reports/REVIEW-<pr-number>.md` per `references/reports.md` § Review: head, base, rounds, findings table, gate run URL, what you fixed yourself, `clean`. The orchestrator records it with `turnstile pass pr <id> READY --deep-review reports/REVIEW-<n>.md --rounds <r> --gate <name>:pass:<run>`.

<paste the common block here>
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

1. Read the brief, `plan.md` § the story, the repos' `CLAUDE.md`, the previous `REVIEW-<n>.md` reports of the story's PRs (do not repeat what they fixed; check that they are fixed).
2. Check out the stack top; verify its SHA with `gh pr view` of the top PR.
3. Review the whole diff; then run the repo gate on the stack top if the brief asks for it.
4. One-line fixes: apply on the ticket PR branch they belong to (signed), merge up the stack only if the brief allows; otherwise report for a stack-step agent.

## Cannot

Merge, ready, replies to humans, Slack, Jira, subagents, rebase, force-push.

## Report

`reports/STORY-<S>-review.md` per `references/reports.md` § Story review: stack top SHA, rounds, findings with target PR, `clean`. Recorded with `turnstile pass story <S> ENV_TESTING --report reports/STORY-<S>-review.md --head <sha> --rounds <r>`.

<paste the common block here>
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
- Signed merge commits; default merge message is fine (no trailer).

## Procedure

1. Record the starting heads of every PR in the stack (`gh pr view <n> --json headRefOid`).
2. Ripple as above; keep a table of PR → old head → new head → CI → gate → Copilot.
3. Verify signatures on every new commit.

## Cannot

Rebase, force-push, `gh pr ready`, Slack, Jira, replies to humans, subagents, code changes beyond conflict resolution the brief authorised.

## Report

`reports/STACK-<date>.md` per `references/reports.md` § Stack: the table above and the `turnstile pass` lines the orchestrator must run (`AI_REVIEW --head <new> --ci success`, then `READY` once the gate evidence exists).

<paste the common block here>
```

`agents/comments-handler.md`:

```markdown
---
name: comments-handler
description: Handles review threads on one PR — verifies each human and Copilot comment against the code, fixes or justifies, loops Copilot to clean, drafts replies for human threads for the lead's approval. Resolves Copilot threads only; never touches human threads, never posts.
model: opus
tools: Read, Edit, Write, Bash, Grep, Glob
---

You turn review comments into verified fixes and honest replies. Agreement is not a verdict; the code is.

## Role

- Every thread gets a verdict: `VALID` → fix + test + signed commit + push; `NOT VALID` → a concrete code-level reason in the report. High-priority Copilot findings are never declined without such a reason.
- Copilot threads: after the fix or justification, resolve the thread (silently), re-request Copilot via REST, repeat until a pass on the current head has no findings. Never resolve an unfixed thread without a recorded reason.
- Human threads: do not reply, do not resolve. Draft the reply text per `references/slack.md` § Reply drafts (one per thread, with the commit that addresses it) in the report; the lead posts or approves it.

## Procedure

1. `gh api graphql` the PR's review threads (unresolved, author, path, line, body); separate human and Copilot.
2. For each: locate the code, decide, act, record.
3. After pushes: CI green, repo gate re-run per brief; verify signatures.

## Cannot

Replying to or resolving human threads, Slack, Jira, `gh pr ready`, merges, rebase, force-push, subagents.

## Report

`reports/COMMENTS-<pr-number>.md` per `references/reports.md` § Comments: thread table (id, author, verdict, commit, resolved?), Copilot loop rounds, draft replies, new head, gate state.

<paste the common block here>
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

Any push, commit, comment, workflow run, deploy, Slack, Jira, edits, subagents.

## Report

`reports/INVESTIGATE-<slug>.md` per `references/reports.md` § Investigation.

<paste the common block here>
```

`agents/tester.md`:

```markdown
---
name: tester
description: Runs a story's test cases on the deployed environment and checks every screen against its Figma frame pixel-level (screenshots side by side plus numeric DOM checks), using an isolated headless browser. Writes ENV-<story>.md and the evidence folder; fails become bugs via the orchestrator. Never changes code.
model: opus
tools: Read, Write, Bash, Grep, Glob, mcp__claude_ai_Figma__get_screenshot, mcp__claude_ai_Figma__get_design_context, mcp__claude_ai_Figma__get_variable_defs, mcp__claude_ai_Figma__get_metadata
---

You are the gate between "it works on my branch" and a human reviewer's time. You test what the plan says, on the environment the plan names, against the design the plan links, and you write down what you saw.

## Role

- Input (from the brief): story id, its test cases (id, preconditions, steps, expected), Figma frames per screen/state (`file:node`), the environment slot (variant, desk, build numbers), the environment recipe (`references/env/<product>.md`) and the credentials the lead supplied in the brief, the parity tolerance (default 1 px, exact colour).
- Browser: an isolated headless Playwright (or the product's headless runner) with its own profile and user-data dir under the scratchpad — never the user's Chrome, never a shared chrome-devtools MCP session. Route to the environment exactly as the recipe says (cookies on the recipe's domain, never as request headers), and prove the routing on the first request (`x-server-name`, static host) before any case.
- Design parity per screen/state: `evidence/<story>/<case>/env.png` next to `figma.png` (from `get_screenshot`), `dom.json` with measured spacing/sizes/fonts/colours against the Figma variables (`get_variable_defs`, `get_design_context`), `diff.md` with every deviation beyond tolerance; copy compared verbatim against Figma / the locale source the brief names.
- Verdict per case: `pass` / `fail` / `not_testable_here` (with the reason). A fail names the screen, the Figma node, the expected and the observed.

## Procedure

1. Read the recipe and the brief; prepare the browser profile; log in with the user the brief names (register `+testerN` variants if sessions collide, per the recipe).
2. Prove routing; record build numbers (`static.version`, backend `x-server-name`) in the report header.
3. Run every case in order; save evidence immediately after each; never retry a failed case silently — record the retry.
4. Figma parity for every screen/state listed in the brief, including states reached mid-case.
5. Re-run mode (brief says `rerun`): only the cases listed, then — if all pass — one full run.

## Cannot

Code changes, pushes, Slack, Jira, PR comments, using the user's visible browser, subagents, inventing a case that is not in the brief (propose it in the report instead).

## Report

`reports/ENV-<story>.md` per `references/reports.md` § Env test: header (environment, builds, routing proof), case table (case → verdict → evidence path), parity table (screen → node → max deviation → verdict), fails list ready for `turnstile bug add`, `not_testable_here` reasons. Recorded with `turnstile pass story <S> DONE --report reports/ENV-<S>.md --cases-pass <n> --cases-fail <n> --figma-parity pass|fail`.

<paste the common block here>
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
- Record run ids, build numbers (`static.version` per app) and image tags as you learn them.

## Procedure

1. Read the brief (repos, branches/PRs, variant/desk, tag to keep, health checks).
2. Trigger the workflows; poll `gh run view` every ≤ 2 min; on failure collect the failing step's log tail.
3. Health check per the brief (an endpoint, a bundle url, a page). Never report "deployed" without it.

## Cannot

Production or RC environments, `ensure` without a tag, Slack, Jira, code changes, subagents, deleting variants.

## Report

`reports/DEPLOY-<slug>-<date>.md` per `references/reports.md` § Deploy: table repo → ref → run → build/tag → health check. Recorded with `turnstile pass story <S> INTEGRATION_REVIEW --build <build>`.

<paste the common block here>
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest tests.test_agents -v`
Expected: all four PASS.

- [ ] **Step 6: Plugin manifest sanity**

Run: `claude plugin validate . 2>&1 | tail -3`
Expected: no error about `agents/` (advice lines about the README install line are fine and handled in Task 9).

- [ ] **Step 7: Commit**

```bash
git add agents tests/test_agents.py
git commit -m "feat(agents): eight role agents with model, effort, tool allowlists and role rules"
```

---

### Task 7: Brief templates and `turnstile brief` (the `dispatch` helper)

**Files:**
- Create: `skills/turnstile/references/briefs/{implementer,reviewer,story-reviewer,stack-step,comments-handler,investigator,tester,deployer}.md`, `turnstile_cli/brief_cmd.py`, `tests/test_brief.py`
- Modify: `turnstile_cli/main.py` (wire)

**Interfaces:**
- Produces:
  - `brief_cmd.PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")`.
  - `brief_cmd.render(template: str, vars: dict) -> Tuple[str, List[str]]` — substituted text and the sorted list of unfilled names.
  - `brief_cmd.builtins(data: dict, delivery: Path, agent: str, name: str) -> dict` — `epic_key, github_org, delivery` (absolute), `variant, desk, env_recipe` (from `epic.environment`, `""` when null), `agent, brief_name, brief_path` (`briefs/<name>.md`), `report_path` (`reports/<name>.md`), `today` (UTC `YYYY-MM-DD`).
  - `brief_cmd.run(delivery, agent, name, var_list: List[str], force=False, io=None) -> int` — agent must exist in `agents/`, template in `references/briefs/`; `--var k=v` entries override builtins; unfilled placeholders → `MISSING placeholder <name>` per name, exit 2, nothing written; existing brief → `MISSING briefs/<name>.md exists (use --force)`; success writes the brief, ledger line `brief <name> for <agent>`, commit `turnstile: brief <name>`, prints `AGENT: turnstile:<agent>`, `BRIEF: <abs path>`, `REPORT: <abs path>`, `PROMPT: Read and execute <abs brief path>. Write your report to <abs report path>. Reply with at most 8 lines.`, `OK brief <name> for <agent>`.
  - CLI: `turnstile brief <agent> <name> [--var k=v]... [--force] [--no-commit]`.
  - Every template contains `{{report_path}}` and `{{epic_key}}`; agent-specific placeholders are listed per template below and are what the skill's `dispatch` section (Task 8) tells the orchestrator to pass.

- [ ] **Step 1: Failing tests**

```python
# tests/test_brief.py
import io, contextlib, json, pathlib, re, shutil, tempfile, unittest
from turnstile_cli import brief_cmd, pass_cmd

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"
BRIEFS = ROOT / "skills" / "turnstile" / "references" / "briefs"

class FakeIO(pass_cmd.IO):
    def __init__(self): self.commits = []; self.renders = 0
    def git_commit(self, delivery, message): self.commits.append(message)
    def renderer(self, data, delivery): self.renders += 1

def placeholders(text): return sorted(set(brief_cmd.PLACEHOLDER.findall(text)))

class Templates(unittest.TestCase):
    def test_one_template_per_agent_with_required_placeholders(self):
        agents = sorted(p.stem for p in (ROOT / "agents").glob("*.md"))
        self.assertEqual(sorted(p.stem for p in BRIEFS.glob("*.md")), agents)
        for p in BRIEFS.glob("*.md"):
            ph = placeholders(p.read_text())
            self.assertIn("report_path", ph, p.name); self.assertIn("epic_key", ph, p.name)
            self.assertTrue(all(re.match(r"^[a-z][a-z0-9_]*$", x) for x in ph), p.name)
    def test_render_reports_missing(self):
        text, missing = brief_cmd.render("a {{x}} b {{y}} {{x}}", {"x": "1"})
        self.assertEqual(text, "a 1 b {{y}} 1"); self.assertEqual(missing, ["y"])

class Run(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir(); (self.d / "briefs").mkdir()
        shutil.copy(FIX, self.d / "state.json"); self.io = FakeIO()
    def run_brief(self, agent, name, var, force=False):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = brief_cmd.run(self.d, agent, name, var, force=force, io=self.io)
        return rc, buf.getvalue()
    def all_vars(self, agent):
        ph = placeholders((BRIEFS / (agent + ".md")).read_text())
        builtin = brief_cmd.builtins(json.loads(FIX.read_text()), self.d, agent, "X")
        return ["%s=%s" % (p, "v-" + p) for p in ph if p not in builtin]

    def test_every_template_renders_with_builtins_plus_vars(self):
        for p in BRIEFS.glob("*.md"):
            rc, out = self.run_brief(p.stem, "T-" + p.stem, self.all_vars(p.stem))
            self.assertEqual(rc, 0, out)
            text = (self.d / "briefs" / ("T-" + p.stem + ".md")).read_text()
            self.assertEqual(placeholders(text), [], p.name); self.assertIn("MYD-1", text); self.assertIn("reports/T-" + p.stem + ".md", text)
            self.assertIn("AGENT: turnstile:" + p.stem, out); self.assertIn("PROMPT: Read and execute", out)
    def test_brief_refuses_unfilled_placeholder(self):
        rc, out = self.run_brief("tester", "ENV-S1", [])
        self.assertEqual(rc, 2); self.assertIn("MISSING placeholder", out)
        self.assertFalse((self.d / "briefs" / "ENV-S1.md").exists()); self.assertEqual(self.io.commits, [])
    def test_refuses_unknown_agent_and_existing_brief(self):
        self.assertEqual(self.run_brief("nobody", "N", [])[0], 2)
        self.run_brief("investigator", "I", self.all_vars("investigator"))
        rc, out = self.run_brief("investigator", "I", self.all_vars("investigator"))
        self.assertEqual(rc, 2); self.assertIn("--force", out)
        self.assertEqual(self.run_brief("investigator", "I", self.all_vars("investigator"), force=True)[0], 0)
    def test_builtins(self):
        b = brief_cmd.builtins(json.loads(FIX.read_text()), self.d, "tester", "ENV-S1")
        self.assertEqual(b["report_path"], "reports/ENV-S1.md"); self.assertEqual(b["variant"], "v1"); self.assertEqual(b["desk"], "desk05")
        self.assertEqual(b["env_recipe"], ""); self.assertEqual(b["github_org"], "pdffiller"); self.assertTrue(pathlib.Path(b["delivery"]).is_absolute())
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_brief -v`
Expected: FAIL — `No module named 'turnstile_cli.brief_cmd'`.

- [ ] **Step 3: Write the eight templates**

Shared head and tail (write them into each file; the middle differs):

Head (every template starts with this):

```markdown
# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.
```

Tail (every template ends with this):

```markdown
## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer. Poll ≤ 2 min, never silent > 5 min. Report at `{{report_path}}` per
`references/reports.md`; keep it updated as you go.
```

`briefs/implementer.md` (middle):

```markdown
## Ticket
{{ticket_key}} — {{ticket_title}}
Repo `{{repo}}` (org `{{github_org}}`), worktree `{{worktree}}`, base branch `{{base_branch}}`, branch `{{branch}}`.
Read the repo's `CLAUDE.md` and `{{repo_guides}}` first.

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

`briefs/reviewer.md` (middle):

```markdown
## PR
{{pr_id}} — {{ticket_key}} {{ticket_title}} · head `{{head}}` · base `{{base_branch}}` · worktree `{{worktree}}` · repo gate `{{gate}}` (run it via `{{gate_skill}}`).

## Ticket scope to check against
{{scope}}

## Invariants
{{invariants}}

## Design
{{figma_frames}}

## Earlier rounds
{{previous_reports}}

Report → `{{report_path}}` as `reports/REVIEW-<n>.md` § Review; include the gate run URL and `clean: true|false`.
```

`briefs/story-reviewer.md` (middle):

```markdown
## Story
{{story_id}} — {{story_title}} · epic branch `{{epic_branch}}` · stack top `{{stack_top_pr}}` @ `{{head}}` · worktree `{{worktree}}`.
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

`briefs/stack-step.md` (middle):

```markdown
## Stack (bottom → top)
{{stack}}

Changed PR: {{changed_pr}} (new head `{{head}}`). Repo `{{repo}}`, worktree `{{worktree}}`, gate `{{gate}}` via `{{gate_skill}}`, Copilot: {{copilot}}.

## Conflict policy
{{conflict_policy}}

Report → `{{report_path}}` § Stack with the table PR → old head → new head → CI → gate → Copilot and the `turnstile pass` lines.
```

`briefs/comments-handler.md` (middle):

```markdown
## PR
{{pr_id}} — {{ticket_key}} · head `{{head}}` · worktree `{{worktree}}` · gate `{{gate}}` via `{{gate_skill}}` · Copilot: {{copilot}}.

## Threads to handle
{{threads}}

## Context the reviewers may lack
{{context}}

Human threads: verdict + fix + draft reply only (per `references/slack.md` § Reply drafts). Copilot threads: fix or justify, resolve, re-request, loop.
Report → `{{report_path}}` § Comments.
```

`briefs/investigator.md` (middle):

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

`briefs/tester.md` (middle):

```markdown
## Story and environment
{{story_id}} — {{story_title}}. Mode: {{mode}} (`full` or `rerun`).
Environment: variant `{{variant}}`, desk `{{desk}}`, builds {{builds}}. Recipe: `{{env_recipe}}`. Credentials: {{credentials}} (from the lead; never commit them anywhere else).

## Test cases
{{test_cases}}

## Screens and states → Figma frames
{{figma_frames}}
Parity tolerance: {{tolerance}}. Copy source: {{copy_source}}.

## Evidence
`evidence/{{story_id}}/<case>/` per `references/evidence.md`.

Report → `{{report_path}}` § Env test; list every fail in the `turnstile bug add` form.
```

`briefs/deployer.md` (middle):

```markdown
## Targets
{{targets}}

Variant `{{variant}}` must keep monolith tag `{{monolith_tag}}` on every `ensure`. Desk `{{desk}}` via {{desk_workflow}}.

## Health checks
{{health_checks}}

Report → `{{report_path}}` § Deploy with run ids, build numbers and tags.
```

- [ ] **Step 4: Implement `brief_cmd.py`**

```python
# turnstile_cli/brief_cmd.py
import datetime, pathlib, re
from typing import List, Optional, Tuple
from . import state as st_mod, ledger
from .errors import TurnstileError

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"
BRIEFS = ROOT / "skills" / "turnstile" / "references" / "briefs"
PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")

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
    return {"epic_key": epic.get("key") or "", "github_org": epic.get("github_org") or "",
            "delivery": str(pathlib.Path(delivery).resolve()), "variant": env.get("variant") or "", "desk": env.get("desk") or "",
            "env_recipe": env.get("recipe") or "", "agent": agent, "brief_name": name,
            "brief_path": "briefs/%s.md" % name, "report_path": "reports/%s.md" % name,
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
    from .pass_cmd import IO
    io = io or IO()
    try:
        delivery = pathlib.Path(delivery)
        if not (AGENTS / (agent + ".md")).exists():
            raise TurnstileError("unknown agent %s (no agents/%s.md)" % (agent, agent))
        tpl = BRIEFS / (agent + ".md")
        if not tpl.exists():
            raise TurnstileError("no brief template for %s (%s)" % (agent, tpl))
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", name):
            raise TurnstileError("brief name must be a file stem like FIX-13223-token (got %r)" % name)
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
        summary = "brief %s for %s" % (name, agent)
        ledger.append(delivery, summary)
        if not no_commit:
            io.git_commit(delivery, "turnstile: " + summary)
        report = delivery / "reports" / (name + ".md")
        print("AGENT: turnstile:%s" % agent)
        print("BRIEF: %s" % out.resolve()); print("REPORT: %s" % report.resolve())
        print("PROMPT: Read and execute %s. Write your report to %s. Reply with at most 8 lines." % (out.resolve(), report.resolve()))
        print("OK " + summary)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
```

`main.py` — parser and dispatch:

```python
    br = sub.add_parser("brief", help="render an agent brief from its template (the dispatch helper)")
    br.add_argument("agent"); br.add_argument("name"); br.add_argument("--var", action="append", default=[], dest="vars")
    br.add_argument("--force", action="store_true"); br.add_argument("--no-commit", action="store_true")
```

```python
        if a.cmd == "brief":
            from .brief_cmd import run as brief_run
            return brief_run(delivery, a.agent, a.name, a.vars, force=a.force, no_commit=a.no_commit)
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest tests.test_brief -v && python3 -m unittest discover -s tests 2>&1 | tail -1`
Expected: PASS; suite `OK`.

- [ ] **Step 6: Commit**

```bash
git add skills/turnstile/references/briefs turnstile_cli/brief_cmd.py turnstile_cli/main.py tests/test_brief.py
git commit -m "feat(brief): brief templates per agent and the turnstile brief renderer for dispatch"
```

---

### Task 8: The skill — `SKILL.md` and references (lifecycle, kickoff, PR body, Slack, reports, evidence, env recipe)

**Files:**
- Create: `skills/turnstile/SKILL.md`, `skills/turnstile/references/lifecycle.md`, `skills/turnstile/references/kickoff.md`, `skills/turnstile/references/pr-body.md`, `skills/turnstile/references/slack.md`, `skills/turnstile/references/reports.md`, `skills/turnstile/references/evidence.md`, `skills/turnstile/references/env/pdffiller-dev.md`, `tests/test_skill_files.py`

**Interfaces:**
- Consumes: CLI commands from Tasks 1–7 and plan 1 (`init`, `status`, `pass`, `approve`, `jira-synced`, `plan-submitted`, `brief`, `bug`, `render-board`, `reconcile`); agent names from Task 6; brief placeholders from Task 7.
- Produces: the orchestrator's procedure for `init`, `status`, `pass`, `dispatch`, `story-gate`, `plan`; the reference texts the agents and briefs cite by path.

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
        text = (SKILL / "SKILL.md").read_text()
        fm = parse_frontmatter(text)
        self.assertEqual(fm["name"], "turnstile"); self.assertTrue(len(fm["description"]) > 60)
        self.assertLessEqual(len(text.splitlines()), 160)
        for cmd in ["## init", "## status", "## pass", "## dispatch", "## story-gate", "## plan"]:
            self.assertIn(cmd, text)
        for cli in ["turnstile status", "turnstile pass", "turnstile approve", "turnstile jira-synced", "turnstile plan-submitted",
                    "turnstile brief", "turnstile bug add", "turnstile bug set"]:
            self.assertIn(cli, text)
    def test_every_reference_link_exists(self):
        for md in [SKILL / "SKILL.md"] + list(REFS.glob("*.md")) + list((REFS / "env").glob("*.md")):
            for rel in re.findall(r"`(references/[A-Za-z0-9_./-]+\.md)`", md.read_text()):
                self.assertTrue((SKILL / rel).exists(), "%s links missing %s" % (md.name, rel))
    def test_reference_files_present(self):
        for name in ["lifecycle.md", "kickoff.md", "plan.md", "pr-body.md", "slack.md", "reports.md", "evidence.md", "env/pdffiller-dev.md"]:
            self.assertTrue((REFS / name).exists(), name)
    def test_lifecycle_tables_cover_every_state(self):
        text = (REFS / "lifecycle.md").read_text()
        for s in ["DEV", "AI_REVIEW", "READY", "ON_HUMAN_REVIEW", "REWORK", "APPROVED", "MERGED",
                  "PLANNED", "IN_PROGRESS", "INTEGRATION_REVIEW", "ENV_TESTING", "DONE"]:
            self.assertIn("**" + s + "**", text)
    def test_slack_review_request_format(self):
        text = (REFS / "slack.md").read_text()
        for line in ["Reviewers: <@", "PR: <https://github.com/", "Task description:", "Estimate review: +"]:
            self.assertIn(line, text)
        self.assertIn("Locales:", text)
    def test_reports_has_a_template_per_agent(self):
        text = (REFS / "reports.md").read_text()
        for h in ["## Ticket", "## Review", "## Story review", "## Stack", "## Comments", "## Investigation", "## Env test", "## Deploy"]:
            self.assertIn(h, text)
    def test_env_recipe_pdffiller(self):
        text = (REFS / "env" / "pdffiller-dev.md").read_text()
        for needle in ["www.pdffillers.com", "jsfillerEnv=desk", "Forward-Variant-pdffiller", "developer_access", "md5", ".pdffillers.com",
                       "never as a request header", "x-server-name", "isolated headless", "+tester"]:
            self.assertIn(needle, text)
        self.assertNotIn("qwe123", text)
```

- [ ] **Step 2: Run, expect failure**

Run: `python3 -m unittest tests.test_skill_files -v`
Expected: FAIL — `FileNotFoundError` on `SKILL.md`.

- [ ] **Step 3: Write `skills/turnstile/SKILL.md`**

````markdown
---
name: turnstile
description: Run or resume the delivery of a multi-repo epic through turnstile's evidence-gated flow — PR states DEV→AI_REVIEW→READY→ON_HUMAN_REVIEW→APPROVED→MERGED, story gates (integration review, environment testing), role agents, lead approvals. Use at the start of every orchestrator session and whenever a PR, story, review, deploy or bug changes state; also on "status", "send for review", "start story", "re-plan", "init epic".
---

# Turnstile

The state is `delivery/state.json` in the knowledge worktree (found through `.turnstile` in the workspace). Only
`turnstile` commands write it. You sequence; the CLI enforces. Every state change is one command, and its side effects
(ledger, board, commit, Jira instruction) happen inside that command — never "later".

Read once per session: `references/lifecycle.md` (DoR/DoD per state with the exact `turnstile pass` call).
Templates: `references/pr-body.md`, `references/slack.md`, `references/reports.md`, `references/evidence.md`; env recipes
in `references/env/`. Chat with the lead in the language the workspace `CLAUDE.md` names.

## Rules that never bend

- Send, reply to humans, `ready`, reviewer requests, merge, start of a story: only after the lead's word for that exact
  action. Record the word with `turnstile approve <ah-id>` (the id comes from `turnstile status`); hooks block the rest.
- A question from the lead is a question: answer and propose, act on a command.
- Delegate all implementation, review, testing and deployment to the `turnstile:*` agents (see `## dispatch`). Never
  read a diff or run a suite yourself; your context is for coordination.
- After every agent report, record its facts (`pass`, `bug`, `approve`, `jira-synced`) before you reply to the lead.

## status

`turnstile status` → reconcile against GitHub + plan state + next actions + what awaits humans. Run it first in every
session and after every batch of agent reports. For each discrepancy it prints the `turnstile pass` to run; run the
unambiguous ones, show the lead the rest. `turnstile reconcile --json` when you need the raw list.

## pass (one transition)

`turnstile pass pr <repo#n> <STATE> --head <sha> [evidence flags]` / `turnstile pass story <S> <STATE> [flags]` — flags per
`references/lifecycle.md`. On `OK` the command prints `JIRA: <ticket> → <status>` (perform it through the Atlassian MCP
`transitionJiraIssue`, then `turnstile jira-synced <repo#n> "<status>"`) and `BOARD: publish <path> → <artifact url>`
(publish the file with the Artifact tool and that `url`; a first publish loads the `artifact-capabilities` skill and
declares `db` + `user`, then stores the url in `state.json` through `turnstile init --board-url` or the migration).
On `MISSING …` nothing was written: get the evidence, do not argue with the gate.

## init (once per epic)

1. `turnstile init --epic <KEY> --workitem <slug> --knowledge <path to the pdffiller-knowledge clone> --lead <login>
   --github-org <org> --repo <name:base:epic_branch:slack:gate:copilot[:branch_prefix]>… --variant <v> --desk <d>` —
   creates the knowledge worktree on `epic/<key>`, `delivery/`, `.turnstile`, the workspace `CLAUDE.md`.
2. Kick-off analysis per `references/kickoff.md`: read the decomposition, PRD, design, test plan and every repo's
   `CLAUDE.md`; write `delivery/plan.md` from its template (stories, merge order, human-review units ≈ 400 logic lines,
   test-case map, Figma frames, human inputs, env slots) including the `turnstile-stories` JSON block.
3. `turnstile plan-submitted` → stories enter `PLANNED`; show the lead the plan summary; wait for the word;
   `turnstile approve <ah-id>`. Without it no story leaves `PLANNED` and no agent starts.
4. `turnstile pass story S1 IN_PROGRESS`, then dispatch implementers per the merge order.

## dispatch <agent> <brief>

1. `turnstile brief <agent> <NAME> --var k=v …` — renders `references/briefs/<agent>.md`; it refuses unfilled
   placeholders, so pass every agent-specific variable (listed at the top of each template). Names: `<KEY>` for
   tickets, `REVIEW-<n>`, `STORY-<S>-review`, `ENV-<S>`, `FIX-<n>-<slug>`, `STACK-<date>`, `COMMENTS-<n>`,
   `INVESTIGATE-<slug>`, `DEPLOY-<slug>-<date>`.
2. Launch with the Agent tool: `subagent_type: "turnstile:<agent>"`, prompt = the `PROMPT:` line the command printed.
   Agents: implementer (sonnet), reviewer (opus xhigh), story-reviewer (fable), stack-step, comments-handler,
   investigator, tester, deployer. One agent per task; several agents in parallel only across different repos or
   stories.
3. On return: read the ≤ 8-line reply (the report is in `reports/`), record the facts with `turnstile pass` / `bug`,
   and only then reply to the lead. Never paste agent output into the chat.

## story-gate <S>

Pre-condition: every PR of `S` is ≥ `READY` and the stack top is deployed to the story's slot (dispatch `deployer`).
1. `turnstile pass story S INTEGRATION_REVIEW --build <build>`.
2. dispatch `story-reviewer` (`STORY-S-review`); findings → `implementer` briefs on the ticket PRs → their gates re-run
   (`pass pr … AI_REVIEW --head <new>`, `reviewer`, `pass pr … READY`); loop until the report says `clean: true`.
3. `turnstile pass story S ENV_TESTING --report reports/STORY-S-review.md --head <stack top> --rounds <r>`.
4. dispatch `tester` (`ENV-S`, mode `full`); each fail → `turnstile bug add --story S --title … --source "tester <date>"
   --figma <node>`; fixes via `implementer`; `turnstile bug set bNN --state testing` after the deploy; `tester` in mode
   `rerun` for the failed cases, then one full run.
5. `turnstile pass story S DONE --report reports/ENV-S.md --cases-pass <n> --cases-fail 0 --figma-parity pass`.
6. Report to the lead per `references/slack.md` § Story report and **stop**: the next story, and the sending of this
   story's human-review units, wait for the word (then `approve`, `pass pr … ON_HUMAN_REVIEW --slack … --approved …`).

## plan (re-plan after a scope change)

Edit `delivery/plan.md` (stories, units, map) with the rationale in `decisions.md`; `turnstile plan-submitted`; the lead
approves again (`approve <ah-id>`). Stories already past `PLANNED` keep their state and evidence; a story cannot be
dropped once started.

## Bugs on the board

Viewers with write access change a bug's status in the board's dropdown; it lands in the artifact db (`bugs/<id>`), not
in `state.json`. At `status` time read the `bugs` collection with `ArtifactData` and fold changes back with
`turnstile bug set <id> --state <s>` so git stays the source of truth.
````

- [ ] **Step 4: Write `references/lifecycle.md`**

```markdown
# Lifecycle — DoR / DoD and the command per transition

Evidence always carries the head it was produced for; a push voids it (`turnstile status` shows the drop).

## PR states

| State | DoR (entry) | DoD (exit) | Command that enters it |
|---|---|---|---|
| **DEV** | ticket in the approved `plan.md`; brief exists; branch from the epic/story branch | draft PR into the epic/story branch; CI green; signed commits, no trailer; body per `references/pr-body.md` | migration or `turnstile pass pr <id> DEV --reason "<why back>"` |
| **AI_REVIEW** | DEV done | **loop until clean on one head**: `deep_review.clean` + `gate.result = pass` + `copilot.open_threads = 0` (where `repo.copilot`), all for `head == pr.head`; CI green | `turnstile pass pr <id> AI_REVIEW --head <sha> --ci success` |
| **READY** | AI_REVIEW done | head unchanged; `blocked_by` null or MERGED for sending | `turnstile pass pr <id> READY --head <sha> --deep-review reports/REVIEW-<n>.md --rounds <r> --gate <gate>:pass:<run-url> [--copilot 0]` → creates `awaiting_human: send` |
| **ON_HUMAN_REVIEW** | lead approved the send (`turnstile approve <ah-id>`); message posted per `references/slack.md` | ≥ 1 approval; 0 unresolved human threads | `turnstile pass pr <id> ON_HUMAN_REVIEW --head <sha> --slack <permalink> --reviewers a,b --approved <ah-id>` → Jira On Review |
| **REWORK** | push after send, new human thread, or changes requested | fixes pushed; gate + Copilot green on the new head (deep review is not repeated); draft replies approved by the lead and posted | `turnstile pass pr <id> REWORK --reason "<thread id or push>"`; back with `ON_HUMAN_REVIEW` as above (new permalink = the reply) |
| **APPROVED** | ON_HUMAN_REVIEW done | lead merged | `turnstile pass pr <id> APPROVED --approvals a,b --open-threads 0` → `awaiting_human: merge` |
| **MERGED** | squash-merged by the lead | — | `turnstile pass pr <id> MERGED --merged-sha <sha>` → Jira On Hold; unblocks dependants |

AI review order on one head: deep review (`reviewer` agent) → repo gate (`pdf-review`, `pr-review`, `review`, `run-lint`
+ `run-unit-tests`) → Copilot (where connected). Any finding → fix → re-run deep review **and** gate.

## Story states

| State | DoD | Command |
|---|---|---|
| **PLANNED** | listed in the approved `plan.md` | `turnstile plan-submitted` + `turnstile approve <ah-id>` |
| **IN_PROGRESS** | every ticket PR ≥ READY, stacked or merged into the story branch; stack top deployed to the slot | `turnstile pass story <S> IN_PROGRESS` (needs the plan approved and `after` stories DONE, or `--reason` from the lead) |
| **INTEGRATION_REVIEW** | whole-story diff reviewed by `story-reviewer` until clean; fixes in the ticket PRs with gates re-run | `turnstile pass story <S> INTEGRATION_REVIEW --build <build>` |
| **ENV_TESTING** | `tester` ran every case + Figma parity; 0 open discrepancies; fails → bugs → fixed → re-run → full run | `turnstile pass story <S> ENV_TESTING --report reports/STORY-<S>-review.md --head <sha> --rounds <r>` |
| **DONE** | lead received the report and said "send" | `turnstile pass story <S> DONE --report reports/ENV-<S>.md --cases-pass <n> --cases-fail 0 --figma-parity pass` |

Stop rule: after DONE nothing starts until the lead says so; parallel stories (`parallel_with` or the lead's word) each
have their own branch, stack, slot and tester run.

## Jira mapping (printed by `pass`, performed through the Atlassian MCP, recorded with `jira-synced`)

DEV / AI_REVIEW / READY → In progress · ON_HUMAN_REVIEW / REWORK / APPROVED → On Review · MERGED → On Hold.
```

- [ ] **Step 5: Write `references/kickoff.md`**

```markdown
# Kick-off analysis (once, before any code)

Output: `delivery/plan.md` from `references/plan.md`. Approval gate: `turnstile plan-submitted` → lead → `turnstile approve`.

1. Read, in this order, and list each in plan.md § 1: the decomposition (ticket map, decisions), the PRD, the design
   brief + Figma file (collect `file:node` per screen and state), the test plan (case ids, preconditions), every
   target repo's `CLAUDE.md` / `AGENTS.md` / testing guide, the precedent epic if the decomposition names one.
2. Stories: business slices testable and releasable on their own. If the decomposition is by repo or by wave, define
   the slices yourself and write the rationale. For each: tickets, repos, `after` (must be DONE first),
   `parallel_with` (explicitly allowed), env slot (variant / desk), Figma frames, test cases.
3. Merge order per story and the story branch each ticket PR stacks into; file overlaps between parallel stories and
   which merge order resolves them.
4. Human-review units: ~400 lines of logic each (tests and markup excluded). A story goes to humans as its story PR or
   2–3 PRs split by subsystem (state + API / UI / tests). Estimate from the ticket scopes; refine after the PRs exist.
5. Inputs from humans (PM report, design copy, credentials) with the date each is needed and which story it blocks.
6. Fill the `turnstile-stories` JSON block (§ 7 of the template) — ids `S1…`, keys `title, tickets, repos, after,
   parallel_with, test_cases, figma, env_slot, human_review_units`. `plan-submitted` validates it.
7. Show the lead: the story table, the unit table, the open inputs. Wait. Record the answer in `decisions.md`.

Re-plan (`## plan` in SKILL.md): same steps on the delta; never drop a started story.
```

- [ ] **Step 6: Write `references/pr-body.md`**

```markdown
# PR body template

Title: `<type>(<scope>): [<KEY>] <summary>` (conventional type, Jira key). Draft, base = the epic or story branch.

```
<one-line intro: what the PR adds and for whom>

Scope:
- `<identifier>` — <what changed>
- `<identifier>` — <what changed>

Tech requirements:
- <tests added / commands green>

Related: <Jira url>
```

Rules: no generated-with footer; no checklist boilerplate; the body ends with the `Related:` line. Update `Scope:` when a
later fix changes behaviour. Never comment on the PR.
```

- [ ] **Step 7: Write `references/slack.md`**

```markdown
# Slack messages

Channels and reviewer logins come from `state.json` (`epic.repos.<repo>.slack`, `prs.<id>.evidence.human.reviewers`)
and the PR's `reviewRequests` (`gh pr view <n> --repo <org>/<repo> --json reviewRequests --jq '.reviewRequests[].login'`,
people only — skip team entries). Resolve a login to a Slack user through the Slack MCP user search by name/email;
never guess. Every message is composed, shown to the lead, and sent only after the lead's word is recorded
(`turnstile approve <ah-id>`); the Slack guard blocks everything else.

## Review request (front repos)

```
Reviewers: <@USER_ID_1> <@USER_ID_2>
PR: <https://github.com/<org>/<repo>/pull/<n>>
Task description: <PR title with the conventional prefix stripped>
Estimate review: +<additions>-<deletions>
```

- Wrap every URL in angle brackets (Slack's auto-linker otherwise swallows the newline).
- A front PR and its paired locales PR go in **one** message with a `Locales: <url>` line under `PR:`; the estimate sums both.
- One repo per message; several repos → consecutive messages.
- Search the channel for the PR URL first; if a request exists, reply in that thread instead.

## Review request (backend / bare link channels)

```
<https://github.com/<org>/<repo>/pull/<n>>
```

## Reply drafts (human threads; written by comments-handler, posted only with the lead's word)

```
<thread id> — <reviewer>: <one-line restatement of the point>
→ <what was done / why not>, commit `<sha>` (or: declined because <code-level reason>)
```

## Story report to the lead (after `pass story <S> DONE`)

```
Story <S> "<title>": integration review clean (<r> rounds, reports/STORY-<S>-review.md), env test <pass>/<total> cases,
Figma parity pass (reports/ENV-<S>.md), bugs fixed: <list>. Units ready to send: <unit → PRs>. Waiting for your word.
```

## Deploy / build announcement

Only when the lead asks; format per the product's release skill (`front-release`), not here.
```

- [ ] **Step 8: Write `references/reports.md`**

```markdown
# Report templates (one file per agent run under `delivery/reports/`)

Every report starts with: `# <TYPE> — <subject> — <date>` and a `Status:` line (`DONE` / `DONE_WITH_CONCERNS` /
`NEEDS_CONTEXT` / `BLOCKED`), then the sections below. Paste real command output summary lines, never paraphrase them.

## Ticket
`reports/<KEY>.md` — PR URL · branch · head · base · files changed (list) · commands run → summary lines · Copilot
threads (id → verdict → commit) · signatures verified · deviations from the brief · open questions · backlog notes.

## Review
`reports/REVIEW-<n>.md` — PR · head · base · worktree · rounds (table round → head → findings count) · findings table
(# · severity · file:line · claim · verification · fix · status) · gate run URL + verdict · fixes applied by the reviewer
(commits) · `clean: true|false`.

## Story review
`reports/STORY-<S>-review.md` — stack top SHA · PRs in order · rounds · findings table with a `target PR` column ·
cross-ticket seams checked · test cases traced · `clean: true|false`.

## Stack
`reports/STACK-<date>.md` — table PR → old head → new head → CI → gate → Copilot · conflicts (files, how resolved) ·
`turnstile pass` lines to run.

## Comments
`reports/COMMENTS-<n>.md` — thread table (id · author · human/Copilot · verdict · commit · resolved?) · Copilot loop
rounds · draft replies (per `references/slack.md`) · new head · gate state.

## Investigation
`reports/INVESTIGATE-<slug>.md` — question · hypotheses · evidence per hypothesis (file:line / command → output) ·
answer · recommendation + cost if wrong · not verified.

## Env test
`reports/ENV-<S>.md` — environment (variant, desk, builds, routing proof: `x-server-name`, static host) · case table
(case · verdict · evidence path · note) · parity table (screen/state · Figma node · max deviation px / colour · verdict)
· fails as `turnstile bug add --story <S> --title "…" --source "tester <date>" --figma <node>` lines ·
`not_testable_here` reasons · totals (pass / fail / not_testable_here).

## Deploy
`reports/DEPLOY-<slug>-<date>.md` — table repo → ref → workflow run → build / image tag → health check result ·
variant tag kept · traps hit.
```

- [ ] **Step 9: Write `references/evidence.md`**

```markdown
# Evidence layout (tester)

```
delivery/evidence/<story>/<case>/
  env.png        # environment screenshot, viewport per the Figma frame, full state reached by the case
  figma.png      # Figma get_screenshot of the frame/node named in plan.md
  dom.json       # measured values: {selector: {x, y, w, h, font, size, lineHeight, color, bg, gap, padding}} + Figma expected
  diff.md        # deviations beyond tolerance (element · property · expected · observed · delta) and copy mismatches
```

One folder per case; a case with several states uses `<case>/<state>/`. Keep images under 1 MB (PNG, no retina
scaling unless the frame is retina). Paths in `ENV-<S>.md` are relative to `delivery/`. Evidence is committed with the
report (`turnstile pass story … DONE` commits `delivery/`).
```

- [ ] **Step 10: Write `references/env/pdffiller-dev.md`**

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
  reload.
- Negative control when in doubt: a nonsense variant name must change the response; identical output means routing
  is not happening.

## Browser
Use an isolated headless browser (Playwright) with its own profile / user-data dir under the scratchpad. Never the user's
visible Chrome, never a shared devtools MCP session. Viewport per the Figma frame; device scale factor 1 unless the
frame is retina.

## Builds
Front: `static.version` of each app on the variant (deployer records it). Monolith: variant image tag (`DEV_ECR_TAG`).
Record both in the `ENV-<S>.md` header.
```

- [ ] **Step 11: Run the tests**

Run: `python3 -m unittest tests.test_skill_files -v && python3 -m unittest discover -s tests 2>&1 | tail -1`
Expected: PASS; suite `OK`. If `test_skill_md_short…` fails on the line count, move prose to a reference, do not delete a command section.

- [ ] **Step 12: Commit**

```bash
git add skills/turnstile/SKILL.md skills/turnstile/references tests/test_skill_files.py
git commit -m "feat(skill): turnstile SKILL.md with init/status/pass/dispatch/story-gate/plan and the references"
```

---

### Task 9: README, version 0.2.0, tag

**Files:**
- Modify: `README.md` (install line; usage grows with the new commands; agents + skill sections; fix `state.yaml` → `state.json`), `turnstile_cli/__init__.py` (`0.2.0`), `.claude-plugin/plugin.json` (`0.2.0`), `tests/test_cli_smoke.py` (expect `turnstile 0.2.0`)

- [ ] **Step 1: Update the smoke test first**

In `tests/test_cli_smoke.py` replace both `"turnstile 0.1.0"` with `"turnstile 0.2.0"`.

Run: `python3 -m unittest tests.test_cli_smoke -v` — Expected: FAIL (still 0.1.0).

- [ ] **Step 2: Bump the version**

`turnstile_cli/__init__.py`: `__version__ = "0.2.0"`. `.claude-plugin/plugin.json`: `"version": "0.2.0"`.

- [ ] **Step 3: README**

Replace `- `state.yaml` — a single source…` with `- `state.json` — a single source of truth for the epic, in git, readable by any session or person.`

Add after the "Why it exists" paragraph:

```markdown
## Install

```
claude plugin marketplace add davepylypenko/turnstile
claude plugin install turnstile
```

(Until a marketplace entry exists: clone the repo and run `claude --plugin-dir <path>`.)
```

Replace the `## Usage (core)` block with:

````markdown
## Usage

```
turnstile init --epic MYD-16538 --workitem pdfd-429-l2f-editor-funnel --knowledge ../pdffiller-knowledge \
  --lead davyd.pylypenko --github-org pdffiller \
  --repo jsfiller:develop:epic_myd-16538_l2f-funnel:CCGLRULNR:pdf-review:false \
  --repo pdffiller:master:l2f-funnel:G8S415WG6:pdf-review:true:l2f-funnel-myd- --variant l2f-funnel --desk desk05
# write delivery/plan.md (skill: references/kickoff.md), then
turnstile plan-submitted && turnstile approve ah-1            # the lead approved the plan
turnstile pass story S1 IN_PROGRESS
turnstile brief implementer MYD-18075 --var ticket_key=MYD-18075 --var ... # then Agent(turnstile:implementer, PROMPT line)
turnstile status                                              # reconcile with GitHub + where we are
turnstile pass pr jsfiller#13222 AI_REVIEW --head d2583e9b --ci success
turnstile pass pr jsfiller#13222 READY --head d2583e9b --deep-review reports/REVIEW-13222.md --rounds 3 --gate pdf-review:pass:<run-url>
turnstile approve ah-3                                        # the lead said "send"
turnstile pass pr jsfiller#13222 ON_HUMAN_REVIEW --head d2583e9b --slack <permalink> --reviewers isachivka --approved ah-3
turnstile jira-synced jsfiller#13222 "On Review"
turnstile pass story S1 INTEGRATION_REVIEW --build 173111     # story gate: story-reviewer → tester → DONE
turnstile bug add --story S1 --title "Share visible on published Create form" --source "tester 2026-10-13" --figma KOew:9098-41434
turnstile bug set b01 --state testing
turnstile render-board
```

Exit code 2 and `MISSING …` lines mean the turnstile did not turn: nothing was written.

Commands: `init`, `plan-submitted`, `pass` (the writer of transitions), `approve`, `jira-synced`, `brief` (renders an
agent brief), `bug add|set`, `reconcile` (read-only, `--json`), `status`, `render-board`.

Skill `turnstile` (`skills/turnstile/SKILL.md`): `init`, `status`, `pass`, `dispatch <agent> <brief>`, `story-gate <S>`,
`plan`. References: lifecycle (DoR/DoD), kick-off, brief/PR/Slack/report/evidence templates, env recipes.

Agents (`agents/`): implementer (sonnet), reviewer (opus, xhigh), story-reviewer (fable), stack-step, comments-handler,
investigator, tester (opus, Figma parity), deployer (sonnet). Launch as `turnstile:<name>` with a brief from `turnstile brief`.
````

Keep the existing Hooks and Tests paragraphs.

- [ ] **Step 4: Verify everything**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -3 && claude plugin validate . 2>&1 | tail -3 && scripts/turnstile --version`
Expected: `OK` with ≥ 98 tests (52 from plan 1 + 46 added here); validate without errors; `turnstile 0.2.0`.

- [ ] **Step 5: Commit and tag**

```bash
git add README.md turnstile_cli/__init__.py .claude-plugin/plugin.json tests/test_cli_smoke.py
git commit -m "docs: usage for init, brief, bug, skill and agents; version 0.2.0"
git tag v0.2.0
```

---

## Self-review

- **Spec coverage.** §2.1 artefacts (`plan.md`, `decisions.md`, `briefs/`, `reports/`, `evidence/`, shrunken workspace `CLAUDE.md`) → Task 1. §2.2 `epic.repos.*.gate` + the secondary `gate_check`, `epic.github_org`, `epic.plan` → Tasks 1, 3, 2. §4.1 kick-off + lead approval → Task 1 (template), Task 2 (gate), Task 8 (`kickoff.md`, `## init`). §4.2 story gates sequencing → Task 8 `## story-gate`, evidence flags unchanged from plan 1. §5 skill commands `init / status / pass / dispatch / story-gate / plan` → Task 8; their CLI helpers → Tasks 1, 2, 4, 7. §5 `render-board` "bugs tab with db-backed dropdowns, legend with the Jira mapping" → Task 5. §7 agents table (models, efforts, does/cannot, common rules) → Task 6; §7.1 tester procedure → Task 6 `tester.md` + Task 8 `evidence.md`, `env/pdffiller-dev.md`. §8 packaging (`skills/turnstile/SKILL.md`, `references/`, `agents/`, `templates/state.json`, `templates/CLAUDE.md.workspace`, personal items out of the plugin) → Tasks 1, 6, 8, 9. §10 "agents: one dry run each on a throwaway branch" is a manual step for plan 3's cut-over, not automatable here — noted, not a task. Spec §12 open question 3 (create Jira story issues at `init`): decided **no** — `plan.md` references tickets only; nothing in this plan calls Jira from `init`.
- **Placeholders.** None of the forbidden phrases; the eight agent files and eight brief templates are written in full; the `<paste the common block here>` marker in Task 6 refers to the block defined two steps above in the same task, and the test asserts the block's sentinel lines in every file. `tests/test_skill_files.py` carries its own `parse_frontmatter` instead of importing across test modules (discovery with `-s tests` imports them as top-level modules).
- **Type consistency.** `pass_cmd.IO` (`git_commit`, `renderer`) is the IO for `plan_cmd`, `bug_cmd`, `brief_cmd`; `init_cmd` has its own `InitIO.git` because it works in the knowledge clone before a `delivery/` exists. `rules.check_story(..., plan_missing=None)` matches the `pass_cmd` call. `github.gate_status(f, repo_cfg)` is called with the same `repo` dict `reconcile.compare` already has. Brief placeholders used in Task 8's `## dispatch` text are the ones Task 7's templates declare; `builtins` keys (`report_path`, `epic_key`, `delivery`, `variant`, `desk`, `env_recipe`, `github_org`, `agent`, `brief_name`, `brief_path`, `today`) are the only unlisted placeholders the templates may use. Agent names in Task 6 = brief template stems in Task 7 = the `turnstile:<name>` launch names in Task 8 (test in Task 7 pins the equality). Bug states in Task 4 (`STATES`) = `BUG_STATES` in Task 5 = the `--state` choices in `main.py`.
- **Review Focus.** 1 → Task 1 `test_init_reuses_worktree_and_refuses_existing_state`; 2 → Task 2 `test_edited_plan_voids_approval`; 3 → Task 3 `test_success_needs_both` + `test_gate_red_when_check_run_fails`; 4 → Task 7 `test_brief_refuses_unfilled_placeholder`; 5 → Task 4 `test_bug_add_validates_story_and_pr`.

## Decisions taken while planning (not in the spec)

- The plan approval is an `awaiting_human` entry of `type: decision`, `payload: plan.md`, approved with the existing `turnstile approve`; the gate also pins the digest of `plan.md`, so an edited plan needs a new submission and approval. No `--reason` override.
- Stories enter `state.json` from a machine-readable ```` ```json turnstile-stories ```` block in `plan.md` (the prose tables stay for humans) rather than from Markdown parsing.
- `dispatch` is a skill procedure backed by `turnstile brief` (template rendering with hard failure on unfilled placeholders); the agent launch itself stays with the Agent tool.
- Bugs get their own writers (`turnstile bug add|set`) because the story gate needs tester fails recorded in `state.json` and `pass` has no place for them.
- The secondary CheckRun name lives in `epic.repos.<repo>.gate_check` (set automatically for `pdf-review` by `init`), so repos without the CI gate keep a single StatusContext.
- Credentials never enter the plugin or git: the tester brief takes them as `--var credentials=…` at dispatch time (the brief file itself is committed, so the lead decides what to put there — flagged as an open point for plan 3).
