# Onboarding check: install from the public repo and start an epic (2026-10-30)

Scope: can another engineer install turnstile from `github.com/davepylypenko/turnstile` and start an epic, following only
`README.md`? Run on this machine with Claude Code 2.1.314 against an **isolated config dir** (`CLAUDE_CONFIG_DIR=/tmp/ts-onboard`,
honoured: it created its own `.claude.json`, `plugins/`, `settings.json`), never the lead's `~/.claude`. Heads checked:
`c483c35` (marketplace + shim + 0.3.0), `b07d775` (`pr add` + README). No GitHub, Slack or Jira writes; the only network calls
are the HTTPS clones Claude Code makes of the public repo.

## Findings that changed the code

| # | Finding | Fix (commit) |
|---|---|---|
| 1 | No `.claude-plugin/marketplace.json`: the README's `claude plugin marketplace add davepylypenko/turnstile` could not work | the repo is its own marketplace (`name: turnstile`, one plugin, `source: "./"`); `claude plugin validate .` passes (`c483c35`) |
| 2 | Nothing put the CLI on PATH after an install; the skill assumed a bare `turnstile` | `scripts/install-cli.sh` writes a `~/.local/bin/turnstile` shim that resolves the installed plugin at run time (`installed_plugins.json` → newest cache entry; `TURNSTILE_HOME` overrides); `init` writes the resolved CLI path into the workspace `CLAUDE.md`; SKILL.md names `${CLAUDE_PLUGIN_ROOT}/scripts/turnstile` (`c483c35`) |
| 3 | `${CLAUDE_PLUGIN_ROOT}` in skill text: verified by a throwaway plugin (`claude -p --model haiku --plugin-dir`, skill text `PATH=${CLAUDE_PLUGIN_ROOT}/scripts/turnstile`): the model received the absolute path, so the substitution happens in SKILL.md, not only in hooks | relied on in SKILL.md (`c483c35`) |
| 4 | No command registers a new PR: `pass pr <new id> …` answers `unknown PR`, so the README's "first `pass pr … AI_REVIEW`" was impossible for a fresh epic | `turnstile pr add <repo#n> --story S --ticket KEY` (facts from GitHub incl. the new `headRefName`; refuses a base that is not the story branch or another open PR of the story, a missing brief, an unapproved plan, a merged PR); the recorded PR passes `AI_REVIEW` in the tests (`e707275`) |
| 5 | `claude plugin update` acts on the manifest version only: after pushing `b07d775` the sandbox stayed on `c483c35` ("already at the latest version (0.3.0)") and lacked `pr add`; uninstall + install picked up `b07d775` | README note; **decision for the lead** (bump to 0.3.1 so installed users receive `pr add`, or accept that only fresh installs get it) |

Not changed: the validator's `ICON_MISSING` warning (listing icon only; no verdict impact).

## What the new engineer types (verified verbatim)

```
claude plugin install turnstile --marketplace davepylypenko/turnstile
sh ~/.claude/plugins/marketplaces/turnstile/scripts/install-cli.sh
turnstile --version
turnstile init --epic DEMO-1 --workitem demo-epic --knowledge ../knowledge --lead lead@example.com --lead-github leadlogin \
  --github-org example-org --repo '{"name":"app","base":"main","epic_branch":"epic/demo-1","slack":"C0123456789","gate":"pr-review","gate_check":null}' \
  --chat-language English
# fill delivery/plan.md (turnstile-stories block: title, tickets, repos, branch), then
turnstile plan-submitted
turnstile status
turnstile brief investigator INVESTIGATE-demo --var question=q --var where=app/src --var hypotheses=h --var answer_shape=table --var time_box=30m
turnstile render-board
```

## Verified live

- Two-step install (`marketplace add` + `install turnstile@turnstile`) and the one-step form (`install turnstile --marketplace …`) in two
  fresh config dirs; cache at `plugins/cache/turnstile/turnstile/0.3.0`, exec bits kept, `gitCommitSha` recorded; `claude plugin validate`
  on the installed copy passes; the marketplace clone (`plugins/marketplaces/turnstile`) holds the whole repo, so the shim installer has a
  version-independent path.
