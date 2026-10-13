# Turnstile core — implementation plan (plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dependency-free CLI `turnstile` that owns the epic state file, refuses transitions without evidence for the current head, performs every side effect of a transition (ledger, board, git commit, Jira instruction), detects drift against GitHub, plus the plugin hooks that physically block forbidden actions.

**Architecture:** One Python package `turnstile_cli` (stdlib only, Python 3.9+) behind a shim `scripts/turnstile`. Pure functions decide (`rules.py`, `reconcile.py`); thin adapters touch the world (`gh`, `git`, filesystem) and are injectable so tests never call the network. The state is `delivery/state.json`; the workspace root holds a `.turnstile` file pointing at the delivery directory so hooks and the CLI find the state from any cwd.

**Tech Stack:** Python 3.9 standard library (`json`, `argparse`, `subprocess`, `unittest`, `dataclasses`), `gh` CLI for GitHub, Claude Code plugin hooks (`hooks/hooks.json`, shell + Python).

**Spec:** `docs/superpowers/specs/2026-10-13-turnstile-design.md` (sections 2, 3, 4.2, 5, 6, 10).

Plans 2 and 3 (not here): skill `SKILL.md` + references + agents + templates + `init`/`dispatch`/`story-gate`; migration of MYD-16538 and vendoring into `pdffiller-knowledge`.

## Global Constraints

- Python 3.9 syntax only: no `match`, no `X | Y` types, no `list[str]` in annotations at runtime (use `typing.List`).
- No third-party packages. Tests run with `python3 -m unittest discover -s tests -v`.
- State file is JSON, 2-space indent, `sort_keys=True`, trailing newline. Written only by `turnstile pass` (and `turnstile init` in plan 2).
- PR ids are `<repo>#<number>` (e.g. `jsfiller#13222`); story ids are `S<n>`; evidence always carries `head` (full 40-char SHA or ≥8-char prefix; comparison is prefix-safe: the shorter one must be a prefix of the longer).
- PR states: `DEV, AI_REVIEW, READY, ON_HUMAN_REVIEW, REWORK, APPROVED, MERGED`. Story states: `PLANNED, IN_PROGRESS, INTEGRATION_REVIEW, ENV_TESTING, DONE`.
- Jira mapping (printed, never performed by the CLI): `DEV/AI_REVIEW/READY → In progress`, `ON_HUMAN_REVIEW/REWORK/APPROVED → On Review`, `MERGED → On Hold`.
- Commit messages in this repo: conventional (`feat(rules): ...`), no `Co-Authored-By` trailer.
- All CLI output is plain text; the last line of a successful `pass` is a one-line summary starting with `OK `; failures exit 2 with lines starting `MISSING ` and no file is written.

## Review Focus

1. **Evidence with a head that is a prefix of the PR head** (short SHA from a report) must count as the same head; a head that merely shares the first 6 characters by coincidence must not. Test in Task 3 (`test_same_head_prefix`, `test_same_head_too_short`).
2. **Repo without Copilot** (`copilot: false`): READY must not demand Copilot evidence; a repo *with* Copilot must. Test in Task 3.
3. **A push after the send** must void `human.sent_head` even when all AI evidence is re-recorded for the new head: reconcile proposes REWORK, and `pass … ON_HUMAN_REVIEW` for the new head needs a new permalink and approval id. Tests in Task 3 and Task 8.
4. **Concurrent edits by two people**: `pass` must refuse when the state file on disk changed since it was read (`mtime`/hash check) instead of silently overwriting. Test in Task 6 (`test_pass_refuses_stale_file`).
5. **Hooks must fail closed on a broken state file**: if `.turnstile` or `state.json` is missing or unparsable, the Slack guard blocks the send with a clear message rather than allowing it. Test in Task 10.

---

## File structure

```
turnstile/
  .claude-plugin/plugin.json          # plugin manifest (name, version, hooks path)
  scripts/turnstile                    # bash shim → python3 -m turnstile_cli "$@"
  turnstile_cli/__init__.py            # __version__
  turnstile_cli/paths.py               # find workspace root (.turnstile) and delivery dir
  turnstile_cli/state.py               # load/save state.json, lookups, file-change guard
  turnstile_cli/rules.py               # states, head comparison, DoD/DoR checks (pure)
  turnstile_cli/ledger.py              # append a ledger line
  turnstile_cli/board.py               # render board.html from state (template + JSON injection)
  turnstile_cli/github.py              # gh graphql adapter → PrFacts
  turnstile_cli/reconcile.py           # compare state vs PrFacts → proposals (pure)
  turnstile_cli/pass_cmd.py            # apply a transition with all side effects
  turnstile_cli/main.py                # argparse: pass | reconcile | render-board | status
  templates/board.html                 # board page; JS renders from window.TURNSTILE_STATE
  hooks/hooks.json                     # PreToolUse/PostToolUse wiring
  hooks/guard_bash.py                  # blocks forbidden git/gh/prometey commands
  hooks/guard_slack.py                 # blocks Slack sends without an approved awaiting_human entry
  hooks/guard_state_edit.py            # warns on manual state.json edits
  tests/fixtures/state_min.json        # one repo, two PRs, one story
  tests/fixtures/gh_pr_13222.json      # recorded gh graphql response
  tests/test_*.py
```

---

### Task 1: Scaffolding, shim, manifest, fixture

**Files:**
- Create: `.claude-plugin/plugin.json`, `scripts/turnstile`, `turnstile_cli/__init__.py`, `turnstile_cli/main.py`, `tests/__init__.py`, `tests/fixtures/state_min.json`, `tests/test_cli_smoke.py`

**Interfaces:**
- Produces: `python3 -m turnstile_cli --version` prints `turnstile 0.1.0`; `scripts/turnstile` forwards args; fixture `state_min.json` used by every later test.

- [x] **Step 1: Write the failing smoke test**

```python
# tests/test_cli_smoke.py
import subprocess, sys, unittest, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

class CliSmoke(unittest.TestCase):
    def test_version(self):
        out = subprocess.run([sys.executable, "-m", "turnstile_cli", "--version"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "turnstile 0.1.0")

    def test_shim_forwards(self):
        out = subprocess.run([str(ROOT / "scripts" / "turnstile"), "--version"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "turnstile 0.1.0")
```

- [x] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest tests.test_cli_smoke -v`
Expected: FAIL (`No module named turnstile_cli`).

- [x] **Step 3: Create the package, main, shim, manifest**

```python
# turnstile_cli/__init__.py
__version__ = "0.1.0"
```

```python
# turnstile_cli/main.py
import argparse, sys
from . import __version__

def build_parser():
    p = argparse.ArgumentParser(prog="turnstile", description="Evidence-gated delivery. No ticket, no entry.")
    p.add_argument("--version", action="version", version="turnstile " + __version__)
    p.add_argument("--delivery", help="path to the delivery dir (default: resolved from .turnstile)")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("status", help="reconcile + where we are")
    return p, sub

def main(argv=None):
    parser, _ = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 0
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

```python
# turnstile_cli/__main__.py
from .main import main
import sys
sys.exit(main())
```

```bash
# scripts/turnstile
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 -c "import sys; sys.path.insert(0, '$HERE'); from turnstile_cli.main import main; sys.exit(main())" "$@"
```
Run `chmod +x scripts/turnstile`.

```json
// .claude-plugin/plugin.json
{
  "name": "turnstile",
  "version": "0.1.0",
  "description": "Evidence-gated delivery for AI agent teams. No ticket, no entry.",
  "author": { "name": "Davyd Pylypenko" },
  "hooks": "./hooks/hooks.json"
}
```

Fixture (used by every later task; keep exactly these ids):

```json
// tests/fixtures/state_min.json
{
  "epic": {
    "key": "MYD-1",
    "workitem": "demo",
    "roles": { "lead": "lead@example.com" },
    "repos": {
      "jsfiller": { "base": "develop", "epic_branch": "epic_myd-1", "slack": "C1", "gate": "pdf-review", "copilot": false },
      "docs-platform": { "base": "main", "epic_branch": "epic_myd-1", "slack": "C2", "gate": "pdf-review", "copilot": true }
    },
    "board": { "artifact_url": "https://claude.ai/artifact/x" },
    "environment": { "variant": "v1", "desk": "desk05" }
  },
  "stories": {
    "S1": { "title": "Header", "tickets": ["MYD-10", "MYD-11"], "repos": ["jsfiller"], "after": [], "parallel_with": [],
            "state": "IN_PROGRESS", "test_cases": ["TP-1"], "figma": [], "env_slot": { "variant": "v1" },
            "human_review_units": [], "evidence": {} }
  },
  "prs": {
    "jsfiller#1": { "ticket": "MYD-10", "story": "S1", "branch": "feature/MYD-10", "base": "epic_myd-1",
                    "state": "AI_REVIEW", "head": "aaaaaaaa11111111", "blocked_by": null,
                    "evidence": { "ci": { "head": "aaaaaaaa11111111", "status": "success" } },
                    "jira": { "status": "In progress", "synced": true }, "next_action": "" },
    "docs-platform#2": { "ticket": "MYD-11", "story": "S1", "branch": "feature/MYD-11", "base": "epic_myd-1",
                    "state": "DEV", "head": "bbbbbbbb22222222", "blocked_by": "jsfiller#1",
                    "evidence": {}, "jira": { "status": "To Do", "synced": false }, "next_action": "" }
  },
  "bugs": [],
  "awaiting_human": []
}
```

- [x] **Step 4: Run the smoke test**

Run: `python3 -m unittest tests.test_cli_smoke -v`
Expected: 2 tests PASS.

- [x] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(cli): package scaffold, shim, plugin manifest, test fixture"
```

---

### Task 2: Paths and state I/O

**Files:**
- Create: `turnstile_cli/paths.py`, `turnstile_cli/state.py`, `tests/test_state.py`

**Interfaces:**
- Produces:
  - `paths.find_delivery(start: Path, override: Optional[str]) -> Path` — walks up from `start` to a `.turnstile` file whose single line is the delivery dir (absolute or relative to that file); `override` wins; raises `TurnstileError` when nothing is found.
  - `state.State` dataclass: `data: dict`, `path: Path`, `loaded_digest: str`.
  - `state.load(path) -> State`, `state.save(st: State) -> None` (refuses when the on-disk digest differs from `loaded_digest`; raises `StaleStateError`), `state.pr(st, pr_id) -> dict`, `state.story(st, sid) -> dict`, `state.repo_cfg(st, pr_id) -> dict` (repo part before `#`), `state.digest(text) -> str` (sha256 hex).
  - `errors.TurnstileError`, `errors.StaleStateError` in `turnstile_cli/errors.py`.

- [x] **Step 1: Write the failing tests**

```python
# tests/test_state.py
import json, pathlib, shutil, tempfile, unittest
from turnstile_cli import state, paths
from turnstile_cli.errors import TurnstileError, StaleStateError

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"

class StateIO(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.delivery = self.tmp / "delivery"; self.delivery.mkdir()
        shutil.copy(FIX, self.delivery / "state.json")
        (self.tmp / ".turnstile").write_text("delivery\n")

    def test_find_delivery_walks_up(self):
        nested = self.tmp / "a" / "b"; nested.mkdir(parents=True)
        self.assertEqual(paths.find_delivery(nested, None), self.delivery.resolve())

    def test_find_delivery_override_and_missing(self):
        self.assertEqual(paths.find_delivery(self.tmp, str(self.delivery)), self.delivery.resolve())
        with self.assertRaises(TurnstileError):
            paths.find_delivery(pathlib.Path(tempfile.mkdtemp()), None)

    def test_round_trip_sorted_keys(self):
        st = state.load(self.delivery / "state.json")
        st.data["prs"]["jsfiller#1"]["state"] = "READY"
        state.save(st)
        text = (self.delivery / "state.json").read_text()
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text)["prs"]["jsfiller#1"]["state"], "READY")
        self.assertLess(text.index('"awaiting_human"'), text.index('"epic"'))  # sorted keys

    def test_save_refuses_stale_file(self):
        st = state.load(self.delivery / "state.json")
        (self.delivery / "state.json").write_text("{}\n")
        with self.assertRaises(StaleStateError):
            state.save(st)

    def test_lookups(self):
        st = state.load(self.delivery / "state.json")
        self.assertEqual(state.pr(st, "jsfiller#1")["ticket"], "MYD-10")
        self.assertEqual(state.story(st, "S1")["title"], "Header")
        self.assertFalse(state.repo_cfg(st, "jsfiller#1")["copilot"])
        with self.assertRaises(TurnstileError):
            state.pr(st, "jsfiller#999")
```

- [x] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_state -v` — Expected: FAIL (import errors).

- [x] **Step 3: Implement**

```python
# turnstile_cli/errors.py
class TurnstileError(Exception):
    """User-facing failure; message is printed, exit code 2."""

class StaleStateError(TurnstileError):
    """state.json changed on disk since it was loaded."""
