# Turnstile

**Evidence-gated delivery for AI agent teams.** A Claude Code plugin that runs a multi-repo epic through a strict
state machine: every PR and every story moves to the next stage only with a valid ticket, and the ticket is evidence
(head SHA + gate result) that a script checks. No ticket, no entry.

Why it exists: when an orchestrating agent coordinates implementers, reviewers and testers across several repositories,
prose rules erode under pressure. Stages blur ("AI review" quietly becomes "human review"), boards go stale, Jira lags,
and context is lost between sessions. Turnstile moves the rules out of prose and into a state file, a transition
command, role-scoped agents and hooks that physically block forbidden actions.

## Prerequisites

- Claude Code **2.1.275 or later** (one-step marketplace install; verified on 2.1.314).
- Python **3.9+**, standard library only (the CLI, the hooks and the tests import nothing else).
- `gh` CLI **authenticated** (`gh auth status`): every `pass pr`, `pr add`, `threads` and `reconcile` reads the PR from GitHub.
- git with **SSH commit signing** on (`gpg.format=ssh`, `commit.gpgsign=true`, a signing key): the Bash guard refuses
  `--no-gpg-sign`, and `pass` refuses a PR with an unsigned commit. `gpg.ssh.allowedSignersFile` is not needed.
- A **knowledge repository** (any git clone with an `origin`) that will hold `delivery/` on an epic branch.
- Optional, only if sends are to be recorded: Slack through an MCP whose tools match `mcp__*slack_send_message*` /
  `slack_schedule_message` (the `slack` plugin of the official marketplace does); Jira through an MCP exposing
  `transitionJiraIssue` / `editJiraIssue` / `createJiraIssue` / `addCommentToJiraIssue` and the reads `atlassianUserInfo` /
  `getJiraIssue` (the Atlassian connector does).
- A **send skill** on the developer's machine that posts a PR to the Slack review channel (default `/send-pr-review`: Ivan
  Zolotukhin's skill in `pdffiller-knowledge`, installed with
  `ln -s <pdffiller-knowledge clone>/playground/zolotukhin-ivan/skills/send-pr-review ~/.claude/skills/send-pr-review`).
  The plugin holds only its name (`send_skill`); `init` and `status` say when it is not found.

## Install

```
claude plugin install turnstile --marketplace davepylypenko/turnstile       # adds the marketplace and installs the plugin
sh ~/.claude/plugins/marketplaces/turnstile/scripts/install-cli.sh          # writes the `turnstile` shim into ~/.local/bin
turnstile --version                                                         # turnstile 0.5.1 (add ~/.local/bin to PATH if the script says so)
claude plugin validate ~/.claude/plugins/marketplaces/turnstile             # optional: ✔ Validation passed
```

Two-step equivalent of the first line: `claude plugin marketplace add davepylypenko/turnstile && claude plugin install turnstile@turnstile`.
The shim resolves the installed plugin at every run (from `installed_plugins.json`, else the newest plugin cache entry),
so `claude plugin update turnstile@turnstile` needs no reinstall. That update acts on a changed `version` in `plugin.json`
only; to pick up a same-version push: `claude plugin uninstall turnstile@turnstile && claude plugin install turnstile@turnstile`.
Without the shim the CLI is
`~/.claude/plugins/cache/turnstile/turnstile/<version>/scripts/turnstile`, and the skill names it as
`${CLAUDE_PLUGIN_ROOT}/scripts/turnstile`. Development from a clone: `claude --plugin-dir <clone>` and
`TURNSTILE_HOME=<clone>` for the shim.

## Getting started (a new lead's first hour)

1. Install (above). Keep your clones side by side in one folder, the **clone root** (e.g. `~/Desktop/pdffiller/` holding
   `pdffiller-knowledge/`, `jsfiller/`, `docs-platform/`, …).