- The shim: `turnstile --version` → `turnstile 0.3.0` through `installed_plugins.json`; after `uninstall` + `install` the same shim serves
  the new copy (`b07d775`, `pr add --help` works) with no reinstall of the shim.
- Scratch workspace: `init` created the knowledge worktree on `epic/demo-1` (cut from the local `origin/main`), `delivery/` with
  `state.json`, `ledger.md`, `plan.md`, `decisions.md`, `briefs/ reports/ evidence/`, the `.turnstile` marker and a workspace `CLAUDE.md`
  whose CLI line is the shim path; `plan-submitted` first refused the unfilled template (`MISSING story S1 lacks 'title'`), then accepted a
  filled block and printed the lead's approve line; `status` listed `ah-1 plan` and `ah-2 start_story S1`; `brief investigator` rendered
  and committed; `render-board` wrote `board.html` (uncommitted until the next pass, as `status` says). Every commit in the worktree carries
  an SSH `gpgsig` (`git cat-file commit`); `git log --format=%G?` prints `N` only because no `allowedSignersFile` is configured locally.
- `python3 -m unittest discover -s tests`: 324 → 340 green (`install-cli` 5, `pr add` 4, `vendor` 3, tester credentials 3, init CLI path 1).

## Not verified

- The lead's approve line (`! TURNSTILE_LEAD=1 turnstile approve ah-1`): the lead's own act; an agent never runs it.
- `pr add` / `pass pr` against a real GitHub PR (no epic PR exists in the scratch org); covered by tests with canned facts.
- The hooks inside an interactive session started from the installed copy (`hooks.json` is unchanged since the 2026-10-14 live checks).
- A `claude plugin update` across a real version bump (0.3.0 → 0.3.1): not possible without tagging a new version.

## Transcripts

### Install from GitHub (config dir /tmp/ts-onboard)

```
$ claude --version
2.1.314 (Claude Code)
[exit 0]
$ claude plugin marketplace add davepylypenko/turnstile
Adding marketplace…SSH not configured, cloning via HTTPS: https://github.com/davepylypenko/turnstile.git
Refreshing marketplace cache (timeout: 120s)…
Cloning repository (timeout: 120s): https://github.com/davepylypenko/turnstile.git
Clone complete, validating marketplace…
Cleaning up old marketplace cache…
✔ Successfully added marketplace: turnstile (declared in user settings)
[exit 0]
$ claude plugin install turnstile@turnstile
Installing plugin "turnstile@turnstile"...✔ Successfully installed plugin: turnstile@turnstile (scope: user)
[exit 0]
$ cat /tmp/ts-onboard/plugins/installed_plugins.json
{
  "version": 2,
  "plugins": {
    "turnstile@turnstile": [
      {
        "scope": "user",
        "installPath": "/tmp/ts-onboard/plugins/cache/turnstile/turnstile/0.3.0",
        "version": "0.3.0",
        "installedAt": "2026-10-30T17:16:42.038Z",
        "lastUpdated": "2026-10-30T17:16:42.038Z",
        "gitCommitSha": "c483c3553990912db015e85df9af61219058bdd1"
      }
    ]
  }
}[exit 0]
$ claude plugin validate /tmp/ts-onboard/plugins/cache/turnstile/turnstile/0.3.0
Validating marketplace manifest: /tmp/ts-onboard/plugins/cache/turnstile/turnstile/0.3.0/.claude-plugin/marketplace.json

Plugin directory checks for /tmp/ts-onboard/plugins/cache/turnstile/turnstile/0.3.0. The plugin directory is the catalog that plugins are submitted to; this is a subset of what it runs.

⚠ Found 1 plugin directory warning:

  ❯ .claude-plugin/plugin.json icon: No icon (ICON_MISSING). No icon found in the plugin. The validator looked for `icon` in plugin.json and for a file at .claude-plugin/icon.png or .svg, assets/icon.png or .svg, or a similar path.
    Fix: Add a square PNG to the plugin folder at .claude-plugin/icon.png, or set `icon` in plugin.json to the path of a square PNG or JPEG in the plugin: 512 to 2048 px on each side, under 2 MB. SVG and WebP are not accepted. That file may become the listing icon only once: the first time the plugin is saved or submitted in the developer portal. Adding or changing it later does not change the icon.

About these checks:

  ❯ This folder also holds a marketplace manifest. The plugin directory treats such a folder as a plugin, so these checks cover only the plugin in this folder. To check another plugin that the marketplace lists, run validate on that plugin's folder.

These plugin directory checks do not change the result below.

The directory also runs a safety scan and a policy review that this command does not.

ℹ Advice (does not change the verdict):

  ❯ /tmp/ts-onboard/plugins/cache/turnstile/turnstile/0.3.0/README.md: This README has no line that installs "turnstile" from a marketplace. Add the install line, which works in one step on Claude Code 2.1.275 or later. In it, replace <owner>/<repo> with the repository that holds the marketplace.
      /plugin install turnstile --marketplace <owner>/<repo>

✔ Validation passed
[exit 0]
$ ls -l /tmp/ts-onboard/plugins/cache/turnstile/turnstile/0.3.0/scripts
total 24
-rwxr-xr-x  1 davyd  wheel  1597 Oct 30 19:16 install-cli.sh
-rwxr-xr-x  1 davyd  wheel   212 Oct 30 19:16 turnstile
-rwxr-xr-x  1 davyd  wheel  1571 Oct 30 19:16 vendor.sh
[exit 0]
$ ls /tmp/ts-onboard/plugins/marketplaces/turnstile/scripts
install-cli.sh
turnstile
vendor.sh
[exit 0]
$ sh /tmp/ts-onboard/plugins/marketplaces/turnstile/scripts/install-cli.sh /tmp/ts-onboard/bin
installed /tmp/ts-onboard/bin/turnstile
note: /tmp/ts-onboard/bin is not on PATH; add it to your shell profile, e.g. export PATH="/tmp/ts-onboard/bin:$PATH"
[exit 0]
$ which turnstile
/tmp/ts-onboard/bin/turnstile
[exit 0]
$ turnstile --version
turnstile 0.3.0
[exit 0]
$ claude plugin list
Installed plugins:

  ❯ turnstile@turnstile
    Version: 0.3.0
    Scope: user
    Status: ✔ enabled

[exit 0]
```