```

```python
# turnstile_cli/paths.py
import pathlib
from typing import Optional
from .errors import TurnstileError

MARKER = ".turnstile"

def find_delivery(start: pathlib.Path, override: Optional[str]) -> pathlib.Path:
    if override:
        p = pathlib.Path(override).expanduser().resolve()
        if not (p / "state.json").exists():
            raise TurnstileError("no state.json in %s" % p)
        return p
    cur = start.resolve()
    for d in [cur] + list(cur.parents):
        marker = d / MARKER
        if marker.exists():
            target = marker.read_text().strip().splitlines()[0]
            p = (d / target).resolve() if not pathlib.Path(target).is_absolute() else pathlib.Path(target)
            return p
    raise TurnstileError("no %s found from %s upward; pass --delivery <dir>" % (MARKER, cur))
```

```python
# turnstile_cli/state.py
import hashlib, json, pathlib
from dataclasses import dataclass
from .errors import TurnstileError, StaleStateError

@dataclass
class State:
    data: dict
    path: pathlib.Path
    loaded_digest: str

def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def load(path: pathlib.Path) -> State:
    path = pathlib.Path(path)
    if not path.exists():
        raise TurnstileError("state file not found: %s" % path)
    text = path.read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise TurnstileError("state file is not valid JSON: %s (%s)" % (path, e))
    return State(data=data, path=path, loaded_digest=digest(text))

def dumps(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

def save(st: State) -> None:
    current = st.path.read_text() if st.path.exists() else ""
    if digest(current) != st.loaded_digest:
        raise StaleStateError("%s changed on disk since it was loaded; re-run the command" % st.path)
    text = dumps(st.data)
    st.path.write_text(text)
    st.loaded_digest = digest(text)

def pr(st: State, pr_id: str) -> dict:
    try:
        return st.data["prs"][pr_id]
    except KeyError:
        raise TurnstileError("unknown PR %s" % pr_id)

def story(st: State, sid: str) -> dict:
    try:
        return st.data["stories"][sid]
    except KeyError:
        raise TurnstileError("unknown story %s" % sid)

def repo_cfg(st: State, pr_id: str) -> dict:
    repo = pr_id.split("#", 1)[0]
    try:
        return st.data["epic"]["repos"][repo]
    except KeyError:
        raise TurnstileError("repo %s is not configured in epic.repos" % repo)
```

- [x] **Step 4: Run tests** — `python3 -m unittest tests.test_state -v` — Expected: 5 PASS.

- [x] **Step 5: Commit** — `git add -A && git commit -m "feat(state): delivery discovery, JSON state I/O with stale-file guard"`

---

### Task 3: PR transition rules (pure)

**Files:**
- Create: `turnstile_cli/rules.py`, `tests/test_rules_pr.py`

**Interfaces:**
- Produces:
  - constants `PR_STATES`, `STORY_STATES`, `JIRA_FOR_PR_STATE: Dict[str, str]`.
  - `same_head(a: str, b: str) -> bool` — both ≥8 chars, shorter is a prefix of longer.
  - `check_pr(pr: dict, target: str, repo_cfg: dict, prs: dict) -> List[str]` — returns the list of `MISSING …` reasons; empty list means allowed. `prs` is the whole `state["prs"]` (for `blocked_by`).
  - `next_action_pr(pr: dict, repo_cfg: dict) -> str`.

Rules encoded (from spec §3), checked in this order; every evidence head must `same_head` the PR head:

| target | requires |
|---|---|
| DEV | from `None` only (creation; handled by plan 2 `init`), or any state when `--reason` is given (re-open) — here: allowed from `REWORK`/`AI_REVIEW` with reason |
| AI_REVIEW | from DEV/REWORK/READY/ON_HUMAN_REVIEW (void); `ci.status==success` on head |
| READY | from AI_REVIEW; `ci` success; `deep_review.clean` true; `gate.result==pass` with `gate.name==repo_cfg.gate` (skip when repo has no gate: `gate` null); `copilot.open_threads==0` when `repo_cfg.copilot`; all heads match |
| ON_HUMAN_REVIEW | from READY or REWORK; READY-conditions still hold; `human.slack_permalink`, `human.sent_head==head`, `human.approved_by_lead` (the awaiting id) present; `blocked_by` null or that PR `MERGED` |
| REWORK | from ON_HUMAN_REVIEW/APPROVED with `--reason` |
| APPROVED | from ON_HUMAN_REVIEW; `human.approvals` non-empty; `human.open_threads==0`; `sent_head==head` |
| MERGED | from APPROVED (or ON_HUMAN_REVIEW when reconcile reports merged) ; `merged_sha` given |

- [x] **Step 1: Write the failing tests**

```python
# tests/test_rules_pr.py
import copy, json, pathlib, unittest
from turnstile_cli import rules

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())
H = "aaaaaaaa11111111"

def pr_with(**ev):
    p = copy.deepcopy(FIX["prs"]["jsfiller#1"])
    p["evidence"].update(ev)
    return p

FULL = dict(
    ci={"head": H, "status": "success"},
    deep_review={"head": H, "report": "reports/R.md", "rounds": 2, "clean": True},
    gate={"name": "pdf-review", "head": H, "result": "pass", "run": "u"},
)

class Heads(unittest.TestCase):
    def test_same_head_prefix(self):
        self.assertTrue(rules.same_head("aaaaaaaa", "aaaaaaaa11111111"))
    def test_same_head_too_short(self):
        self.assertFalse(rules.same_head("aaaaaa", "aaaaaa11111111"))
    def test_different(self):
        self.assertFalse(rules.same_head("aaaaaaaa1", "aaaaaaaa2"))

class ToReady(unittest.TestCase):
    repo = FIX["epic"]["repos"]["jsfiller"]
    def test_ok(self):
        self.assertEqual(rules.check_pr(pr_with(**FULL), "READY", self.repo, FIX["prs"]), [])
    def test_missing_gate(self):
        ev = dict(FULL); del ev["gate"]
        out = rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])
        self.assertTrue(any("gate" in m for m in out))
    def test_stale_deep_review_head(self):
        ev = dict(FULL); ev["deep_review"] = dict(FULL["deep_review"], head="cccccccc33333333")
        out = rules.check_pr(pr_with(**ev), "READY", self.repo, FIX["prs"])
        self.assertTrue(any("deep_review" in m and "head" in m for m in out))
    def test_copilot_required_only_when_enabled(self):
        repo_cp = dict(self.repo, copilot=True)
        self.assertTrue(any("copilot" in m for m in rules.check_pr(pr_with(**FULL), "READY", repo_cp, FIX["prs"])))
        ok = rules.check_pr(pr_with(copilot={"head": H, "open_threads": 0}, **FULL), "READY", repo_cp, FIX["prs"])
        self.assertEqual(ok, [])
    def test_wrong_source_state(self):
        p = pr_with(**FULL); p["state"] = "DEV"
        self.assertTrue(any("from DEV" in m for m in rules.check_pr(p, "READY", self.repo, FIX["prs"])))

class ToHuman(unittest.TestCase):
    repo = FIX["epic"]["repos"]["jsfiller"]
    def ready(self):
        p = pr_with(**FULL); p["state"] = "READY"; return p
    def test_needs_permalink_and_approval(self):
        out = rules.check_pr(self.ready(), "ON_HUMAN_REVIEW", self.repo, FIX["prs"])
        self.assertTrue(any("slack_permalink" in m for m in out))
        self.assertTrue(any("approved" in m for m in out))
    def test_blocked_by_unmerged(self):
        p = self.ready(); p["blocked_by"] = "docs-platform#2"
        p["evidence"]["human"] = {"head": H, "slack_permalink": "u", "sent_head": H, "approved": "ah-1"}
        out = rules.check_pr(p, "ON_HUMAN_REVIEW", self.repo, FIX["prs"])
        self.assertTrue(any("blocked_by" in m for m in out))
    def test_push_after_send_voids(self):
        p = self.ready(); p["state"] = "ON_HUMAN_REVIEW"; p["head"] = "dddddddd44444444"
        p["evidence"]["human"] = {"head": H, "slack_permalink": "u", "sent_head": H, "approved": "ah-1"}
        out = rules.check_pr(p, "APPROVED", self.repo, FIX["prs"])
        self.assertTrue(any("sent_head" in m for m in out))
        self.assertEqual(rules.check_pr(p, "REWORK", self.repo, FIX["prs"], reason="push after send"), [])

class NextAction(unittest.TestCase):
    def test_strings(self):
        repo = FIX["epic"]["repos"]["jsfiller"]
        p = pr_with(); self.assertIn("deep review", rules.next_action_pr(p, repo))
        p = pr_with(**FULL); p["state"] = "READY"; self.assertIn("lead", rules.next_action_pr(p, repo))
```

- [x] **Step 2: Run to verify failure** — `python3 -m unittest tests.test_rules_pr -v` — Expected: FAIL (no module `rules`).

- [x] **Step 3: Implement**

```python
# turnstile_cli/rules.py
from typing import Dict, List, Optional

PR_STATES = ["DEV", "AI_REVIEW", "READY", "ON_HUMAN_REVIEW", "REWORK", "APPROVED", "MERGED"]
STORY_STATES = ["PLANNED", "IN_PROGRESS", "INTEGRATION_REVIEW", "ENV_TESTING", "DONE"]
JIRA_FOR_PR_STATE = {"DEV": "In progress", "AI_REVIEW": "In progress", "READY": "In progress",
                     "ON_HUMAN_REVIEW": "On Review", "REWORK": "On Review", "APPROVED": "On Review",
                     "MERGED": "On Hold"}

PR_FROM = {
    "DEV": ["AI_REVIEW", "REWORK"],
    "AI_REVIEW": ["DEV", "REWORK", "READY", "ON_HUMAN_REVIEW"],
    "READY": ["AI_REVIEW"],
    "ON_HUMAN_REVIEW": ["READY", "REWORK"],
    "REWORK": ["ON_HUMAN_REVIEW", "APPROVED"],
    "APPROVED": ["ON_HUMAN_REVIEW"],
    "MERGED": ["APPROVED", "ON_HUMAN_REVIEW"],
}