2. Create the epic from a terminal **in the clone root** (or inside the knowledge clone). `init` detects the root, creates the
   workspace folder `<root>/<epic key, lower case>` and fills it: a worktree of the knowledge clone on `epic/<key>` (cut from
   `origin/main`) and, for every `--repo`, a worktree of `<root>/<name>` on the per-workspace branch `ws/<key>`, cut from
   `origin/<base>` after a fetch (the shared base is never checked out, so the main clone may hold it). `--knowledge <clone>` is
   needed only when the clone is not `<root>/pdffiller-knowledge`, `--clone-root <dir>` when you run it elsewhere, `"path"` in a
   `--repo` JSON when a clone is not `<root>/<name>`:

   ```
   cd ~/Desktop/pdffiller
   turnstile init --epic MYD-1 --workitem my-epic \
     --lead you@example.com --lead-github <your login> --github-org <org> \
     --repo '{"name":"jsfiller","base":"develop","slack":"C0123456789","gate":"pdf-review","ci_ignore":["pdf-review","gate / gate"]}' \
     --chat-language English
   ```

   ```
   ~/Desktop/pdffiller/                ← clone root (run `turnstile init` here)
     pdffiller-knowledge/  jsfiller/  docs-platform/ …   ← your clones
     myd-1/                            ← created by init: the workspace you open in Claude Code
       .turnstile  CLAUDE.md
       pdffiller-knowledge/            ← worktree epic/myd-1 → context/workitems/my-epic/delivery/
       jsfiller/                       ← worktree ws/myd-1 from origin/develop
       docs-platform/                  ← …
   ```

   It prints `WORKSPACE`, `WORKTREE`, one `REPO:` line per repo, `DELIVERY`, `CLAUDE_MD`, `CONFIG`, `SEND_SKILL` (where the send skill
   was found, or the install line and a `NEXT` to ask the lead which skill to use) and `NEXT`, writes `.turnstile`
   (workspace → delivery dir), a workspace `CLAUDE.md` for the orchestrator (the CLI path and the repo worktrees), the git-ignored
   `delivery/.workspace.json` (this machine's absolute paths; `state.json` keeps only the relative names, `epic.repos.<r>.path`) and
   commits the `delivery/` skeleton. A workspace folder that exists and is not empty is refused, unless it already is this epic's
   workspace (then `init` attaches); a repo without a clone is refused with the expected path before anything is created.
   Then open the workspace: `cd ~/Desktop/pdffiller/myd-1 && claude` — the hooks and `.turnstile` live there; the terminal or
   Claude Code session in the clone root cannot drive the epic. Agents cut ticket branches inside `<workspace>/<repo>` from
   `origin/<base>` (or the story branch), never from `ws/*`; `turnstile brief … --var repo=<name>` renders that worktree's path.
3. Write `delivery/plan.md` (`skills/turnstile/references/kickoff.md`; in Claude Code the orchestrator does this from the
   decomposition). The `turnstile-stories` JSON block needs at least `title`, `tickets`, `repos` and `branch` per story.
   Then `turnstile plan-submitted` → `APPROVAL: the lead types: ! TURNSTILE_LEAD=1 turnstile approve ah-1`.
4. Approve it by typing `! TURNSTILE_LEAD=1 turnstile approve ah-1` in the Claude Code prompt (never through the model).
   `turnstile status` now lists `ah-2 lead start_story S1`; approve that the same way when the story may start, then
   the orchestrator records `turnstile pass story S1 IN_PROGRESS --approved ah-2`.
5. First ticket: `turnstile brief implementer MYD-2 --var ticket_key=MYD-2 --var repo=app --var ...` (it prints
   `MISSING placeholder <name> (pass --var <name>=...)` for every variable still missing, then `AGENT:` and `PROMPT:`); the
   orchestrator launches `Agent(subagent_type: "turnstile:implementer", prompt: <the PROMPT line>)` — `/turnstile` in
   Claude Code drives steps 3–7 for you.
6. The implementer reports a draft PR: `turnstile pr add app#12 --story S1 --ticket MYD-2` records it as `DEV` (head,
   branch and base from GitHub; refused when the base is not the story branch); with CI green,
   `turnstile pass pr app#12 AI_REVIEW --head <sha> --ci success`. On `MISSING …` nothing was written.
7. `turnstile status` (reconcile against GitHub + what awaits the lead) and `turnstile render-board` (`delivery/board.html`;
   publish it as a claude.ai artifact and pass its url to `init --board-url` so every `pass` prints `BOARD: publish …`).

Verified end to end on 2026-10-30 (`docs/superpowers/reviews/2026-10-30-onboarding-check.md`).

## Trunk mode (one flag per epic)

Recommended for new epics: `init --story-mode trunk --flag <experiment flag>` (`epic.flag`; later `config set flag=<name> --epic`). Every PR goes
straight into the repo base (`epic.repos.<r>.base`) behind that one flag — `pr add` refuses another base unless `--stacked-on <pr>`
names a deliberate stack — and flows `DEV → … → MERGED` on its own: the story gates are not a prerequisite for `ON_HUMAN_REVIEW`
(the old `human_review: per_pr` keeps working for migrated stories). The story gates come **after** the merges: `pass story S
INTEGRATION_REVIEW --build <n> --head <base sha> [--base-heads repo=sha,…]` records a deploy of the base and verifies on GitHub
(`compare` status `identical`/`ahead`) that every merged PR's merge commit is contained in it and no PR is still open; the
story-reviewer reviews the union of the merged diffs on that head. `ENV_TESTING` records two arms on the same head:
`--arm treatment` (flag on, `stories.<S>.test_cases`) and `--arm control` (flag off, `stories.<S>.control_cases`, parity may be
`not_testable_here`); bugs carry `--arm`. `DONE` needs the last run of **each** arm full and clean on the deploy head, every bug
done and every PR merged. `plan.md` stories take `"mode": "trunk" | "stack"` (default `epic.story_mode`, `stack` for old
epics — stack mode behaves exactly as before) and `"control_cases"`. The tester toggles the flag only as the environment recipe's
§ Feature flag says (unknown → `BLOCKED`). `epic_branch` in `--repo` is optional now (defaults to the base) and is recorded only.

## Continuing someone else's epic

`turnstile attach --epic MYD-1 [--clone-root <dir>] [--knowledge <clone>] [--workspace <dir>] [--workitem my-epic]`, run in your
own clone root (or inside your knowledge clone), creates `<root>/<key>` the same way: it fetches `origin/epic/<key>`, adds the
knowledge worktree inside the workspace (fast-forwarded to origin), finds the delivery dir, adds a `ws/<key>` worktree of your
`<root>/<name>` clone for every `epic.repos` entry (a missing clone is refused with its expected path), writes `.turnstile`,
`delivery/.workspace.json` and the workspace `CLAUDE.md` (an existing one is kept; `CLAUDE.md.turnstile` is written instead) and
prints `status`; then `cd <workspace> && claude`, where the skill's `## preferences` step asks for this person's own
review skill, send skill and models. Every writer first fetches: a worktree
behind origin is refused (`MISSING: epic branch behind origin by N commits — run: turnstile sync`). `turnstile sync` fetches,
fast-forwards and pushes — never rebase, never force; diverged histories print both heads and wait for the lead to merge.

## Several developers on one epic

The delivery state lives on the epic branch, so every developer drives the same epic from their own machine: one `turnstile attach --epic MYD-1 --github <login>` each. `epic.members.<login>` holds a developer's
Prometey variant (default `<key>-<login>`), desk and board artifact, so one developer's deploys never overwrite another's variant and `BOARD: publish` points at an artifact that developer can update. The
member of a machine is the `member` in its untracked `delivery/.workspace.json`; `status` prints it, `turnstile board-url <url>` records the board artifact. Every writer fetches first and a worktree behind origin is
refused until `turnstile sync` (never rebase, never force). `turnstile pr add` and `turnstile pass story … IN_PROGRESS` record the member as the `owner` of the PR or story (`--owner <login>` overrides); every write renders `delivery/board.html` (everything) and `delivery/boards/<login>.html` per member, with only that member's stories, PRs, bugs and awaiting entries. Every developer publishes their own file to their own artifact. Approvals (`turnstile approve`) stay with
the lead only.

## What you get

- `state.json` — a single source of truth for the epic, in git, readable by any session or person. Every write is
  committed to the epic branch of the knowledge repo and pushed to origin at once (`SYNC:` opens every `status`; a failed
  push is a `WARN` plus `turnstile sync`; `--no-push` for offline work, after which READY and beyond wait for a sync).
- `turnstile pass` — the only way to change state; validates DoR/DoD, verifies the PR head against GitHub, then writes
  the ledger, renders the board, commits the state and tells you which Jira transition to make and, on take-up, to assign
  the ticket to yourself when nobody holds it yet (the orchestrator's own Atlassian account, recorded with `jira-synced
  --assignee`); the plugin never moves a ticket away from its holder, and `jira-synced --assignee` records a hand-over made by hand.
- `turnstile reconcile` — read-only drift check against GitHub; every command it proposes is one `pass` would accept.
- `turnstile threads` — records each human review thread as `self_resolved` (the agent replies at once) or `needs_lead`
  (the reply waits for the lead's word on that thread), from GitHub facts.
- `turnstile init` / `plan-submitted` / `brief` / `bug add|set` — the epic skeleton, the lead-approved plan (a re-plan cannot
  move a started story's branch), agent briefs and the bug list (one bug per story + test case), all written through the
  same guarded path as `pass`.
- Skill `turnstile` (`skills/turnstile/SKILL.md`): `init`, `status`, `pass`, `dispatch <agent> <brief>`, `story-gate <S>`,
  `plan`; references for DoR/DoD, kick-off, briefs, PR body, Slack, reports, evidence and env recipes.
- Role agents: implementer, gate-runner, reviewer, story-reviewer, stack-step, comments-handler, investigator, tester, deployer.
  Tester credentials never touch a file: the tester reads `TURNSTILE_TEST_PASSWORD` or the keychain item
  `turnstile-test-password` at login (`skills/turnstile/references/env/pdffiller-dev.md` § Credentials).
- Hooks that record Slack sends (never blocking them) and block merges, reviewer requests, force pushes, PR comments,
  review submissions, resolving human threads and manual state edits unless the lead approved that exact action; a reply to a reviewer thread passes only for
  a classified thread (at once when the agent resolved it, with the lead's word when it needs the lead), and the re-request
  of a REWORK PR's thread authors passes once every thread has its reply and the head is clean (lead rule 2026-10-14).
- Story gates: whole-story deep review and environment testing against the test plan and the Figma design, before
  anything reaches human review.
- Token discipline (lead rules 2026-10-19, 2026-10-26): every agent's model and effort come from the plugin defaults
  (`models.DEFAULTS`: implementer, deployer, tester sonnet; stack-step, comments-handler, investigator haiku;
  reviewer opus high; story-reviewer opus xhigh); `epic.models` (`init --models`, `config set --epic`) holds only
  overrides, and `turnstile brief` prints the result on its `AGENT:` line; agents start
  one at a time, in parallel only across different repositories; waiting on GitHub or CI goes through `Monitor` or a background command,
  never a cron or watchdog, with no interim "still waiting" messages to the lead; the repo gate runs once per head and is
  re-run only for P1/P2 findings; the orchestrator dispatches and never reads diffs or runs suites itself.
  Cache-read cost is driven by long contexts and wake-ups, so: agents wait on CI, a deploy or a gate with ONE blocking command
  (`gh run watch --exit-status`, `gh pr checks --watch`) and never end a turn with a "waiting" message; the `gate-runner` (sonnet)
  runs the repo gate on a fresh head before the reviewer, who re-runs it only if it pushes; reviewer round 2 and later is a delta review
  (`{{round_mode}}` is filled from the `-r<n>` brief name; aim ≤ 80 tool calls); the orchestrator reads only an agent's reply,
  publishes the board once per batch through a haiku subagent (`references/board.md`), starts a new session each day, runs `/compact`
  past ~150 k and uses `turnstile status --brief` (only what changed since the previous status).

### Per-person overrides

Three layers, highest first: **user** (`~/.config/turnstile/config.json`, or `$TURNSTILE_USER_CONFIG`; per person,
never in git) > **epic** (`epic.models`, `epic.review_skill`, `epic.story_review_skill`, `epic.send_skill` in `state.json`, written through
the same guarded commit path as `pass`) > **plugin defaults**. `turnstile config list` prints every effective value with its source;
`turnstile config set <key>=<value>` writes the user file at once; `--epic` proposes the change as an `awaiting_human` entry of
type `config` (old and new value) that the lead approves with the usual line, after which `turnstile config apply <ah-id>` commits
it; `turnstile config unset <key> [--epic]` (or `=default`) resets. `TURNSTILE_USER_CONFIG` is the lead's shell variable: the Bash
guard refuses it in any model-issued command, and the CLI accepts only a `.json` path outside every git checkout or workspace. Keys: `models.<agent>` (`<model>` or `<model>:<effort>`), `review_skill`, `story_review_skill`, `send_skill`.
`review_skill` is the skill the `reviewer` agent runs for the deep review (the `--deep-review` report), `story_review_skill`
the story-reviewer's; `/code-review` is invoked with the agent's own effort level as its argument (`/code-review high` by default for the reviewer, `xhigh` for the story-reviewer), any other skill bare, exactly as the brief prints it; neither replaces the repo gate CI check (`epic.repos.<r>.gate` / `gate_check` stay the READY evidence).
`send_skill` (default `/send-pr-review`) is the slash command the orchestrator invokes to post a READY PR to Slack review — a skill
that lives on the developer's machine, never in the plugin: the name is resolved as `~/.claude/skills/<name>/SKILL.md` or
`~/.claude/commands/<name>.md` (`$CLAUDE_CONFIG_DIR` replaces `~/.claude` when set), then the same two under `.claude/` of the cwd,
the workspace and the clone root, then the plugin cache `~/.claude/plugins/cache/*/*/*/skills/<name>/SKILL.md` and
`…/commands/<name>.md`; `/plugin:skill` looks only in that plugin's cache entries, at any depth below the version folder (a
`skills/<group>/<skill>/SKILL.md` layout included) and in its `commands/<skill>.md`. A lookup never fails: an unreadable or missing
folder is skipped. `init` prints `SEND_SKILL: … (found: <path>)` or the install line plus a `NEXT` to ask the lead which skill to
use; `status` prints one `WARN: send skill … not found` line while it is missing and its `config:` line shows the effective
(user-aware) value; the READY hint and the story DONE hint in `state.json` name the epic or default skill, never the user file's
(the state is shared, the user file is personal; `config apply` of `send_skill` recomputes the hints). The skill picks the channel
and the format and shows the draft; when the epic
sets `epic.repos.<repo>.slack`, the orchestrator passes that channel explicitly (the explicit channel wins); the lead's word in
chat stays the only gate, then `pass … --slack <permalink> --reviewers …` records the send. Without an installed skill the
templates in `skills/turnstile/references/slack.md` are the fallback and the orchestrator asks the lead which skill to install or use. `repos.<repo>.slack` stays required at `init`.
The skill's `## preferences` step asks the lead once, right after `init`, and maps later chat instructions to these commands.

```
turnstile config set review_skill=/my-review
turnstile config set send_skill=/my-send
turnstile config set models.reviewer=sonnet:medium
```

## Usage

```
cd ~/Desktop/pdffiller                                     # the clone root: pdffiller-knowledge/, jsfiller/, front-link2fill-app/ … side by side
turnstile init --epic MYD-16538 --workitem pdfd-429-l2f-editor-funnel \
  --lead davyd.pylypenko --lead-github <login> [--agent-github <login the agents' gh posts as>] --github-org pdffiller \
  --repo '{"name":"jsfiller","base":"develop","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CCGLRULNR","gate":"pdf-review","ci_ignore":["pdf-review","gate / gate"]}' \
  --repo '{"name":"front-link2fill-app","base":"master","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CFZ7EC5BN","gate":"pr-review","gate_check":null,"copilot":true}' \
  --variant l2f-funnel --desk desk05 --chat-language Ukrainian          # creates ~/Desktop/pdffiller/myd-16538/ with a worktree per repo (ws/myd-16538 from origin/<base>)
cd ~/Desktop/pdffiller/myd-16538 && claude                 # the workspace: hooks, .turnstile and the orchestrator CLAUDE.md live here
# write delivery/plan.md (skill: references/kickoff.md), then
turnstile plan-submitted                                   # the lead: ! TURNSTILE_LEAD=1 turnstile approve ah-1
turnstile brief implementer MYD-18075 --var ticket_key=MYD-18075 --var ...   # then Agent(turnstile:implementer, PROMPT line)
turnstile bug add --story S1 --case TP-004 --title "Share visible on published Create form" --source "tester 2026-10-13" --figma KOew:9098-41434
turnstile pass story S1 ENV_TESTING --report reports/ENV-S1.md --cases-pass 30 --cases-fail 1 --failed-cases TP-004 --figma-parity pass --build 173111 --head <stack-top sha>
turnstile bug set b01 --state done
turnstile pass story S1 INTEGRATION_REVIEW --build 173120 --head <new stack-top sha>   # re-entry after fixes: records the redeploy; review again on that head
turnstile pass story S1 ENV_TESTING --report reports/ENV-S1.md --cases-pass 31 --cases-fail 0 --figma-parity pass --build 173120 --head <new stack-top sha> --full
echo delivery > .turnstile                      # workspace root → delivery dir (init writes it; by hand for an existing delivery dir)
turnstile status                                # reconcile with GitHub + where we are (exit 1 when gh facts are missing)
turnstile pr add jsfiller#13222 --story S1 --ticket MYD-18075   # a new draft PR enters as DEV (head, branch, base from GitHub); prints "JIRA: MYD-18075 → In progress · assignee: you"
turnstile jira-synced jsfiller#13222 "In progress" --assignee 5f1a…c3 --assignee-name "Davyd Pylypenko"   # transitioned and assigned to the orchestrator's own account (atlassianUserInfo)
turnstile pass pr jsfiller#13222 AI_REVIEW --head d2583e9b --ci success
turnstile pass pr jsfiller#13222 READY --head d2583e9b --deep-review reports/REVIEW-13222.md --rounds 3 --gate pdf-review:pass:<run-url>
# the lead says "send" in chat; the message goes out through the send skill (/send-pr-review <url>; the PostToolUse hook records it), then
turnstile pass pr jsfiller#13222 ON_HUMAN_REVIEW --head d2583e9b --slack <permalink> --reviewers isachivka
turnstile jira-synced jsfiller#13222 "On Review"
turnstile pass pr jsfiller#13222 REWORK --reason "human thread r4231213730"      # opens no entry
turnstile threads jsfiller#13222 --self-resolved PRRT_kwDOa --needs-lead PRRT_kwDOc --report reports/COMMENTS-13222.md   # one 'reply' entry per needs_lead thread
gh api -X POST repos/pdffiller/jsfiller/pulls/13222/comments/2412345678/replies -f body='Fixed in 9f1c2a3b'   # self_resolved: at once
! TURNSTILE_LEAD=1 turnstile approve ah-3       # the lead's word on the needs_lead thread (typed in the Claude Code prompt; agents never do); then its reply goes out
gh api -X POST repos/pdffiller/jsfiller/pulls/13222/requested_reviewers -f 'reviewers[]=isachivka'   # all replied + head clean: re-request the thread authors
turnstile pass pr jsfiller#13222 ON_HUMAN_REVIEW --head 9f1c2a3b --ci success --gate pdf-review:pass --rerequested isachivka   # no --slack from REWORK
turnstile pass pr jsfiller#13222 APPROVED --approvals isachivka --open-threads 0
turnstile pass pr jsfiller#13222 MERGED --merged-sha <sha>
turnstile pass story S1 IN_PROGRESS --approved ah-1                              # the lead's start_story word; no --reason bypass
turnstile pass story S1 INTEGRATION_REVIEW --build 173111 --head <stack-top sha>
turnstile pass story S1 ENV_TESTING --report reports/STORY-S1-review.md --head <stack-top sha> --rounds 2
turnstile pass story S1 DONE --approved ah-9                                     # last run full, 0 fails, parity pass, env_test.head == deploy.head == stack top
turnstile render-board
```

Exit code 2 and `MISSING …` lines mean the turnstile did not turn: nothing was written. The state, ledger and board
are written only after the rules pass, and restored if the git commit fails (`MISSING git commit failed: …`).

### Heads and GitHub

Every PR pass asks GitHub for the PR's facts (`gh api graphql`): head, status rollup, check contexts, latest reviews,
unresolved threads, merge state. The pass is refused when the recorded `--head` (or the stored head) is not the real
one, when `gh` fails, and when the evidence contradicts GitHub for that head: `--ci success` with a rollup that is not
success, `--gate <name>:pass` while that StatusContext/CheckRun is pending, failed or absent, `--copilot 0` with open
Copilot threads, `--approvals a,b` with a login missing from `latestReviews` for the head, unresolved human threads or
changes requested at APPROVED, `MERGED` while GitHub shows the PR open, any unsigned commit in the PR, a PR base that is not the recorded `base`. Self-reported evidence never outranks GitHub. The gate's GitHub context is `epic.repos.<repo>.gate_check` (default: the gate name; `null` for a skill gate that posts no check, e.g. `pr-review`, where the report file is the evidence). Entering AI_REVIEW, CI is the check contexts minus `ci_ignore` (default: the gate's context; jsfiller/docs-platform: `["pdf-review", "gate / gate"]`), because the gate runs during AI_REVIEW; from READY on the whole rollup must be green. `--offline` skips the check with a loud `WARN` line and records
`evidence.head_verified: false`; `READY` and `ON_HUMAN_REVIEW` stay refused until a pass runs online for that head.
Every commit message is checked for a `Co-Authored-By` trailer or the generated-with footer and the PR body for the
footer (R3-10). From REWORK, ON_HUMAN_REVIEW requires, for every human thread opened since the send
(`evidence.human.sent_at`) and every unresolved one, a classification (`prs.<id>.threads`) that covers the reviewer's last
comment and a reply newer than that comment: by `epic.roles.agent_github` (default `lead_github`) for `self_resolved`, after
the lead approved the thread's `reply` entry for `needs_lead` (a reply from the lead's own login, when it differs from the
agents', also settles it). `--slack`, `--approved` and `--reviewers` are refused on that pass: the replies notify the
reviewers, and only `needs_lead` threads wait for the lead. A thread-driven rework (a reviewer commented on a thread since the
PR last went to humans) also needs `--rerequested <logins>`: exactly those reviewers, each with a GitHub review request newer than
our last reply on their threads and than the clean signal on the head (Copilot's review of it, else the gate check's completion),
still pending in `reviewRequests` or answered by a review of the head. It records `evidence.human.rerequested = {logins, head, at}`
and `reviewer_notified: true`. A push-only rework takes no `--rerequested` and records `reviewer_notified: false`.

### Review threads (lead rule 2026-10-14)

"If a reviewer left a comment and you resolved it yourself, reply immediately without asking; stop only on comments that
need the lead's decision or involvement." The comments-handler classifies every human thread and records it with
`turnstile threads <repo#n> --self-resolved <ids> --needs-lead <ids> [--report reports/COMMENTS-<n>.md]` (REWORK only; ids
are `PRRT_…` thread ids or REST comment ids, checked against GitHub: human thread, reviewer comment present). `self_resolved`
= fixed in code or answered with a code-level justification: the agent replies at once through
`gh api -X POST repos/<org>/<repo>/pulls/<n>/comments/<top-level comment id>/replies`. `needs_lead` = a product, design, scope
or architecture decision, a disagreement on direction, a conflict with a recorded decision, another team: one `reply` entry
per thread, approved by the lead like every other entry, then the reply goes out. Each classification is bound to the
reviewer's last comment; a newer one needs a new classification (which voids a `reply` entry made for the old state).
`turnstile threads <repo#n>` without ids lists the threads in scope; `turnstile status` shows what they still need.

"If you replied to all comments on a PR and Copilot passed again, ping the reviewer to look again" (lead rule 2026-10-14, the
re-request): once every human thread in scope has our latest reply and Copilot reviewed the current head with 0 open threads (repos
without Copilot: the gate check green on the head), the agents re-request review on GitHub from the reviewers who commented on the
threads in this round — `gh api -X POST repos/<org>/<repo>/pulls/<n>/requested_reviewers -f 'reviewers[]=<login>'`, no lead
approval; Slack sends are gated by the lead's word in chat only. `turnstile status` prints that exact command while it has not happened for the head, then the
`--rerequested` pass. A push-only rework (no reviewer comment since the PR last went to humans) pings nobody: the return records
`reviewer_notified: false`, the board reads "reviewers not notified", and the lead decides.

### The lead's word (`awaiting_human`)

`pass` opens entries for the lead: `merge` on APPROVED, `story_done` when a story enters ENV_TESTING, `start_story`
for every PLANNED story whose `after` stories are DONE. Only the lead approves them (see "How the lead approves").
`pass … --approved <ah-id>` then requires an entry of the right type for that PR/story that is approved, not consumed
and not voided; the pass consumes it. Slack sends are gated by the lead's word in chat only (2026-11-05): READY opens no
entry, the message is composed by the configured send skill (`send_skill`, see "Per-person overrides"), the plugin records the send (a ledger line from the PostToolUse hook, `evidence.human` via `pass … --slack`) and
never blocks it; a `send` entry left in an older state file is consumed or voided on the pass and never required (its
`used_at` is still marked by the recorder). `plan` entries are
opened by `plan-submitted`; no story leaves PLANNED until the newest one is approved and `plan.md` is unchanged. `reply`
entries are opened by `turnstile threads`, one per `needs_lead` thread; each allows the GitHub replies on that thread only,
never a Slack message, and is consumed when the PR returns to ON_HUMAN_REVIEW (voided on REWORK → DEV or a re-classification).

### Stories

`stories.<S>.branch` is the story branch; INTEGRATION_REVIEW requires every PR of the story to be based on it or on
another PR of the story (a stack), or MERGED, and `evidence.deploy.head` to be the current stack top (the open PR no
other PR of the story is based on; one top per repo for a multi-repo story). After fixes INTEGRATION_REVIEW re-enters
itself with `--build --head` to record the redeploy; ENV_TESTING then needs a review round on that head. ENV_TESTING
re-enters itself to record a test run (`--cases-pass/--cases-fail/--failed-cases/--figma-parity --build --head`, `--full`
for a complete run; the head must be the deploy head); every failed case needs a bug keyed by story + case id
(`turnstile bug add --case`); a case that fails again appends to its bug and reopens it when done, never a duplicate.
DONE needs the last run full and clean on `deploy.head` (= the stack top) and every bug of the story done.
Every deploy record, ENV_TESTING pass and DONE also asks GitHub for the head of every PR in `deploy.heads` and refuses
when any differs (a push without `pass pr` leaves `state.json` stale); `--offline` records `deploy.head_verified: false`
and DONE refuses it.

Agents (`agents/`): implementer, deployer, gate-runner, tester (sonnet; the tester does Figma parity), stack-step, comments-handler,
investigator (haiku), reviewer (opus, high), story-reviewer (opus, xhigh); the frontmatter equals the plugin defaults
(`models.DEFAULTS`), and `epic.models` holds only the per-epic overrides written by `init --models
'{"<agent>":{"model":…,"effort":…}}'` or `config set --epic` (model `haiku|sonnet|opus|fable`, effort
`low|medium|high|xhigh`). Launched as `turnstile:<name>` with the model and effort from the `AGENT:` line of
`turnstile brief`.

### How the lead approves

The lead approves an `awaiting_human` entry **only by typing the command themself in the Claude Code prompt with the
`!` prefix**:

```
! TURNSTILE_LEAD=1 turnstile approve ah-3
```

The `!` prefix runs the line in the user's shell, outside the model's tool calls, so no hook sees it and no agent can
issue it. `approve` records `approved_via: "lead-terminal"` on the entry and the ledger line says so. The Bash hook
blocks **any** model-issued command that contains `turnstile approve` or `TURNSTILE_MIGRATION`, or that sets or reads
`TURNSTILE_LEAD` (`TURNSTILE_LEAD=…`, `export TURNSTILE_LEAD`, `$TURNSTILE_LEAD`; a bare mention in a note is prose), in
any quoting, `env`, `export`, `bash -c` or heredoc form (the check runs on the command with quotes and backslashes
stripped and whitespace collapsed), and the CLI keeps refusing `approve` without `TURNSTILE_LEAD=1` in its environment.
The orchestrator's job is to report what awaits the lead (`turnstile status`) and ask the lead to run that line; it
never runs it.

### Commands

`init`, `plan-submitted`, `pr add` (a new PR enters as DEV from its GitHub facts), `config list|set|unset|apply` (per-person and per-epic models, review skills and the send skill; the epic layer waits for the lead), `pass` (the writer of transitions), `approve` (lead only), `threads` (thread classification from
GitHub facts), `jira-synced` (validated against the PR's state; `--assignee <accountId> [--assignee-name "<name>"]` records who holds the ticket — the take-up, or a hand-over made by hand; the plugin never moves a ticket away from its holder), `brief` (renders an agent brief; refuses unfilled placeholders and, for every agent but the investigator, an unapproved
plan), `bug add|set`, `reconcile` (read-only, `--json`), `status`, `render-board`.

`pass pr` flags: `--head`, `--ci success|failure`, `--deep-review <report> --rounds N [--not-clean]`,
`--gate <name>:<pass|fail>[:<run-url>]`, `--copilot <open-threads>`, `--slack <permalink> --reviewers a,b`
(READY → ON_HUMAN_REVIEW only), `--rerequested a,b` (REWORK → ON_HUMAN_REVIEW only), `--approvals a,b --open-threads N`, `--merged-sha`, `--reason`, `--offline`, `--no-commit`.
`pass story` flags: `--approved`, `--reason`, `--build --head`, `--report --head --rounds [--not-clean]`,
`--report --cases-pass N --cases-fail N [--cases-not-testable N] [--failed-cases a,b] --figma-parity pass|fail|not_testable_here --build --head [--full]`
(a `--full` run's three counts must add up to `stories.<S>.test_cases`). Report paths are
relative to `delivery/` and must exist.

### Hooks

`hooks/hooks.json`, PreToolUse plus one PostToolUse, apply to subagents too, and fail closed (a crash, a malformed payload or a missing
`python3` blocks the call). **They guard a turnstile workspace (2026-11-04):** when no `.turnstile` marker is found upward from the
session's project dir (`CLAUDE_PROJECT_DIR`), the cwd or a directory the command enters (`cd`, `git -C`, `--work-tree`), every hook is
inert — exit 0, nothing checked — except the Bash guard's universal safety rules, which stay on everywhere: force-push, `git rebase` /
`pull --rebase` / `pull.rebase true`, `--no-gpg-sign` / `commit.gpgsign=false`. The hook list below describes a workspace session:

- `guard_bash.py` blocks `gh pr merge|ready`, `--add-reviewer`, `gh pr create --reviewer|-r`, human `requested_reviewers`
  requests (the Copilot bot may be requested; `--input` bodies, team reviewers and computed logins or routes are refused; the
  one human exception is below), REST `pulls/N/merge` writes, GraphQL
  `mergePullRequest|markPullRequestReadyForReview|requestReviews*`, `ready_for_review`, `git push --force*`/`-f`/`+ref`,
  `git rebase`, `--no-gpg-sign`, `-c commit.gpgsign=false`, an empty Prometey `service_github_tag=`, a
  `Co-Authored-By` trailer or the "Generated with [Claude Code]" footer in a `git commit` / `gh pr create|edit` /
  `gh api` call — also when they sit in a file given with `-F`/`--file`/`--body-file`/`--input` (the hook reads it) —
  `gh api graphql` with `query=@file` or `--input` (a mutation in a file), `git config pull.rebase true`, the spaced
  `service_github_tag ''` form, every command that contains `turnstile approve` or `TURNSTILE_MIGRATION` or sets or reads
  `TURNSTILE_LEAD` (the lead's markers; see "How the lead approves"), and **every command that mentions `state.json` (also as a glob) or
  the delivery dir and is not read-only** — read-only means every pipeline segment starts with `cat`, `less`, `head`,
  `tail`, `grep`, `jq`, `ls`, `find` without `-exec|-delete`, `sort` without `-o`, `wc`, `diff`, `sed` without `-i`, `git diff|log|show|status|blame|push|fetch`,
  `turnstile …` / `python3 -m turnstile_cli …`, and no redirect writes into the delivery dir. `perl -pi`, `node -e`,
  `ruby -e`, `env perl …`, `awk`, `python3 - <<EOF`, `tee`, `cp`, `mv`, `rm`, `mkdir`, `git add|commit|config|worktree` on the delivery dir are therefore
  refused, as are `git checkout|restore|stash|reset|clean` that touch it, and — inside the git worktree that holds the
  delivery dir (the knowledge worktree, by cwd or `-C`) — every `git checkout|switch|restore|stash|reset|clean` with no
  pathspec, a ref, or a pathspec that covers the delivery dir (`.`, `..`, `:/`, an ancestor); a pathspec elsewhere in that
  worktree, `git stash list|show`, `git clean -n` pass. Reports and briefs go through the Write tool and
  are committed by the next `turnstile pass`. Global options before the subcommand (`git -C dir`, `git -c k=v`,
  `gh -R owner/repo`) are covered. **Role rules:** when the hook payload names the caller `agent_type: turnstile:tester` (Claude Code
  2.1.x sends `agent_id`/`agent_type` for every subagent tool call; it ignores `hooks` in plugin agent frontmatter, so
  `TURNSTILE_ROLE` is only for tests and non-plugin agents) `git push`, `git commit`,
  `gh pr|issue comment|review|create|edit|close|reopen|merge|ready` and `gh api` writes are refused too.
  **PR conversation (2026-10-14), for every caller:** `gh pr comment`, `gh issue comment` and `issues/<n>/comments` /
  `issues/comments/<id>` writes (`issue-comment`; a body — inline, `--body-file` or `-F body=@file` — that carries the repo
  gate's `<!-- pdf-review:… -->` / `<!-- crit-review:… -->` marker passes, a DELETE never), `gh pr review` and
  `pulls/<n>/reviews…` writes (`review-submission`), `pulls/<n>/comments` writes incl. `in_reply_to` and
  `pulls/comments/<id>` edits (`review-comment`), GraphQL `addPullRequestReview*`, `submitPullRequestReview`, `addComment`,
  `updateIssueComment` and the like (`graphql-review-write`), `resolveReviewThread`/`unresolveReviewThread` unless every
  literal `PRRT_…` id is a thread GitHub says a bot opened (`resolve-thread`, `resolve-human-thread`), and a REST write to a
  computed endpoint (`rest-computed-route`). `POST repos/<org>/<repo>/pulls/<n>/comments/<id>/replies` (literal) passes only
  for a PR of the epic in REWORK (`reply-unknown-pr`, `reply-not-rework`), a thread classified in `state.json`
  (`reply-unclassified`), with the lead's approved `reply` entry for a `needs_lead` thread (`reply-needs-lead`), and while
  GitHub shows no reviewer comment newer than the classification (`reply-reclassify`; `gh` failing → `reply-unverified`).
  **Re-request (lead rule 2026-10-14):** `gh api` POST to the literal `repos/<org>/<repo>/pulls/<n>/requested_reviewers` with
  literal `-f|-F 'reviewers[]=<login>'` fields passes for humans only for a PR of the epic (`human-reviewer-request` otherwise) in
  REWORK (`rerequest-not-rework`) whose threads all have their replies as the pass requires (`rerequest-replies`), in a round with
  thread authors (`rerequest-push-only`), for exactly those authors (`rerequest-not-authors`), with Copilot's latest review on
  the GitHub head and 0 open Copilot threads (`rerequest-copilot`) or, without Copilot, the gate check green on the head
  (`rerequest-gate`); `gh` failing → `rerequest-unverified`.
- `guard_role.py` (PreToolUse, matcher `mcp__.*(transitionJiraIssue|editJiraIssue|createJiraIssue|addCommentToJiraIssue)`)
  refuses Jira writes under any MCP prefix when the caller is any subagent (payload `agent_id`) or a turnstile role; the
  main-thread orchestrator (no `agent_id`) passes and records with `jira-synced` (`editJiraIssue` is how it sets the assignee
  to its own account on take-up; `atlassianUserInfo` and `getJiraIssue` are reads and are not matched).
- Slack sends are gated by the lead's word in chat only (2026-11-05); the plugin records them and never blocks. There is
  no PreToolUse hook on Slack. `post_slack.py` (PostToolUse, matcher `mcp__.*slack_(send|schedule)_message.*`) records a
  send once the tool result carries a `message_ts`: a ledger line `slack send to <channel> ts <ts>` plus ` for <pr ids>`
  when the text mentions PRs, an old open `send` entry of a mentioned PR marked `used_at`/`used_channel`/`message_ts`, a
  board render and a git commit of `delivery/`. It exits 0 in every case: outside a workspace, without a `message_ts`,
  for any channel or text, and when the state cannot be read (then nothing is recorded). `pass … ON_HUMAN_REVIEW` requires
  a permalink of the form `https://<workspace>.slack.com/archives/…`.
- `guard_state_edit.py` blocks Edit/Write/MultiEdit on `state.json` and `ledger.md` (anywhere in a workspace session, or when the
  target lies in a workspace) unless the environment has `TURNSTILE_MIGRATION=1`.

### Threat model

The hooks, the ledger and `turnstile reconcile` are **defence in depth, not proof**. Everything runs as one OS user:
an agent that finds a write path the Bash guard does not recognise can edit `state.json`, and the lead's markers are
only blocked for commands that pass through the model's tool calls. What holds the line:

- the lead's approval never passes through the model (`!`-prefixed prompt line), so no agent can produce one;
- every writer the plugin knows (`pass`, `approve`, the Slack PostToolUse hook) leaves a ledger line and a git commit,
  so a write that did not come through them is visible as drift: `turnstile reconcile` flags every `approved_at` whose
  ledger line is missing or lacks `approved_via: lead-terminal` (`approval_unlogged`), heads, checks, approvals and
  threads are compared with GitHub, and `status` lists uncommitted changes in `delivery/`;
- Slack sends are not gated by the plugin at all (2026-11-05): the lead's word in chat is the only gate, the PostToolUse
  hook records every send that went out, and the ledger shows them. Approvals of `start_story`/`story_done` entries in
  `state.json` are forgeable by a script file the guard never sees.

The residual risk (same OS user, an unrecognised write path) is accepted; it is reviewed, not prevented. The thread
rule adds three accepted limits: the `self_resolved` / `needs_lead` call is the agent's judgment (the hook enforces that a
reply goes only to a classified thread, not that the class is right; the ledger line and the board show every class to the
lead); the gate-marker exception can be imitated by an agent that writes the marker into an ordinary comment; and a `curl`
to a URL that is entirely computed (no literal `api.github.com/repos/…`) is not recognised as a GitHub write.

Tests: `python3 -m unittest discover -s tests -v` (stdlib only, no network; a canned `gh` on `PATH` serves the
end-to-end test).

Design spec: [`docs/superpowers/specs/2026-10-13-turnstile-design.md`](docs/superpowers/specs/2026-10-13-turnstile-design.md).

## Status

Pre-alpha. Being extracted from a live epic delivery; the first consumer migrates mid-flight.

## License

MIT