### Scratch workspace

```
$ turnstile init --epic DEMO-1 --workitem demo-epic --knowledge ../knowledge --lead lead@example.com --lead-github leadlogin --github-org example-org --repo {"name":"app","base":"main","epic_branch":"epic/demo-1","slack":"C0123456789","gate":"pr-review","gate_check":null} --chat-language English
WORKTREE: <scratch>/ws/knowledge (epic/demo-1)
DELIVERY: <scratch>/ws/knowledge/context/workitems/demo-epic/delivery
CLAUDE_MD: <scratch>/ws/CLAUDE.md
NEXT: write <scratch>/ws/knowledge/context/workitems/demo-epic/delivery/plan.md per references/kickoff.md, then: turnstile plan-submitted
OK init DEMO-1
[exit 0]
$ cat .turnstile
knowledge/context/workitems/demo-epic/delivery
[exit 0]
$ sed -n 1,6p CLAUDE.md
# DEMO-1 — orchestrator workspace

You are the orchestrator of epic **DEMO-1**. The delivery state lives in `knowledge/context/workitems/demo-epic/delivery/` (`state.json`,
`ledger.md`, `plan.md`, `decisions.md`, `briefs/`, `reports/`, `evidence/`, `board.html`) on the epic branch of the
knowledge worktree. Plugin: `turnstile` — invoke the `turnstile` skill first in every session; it starts with
`turnstile status`. CLI: `/tmp/ts-onboard/bin/turnstile` (`turnstile` below means this path when the bare name is not on PATH).
[exit 0]
$ git -C knowledge log --oneline -3
d5aee47 turnstile: init DEMO-1
7ec0d31 init
[exit 0]
$ turnstile plan-submitted
MISSING story S1 lacks 'title'
[exit 2]
$ turnstile status
== DEMO-1
plan: not submitted (turnstile plan-submitted)
awaiting humans: 0
== reconcile: 0 discrepancy(ies)
[exit 0]
$ turnstile brief investigator INVESTIGATE-demo --var question=v --var scope=v --var files=v
MISSING placeholder answer_shape (pass --var answer_shape=...)
MISSING placeholder hypotheses (pass --var hypotheses=...)
MISSING placeholder time_box (pass --var time_box=...)
MISSING placeholder where (pass --var where=...)
[exit 2]
$ turnstile render-board
OK rendered <scratch>/ws/knowledge/context/workitems/demo-epic/delivery/board.html
[exit 0]
$ git -C knowledge log --oneline -5
d5aee47 turnstile: init DEMO-1
7ec0d31 init
[exit 0]
$ git -C knowledge status --porcelain
?? context/workitems/demo-epic/delivery/board.html
[exit 0]
$ turnstile status
== DEMO-1
plan: not submitted (turnstile plan-submitted)
awaiting humans: 0
uncommitted changes in delivery (1 file(s)): board.html — a write outside turnstile; the next pass commits it, reconcile it first
== reconcile: 0 discrepancy(ies)
[exit 0]
(plan.md: S1 title/tickets/repos/branch/test_cases filled in the turnstile-stories block)
$ turnstile plan-submitted
PLAN: 1 stories (1 new)
APPROVAL: the lead types: ! TURNSTILE_LEAD=1 turnstile approve ah-1
OK plan submitted: 1 stories (1 new: S1), approval ah-1
[exit 0]
$ turnstile status
== DEMO-1
plan: awaiting approval ah-1
story S1 [PLANNED] First slice — wait for the lead to start it
awaiting humans: 2
  ah-1 lead plan plan.md
  ah-2 lead start_story S1
== reconcile: 0 discrepancy(ies)
[exit 0]
$ turnstile brief investigator INVESTIGATE-demo --var question=q --var where=app/src --var hypotheses=h --var answer_shape=table --var time_box=30m
AGENT: turnstile:investigator
BRIEF: <scratch>/ws/knowledge/context/workitems/demo-epic/delivery/briefs/INVESTIGATE-demo.md
REPORT: <scratch>/ws/knowledge/context/workitems/demo-epic/delivery/reports/INVESTIGATE-demo.md
PROMPT: Read and execute <scratch>/ws/knowledge/context/workitems/demo-epic/delivery/briefs/INVESTIGATE-demo.md. Write your report to <scratch>/ws/knowledge/context/workitems/demo-epic/delivery/reports/INVESTIGATE-demo.md. Reply with at most 8 lines.
OK brief INVESTIGATE-demo for investigator
[exit 0]
$ turnstile render-board
OK rendered <scratch>/ws/knowledge/context/workitems/demo-epic/delivery/board.html
[exit 0]
$ git -C knowledge log --oneline -5
9c99f42 turnstile: brief INVESTIGATE-demo for investigator
c9fe132 turnstile: plan submitted: 1 stories (1 new: S1), approval ah-1
d5aee47 turnstile: init DEMO-1
7ec0d31 init
[exit 0]
$ git -C knowledge status --porcelain
[exit 0]
$ ls <scratch>/ws/knowledge/context/workitems/demo-epic/delivery <scratch>/ws/knowledge/context/workitems/demo-epic/delivery/briefs
<scratch>/ws/knowledge/context/workitems/demo-epic/delivery:
board.html
briefs
decisions.md
evidence
ledger.md
plan.md
reports
state.json

<scratch>/ws/knowledge/context/workitems/demo-epic/delivery/briefs:
INVESTIGATE-demo.md
[exit 0]
```