def same_head(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b or len(a) < 8 or len(b) < 8:
        return False
    a, b = a.lower(), b.lower()
    return a.startswith(b) if len(a) >= len(b) else b.startswith(a)

def _ev(pr: dict, key: str) -> Optional[dict]:
    return (pr.get("evidence") or {}).get(key)

def _need_head(pr: dict, key: str, out: List[str]) -> Optional[dict]:
    ev = _ev(pr, key)
    if ev is None:
        out.append("MISSING evidence.%s" % key)
        return None
    if not same_head(ev.get("head"), pr.get("head")):
        out.append("MISSING evidence.%s for current head %s (has %s)" % (key, pr.get("head"), ev.get("head")))
    return ev

def _ai_review_done(pr: dict, repo_cfg: dict, out: List[str]) -> None:
    ci = _need_head(pr, "ci", out)
    if ci and ci.get("status") != "success":
        out.append("MISSING evidence.ci.status == success (has %s)" % ci.get("status"))
    dr = _need_head(pr, "deep_review", out)
    if dr and not dr.get("clean"):
        out.append("MISSING evidence.deep_review.clean == true")
    gate_name = repo_cfg.get("gate")
    if gate_name:
        g = _need_head(pr, "gate", out)
        if g:
            if g.get("name") != gate_name:
                out.append("MISSING evidence.gate.name == %s (has %s)" % (gate_name, g.get("name")))
            if g.get("result") != "pass":
                out.append("MISSING evidence.gate.result == pass (has %s)" % g.get("result"))
    if repo_cfg.get("copilot"):
        c = _need_head(pr, "copilot", out)
        if c and c.get("open_threads", 1) != 0:
            out.append("MISSING evidence.copilot.open_threads == 0 (has %s)" % c.get("open_threads"))

def check_pr(pr: dict, target: str, repo_cfg: dict, prs: Dict[str, dict], reason: Optional[str] = None) -> List[str]:
    out: List[str] = []
    if target not in PR_STATES:
        return ["MISSING valid target state (one of %s)" % ", ".join(PR_STATES)]
    src = pr.get("state")
    if src not in PR_FROM[target]:
        return ["MISSING allowed transition: %s from %s (allowed from %s)" % (target, src, ", ".join(PR_FROM[target]))]
    if target == "DEV" or target == "REWORK":
        if not reason:
            out.append("MISSING --reason for %s" % target)
        return out
    if target == "AI_REVIEW":
        ci = _need_head(pr, "ci", out)
        if ci and ci.get("status") != "success":
            out.append("MISSING evidence.ci.status == success")
        return out
    if target == "READY":
        _ai_review_done(pr, repo_cfg, out)
        return out
    if target == "ON_HUMAN_REVIEW":
        _ai_review_done(pr, repo_cfg, out)
        h = _ev(pr, "human") or {}
        if not h.get("slack_permalink"):
            out.append("MISSING evidence.human.slack_permalink")
        if not same_head(h.get("sent_head"), pr.get("head")):
            out.append("MISSING evidence.human.sent_head == current head")
        if not h.get("approved"):
            out.append("MISSING evidence.human.approved (awaiting_human id the lead approved)")
        b = pr.get("blocked_by")
        if b and (prs.get(b) or {}).get("state") != "MERGED":
            out.append("MISSING blocked_by %s to be MERGED before sending (is %s)" % (b, (prs.get(b) or {}).get("state")))
        return out
    if target == "APPROVED":
        h = _ev(pr, "human") or {}
        if not same_head(h.get("sent_head"), pr.get("head")):
            out.append("MISSING evidence.human.sent_head == current head (push after send → REWORK)")
        if not h.get("approvals"):
            out.append("MISSING evidence.human.approvals (at least one)")
        if h.get("open_threads", 1) != 0:
            out.append("MISSING evidence.human.open_threads == 0 (has %s)" % h.get("open_threads"))
        return out
    if target == "MERGED":
        if not pr.get("merged_sha"):
            out.append("MISSING merged_sha")
        return out
    return out

def next_action_pr(pr: dict, repo_cfg: dict) -> str:
    s = pr.get("state")
    if s == "DEV":
        return "open draft PR, get CI green, then pass AI_REVIEW"
    if s == "AI_REVIEW":
        missing = check_pr(pr, "READY", repo_cfg, {})
        if any("deep_review" in m for m in missing):
            return "run deep review (reviewer agent) on head %s" % pr.get("head")
        if any("gate" in m for m in missing):
            return "run repo gate %s on head %s" % (repo_cfg.get("gate"), pr.get("head"))
        if any("copilot" in m for m in missing):
            return "request Copilot review, close its threads"
        return "pass READY"
    if s == "READY":
        return "wait for the lead's word to send" + (" (blocked by %s)" % pr["blocked_by"] if pr.get("blocked_by") else "")
    if s == "ON_HUMAN_REVIEW":
        return "wait for human approval; reconcile for threads/pushes"
    if s == "REWORK":
        return "fix, re-run gate/copilot on the new head, draft replies, get the lead's word, then pass ON_HUMAN_REVIEW"
    if s == "APPROVED":
        return "wait for the lead to merge"
    return "done"
```

- [x] **Step 4: Run tests** — `python3 -m unittest tests.test_rules_pr -v` — Expected: all PASS.

- [x] **Step 5: Commit** — `git add -A && git commit -m "feat(rules): PR transition DoR/DoD checks with head-bound evidence"`

---

### Task 4: Story transition rules (pure)

**Files:**
- Modify: `turnstile_cli/rules.py` (append)
- Create: `tests/test_rules_story.py`

**Interfaces:**
- Produces: `check_story(story: dict, target: str, prs: Dict[str, dict], stories: Dict[str, dict], reason: Optional[str]=None) -> List[str]`; `next_action_story(story: dict, prs) -> str`.

Rules (spec §4.2): `PLANNED→IN_PROGRESS` needs `after` stories DONE (unless `reason` = lead override, recorded); `IN_PROGRESS→INTEGRATION_REVIEW` needs every PR with `story==id` in state ≥ READY (READY, ON_HUMAN_REVIEW, REWORK, APPROVED, MERGED) and `evidence.deploy.build` present; `INTEGRATION_REVIEW→ENV_TESTING` needs `evidence.integration_review.clean` and its `head`; `ENV_TESTING→DONE` needs `evidence.env_test` with `cases.fail == 0` and `figma_parity == "pass"`; `DONE` is terminal; any state → `IN_PROGRESS` with `reason` (reopen).

- [x] **Step 1: Write the failing tests**

```python
# tests/test_rules_story.py
import copy, json, pathlib, unittest
from turnstile_cli import rules

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())

def story(state, **ev):
    s = copy.deepcopy(FIX["stories"]["S1"]); s["state"] = state; s["evidence"].update(ev); return s

def prs(*states):
    out = copy.deepcopy(FIX["prs"])
    for pid, st in zip(["jsfiller#1", "docs-platform#2"], states):
        out[pid]["state"] = st
    return out

class StoryRules(unittest.TestCase):
    def test_to_integration_review_needs_all_prs_ready_and_deploy(self):
        out = rules.check_story(story("IN_PROGRESS"), "INTEGRATION_REVIEW", prs("READY", "DEV"), FIX["stories"])
        self.assertTrue(any("docs-platform#2" in m for m in out))
        self.assertTrue(any("deploy" in m for m in out))
        ok = rules.check_story(story("IN_PROGRESS", deploy={"build": "173111"}), "INTEGRATION_REVIEW",
                               prs("READY", "MERGED"), FIX["stories"])
        self.assertEqual(ok, [])
    def test_to_env_testing(self):
        out = rules.check_story(story("INTEGRATION_REVIEW"), "ENV_TESTING", prs("READY", "READY"), FIX["stories"])
        self.assertTrue(any("integration_review" in m for m in out))
    def test_to_done_requires_clean_env_test(self):
        s = story("ENV_TESTING", env_test={"report": "r", "cases": {"pass": 3, "fail": 1}, "figma_parity": "fail"})
        out = rules.check_story(s, "DONE", prs("READY", "READY"), FIX["stories"])
        self.assertTrue(any("fail" in m for m in out))
        self.assertTrue(any("figma" in m for m in out))
    def test_planned_waits_for_after_unless_reason(self):
        stories = {"S0": {"state": "IN_PROGRESS"}, "S1": story("PLANNED")}
        s = story("PLANNED"); s["after"] = ["S0"]
        self.assertTrue(rules.check_story(s, "IN_PROGRESS", {}, stories))
        self.assertEqual(rules.check_story(s, "IN_PROGRESS", {}, stories, reason="lead: run in parallel"), [])
```

- [x] **Step 2: Run to verify failure** — Expected: AttributeError `check_story`.

- [x] **Step 3: Implement (append to rules.py)**

```python
STORY_FROM = {
    "PLANNED": [],
    "IN_PROGRESS": ["PLANNED", "INTEGRATION_REVIEW", "ENV_TESTING", "DONE"],
    "INTEGRATION_REVIEW": ["IN_PROGRESS", "ENV_TESTING"],
    "ENV_TESTING": ["INTEGRATION_REVIEW"],
    "DONE": ["ENV_TESTING"],
}
PR_AT_LEAST_READY = ["READY", "ON_HUMAN_REVIEW", "REWORK", "APPROVED", "MERGED"]

def check_story(story: dict, target: str, prs: Dict[str, dict], stories: Dict[str, dict], reason: Optional[str] = None) -> List[str]:
    out: List[str] = []
    if target not in STORY_STATES:
        return ["MISSING valid target state (one of %s)" % ", ".join(STORY_STATES)]
    src = story.get("state")
    if src not in STORY_FROM[target]:
        return ["MISSING allowed transition: %s from %s" % (target, src)]
    sid = story.get("id") or ""
    if target == "IN_PROGRESS":
        if src != "PLANNED" and not reason:
            out.append("MISSING --reason to reopen a story")
        for dep in story.get("after") or []:
            if (stories.get(dep) or {}).get("state") != "DONE" and not reason:
                out.append("MISSING story %s to be DONE first (or --reason for a lead override)" % dep)
        return out
    if target == "INTEGRATION_REVIEW":
        for pid, p in prs.items():
            if p.get("story") == (story.get("id") or sid) or p.get("story") == story.get("_id"):
                pass
        mine = [pid for pid, p in prs.items() if p.get("story") == story.get("_id")]
        for pid in mine:
            if prs[pid].get("state") not in PR_AT_LEAST_READY:
                out.append("MISSING PR %s at least READY (is %s)" % (pid, prs[pid].get("state")))
        if not (story.get("evidence") or {}).get("deploy", {}).get("build"):
            out.append("MISSING evidence.deploy.build (stack top deployed to the story env slot)")
        return out
    if target == "ENV_TESTING":
        ir = (story.get("evidence") or {}).get("integration_review") or {}
        if not ir.get("clean") or not ir.get("head"):
            out.append("MISSING evidence.integration_review.clean with head")
        return out
    if target == "DONE":
        et = (story.get("evidence") or {}).get("env_test") or {}
        cases = et.get("cases") or {}
        if not et.get("report"):
            out.append("MISSING evidence.env_test.report")
        if cases.get("fail", 1) != 0:
            out.append("MISSING evidence.env_test.cases.fail == 0 (has %s)" % cases.get("fail"))
        if et.get("figma_parity") != "pass":
            out.append("MISSING evidence.env_test.figma_parity == pass (has %s)" % et.get("figma_parity"))
        return out
    return out

def next_action_story(story: dict, prs: Dict[str, dict]) -> str:
    s = story.get("state")
    return {"PLANNED": "wait for the lead to start it",
            "IN_PROGRESS": "bring every PR to READY, deploy the stack top, then pass INTEGRATION_REVIEW",
            "INTEGRATION_REVIEW": "run the story-reviewer agent until clean, then pass ENV_TESTING",
            "ENV_TESTING": "run the tester agent; fix bugs; re-run; then pass DONE",
            "DONE": "wait for the lead's word to send the story's units to humans"}.get(s, "")
```

Note for the implementer: `check_story` matches PRs by `p["story"] == story["_id"]`; `pass_cmd` (Task 6) injects `story["_id"] = sid` before calling and strips it before saving. Remove the dead `for pid, p in prs.items(): … pass` loop above — it is not needed; keep only the `mine` computation.

- [x] **Step 4: Run** — `python3 -m unittest tests.test_rules_story -v` — Expected: PASS. (In the tests, set `s["_id"] = "S1"` inside the `story()` helper so the PR match works: add `s["_id"] = "S1"` after the deepcopy.)

- [x] **Step 5: Commit** — `git add -A && git commit -m "feat(rules): story transition checks"`

---

### Task 5: Ledger

**Files:**
- Create: `turnstile_cli/ledger.py`, `tests/test_ledger.py`

**Interfaces:**
- Produces: `ledger.append(delivery: Path, line: str, when: Optional[datetime]=None) -> None` writes `- <YYYY-MM-DD HH:MM UTC> <line>\n` to `delivery/ledger.md`, creating the file with a `# Ledger` header when absent.

- [x] **Step 1: Failing test**

```python
# tests/test_ledger.py
import datetime, pathlib, tempfile, unittest
from turnstile_cli import ledger

class Ledger(unittest.TestCase):
    def test_creates_and_appends(self):
        d = pathlib.Path(tempfile.mkdtemp())
        when = datetime.datetime(2026, 10, 13, 12, 0)
        ledger.append(d, "pass jsfiller#1 AI_REVIEW → READY (head aaaaaaaa)", when)
        ledger.append(d, "second", when)
        text = (d / "ledger.md").read_text()
        self.assertTrue(text.startswith("# Ledger\n"))
        self.assertIn("- 2026-10-13 12:00 UTC pass jsfiller#1 AI_REVIEW → READY (head aaaaaaaa)\n", text)
        self.assertTrue(text.endswith("- 2026-10-13 12:00 UTC second\n"))
```

- [x] **Step 2: Run, expect failure.**

- [x] **Step 3: Implement**

```python
# turnstile_cli/ledger.py
import datetime, pathlib
from typing import Optional

def append(delivery: pathlib.Path, line: str, when: Optional[datetime.datetime] = None) -> None:
    path = pathlib.Path(delivery) / "ledger.md"
    when = when or datetime.datetime.utcnow()
    if not path.exists():
        path.write_text("# Ledger\n\n")
    with path.open("a") as f:
        f.write("- %s UTC %s\n" % (when.strftime("%Y-%m-%d %H:%M"), line))
```

- [x] **Step 4: Run, expect PASS.** — [ ] **Step 5: Commit** `git commit -am "feat(ledger): append-only event log"` (after `git add`).

---

### Task 6: `pass` command (transition with side effects)

**Files:**
- Create: `turnstile_cli/pass_cmd.py`, `tests/test_pass.py`
- Modify: `turnstile_cli/main.py` (wire subcommand)

**Interfaces:**
- Consumes: `state.*`, `rules.*`, `ledger.append`, `board.render` (Task 7; until then `pass_cmd` calls `board.render` through an injectable `renderer` defaulting to a no-op when `templates/board.html` is missing).
- Produces:
  - `pass_cmd.run(delivery: Path, kind: str, ident: str, target: str, opts: Options, io: IO) -> int` where `Options` is a dataclass with every CLI flag (`head, ci, deep_review, rounds, gate, copilot, slack, reviewers, approved, approvals, open_threads, reason, merged_sha, report, build, cases_pass, cases_fail, figma_parity, no_commit`) and `IO` has `git_commit(delivery, message) -> None` and `renderer(state_data, delivery) -> None` (both injectable).
  - CLI: `turnstile pass pr <id> <STATE> [flags]`, `turnstile pass story <id> <STATE> [flags]`.
  - On success prints: `JIRA: <ticket> → <status>` (PRs only, when the mapped status differs from `pr.jira.status`), `BOARD: publish <delivery>/board.html` and last line `OK pr <id> <from> → <to> (head <h>)`; sets `pr.jira.synced = false` when a Jira move is required (the skill flips it to true after the MCP call via `turnstile jira-synced <id>`, a tiny subcommand added here).
  - On failure prints every `MISSING …` line and returns 2; nothing written.

Evidence update semantics (`--head` is required for every PR evidence flag; `pr.head` is updated to `--head` when given):

| flag | writes |
|---|---|
| `--ci success|failure` | `evidence.ci = {head, status}` |
| `--deep-review <report> --rounds N [--not-clean]` | `evidence.deep_review = {head, report, rounds, clean}` |
| `--gate <name>:<pass|fail>[:<run-url>]` | `evidence.gate = {name, head, result, run}` |
| `--copilot <open_threads>` | `evidence.copilot = {head, open_threads}` |
| `--slack <permalink> --reviewers a,b --approved <ah-id>` | `evidence.human = {head, slack_permalink, reviewers, sent_head: head, approved, open_threads: 0, approvals: [], sent_at}` and marks that `awaiting_human` entry `approved_at` |
| `--approvals a,b --open-threads N` | updates `evidence.human.approvals/open_threads` |
| `--merged-sha <sha>` | `pr.merged_sha` |
| story: `--build`, `--report`, `--rounds`, `--cases-pass/--cases-fail`, `--figma-parity pass|fail`, `--head` | `evidence.deploy/integration_review/env_test` accordingly |

After a successful PR transition the command also: recomputes `next_action` for every PR and story; when target is `MERGED`, appends to the ledger which PRs had `blocked_by == ident`; when target is `READY`, appends an `awaiting_human` entry `{id: "ah-<n>", owner: "lead", type: "send", pr: ident, created_at, payload: null, approved_at: null}` if none open for that PR.

- [x] **Step 1: Failing tests**

```python
# tests/test_pass.py
import json, pathlib, shutil, tempfile, unittest
from turnstile_cli import pass_cmd, state

FIX = pathlib.Path(__file__).parent / "fixtures" / "state_min.json"
H = "aaaaaaaa11111111"

class FakeIO:
    def __init__(self):
        self.commits = []; self.renders = 0
    def git_commit(self, delivery, message): self.commits.append(message)
    def renderer(self, data, delivery): self.renders += 1

def opts(**kw):
    o = pass_cmd.Options(); [setattr(o, k, v) for k, v in kw.items()]; return o

class PassCmd(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp()) / "delivery"; self.d.mkdir()
        shutil.copy(FIX, self.d / "state.json"); self.io = FakeIO()
        (self.d / "reports").mkdir(); (self.d / "reports" / "R.md").write_text("ok")

    def test_refuses_without_evidence_and_writes_nothing(self):
        before = (self.d / "state.json").read_text()
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "READY", opts(head=H), self.io)
        self.assertEqual(rc, 2)
        self.assertEqual((self.d / "state.json").read_text(), before)
        self.assertEqual(self.io.commits, [])

    def test_ready_records_evidence_ledger_board_commit_and_awaiting(self):
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "READY",
                          opts(head=H, ci="success", deep_review="reports/R.md", rounds=2, gate="pdf-review:pass:u"), self.io)
        self.assertEqual(rc, 0)
        data = json.loads((self.d / "state.json").read_text())
        pr = data["prs"]["jsfiller#1"]
        self.assertEqual(pr["state"], "READY")
        self.assertEqual(pr["evidence"]["gate"], {"name": "pdf-review", "head": H, "result": "pass", "run": "u"})
        self.assertEqual(pr["next_action"], "wait for the lead's word to send")
        self.assertEqual(data["awaiting_human"][0]["type"], "send")
        self.assertIn("READY", (self.d / "ledger.md").read_text())
        self.assertEqual(self.io.renders, 1)
        self.assertEqual(len(self.io.commits), 1)

    def test_head_change_voids_old_evidence(self):
        pass_cmd.run(self.d, "pr", "jsfiller#1", "READY",
                     opts(head=H, ci="success", deep_review="reports/R.md", rounds=1, gate="pdf-review:pass"), self.io)
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "AI_REVIEW", opts(head="eeeeeeee55555555", ci="success"), self.io)
        self.assertEqual(rc, 0)
        rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "READY", opts(head="eeeeeeee55555555"), self.io)
        self.assertEqual(rc, 2)  # deep_review and gate are for the old head

    def test_jira_instruction_printed_and_synced_flag(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pass_cmd.run(self.d, "pr", "docs-platform#2", "AI_REVIEW", opts(head="bbbbbbbb22222222", ci="success"), self.io)
        self.assertIn("JIRA: MYD-11 → In progress", buf.getvalue())
        data = json.loads((self.d / "state.json").read_text())
        self.assertFalse(data["prs"]["docs-platform#2"]["jira"]["synced"])
        rc = pass_cmd.jira_synced(self.d, "docs-platform#2", "In progress", self.io)
        self.assertEqual(rc, 0)
        data = json.loads((self.d / "state.json").read_text())
        self.assertEqual(data["prs"]["docs-platform#2"]["jira"], {"status": "In progress", "synced": True})

    def test_pass_refuses_stale_file(self):
        st = state.load(self.d / "state.json")
        (self.d / "state.json").write_text(state.dumps(st.data).replace('"IN_PROGRESS"', '"PLANNED"'))
        # simulate a concurrent edit between load and save inside run(): monkeypatch state.load to return the old object
        orig = state.load
        state.load = lambda p: st
        try:
            rc = pass_cmd.run(self.d, "pr", "jsfiller#1", "AI_REVIEW", opts(head=H, ci="success"), self.io)
        finally:
            state.load = orig
        self.assertEqual(rc, 2)

    def test_story_transition(self):
        for pid, st_ in (("jsfiller#1", "MERGED"), ("docs-platform#2", "MERGED")):
            data = json.loads((self.d / "state.json").read_text()); data["prs"][pid]["state"] = st_
            (self.d / "state.json").write_text(state.dumps(data))
        rc = pass_cmd.run(self.d, "story", "S1", "INTEGRATION_REVIEW", opts(build="173111"), self.io)
        self.assertEqual(rc, 0)
        data = json.loads((self.d / "state.json").read_text())
        self.assertEqual(data["stories"]["S1"]["state"], "INTEGRATION_REVIEW")
        self.assertEqual(data["stories"]["S1"]["evidence"]["deploy"]["build"], "173111")
        self.assertNotIn("_id", data["stories"]["S1"])
```

- [x] **Step 2: Run, expect failure** (`pass_cmd` missing).

- [x] **Step 3: Implement**

```python
# turnstile_cli/pass_cmd.py
import datetime, pathlib, subprocess
from dataclasses import dataclass, field
from typing import List, Optional
from . import state as st_mod, rules, ledger
from .errors import TurnstileError, StaleStateError

@dataclass
class Options:
    head: Optional[str] = None
    ci: Optional[str] = None
    deep_review: Optional[str] = None
    rounds: Optional[int] = None
    not_clean: bool = False
    gate: Optional[str] = None
    copilot: Optional[int] = None
    slack: Optional[str] = None
    reviewers: Optional[str] = None
    approved: Optional[str] = None
    approvals: Optional[str] = None
    open_threads: Optional[int] = None
    reason: Optional[str] = None
    merged_sha: Optional[str] = None
    report: Optional[str] = None
    build: Optional[str] = None
    cases_pass: Optional[int] = None
    cases_fail: Optional[int] = None
    figma_parity: Optional[str] = None
    no_commit: bool = False

class IO:
    def git_commit(self, delivery: pathlib.Path, message: str) -> None:
        subprocess.run(["git", "add", "-A", "."], cwd=str(delivery), check=True)
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=str(delivery), check=True)
    def renderer(self, data: dict, delivery: pathlib.Path) -> None:
        try:
            from . import board
        except ImportError:
            return
        board.render(data, delivery)

def _now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")

def _apply_pr_evidence(pr: dict, o: Options, awaiting: List[dict]) -> None:
    if o.head:
        pr["head"] = o.head
    h = pr.get("head")
    ev = pr.setdefault("evidence", {})
    if o.ci:
        ev["ci"] = {"head": h, "status": o.ci}
    if o.deep_review:
        ev["deep_review"] = {"head": h, "report": o.deep_review, "rounds": o.rounds or 1, "clean": not o.not_clean}
    if o.gate:
        parts = o.gate.split(":")
        ev["gate"] = {"name": parts[0], "head": h, "result": parts[1] if len(parts) > 1 else "pass",
                      "run": parts[2] if len(parts) > 2 else None}
    if o.copilot is not None:
        ev["copilot"] = {"head": h, "open_threads": o.copilot}
    if o.slack:
        ev["human"] = {"head": h, "slack_permalink": o.slack, "reviewers": (o.reviewers or "").split(",") if o.reviewers else [],
                       "sent_head": h, "approved": o.approved, "open_threads": 0, "approvals": [], "sent_at": _now()}
        for a in awaiting:
            if a.get("id") == o.approved:
                a["approved_at"] = _now()
    if o.approvals is not None or o.open_threads is not None:
        human = ev.setdefault("human", {"head": h, "sent_head": h, "approvals": [], "open_threads": 0})
        if o.approvals is not None:
            human["approvals"] = [x for x in o.approvals.split(",") if x]
        if o.open_threads is not None:
            human["open_threads"] = o.open_threads
    if o.merged_sha:
        pr["merged_sha"] = o.merged_sha

def _apply_story_evidence(story: dict, o: Options) -> None:
    ev = story.setdefault("evidence", {})
    if o.build:
        ev["deploy"] = {"build": o.build, "at": _now()}
    if o.report and o.figma_parity is None and o.cases_fail is None:
        ev["integration_review"] = {"report": o.report, "head": o.head, "rounds": o.rounds or 1, "clean": not o.not_clean}
    if o.figma_parity is not None or o.cases_fail is not None:
        ev["env_test"] = {"report": o.report, "cases": {"pass": o.cases_pass or 0, "fail": o.cases_fail or 0},
                          "figma_parity": o.figma_parity}

def _recompute_next_actions(data: dict) -> None:
    for pid, pr in data["prs"].items():
        repo = data["epic"]["repos"].get(pid.split("#", 1)[0], {})
        pr["next_action"] = rules.next_action_pr(pr, repo)
    for sid, s in data["stories"].items():
        s["next_action"] = rules.next_action_story(s, data["prs"])

def _next_ah_id(data: dict) -> str:
    n = 1 + max([int(a["id"].split("-")[1]) for a in data.get("awaiting_human", []) if a.get("id", "").startswith("ah-")] or [0])
    return "ah-%d" % n

def _side_effects(delivery: pathlib.Path, st: "st_mod.State", summary: str, io: IO, o: Options) -> None:
    st_mod.save(st)
    ledger.append(delivery, summary)
    io.renderer(st.data, delivery)
    if not o.no_commit:
        io.git_commit(delivery, "turnstile: " + summary)

def run(delivery: pathlib.Path, kind: str, ident: str, target: str, o: Options, io: Optional[IO] = None) -> int:
    io = io or IO()
    try:
        st = st_mod.load(pathlib.Path(delivery) / "state.json")
        data = st.data
        if kind == "pr":
            pr = st_mod.pr(st, ident)
            repo = st_mod.repo_cfg(st, ident)
            import copy
            trial = copy.deepcopy(pr)
            _apply_pr_evidence(trial, o, copy.deepcopy(data.get("awaiting_human", [])))
            missing = rules.check_pr(trial, target, repo, data["prs"], reason=o.reason)
            if missing:
                print("\n".join(missing)); return 2
            src = pr["state"]
            _apply_pr_evidence(pr, o, data.setdefault("awaiting_human", []))
            pr["state"] = target
            if o.reason:
                pr["last_reason"] = o.reason
            jira_target = rules.JIRA_FOR_PR_STATE[target]
            if (pr.get("jira") or {}).get("status") != jira_target:
                pr["jira"] = {"status": jira_target, "synced": False}
                print("JIRA: %s → %s" % (pr["ticket"], jira_target))
            if target == "READY" and not any(a.get("pr") == ident and a.get("type") == "send" and not a.get("approved_at")
                                             for a in data["awaiting_human"]):
                data["awaiting_human"].append({"id": _next_ah_id(data), "owner": "lead", "type": "send", "pr": ident,
                                               "created_at": _now(), "payload": None, "approved_at": None})
            if target == "APPROVED":
                data["awaiting_human"].append({"id": _next_ah_id(data), "owner": "lead", "type": "merge", "pr": ident,
                                               "created_at": _now(), "payload": None, "approved_at": None})
            if target == "MERGED":
                unblocked = [p for p, v in data["prs"].items() if v.get("blocked_by") == ident]
                if unblocked:
                    ledger.append(delivery, "unblocked for sending by %s: %s" % (ident, ", ".join(unblocked)))
            _recompute_next_actions(data)
            summary = "pass pr %s %s → %s (head %s)%s" % (ident, src, target, pr.get("head"), " — " + o.reason if o.reason else "")
        elif kind == "story":
            story = st_mod.story(st, ident)
            import copy
            trial = copy.deepcopy(story); trial["_id"] = ident
            _apply_story_evidence(trial, o)
            missing = rules.check_story(trial, target, data["prs"], data["stories"], reason=o.reason)
            if missing:
                print("\n".join(missing)); return 2
            src = story["state"]
            _apply_story_evidence(story, o)
            story["state"] = target
            _recompute_next_actions(data)
            summary = "pass story %s %s → %s%s" % (ident, src, target, " — " + o.reason if o.reason else "")
        else:
            raise TurnstileError("kind must be pr or story")
        _side_effects(delivery, st, summary, io, o)
        print("BOARD: publish %s" % (pathlib.Path(delivery) / "board.html"))
        print("OK " + summary)
        return 0
    except StaleStateError as e:
        print("MISSING fresh state: %s" % e); return 2
    except TurnstileError as e:
        print("MISSING %s" % e); return 2

def jira_synced(delivery: pathlib.Path, ident: str, status: str, io: Optional[IO] = None) -> int:
    io = io or IO()
    st = st_mod.load(pathlib.Path(delivery) / "state.json")
    pr = st_mod.pr(st, ident)
    pr["jira"] = {"status": status, "synced": True}
    st_mod.save(st)
    ledger.append(delivery, "jira %s → %s (synced)" % (pr["ticket"], status))
    io.git_commit(delivery, "turnstile: jira %s → %s" % (pr["ticket"], status))
    print("OK jira %s synced" % ident)
    return 0
```