### One-step install (config dir /tmp/ts-onboard-onestep)

```
$ claude plugin install turnstile --marketplace davepylypenko/turnstile
Adding marketplace…
SSH not configured, cloning via HTTPS: https://github.com/davepylypenko/turnstile.git
Refreshing marketplace cache (timeout: 120s)…
Cloning repository (timeout: 120s): https://github.com/davepylypenko/turnstile.git
Clone complete, validating marketplace…
✔ Successfully added marketplace: turnstile (declared in user settings)
Installing plugin "turnstile@turnstile"...✔ Successfully installed plugin: turnstile@turnstile (scope: user)
[exit 0]
$ claude plugin list
Installed plugins:

  ❯ turnstile@turnstile
    Version: 0.3.0
    Scope: user
    Status: ✔ enabled

[exit 0]
$ sh /tmp/ts-onboard-onestep/plugins/marketplaces/turnstile/scripts/install-cli.sh /tmp/ts-onboard-onestep/bin
installed /tmp/ts-onboard-onestep/bin/turnstile
note: /tmp/ts-onboard-onestep/bin is not on PATH; add it to your shell profile, e.g. export PATH="/tmp/ts-onboard-onestep/bin:$PATH"
[exit 0]
$ /tmp/ts-onboard-onestep/bin/turnstile --version
turnstile 0.3.0
[exit 0]
```