Wire into `main.py` (replace the body from Task 1):

```python
# turnstile_cli/main.py  (full)
import argparse, pathlib, sys
from . import __version__, paths
from .errors import TurnstileError

def build_parser():
    p = argparse.ArgumentParser(prog="turnstile", description="Evidence-gated delivery. No ticket, no entry.")
    p.add_argument("--version", action="version", version="turnstile " + __version__)
    p.add_argument("--delivery")
    sub = p.add_subparsers(dest="cmd")

    ps = sub.add_parser("pass", help="move a PR or story to the next state with evidence")
    ps.add_argument("kind", choices=["pr", "story"]); ps.add_argument("ident"); ps.add_argument("target")
    for flag, kw in [("--head", {}), ("--ci", {"choices": ["success", "failure"]}), ("--deep-review", {}),
                     ("--rounds", {"type": int}), ("--gate", {}), ("--copilot", {"type": int}), ("--slack", {}),
                     ("--reviewers", {}), ("--approved", {}), ("--approvals", {}), ("--open-threads", {"type": int}),
                     ("--reason", {}), ("--merged-sha", {}), ("--report", {}), ("--build", {}),
                     ("--cases-pass", {"type": int}), ("--cases-fail", {"type": int}),
                     ("--figma-parity", {"choices": ["pass", "fail"]})]:
        ps.add_argument(flag, **kw)
    ps.add_argument("--not-clean", action="store_true"); ps.add_argument("--no-commit", action="store_true")

    js = sub.add_parser("jira-synced"); js.add_argument("ident"); js.add_argument("status")
    sub.add_parser("render-board")
    rc = sub.add_parser("reconcile"); rc.add_argument("--json", action="store_true")
    sub.add_parser("status")
    return p

def main(argv=None):
    parser = build_parser()
    a = parser.parse_args(argv)
    if a.cmd is None:
        parser.print_help(); return 0
    try:
        delivery = paths.find_delivery(pathlib.Path.cwd(), a.delivery)
        if a.cmd == "pass":
            from .pass_cmd import run, Options
            o = Options(**{k.replace("-", "_"): v for k, v in vars(a).items()
                           if k not in ("cmd", "delivery", "kind", "ident", "target")})
            return run(delivery, a.kind, a.ident, a.target, o)
        if a.cmd == "jira-synced":
            from .pass_cmd import jira_synced
            return jira_synced(delivery, a.ident, a.status)
        if a.cmd == "render-board":
            from . import board, state
            board.render(state.load(delivery / "state.json").data, delivery)
            print("OK rendered %s" % (delivery / "board.html")); return 0
        if a.cmd in ("reconcile", "status"):
            from .reconcile import cli
            return cli(delivery, as_json=getattr(a, "json", False), status=(a.cmd == "status"))
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

(`argparse` stores `--deep-review` as `deep_review`, `--not-clean` as `not_clean`, etc., matching `Options`.)

- [x] **Step 4: Run** — `python3 -m unittest tests.test_pass tests.test_cli_smoke -v` — Expected: PASS (the `render-board`/`reconcile` branches import modules that do not exist yet; they are only reached when invoked, which these tests do not do).

- [x] **Step 5: Commit** — `git add -A && git commit -m "feat(pass): evidence-gated transitions with ledger, board, commit and Jira instruction"`

---

### Task 7: Board renderer and template

**Files:**
- Create: `turnstile_cli/board.py`, `templates/board.html`, `tests/test_board.py`

**Interfaces:**
- Produces: `board.render(data: dict, delivery: Path) -> Path` — reads `templates/board.html` (next to the package: `pathlib.Path(__file__).resolve().parents[1] / "templates" / "board.html"`), replaces the exact token `/*__TURNSTILE_STATE__*/null` with the JSON of `data` and `__TURNSTILE_UPDATED__` with the UTC timestamp, writes `delivery/board.html`.
- The template's JS renders: a summary tile row (one tile per PR state with counts, one "Stories" tile, one "Bugs" tile), a "Stories" table (id, title, state, PRs with states, evidence summary, next action), one table per repo (ticket, PR link, Slack link, state badge, AI gate heads, blocked_by, next_action, jira status + synced mark), a "Bugs" tab (id, story, title, source, PR, state, note) and an "Awaiting humans" list (owner, type, pr, created_at, approved?). Bug status dropdowns and the artifact `db` overlay are carried over from the current MYD-16538 board in plan 3 (migration) — here the bugs tab is read-only.

- [x] **Step 1: Failing test**

```python
# tests/test_board.py
import json, pathlib, tempfile, unittest
from turnstile_cli import board

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "state_min.json").read_text())

class Board(unittest.TestCase):
    def test_render_embeds_state_and_updated(self):
        d = pathlib.Path(tempfile.mkdtemp())
        out = board.render(FIX, d)
        html = out.read_text()
        self.assertEqual(out, d / "board.html")
        self.assertIn('"jsfiller#1"', html)
        self.assertNotIn("__TURNSTILE_STATE__", html)
        self.assertNotIn("__TURNSTILE_UPDATED__", html)
        self.assertIn("<title>", html)
        self.assertIn("prefers-color-scheme: dark", html)
    def test_json_is_script_safe(self):
        d = pathlib.Path(tempfile.mkdtemp())
        data = json.loads(json.dumps(FIX)); data["bugs"] = [{"id": "b1", "title": "</script><b>x", "state": "todo", "story": "S1", "source": "", "pr": "", "note": ""}]
        html = board.render(data, d).read_text()
        self.assertNotIn("</script><b>x", html)
        self.assertIn("<\\/script>", html)
```

- [x] **Step 2: Run, expect failure.**

- [x] **Step 3: Implement**

```python
# turnstile_cli/board.py
import datetime, json, pathlib

TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "templates" / "board.html"
TOKEN = "/*__TURNSTILE_STATE__*/null"

def render(data: dict, delivery: pathlib.Path) -> pathlib.Path:
    html = TEMPLATE.read_text()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace(TOKEN, payload)
    html = html.replace("__TURNSTILE_UPDATED__", datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    out = pathlib.Path(delivery) / "board.html"
    out.write_text(html)
    return out
```

```html
<!-- templates/board.html -->
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Turnstile Board</title>
<meta name="description" content="Epic delivery state: PRs, stories, bugs and what waits for humans.">
<style>
:root { --bg:#f6f7f9; --card:#fff; --ink:#1c1f24; --muted:#6b7280; --line:#e5e7eb; --accent:#2563eb;
  --dev:#9ca3af; --ai:#f59e0b; --ready:#10b981; --human:#3b82f6; --rework:#ef4444; --approved:#8b5cf6; --merged:#111827; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0f1115; --card:#171a21; --ink:#e5e7eb; --muted:#9ca3af; --line:#2a2f3a; } }
:root[data-theme="dark"] { --bg:#0f1115; --card:#171a21; --ink:#e5e7eb; --muted:#9ca3af; --line:#2a2f3a; }
* { box-sizing:border-box } body { margin:0; padding:16px; background:var(--bg); color:var(--ink); font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif }
h1 { font-size:20px; margin:0 0 4px } .updated { color:var(--muted); font-size:12px; margin-bottom:12px }
.tiles { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px } .tile { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:8px 12px; min-width:110px }
.tile b { display:block; font-size:22px } .tile span { color:var(--muted); font-size:12px }
h2 { font-size:16px; margin:20px 0 8px } .scroll { overflow-x:auto } table { border-collapse:collapse; width:100%; background:var(--card); border:1px solid var(--line); border-radius:8px }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; font-size:13px } th { color:var(--muted); font-weight:600 }
.badge { display:inline-block; padding:1px 8px; border-radius:999px; color:#fff; font-size:11px; font-weight:600 }
.k { font-family: ui-monospace, Menlo, monospace; font-size:12px } .muted { color:var(--muted) } a { color:var(--accent) }
.tabs button { background:none; border:1px solid var(--line); border-radius:6px; padding:4px 10px; margin-right:6px; color:var(--ink); cursor:pointer } .tabs button.on { border-color:var(--accent); color:var(--accent) }
.hidden { display:none }
</style>
</head>
<body>
<h1 id="title">Turnstile</h1>
<div class="updated">updated __TURNSTILE_UPDATED__</div>
<div class="tiles" id="tiles"></div>
<div class="tabs"><button data-tab="prs" class="on">PRs</button><button data-tab="stories">Stories</button><button data-tab="bugs">Bugs</button><button data-tab="awaiting">Awaiting humans</button></div>
<div id="prs"></div><div id="stories" class="hidden"></div><div id="bugs" class="hidden"></div><div id="awaiting" class="hidden"></div>
<script>
const STATE = /*__TURNSTILE_STATE__*/null;
const COLORS = { DEV:'var(--dev)', AI_REVIEW:'var(--ai)', READY:'var(--ready)', ON_HUMAN_REVIEW:'var(--human)', REWORK:'var(--rework)', APPROVED:'var(--approved)', MERGED:'var(--merged)' };
const PR_STATES = Object.keys(COLORS);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const badge = s => '<span class="badge" style="background:' + (COLORS[s] || 'var(--muted)') + '">' + esc(s) + '</span>';
const prUrl = id => { const [repo, n] = id.split('#'); return 'https://github.com/pdffiller/' + repo + '/pull/' + n; };
const short = h => h ? String(h).slice(0, 8) : '—';
function tiles() {
  const prs = Object.values(STATE.prs || {});
  const t = PR_STATES.map(s => ({ n: prs.filter(p => p.state === s).length, l: s }));
  t.push({ n: Object.keys(STATE.stories || {}).length, l: 'Stories' }, { n: (STATE.bugs || []).filter(b => b.state !== 'done').length, l: 'Open bugs' },
         { n: (STATE.awaiting_human || []).filter(a => !a.approved_at).length, l: 'Awaiting humans' });
  document.getElementById('tiles').innerHTML = t.map(x => '<div class="tile"><b>' + x.n + '</b><span>' + esc(x.l) + '</span></div>').join('');
}
function gateCell(p) {
  const e = p.evidence || {}, cur = p.head;
  const mark = (name, ev, ok) => ev ? (name + ' ' + (ok && ev.head && cur && (cur.startsWith(ev.head) || ev.head.startsWith(cur)) ? '✓' : '✗') + ' ' + short(ev.head)) : name + ' —';
  return [mark('deep', e.deep_review, e.deep_review && e.deep_review.clean), mark(e.gate ? e.gate.name : 'gate', e.gate, e.gate && e.gate.result === 'pass'),
          e.copilot ? mark('copilot', e.copilot, e.copilot.open_threads === 0) : ''].filter(Boolean).join(' · ');
}
function prs() {
  const byRepo = {};
  Object.entries(STATE.prs || {}).forEach(([id, p]) => { const r = id.split('#')[0]; (byRepo[r] = byRepo[r] || []).push([id, p]); });
  document.getElementById('prs').innerHTML = Object.entries(byRepo).map(([repo, rows]) =>
    '<h2>' + esc(repo) + '</h2><div class="scroll"><table><thead><tr><th>Ticket</th><th>PR</th><th>Slack</th><th>State</th><th>AI gates (head ' + '' + ')</th><th>Blocked by</th><th>Jira</th><th>Next action</th></tr></thead><tbody>' +
    rows.sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true })).map(([id, p]) => {
      const h = (p.evidence || {}).human || {};
      return '<tr><td>' + esc(p.ticket) + '</td><td class="k"><a href="' + prUrl(id) + '" target="_blank" rel="noopener">#' + esc(id.split('#')[1]) + '</a> <span class="muted">' + short(p.head) + '</span></td>' +
        '<td>' + (h.slack_permalink ? '<a href="' + esc(h.slack_permalink) + '" target="_blank" rel="noopener">thread ↗</a>' : '—') + '</td>' +
        '<td>' + badge(p.state) + '</td><td class="k">' + esc(gateCell(p)) + '</td><td class="k">' + esc(p.blocked_by || '—') + '</td>' +
        '<td>' + esc((p.jira || {}).status || '—') + ((p.jira || {}).synced === false ? ' <span class="muted">(not synced)</span>' : '') + '</td><td>' + esc(p.next_action) + '</td></tr>';
    }).join('') + '</tbody></table></div>').join('');
}
function stories() {
  document.getElementById('stories').innerHTML = '<div class="scroll"><table><thead><tr><th>Story</th><th>State</th><th>PRs</th><th>Evidence</th><th>Next action</th></tr></thead><tbody>' +
    Object.entries(STATE.stories || {}).map(([sid, s]) => {
      const prs = Object.entries(STATE.prs || {}).filter(([, p]) => p.story === sid).map(([id, p]) => esc(id) + ' ' + badge(p.state)).join('<br>');
      const e = s.evidence || {};
      const ev = ['deploy ' + (e.deploy ? e.deploy.build : '—'), 'review ' + (e.integration_review ? (e.integration_review.clean ? '✓' : '✗') : '—'),
                  'env ' + (e.env_test ? (e.env_test.cases.fail === 0 && e.env_test.figma_parity === 'pass' ? '✓' : '✗ ' + e.env_test.cases.fail + ' fail') : '—')].join(' · ');
      return '<tr><td><b>' + esc(sid) + '</b> ' + esc(s.title) + '</td><td>' + badge(s.state) + '</td><td>' + prs + '</td><td class="k">' + esc(ev) + '</td><td>' + esc(s.next_action) + '</td></tr>';
    }).join('') + '</tbody></table></div>';
}
function bugs() {
  document.getElementById('bugs').innerHTML = '<div class="scroll"><table><thead><tr><th>#</th><th>Story</th><th>Bug</th><th>Source</th><th>PR</th><th>State</th><th>Note</th></tr></thead><tbody>' +
    (STATE.bugs || []).map(b => '<tr><td class="k">' + esc(b.id) + '</td><td>' + esc(b.story) + '</td><td>' + esc(b.title) + '</td><td class="muted">' + esc(b.source) + '</td><td class="k">' +
      (b.pr ? '<a href="' + prUrl(b.pr) + '" target="_blank" rel="noopener">' + esc(b.pr) + '</a>' : '—') + '</td><td>' + badge(b.state) + '</td><td>' + esc(b.note) + '</td></tr>').join('') + '</tbody></table></div>';
}
function awaiting() {
  document.getElementById('awaiting').innerHTML = '<div class="scroll"><table><thead><tr><th>Id</th><th>Owner</th><th>Type</th><th>PR / story</th><th>Created</th><th>Approved</th></tr></thead><tbody>' +
    (STATE.awaiting_human || []).map(a => '<tr><td class="k">' + esc(a.id) + '</td><td>' + esc(a.owner) + '</td><td>' + esc(a.type) + '</td><td class="k">' + esc(a.pr || a.story) + '</td><td class="muted">' + esc(a.created_at) + '</td><td>' + (a.approved_at ? esc(a.approved_at) : '<b>pending</b>') + '</td></tr>').join('') + '</tbody></table></div>';
}
document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.tabs button').forEach(x => x.classList.toggle('on', x === b));
  ['prs', 'stories', 'bugs', 'awaiting'].forEach(id => document.getElementById(id).classList.toggle('hidden', id !== b.dataset.tab));
}));
if (STATE) { document.getElementById('title').textContent = 'Turnstile — ' + (STATE.epic || {}).key; tiles(); prs(); stories(); bugs(); awaiting(); }
</script>
</body>
</html>
```

Note: the GitHub org in `prUrl` is hard-coded to `pdffiller` for now; plan 2 moves it into `epic.github_org` in the state. Add `"github_org": "pdffiller"` to `epic` in the fixture now and read `STATE.epic.github_org || 'pdffiller'` in `prUrl` so the template is already correct.

- [x] **Step 4: Run** — `python3 -m unittest tests.test_board -v` — Expected: PASS. Open `board.html` from a test run in a browser once and confirm the four tabs render on phone width without horizontal scroll.

- [x] **Step 5: Commit** — `git add -A && git commit -m "feat(board): render board.html from state"`

---

### Task 8: GitHub adapter and reconcile (pure comparison + CLI)

**Files:**
- Create: `turnstile_cli/github.py`, `turnstile_cli/reconcile.py`, `tests/fixtures/gh_pr_13222.json`, `tests/test_reconcile.py`

**Interfaces:**
- Produces:
  - `github.PrFacts` dataclass: `id, head, merged: bool, merged_sha: Optional[str], draft: bool, ci: str ("success"|"failure"|"pending"|"unknown"), checks: Dict[str,str]` (check name → `success|failure|pending|cancelled`), `approvals: List[str]`, `human_threads_open: int`, `copilot_threads_open: int`, `changes_requested: List[str]`.
  - `github.fetch(pr_id: str, org: str) -> PrFacts` runs the GraphQL below through `gh api graphql` and parses with `github.parse(pr_id, payload: dict) -> PrFacts` (pure; tested with the recorded fixture).
  - `reconcile.compare(data: dict, facts: Dict[str, PrFacts]) -> List[Proposal]` where `Proposal` is `(pr_id, kind, message, suggested_cmd: Optional[str])`, kinds: `head_changed, merged, approved, human_thread, copilot_thread, gate_red, ci_red, jira_unsynced, draft_mismatch`.
  - `reconcile.cli(delivery, as_json, status) -> int` prints proposals (and, for `status`, the per-PR/story `next_action` and open `awaiting_human`), exit 0 always (it only reports).

GraphQL (one PR; `gh api graphql -f query=… -f o=<org> -f r=<repo> -F n=<number>`):

```graphql
query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ pullRequest(number:$n){
  isDraft merged mergeCommit{oid} headRefOid reviewDecision
  latestReviews(first:30){nodes{author{login} state}}
  reviewThreads(first:100){nodes{isResolved comments(first:1){nodes{author{login}}}}}
  commits(last:1){nodes{commit{statusCheckRollup{state contexts(first:50){nodes{
    ... on CheckRun{name conclusion status} ... on StatusContext{context state}}}}}}} } } }
```

Mapping: `ci` = rollup `state` lower-cased (`SUCCESS→success`, `FAILURE/ERROR→failure`, `PENDING/EXPECTED→pending`); `checks[name]` = `conclusion` lower-cased for CheckRuns (`cancelled` kept distinct), `state` for StatusContext; a thread is Copilot's when its first comment author is `copilot-pull-request-reviewer`, otherwise human; `approvals` = logins with `APPROVED` in `latestReviews` excluding bots; `changes_requested` likewise for `CHANGES_REQUESTED`.

Comparison rules (in this order per PR, skip MERGED PRs except for `merged` confirmation):

| condition | kind | suggested command |
|---|---|---|
| `facts.merged` and state != MERGED | merged | `turnstile pass pr <id> MERGED --merged-sha <sha>` |
| `facts.head` not same_head as `pr.head` | head_changed | state in (ON_HUMAN_REVIEW, APPROVED) → `… REWORK --reason "push after send (<new head>)"`; else `… AI_REVIEW --head <new> --ci <ci>` |
| state == ON_HUMAN_REVIEW and `human_threads_open > 0` | human_thread | `… REWORK --reason "<n> human thread(s)"` |
| state == ON_HUMAN_REVIEW and approvals and `human_threads_open == 0` | approved | `… APPROVED --approvals <a,b> --open-threads 0` |
| `copilot_threads_open > 0` and evidence.copilot says 0 for this head | copilot_thread | message only |
| repo gate check present in `facts.checks` with value != success while evidence.gate says pass for this head | gate_red | message only |
| `facts.ci == failure` while evidence.ci success for this head | ci_red | message only |
| `pr.jira.synced == false` | jira_unsynced | `turnstile jira-synced <id> "<status>"` (after the MCP transition) |
| `facts.draft` and state in (ON_HUMAN_REVIEW, APPROVED) | draft_mismatch | message only |

- [x] **Step 1: Record the fixture** — run once against a real PR and save the raw `data.repository.pullRequest` object to `tests/fixtures/gh_pr_13222.json` (any real PR works; then edit values so that: `headRefOid` starts with `aaaaaaaa1111`, `merged:false`, one unresolved thread by `lMakDen`, one resolved by `copilot-pull-request-reviewer`, `latestReviews` contains `{"author":{"login":"isachivka"},"state":"APPROVED"}`, rollup `SUCCESS`, a CheckRun `{"name":"pdf-review","conclusion":"SUCCESS"}`).

- [x] **Step 2: Failing tests**

```python
# tests/test_reconcile.py
import copy, json, pathlib, unittest
from turnstile_cli import github, reconcile

D = pathlib.Path(__file__).parent / "fixtures"
FIX = json.loads((D / "state_min.json").read_text())
PAYLOAD = json.loads((D / "gh_pr_13222.json").read_text())

class Parse(unittest.TestCase):
    def test_parse(self):
        f = github.parse("jsfiller#1", PAYLOAD)
        self.assertTrue(f.head.startswith("aaaaaaaa1111"))
        self.assertEqual(f.ci, "success"); self.assertEqual(f.checks["pdf-review"], "success")
        self.assertEqual(f.human_threads_open, 1); self.assertEqual(f.copilot_threads_open, 0)
        self.assertEqual(f.approvals, ["isachivka"]); self.assertFalse(f.merged)

class Compare(unittest.TestCase):
    def facts(self, **kw):
        f = github.parse("jsfiller#1", PAYLOAD)
        for k, v in kw.items(): setattr(f, k, v)
        return {"jsfiller#1": f}
    def data(self, state, **ev):
        d = copy.deepcopy(FIX); p = d["prs"]["jsfiller#1"]; p["state"] = state; p["evidence"].update(ev); return d
    def test_push_after_send_proposes_rework(self):
        d = self.data("ON_HUMAN_REVIEW", human={"head": "aaaaaaaa11111111", "sent_head": "aaaaaaaa11111111", "slack_permalink": "u", "approved": "ah-1", "open_threads": 0, "approvals": []})
        props = reconcile.compare(d, self.facts(head="ffffffff66666666"))
        self.assertEqual(props[0].kind, "head_changed"); self.assertIn("REWORK", props[0].suggested_cmd)
    def test_human_thread_proposes_rework(self):
        d = self.data("ON_HUMAN_REVIEW", human={"head": "aaaaaaaa11111111", "sent_head": "aaaaaaaa11111111", "slack_permalink": "u", "approved": "ah-1", "open_threads": 0, "approvals": []})
        props = reconcile.compare(d, self.facts())
        self.assertEqual([p.kind for p in props], ["human_thread"])
    def test_approved_with_no_threads(self):
        d = self.data("ON_HUMAN_REVIEW", human={"head": "aaaaaaaa11111111", "sent_head": "aaaaaaaa11111111", "slack_permalink": "u", "approved": "ah-1", "open_threads": 0, "approvals": []})
        props = reconcile.compare(d, self.facts(human_threads_open=0))
        self.assertEqual(props[0].kind, "approved"); self.assertIn("--approvals isachivka", props[0].suggested_cmd)
    def test_merged(self):
        props = reconcile.compare(self.data("APPROVED"), self.facts(merged=True, merged_sha="abcabcabcabcabca"))
        self.assertEqual(props[0].kind, "merged"); self.assertIn("MERGED --merged-sha abcabcabcabcabca", props[0].suggested_cmd)
    def test_gate_red_against_recorded_pass(self):
        d = self.data("READY", gate={"name": "pdf-review", "head": "aaaaaaaa11111111", "result": "pass"})
        f = self.facts(human_threads_open=0); f["jsfiller#1"].checks["pdf-review"] = "failure"
        self.assertIn("gate_red", [p.kind for p in reconcile.compare(d, f)])
    def test_jira_unsynced(self):
        d = self.data("AI_REVIEW"); d["prs"]["jsfiller#1"]["jira"]["synced"] = False
        self.assertIn("jira_unsynced", [p.kind for p in reconcile.compare(d, self.facts(human_threads_open=0))])