### Update semantics

```
$ claude plugin marketplace update turnstile
Updating marketplace: turnstile...Refreshing marketplace cache (timeout: 120s)…
Cloning repository (timeout: 120s): https://github.com/davepylypenko/turnstile.git
Replacing the existing marketplace clone…
Clone complete, validating marketplace…
✔ Successfully updated marketplace: turnstile
[exit 0]
$ claude plugin update turnstile@turnstile
Checking for updates for plugin "turnstile@turnstile"…
✔ turnstile is already at the latest version (0.3.0).
[exit 0]
$ python3 -c import json;e=json.load(open('/tmp/ts-onboard/plugins/installed_plugins.json'))['plugins']['turnstile@turnstile'][0];print(e['installPath'], e['gitCommitSha'])
/tmp/ts-onboard/plugins/cache/turnstile/turnstile/0.3.0 c483c3553990912db015e85df9af61219058bdd1
[exit 0]
$ git -C /tmp/ts-onboard/plugins/marketplaces/turnstile log --oneline -1
b07d775 docs(readme): prerequisites, one-step install with the PATH shim, a new lead's first hour
[exit 0]
$ turnstile --version
turnstile 0.3.0
[exit 0]
$ turnstile pr add --help
usage: turnstile [-h] [--version] [--delivery DELIVERY]
                 {pass,jira-synced,approve,render-board,reconcile,status,bug,threads,brief,plan-submitted,init}
                 ...
turnstile: error: argument cmd: invalid choice: 'pr' (choose from 'pass', 'jira-synced', 'approve', 'render-board', 'reconcile', 'status', 'bug', 'threads', 'brief', 'plan-submitted', 'init')
[exit 2]
$ ls /tmp/ts-onboard/plugins/cache/turnstile/turnstile/
0.3.0
[exit 0]
## reinstall in the one-step sandbox (same version, new commit)
$ claude plugin uninstall turnstile@turnstile
✔ Successfully uninstalled plugin: turnstile (scope: user)
[exit 0]
$ claude plugin marketplace update turnstile
Updating marketplace: turnstile...Refreshing marketplace cache (timeout: 120s)…
Cloning repository (timeout: 120s): https://github.com/davepylypenko/turnstile.git
Replacing the existing marketplace clone…
Clone complete, validating marketplace…
✔ Successfully updated marketplace: turnstile
[exit 0]
$ claude plugin install turnstile@turnstile
Installing plugin "turnstile@turnstile"...✔ Successfully installed plugin: turnstile@turnstile (scope: user)
[exit 0]
$ python3 -c import json;e=json.load(open('/tmp/ts-onboard-onestep/plugins/installed_plugins.json'))['plugins']['turnstile@turnstile'][0];print(e['installPath'], e['gitCommitSha'])
/tmp/ts-onboard-onestep/plugins/cache/turnstile/turnstile/0.3.0 b07d7756d6269133f3fc3cb8e8ac4670bbedbd2f
[exit 0]
$ /tmp/ts-onboard-onestep/bin/turnstile --version
turnstile 0.3.0
[exit 0]
$ /tmp/ts-onboard-onestep/bin/turnstile pr add --help
usage: turnstile pr add [-h] --story STORY --ticket TICKET [--no-commit] ident

positional arguments:
  ident

optional arguments:
  -h, --help       show this help message and exit
  --story STORY
  --ticket TICKET
  --no-commit
[exit 0]
```