```

- [x] **Step 3: Run, expect failure.**

- [x] **Step 4: Implement**

```python
# turnstile_cli/github.py
import json, subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .errors import TurnstileError

BOT = "copilot-pull-request-reviewer"
QUERY = """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ pullRequest(number:$n){
  isDraft merged mergeCommit{oid} headRefOid reviewDecision
  latestReviews(first:30){nodes{author{login} state}}
  reviewThreads(first:100){nodes{isResolved comments(first:1){nodes{author{login}}}}}
  commits(last:1){nodes{commit{statusCheckRollup{state contexts(first:50){nodes{
    ... on CheckRun{name conclusion status} ... on StatusContext{context state}}}}}}} } } }"""

@dataclass
class PrFacts:
    id: str
    head: str
    merged: bool
    merged_sha: Optional[str]
    draft: bool
    ci: str
    checks: Dict[str, str] = field(default_factory=dict)
    approvals: List[str] = field(default_factory=list)
    changes_requested: List[str] = field(default_factory=list)
    human_threads_open: int = 0
    copilot_threads_open: int = 0

def _low(x: Optional[str]) -> str:
    return (x or "unknown").lower()

def parse(pr_id: str, pr: dict) -> PrFacts:
    rollup = ((pr.get("commits") or {}).get("nodes") or [{}])[0].get("commit", {}).get("statusCheckRollup") or {}
    ci = {"success": "success", "failure": "failure", "error": "failure", "pending": "pending", "expected": "pending"}.get(_low(rollup.get("state")), "unknown")
    checks: Dict[str, str] = {}
    for c in (rollup.get("contexts") or {}).get("nodes") or []:
        if "name" in c:
            checks[c["name"]] = _low(c.get("conclusion") or c.get("status"))
        elif "context" in c:
            checks[c["context"]] = _low(c.get("state"))
    approvals, changes = [], []
    for r in (pr.get("latestReviews") or {}).get("nodes") or []:
        login = (r.get("author") or {}).get("login", "")
        if login.endswith("[bot]") or login == BOT or login == "Snyk-Agent":
            continue
        if r.get("state") == "APPROVED": approvals.append(login)
        if r.get("state") == "CHANGES_REQUESTED": changes.append(login)
    human_open = copilot_open = 0
    for t in (pr.get("reviewThreads") or {}).get("nodes") or []:
        if t.get("isResolved"): continue
        first = ((t.get("comments") or {}).get("nodes") or [{}])[0]
        if ((first.get("author") or {}).get("login")) == BOT: copilot_open += 1
        else: human_open += 1
    return PrFacts(id=pr_id, head=pr.get("headRefOid") or "", merged=bool(pr.get("merged")),
                   merged_sha=(pr.get("mergeCommit") or {}).get("oid"), draft=bool(pr.get("isDraft")), ci=ci, checks=checks,
                   approvals=sorted(approvals), changes_requested=sorted(changes),
                   human_threads_open=human_open, copilot_threads_open=copilot_open)

def fetch(pr_id: str, org: str) -> PrFacts:
    repo, num = pr_id.split("#", 1)
    out = subprocess.run(["gh", "api", "graphql", "-f", "query=" + QUERY, "-f", "o=" + org, "-f", "r=" + repo, "-F", "n=" + num],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise TurnstileError("gh api failed for %s: %s" % (pr_id, out.stderr.strip()[:200]))
    pr = json.loads(out.stdout)["data"]["repository"]["pullRequest"]
    return parse(pr_id, pr)
```

```python
# turnstile_cli/reconcile.py
import json, pathlib
from dataclasses import dataclass
from typing import Dict, List, Optional
from . import rules, state as st_mod, github

@dataclass
class Proposal:
    pr: str
    kind: str
    message: str
    suggested_cmd: Optional[str]

def _ev_for_head(pr: dict, key: str) -> Optional[dict]:
    ev = (pr.get("evidence") or {}).get(key)
    return ev if ev and rules.same_head(ev.get("head"), pr.get("head")) else None

def compare(data: dict, facts: Dict[str, github.PrFacts]) -> List[Proposal]:
    out: List[Proposal] = []
    for pid, pr in data["prs"].items():
        f = facts.get(pid)
        if f is None:
            continue
        st = pr.get("state")
        repo = data["epic"]["repos"].get(pid.split("#", 1)[0], {})
        if f.merged and st != "MERGED":
            out.append(Proposal(pid, "merged", "merged on GitHub (%s)" % (f.merged_sha or "")[:8],
                                "turnstile pass pr %s MERGED --merged-sha %s" % (pid, f.merged_sha)))
            continue
        if st == "MERGED":
            continue
        if not rules.same_head(f.head, pr.get("head")):
            if st in ("ON_HUMAN_REVIEW", "APPROVED"):
                cmd = 'turnstile pass pr %s REWORK --reason "push after send (%s)"' % (pid, f.head[:8])
            else:
                cmd = "turnstile pass pr %s AI_REVIEW --head %s --ci %s" % (pid, f.head, f.ci)
            out.append(Proposal(pid, "head_changed", "head is %s, state has %s" % (f.head[:8], (pr.get("head") or "")[:8]), cmd))
            continue
        if st == "ON_HUMAN_REVIEW" and f.human_threads_open > 0:
            out.append(Proposal(pid, "human_thread", "%d unresolved human thread(s)" % f.human_threads_open,
                                'turnstile pass pr %s REWORK --reason "%d human thread(s)"' % (pid, f.human_threads_open)))
        elif st == "ON_HUMAN_REVIEW" and f.approvals and f.human_threads_open == 0:
            out.append(Proposal(pid, "approved", "approved by %s" % ", ".join(f.approvals),
                                "turnstile pass pr %s APPROVED --approvals %s --open-threads 0" % (pid, ",".join(f.approvals))))
        cp = _ev_for_head(pr, "copilot")
        if cp and cp.get("open_threads") == 0 and f.copilot_threads_open > 0:
            out.append(Proposal(pid, "copilot_thread", "%d open Copilot thread(s) but evidence says 0" % f.copilot_threads_open, None))
        g = _ev_for_head(pr, "gate")
        gate_name = repo.get("gate")
        if g and gate_name and f.checks.get(gate_name) not in (None, "success") and g.get("result") == "pass":
            out.append(Proposal(pid, "gate_red", "check %s is %s on GitHub but evidence says pass" % (gate_name, f.checks.get(gate_name)), None))
        ci = _ev_for_head(pr, "ci")
        if ci and ci.get("status") == "success" and f.ci == "failure":
            out.append(Proposal(pid, "ci_red", "CI is red on GitHub but evidence says success", None))
        if (pr.get("jira") or {}).get("synced") is False:
            out.append(Proposal(pid, "jira_unsynced", "Jira not moved to %s" % pr["jira"].get("status"),
                                'turnstile jira-synced %s "%s"' % (pid, pr["jira"].get("status"))))
        if f.draft and st in ("ON_HUMAN_REVIEW", "APPROVED"):
            out.append(Proposal(pid, "draft_mismatch", "PR is still a draft on GitHub", None))
    return out

def cli(delivery: pathlib.Path, as_json: bool = False, status: bool = False) -> int:
    st = st_mod.load(pathlib.Path(delivery) / "state.json")
    org = st.data["epic"].get("github_org", "pdffiller")
    facts = {}
    for pid, pr in st.data["prs"].items():
        if pr.get("state") == "MERGED":
            continue
        try:
            facts[pid] = github.fetch(pid, org)
        except Exception as e:  # network/gh problems must not hide the rest
            print("WARN %s: %s" % (pid, e))
    props = compare(st.data, facts)
    if as_json:
        print(json.dumps([p.__dict__ for p in props], indent=2)); return 0
    if status:
        print("== %s" % st.data["epic"]["key"])
        for sid, s in st.data["stories"].items():
            print("story %s [%s] %s — %s" % (sid, s.get("state"), s.get("title"), s.get("next_action", "")))
        for pid, pr in st.data["prs"].items():
            print("pr %-28s [%s] %s" % (pid, pr.get("state"), pr.get("next_action", "")))
        pending = [a for a in st.data.get("awaiting_human", []) if not a.get("approved_at")]
        print("awaiting humans: %d" % len(pending))
        for a in pending:
            print("  %s %s %s %s" % (a["id"], a["owner"], a["type"], a.get("pr") or a.get("story")))
    print("== reconcile: %d discrepancy(ies)" % len(props))
    for p in props:
        print("%s %s: %s" % (p.pr, p.kind, p.message))
        if p.suggested_cmd:
            print("    → " + p.suggested_cmd)
    return 0
```

- [x] **Step 5: Run** — `python3 -m unittest tests.test_reconcile -v` — Expected: PASS.

- [x] **Step 6: Commit** — `git add -A && git commit -m "feat(reconcile): GitHub facts adapter and drift proposals"`

---

### Task 9: End-to-end CLI test and `status`

**Files:**
- Create: `tests/test_e2e.py`

- [x] **Step 1: Write the test** (uses the shim, a temp workspace with `.turnstile`, a git repo so the commit side effect runs for real, and `--no-commit` where git is not wanted)

```python
# tests/test_e2e.py
import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"
H = "aaaaaaaa11111111"

def sh(args, cwd):
    return subprocess.run([str(ROOT / "scripts" / "turnstile")] + args, cwd=cwd, capture_output=True, text=True)

class E2E(unittest.TestCase):
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")
        subprocess.run(["git", "init", "-q"], cwd=self.ws, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."], cwd=self.ws, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-qm", "init"], cwd=self.ws, check=True)
        self.env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def test_full_pr_path_with_real_git_commit(self):
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.ws, check=True)
        r = sh(["pass", "pr", "jsfiller#1", "READY", "--head", H, "--ci", "success", "--deep-review", "reports/R.md", "--rounds", "1", "--gate", "pdf-review:pass"], cwd=self.ws / "delivery")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.strip().splitlines()[-1].startswith("OK pass pr jsfiller#1 AI_REVIEW → READY"))
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.ws, capture_output=True, text=True).stdout
        self.assertIn("turnstile: pass pr jsfiller#1", log)
        self.assertTrue((self.ws / "delivery" / "board.html").exists())
        r = sh(["pass", "pr", "jsfiller#1", "ON_HUMAN_REVIEW", "--head", H], cwd=self.ws)
        self.assertEqual(r.returncode, 2); self.assertIn("MISSING evidence.human.slack_permalink", r.stdout)

    def test_status_without_network(self):
        r = sh(["status"], cwd=self.ws)
        self.assertEqual(r.returncode, 0)
        self.assertIn("== MYD-1", r.stdout); self.assertIn("awaiting humans:", r.stdout)
```

`status` calls `github.fetch`, which needs network: in the test environment `gh` fails and `cli` prints `WARN` lines and continues, so the assertion still holds. If `gh` is absent entirely, `subprocess` raises `FileNotFoundError`, which the `except Exception` in `cli` also catches.

- [x] **Step 2: Run** — `python3 -m unittest discover -s tests -v` — Expected: all PASS.

- [x] **Step 3: Commit** — `git add -A && git commit -m "test: end-to-end CLI path"`

---

### Task 10: Hooks (guards)

**Files:**
- Create: `hooks/hooks.json`, `hooks/guard_bash.py`, `hooks/guard_slack.py`, `hooks/guard_state_edit.py`, `tests/test_hooks.py`

**Interfaces:**
- Claude Code hook contract: the hook reads one JSON object on stdin (`{"tool_name": ..., "tool_input": {...}, "cwd": ...}`); exit code `2` blocks the call and the text on **stderr** is shown to the model; exit `0` allows. Guards locate the state through `paths.find_delivery(cwd)` by adding the plugin root (`CLAUDE_PLUGIN_ROOT`, or the script's grandparent) to `sys.path`.

```json
// hooks/hooks.json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/guard_bash.py\"" } ] },
      { "matcher": "mcp__.*slack_send_message.*", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/guard_slack.py\"" } ] }
    ],
    "PostToolUse": [
      { "matcher": "Edit|Write|MultiEdit", "hooks": [ { "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/guard_state_edit.py\"" } ] }
    ]
  }
}
```

`guard_bash.py` blocks when the command matches any of (regex, case-insensitive, after stripping line continuations):
`\bgh pr merge\b`, `\bgh pr ready\b`, `--add-reviewer`, `requested_reviewers` unless the same command contains `copilot-pull-request-reviewer`, `git push\b.*(--force|-f\b|\+\S)`, `git rebase\b`, `--no-gpg-sign`, `Co-Authored-By`, `Generated with \[Claude Code\]`, `service_github_tag=\s*(?=&|$|")` (empty tag), `gh pr edit\b.*--body.*Generated with`. It prints the matched rule on stderr: `turnstile: blocked by rule <name>. The lead performs this action, or approve it through turnstile.`

`guard_slack.py` reads `tool_input.text`/`message` and extracts PR ids (`<repo>#<n>` or GitHub PR URLs → `repo#n`); loads the state; allows only if for **every** extracted PR there is an `awaiting_human` entry of type `send` or `reply` with `approved_at` set and (for `send`) the PR state is `READY`; messages with no PR reference are blocked too (`turnstile: Slack sends must reference the PR they are about and be approved`). Missing/invalid state → block (fail closed).

`guard_state_edit.py`: if `tool_input.file_path` ends with `/state.json` under a delivery dir, print on stdout `turnstile: state.json is written only by 'turnstile pass'; run 'turnstile reconcile' to see what you broke` and exit 0 (warning, not block — the file may be edited deliberately during migration).

- [x] **Step 1: Failing tests**

```python
# tests/test_hooks.py
import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state_min.json"

def hook(name, payload, cwd):
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(ROOT))
    return subprocess.run([sys.executable, str(ROOT / "hooks" / name)], input=json.dumps(payload), cwd=cwd, capture_output=True, text=True, env=env)

class Hooks(unittest.TestCase):
    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp()); d = self.ws / "delivery"; d.mkdir()
        shutil.copy(FIX, d / "state.json"); (self.ws / ".turnstile").write_text("delivery\n")

    def bash(self, cmd):
        return hook("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(self.ws)}, self.ws)

    def test_bash_blocks(self):
        for cmd in ["gh pr merge 1", "gh pr ready 1", "gh pr edit 1 --add-reviewer x", "git push --force origin x", "git push -f",
                    "git rebase develop", "git commit --no-gpg-sign -m x", "git commit -m 'x\n\nCo-Authored-By: a'",
                    "gh api -X POST repos/o/r/pulls/1/requested_reviewers -f 'reviewers[]=isachivka'",
                    "gh workflow run x -f service_github_tag= -f y=1"]:
            r = self.bash(cmd); self.assertEqual(r.returncode, 2, cmd); self.assertIn("blocked by rule", r.stderr)

    def test_bash_allows(self):
        for cmd in ["git push origin feature/x", "gh pr view 1", "gh api -X POST repos/o/r/pulls/1/requested_reviewers -f 'reviewers[]=copilot-pull-request-reviewer[bot]'",
                    "git commit -S -m 'feat: x'", "gh workflow run x -f service_github_tag=l2f-funnel-abc"]:
            self.assertEqual(self.bash(cmd).returncode, 0, cmd)

    def slack(self, text):
        return hook("guard_slack.py", {"tool_name": "mcp__plugin_slack_slack__slack_send_message", "tool_input": {"channel_id": "C1", "text": text}, "cwd": str(self.ws)}, self.ws)

    def test_slack_blocks_without_approval(self):
        r = self.slack("PR: <https://github.com/pdffiller/jsfiller/pull/1>"); self.assertEqual(r.returncode, 2)
        r = self.slack("hello"); self.assertEqual(r.returncode, 2)

    def test_slack_allows_approved_send_of_ready_pr(self):
        d = json.loads((self.ws / "delivery" / "state.json").read_text())
        d["prs"]["jsfiller#1"]["state"] = "READY"
        d["awaiting_human"] = [{"id": "ah-1", "owner": "lead", "type": "send", "pr": "jsfiller#1", "created_at": "x", "payload": None, "approved_at": "2026-10-13T10:00Z"}]
        (self.ws / "delivery" / "state.json").write_text(json.dumps(d))
        self.assertEqual(self.slack("PR: <https://github.com/pdffiller/jsfiller/pull/1>").returncode, 0)

    def test_slack_fails_closed_on_broken_state(self):
        (self.ws / "delivery" / "state.json").write_text("{not json")
        r = self.slack("PR: <https://github.com/pdffiller/jsfiller/pull/1>"); self.assertEqual(r.returncode, 2)
        shutil.rmtree(self.ws / "delivery")
        r = self.slack("PR: <https://github.com/pdffiller/jsfiller/pull/1>"); self.assertEqual(r.returncode, 2)

    def test_state_edit_warns(self):
        r = hook("guard_state_edit.py", {"tool_name": "Edit", "tool_input": {"file_path": str(self.ws / "delivery" / "state.json")}, "cwd": str(self.ws)}, self.ws)
        self.assertEqual(r.returncode, 0); self.assertIn("turnstile pass", r.stdout)
```

- [x] **Step 2: Run, expect failure.**

- [x] **Step 3: Implement**

```python
# hooks/_common.py
import json, os, pathlib, sys

def plugin_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or pathlib.Path(__file__).resolve().parents[1])

def read_payload() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}

def block(msg: str) -> None:
    sys.stderr.write("turnstile: " + msg + "\n"); sys.exit(2)

def load_state(cwd: str):
    sys.path.insert(0, str(plugin_root()))
    from turnstile_cli import paths, state
    d = paths.find_delivery(pathlib.Path(cwd or "."), None)
    return state.load(d / "state.json").data
```

```python
# hooks/guard_bash.py
import re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload, block

RULES = [
    ("merge", r"\bgh\s+pr\s+merge\b"), ("ready", r"\bgh\s+pr\s+ready\b"), ("add-reviewer", r"--add-reviewer\b"),
    ("force-push", r"\bgit\s+push\b[^\n]*(\s--force(-with-lease)?\b|\s-f\b|\s\+\S)"), ("rebase", r"\bgit\s+rebase\b"),
    ("unsigned", r"--no-gpg-sign\b"), ("trailer", r"Co-Authored-By"), ("footer", r"Generated with \[Claude Code\]"),
    ("empty-variant-tag", r"service_github_tag=\s*(?=\s|&|$|\"|')"),
]

def main():
    cmd = (read_payload().get("tool_input") or {}).get("command") or ""
    flat = cmd.replace("\\\n", " ")
    for name, rx in RULES:
        if re.search(rx, flat, re.I | re.M):
            block("blocked by rule %s. The lead performs this action, or approve it through turnstile." % name)
    if re.search(r"requested_reviewers", flat) and "copilot-pull-request-reviewer" not in flat:
        block("blocked by rule human-reviewer-request. The lead requests human reviewers.")
    sys.exit(0)

if __name__ == "__main__":
    main()
```

```python
# hooks/guard_slack.py
import re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload, block, load_state

PR_RX = re.compile(r"github\.com/[^/\s]+/([^/\s]+)/pull/(\d+)|\b([a-z0-9-]+)#(\d+)\b", re.I)

def prs_in(text: str):
    out = set()
    for m in PR_RX.finditer(text or ""):
        repo, n = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        out.add("%s#%s" % (repo, n))
    return out

def main():
    p = read_payload(); ti = p.get("tool_input") or {}
    text = ti.get("text") or ti.get("message") or ""
    ids = prs_in(text)
    if not ids:
        block("Slack sends must reference the PR they are about and be approved (no PR id found).")
    try:
        data = load_state(p.get("cwd") or ".")
    except Exception as e:
        block("cannot read the delivery state (%s); failing closed." % e)
    for pid in sorted(ids):
        ok = False
        for a in data.get("awaiting_human", []):
            if a.get("pr") == pid and a.get("type") in ("send", "reply") and a.get("approved_at"):
                if a["type"] == "reply" or (data.get("prs", {}).get(pid, {}).get("state") == "READY"):
                    ok = True
        if not ok:
            block("no approved send/reply for %s in awaiting_human (state %s). Get the lead's word, then: turnstile pass … --approved <ah-id>."
                  % (pid, data.get("prs", {}).get(pid, {}).get("state")))
    sys.exit(0)

if __name__ == "__main__":
    main()
```

```python
# hooks/guard_state_edit.py
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload

def main():
    fp = ((read_payload().get("tool_input") or {}).get("file_path") or "")
    if fp.endswith("/state.json"):
        print("turnstile: state.json is written only by 'turnstile pass'; run 'turnstile reconcile' to see what you changed.")
    sys.exit(0)

if __name__ == "__main__":
    main()
```

Note: the approval for `send` is set by `turnstile pass pr <id> ON_HUMAN_REVIEW … --approved <ah-id>`, which happens *after* the Slack message exists (it needs the permalink). Order in the skill (plan 2): the lead says "send" → the orchestrator runs `turnstile approve <ah-id>` (tiny subcommand: sets `approved_at`, commits; add it to `pass_cmd.py` as `approve(delivery, ah_id, io)` and wire `turnstile approve <id>` in `main.py` in this task) → the Slack guard lets the message through → `pass … ON_HUMAN_REVIEW --slack <permalink> --approved <ah-id>`. Add a test to `tests/test_pass.py`: `test_approve_sets_approved_at`.

- [x] **Step 4: Run** — `python3 -m unittest discover -s tests -v` — Expected: all PASS.

- [x] **Step 5: Commit** — `git add -A && git commit -m "feat(hooks): bash, slack and state-edit guards; turnstile approve"`

---

### Task 11: README usage section and version tag

**Files:**
- Modify: `README.md` (add "Usage" with the four commands and the hook list), `turnstile_cli/__init__.py` stays `0.1.0`.

- [x] **Step 1:** Add to README after "What you get":

```markdown
## Usage (core)

```
echo delivery > .turnstile                      # workspace root → delivery dir
turnstile status                                # reconcile with GitHub + where we are
turnstile pass pr jsfiller#13222 AI_REVIEW --head d2583e9b --ci success
turnstile pass pr jsfiller#13222 READY --head d2583e9b --deep-review reports/REVIEW-13222.md --rounds 3 --gate pdf-review:pass:<run-url>
turnstile approve ah-3                          # the lead said "send"
turnstile pass pr jsfiller#13222 ON_HUMAN_REVIEW --head d2583e9b --slack <permalink> --reviewers isachivka --approved ah-3
turnstile jira-synced jsfiller#13222 "On Review"
turnstile render-board
```

Exit code 2 and `MISSING …` lines mean the turnstile did not turn: nothing was written.
```

- [x] **Step 2:** `git add -A && git commit -m "docs: core usage" && git tag v0.1.0-core`

---

## Self-review

- **Spec coverage:** §2 artefacts/state → Tasks 1–2 (JSON instead of YAML, recorded in the spec). §3 PR lifecycle → Task 3 + 6. §4.2 story lifecycle → Task 4 + 6. §5 commands → Tasks 6, 7, 8, 9 (`init`, `dispatch`, `story-gate`, `plan` belong to plan 2). §6 hooks → Task 10 (Prometey empty-tag rule included; PR-body footer rule included). §10 testing → every task carries tests; hook tests in Task 10. §7 agents, §8 packaging beyond the manifest, §9 migration → plans 2 and 3.
- **Placeholders:** none; the one "note for the implementer" in Task 4 removes a dead loop and is explicit.
- **Type consistency:** `Options` field names equal argparse dests (`deep_review`, `not_clean`, `open_threads`, `cases_pass`, `cases_fail`, `figma_parity`, `merged_sha`, `no_commit`); `IO.renderer(data, delivery)` signature is the same in Task 6 and the fake in tests; `PrFacts` fields used in `reconcile.compare` exist in `github.PrFacts`; `rules.same_head` used by board JS is re-implemented in JS with the same prefix semantics.
- **Review Focus:** 1 → Task 3 head tests; 2 → Task 3 `test_copilot_required_only_when_enabled`; 3 → Task 3 `test_push_after_send_voids` + Task 8 `test_push_after_send_proposes_rework`; 4 → Task 2 `test_save_refuses_stale_file` + Task 6 `test_pass_refuses_stale_file`; 5 → Task 10 `test_slack_fails_closed_on_broken_state`.

## Deviations

- Task 6: `--gate name:result:run` keeps `:` inside the run URL (`":".join(parts[2:])`); the plan's `parts[2]` would truncate `https://…`.
- Task 6: `_apply_pr_evidence` keeps an already-set `approved_at` on the awaiting entry (set earlier by `turnstile approve`) instead of overwriting it.
- Task 7: no browser check; the four tabs/panes, viewport meta, scroll wrappers and absence of fixed widths were verified with a Python DOM check on the rendered HTML.
- Task 8: fixture `headRefOid` starts with the full 16-char state head `aaaaaaaa11111111`, not only `aaaaaaaa1111`: a 12-char prefix is not `same_head` with the 16-char state head. Recorded from jsfiller#13222; contexts trimmed to six, the real `pdf-review` StatusContext replaced by the CheckRun the plan asks for.
- Task 9: `test_status_without_network` runs the shim with a PATH that has no `gh` and asserts the `WARN` line; the plan assumed `gh` fails in the test environment, but on an authenticated machine it queried GitHub for real.
- Task 9: commit 47c9700 landed with that test still red (grep masked the exit code); fixed forward in 0afc7b7, no force-push.
- Task 10: `guard_slack` points to `turnstile approve <ah-id>` (the order in the plan's note), not `turnstile pass … --approved`.
- Task 10: `turnstile approve` is idempotent (already approved → `OK`, exit 0); unknown id → `MISSING`, exit 2.
