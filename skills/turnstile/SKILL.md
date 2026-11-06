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
The CLI is `${CLAUDE_PLUGIN_ROOT}/scripts/turnstile`; `turnstile …` below means that path, or the bare name when the lead
installed the PATH shim (`scripts/install-cli.sh`). The Bash guard treats both spellings alike. Every write is committed to
the epic branch and pushed to origin; `status` opens with `SYNC:`. On `NOT PUSHED` or "behind origin" run `turnstile sync`
(fetch, fast-forward, push; never rebase or force — diverged histories go to the lead). `--no-push` only for offline work.

## Rules that never bend

- The lead's word is an `awaiting_human` entry approved **by the lead typing** `! TURNSTILE_LEAD=1 turnstile approve <ah-id>`
  in the Claude Code prompt (the `!` runs outside the model). You report the pending ids (`turnstile status`) and ask
  for that line; you never run it, no agent runs it, and the Bash guard refuses any spelling of it.
- A reply on a `needs_lead` thread, merge, story start, story completion, plan approval: all go through such an entry.
- Slack sends are gated by the lead's word in chat only (2026-11-05): compose the message, show it, send it when the lead
  says so. The plugin records the send (a ledger line from the PostToolUse hook, `send` evidence via `pass … --slack`) and
  never blocks, asks or demands a command before it.
- A reply on a `self_resolved` review thread needs no entry: it goes out at once (`## REWORK`). So does the GitHub re-request of
  the thread authors once every thread has its reply and the head is clean (lead rule 2026-10-14). Issue comments, review
  submissions, resolving a human thread and every other human reviewer request are refused for everyone (the repo gate's marker
  comments excepted).
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
On `OK` it prints `JIRA: <ticket> → <status>[ · assignee: you]`: perform the transition through the Atlassian MCP `transitionJiraIssue`; when the line says `assignee: you`, read your own account with `atlassianUserInfo` (no arguments; `account_id`, `name`) and set the assignee in the same step
with `editJiraIssue` (`fields: {"assignee": {"accountId": "<account_id>"}}`), then `turnstile jira-synced <repo#n> "<status>" --assignee <account_id> --assignee-name "<name>"` (plain `turnstile jira-synced <repo#n> "<status>"` once it is recorded). The ticket belongs to the person
whose session took it into work; the plugin never moves it afterwards (`status` lists `jira_unassigned` until it is recorded). It also prints `BOARD: publish <path> → <url>` (publish the file with the Artifact tool and that `url`; a first publish loads the
`artifact-capabilities` skill, declares `db` + `user`, and the url is recorded at `init --board-url` or by the migration). On `MISSING …` nothing was written: get the evidence, do not argue with the gate.
A PR the implementer opened enters the state as `DEV` with `turnstile pr add <repo#n> --story <S> --ticket <KEY>` (head, branch
and base from GitHub; refused when the base is not the story branch or another PR of the story, or the brief is missing).

## init (once per epic)

1. "Start epic MYD-X" comes from the lead in the **clone root** (the folder holding `pdffiller-knowledge/`, `jsfiller/`, …) or inside
   the knowledge clone. Run there: `turnstile init --epic <KEY> --workitem <slug> --lead <login> --lead-github <GitHub login>
   --github-org <org> --repo '<json>'… --variant <v> --desk <d>` (`--knowledge <clone>` only when it is not `<root>/pdffiller-knowledge`,
   `--clone-root <dir>` when run elsewhere). It creates the workspace `<root>/<key-lower>/`: the knowledge worktree on `epic/<key>`, a
   worktree of every `--repo` clone on `ws/<key-lower>` (from `origin/<base>`; a missing clone is refused with its expected path), `delivery/`,
   `.turnstile`, `CLAUDE.md`, `delivery/.workspace.json` (this machine's paths; `brief --var repo=<name>` renders them). Repo JSON keys: `name,
   base, epic_branch, slack, gate, gate_check (null for a skill gate), ci_ignore, copilot, branch_prefix, path`; `--models '{"reviewer":
   {"effort":"high"}}'` seeds `epic.models`. Then tell the lead, explicitly: `cd <workspace> && claude` — the hooks and `.turnstile` live in
   the new folder; this session stays in the root and cannot drive the epic (outside a workspace the hooks are inert; only force-push, rebase and unsigned commits stay refused). Steps 2–4 and `## preferences` run from the new session.
2. Kick-off analysis per `references/kickoff.md`: read decomposition, PRD, design, test plan, every repo's `CLAUDE.md`; write
   `delivery/plan.md` from its template (stories with a story branch each, merge order, human-review units ≈ 400 logic lines,
   test-case map, Figma frames, human inputs, env slots) including the `turnstile-stories` JSON block.
3. `turnstile plan-submitted` → stories enter `PLANNED`, a `plan` entry opens; show the lead the plan summary and the approve line; wait. Without the approval no story leaves `PLANNED` (no `--reason` override).
4. After the lead approved the plan and the first `start_story` entry: `turnstile pass story S1 IN_PROGRESS --approved <ah-id>`, then dispatch implementers per the merge order.

## preferences (right after init, and whenever the lead asks)

Layers, highest first: the lead's user file (`~/.config/turnstile/config.json` or `$TURNSTILE_USER_CONFIG`, never in git) >
epic state (`epic.models`, `epic.review_skill`, `epic.story_review_skill`) > plugin defaults. Ask the lead **one** batched
question — "Do you use your own review skill (name it), and do you want a different model/effort for any agent? Current
effective values:" + the output of `turnstile config list` — then record: `turnstile config set models.<agent>=<model>[:<effort>]`,
`config set review_skill=/my-review`, `config set story_review_skill=…` (user layer: at once; `--epic`, only when the lead says it is
for the whole epic or team, opens a `config` entry — the lead approves it with the usual line, then `turnstile config apply <ah-id>`;
`=default` / `config unset` resets) and show `turnstile config list` again. Later chat instructions ("use my /x-review skill",
"reviewer on sonnet") map to the same commands; never ask what the user file already answers; `turnstile status` prints the effective line.
`review_skill` is what the `reviewer` runs for the deep review (`--deep-review` report), `story_review_skill` the story-reviewer's; the brief
prints the exact invocation (`/code-review` takes the agent's effort as its level, `/code-review xhigh` by default; any other skill runs bare); an agent set without an effort (`models.reviewer=sonnet`) runs at its default effort and the `AGENT:` line prints that resolved effort. Neither replaces the repo gate (`epic.repos.<r>.gate` / `gate_check` stay the READY evidence).

## attach (continue an epic from another machine)

"Continue epic X" → in the person's clone root (or knowledge clone): `turnstile attach --epic <KEY> [--clone-root <dir>] [--knowledge <clone>]
[--workspace <dir>] [--workitem <name>]`: fetches `origin/epic/<key>`, creates `<root>/<key-lower>` with the knowledge worktree, a `ws/<key-lower>`
worktree per `epic.repos` clone, `.turnstile`, `.workspace.json`, the workspace `CLAUDE.md`, prints `status`. Then `cd <workspace> && claude` (this
session cannot drive it) and run `## preferences` there (this person's user file may be empty). A worktree behind origin refuses every writer until `turnstile sync`.

## dispatch <agent> <brief>

1. `turnstile brief <agent> <NAME> --var k=v …` renders `references/briefs/<agent>.md`; it refuses unfilled
   placeholders, so pass every agent-specific variable listed in the template, and refuses every agent but the
   `investigator` while `plan.md` is unapproved (spec §4.1: no agent starts before the plan). Names: `<KEY>` for tickets,
   `REVIEW-<n>`, `STORY-<S>-review`, `ENV-<S>`, `FIX-<n>-<slug>`, `STACK-<date>`, `COMMENTS-<n>`,
   `INVESTIGATE-<slug>`, `DEPLOY-<slug>-<date>`. A repeat of the same job (a second review round, a rerun) gets a round
   suffix — `REVIEW-<n>-r2`, `STORY-<S>-review-r2`, `ENV-<S>-r2` — so the first round's brief and report survive; `--force`
   overwrites them and is for a brief that was never dispatched.
2. Launch with the Agent tool: `subagent_type: "turnstile:<agent>"`, prompt = the `PROMPT:` line the command printed.
   For `tester` pass `--var test_user=<address>`; the password is never in the prompt or the brief — the tester reads
   `TURNSTILE_TEST_PASSWORD` or the keychain item `turnstile-test-password` itself at login (`references/env/pdffiller-dev.md`
   § Credentials); the tester resolves its Figma tools per `references/tools/figma.md` and comes back `BLOCKED` when the
   environment has none. Model and effort come from the `AGENT:` line the command printed (`AGENT: turnstile:reviewer
   model=opus effort=xhigh`, resolved per `## preferences`): pass `model` and, when the line carries one, `effort` to the
   Agent tool — never pick a model yourself. The reviewer briefs carry the resolved review skill and the agent's effort as its argument. One agent per task;
   parallel agents only across different repositories (`## Token discipline`).
3. On return read the ≤ 8-line reply (the report is in `reports/`), record the facts with `turnstile pass` / `bug`,
   then reply to the lead. Never paste agent output into the chat.

## story-gate <S>

Pre-condition: every PR of `S` is ≥ `READY`, each based on the story branch or on the PR below it, and the stack top
is deployed to the story's slot (dispatch `deployer`).
1. `turnstile pass story S INTEGRATION_REVIEW --build <build> --head <stack-top sha>` (the head must be the current stack
   top: the open PR of the story no other PR is based on).
2. dispatch `story-reviewer` (`STORY-S-review`); findings → `implementer` briefs on the ticket PRs → `stack-step` →
   their gates re-run (`pass pr … AI_REVIEW --head <new> --ci success`, `reviewer`, `pass pr … READY …`); the fixes
   moved the stack top, so dispatch `deployer` and re-enter `pass story S INTEGRATION_REVIEW --build <new> --head <new>`;
   a new review round (`STORY-S-review-r2`) on that head; loop until the report says `clean: true`.
3. `turnstile pass story S ENV_TESTING --report reports/STORY-S-review.md --head <stack top> --rounds <r>` (opens the
   lead's `story_done` entry; refused when the review head is not the deploy head).
4. dispatch `tester` (`ENV-S`, mode `full`). For every failed case first `turnstile bug add --story S --case <id> --title …
   --source "tester <date>" --figma <node>` (one bug per story + case; a case that already has a bug needs none: the run
   record appends to it and reopens a done one), then record the run: `turnstile pass story S ENV_TESTING --report
   reports/ENV-S.md --cases-pass <n> --cases-fail <n> --cases-not-testable <n> --failed-cases <id,…> --figma-parity
   pass|fail|not_testable_here --build <build> --head <stack top> --full` (the head must be `deploy.head`; the three counts of
   a full run add up to the story's test cases). Fixes via `implementer` → gates → `stack-step` →
   `deployer` → `pass story S INTEGRATION_REVIEW --build --head` (records the redeploy) → review round → `pass story S
   ENV_TESTING --report … --head …`; `turnstile bug set bNN --state testing` after the deploy; `tester` in mode `rerun`
   (`ENV-S-r2`) for the failed cases (recorded without `--full`); `bug set bNN --state done`; then one full run.
5. `turnstile pass story S DONE --approved <story_done ah-id>` — needs the last run `--full` with 0 fails, parity pass,
   `env_test.head == deploy.head ==` the current stack top, every bug of the story `done`, every PR ≥ READY. Steps 1, 3, 4
   and 5 ask GitHub for the head of every PR in `deploy.heads` and refuse on any drift (never `--offline` at DONE).
6. Report to the lead per `references/slack.md` § Story report and **stop**: the next story waits for the lead's
   `start_story` entry (there is no `--reason` way to start a story, and a parallel start needs `parallel_with` in the
   approved plan); the sends of this story's units go out on the lead's word in chat, then `pass pr … ON_HUMAN_REVIEW
   --head … --slack <permalink> --reviewers a,b` records each one.

## trunk mode (`stories.<S>.mode: trunk`, `epic.flag`)

PRs merge into the repo base behind the one epic flag and reach humans on their own (`pr add` wants the repo base; `--stacked-on`
for a deliberate stack). After every PR of the story is MERGED: deploy the base, `pass story S INTEGRATION_REVIEW --build <n>
--head <base sha>` (GitHub compare proves the merges are in it), story-reviewer on the merged diff, then two tester runs on the
same head — `ENV-S-treatment` (`--var arm=treatment`) and `ENV-S-control` (`--var arm=control`, flag off, `control_cases`) —
recorded with `--arm`; `DONE` needs both arms full and clean. The brief carries `{{flag}}`; a tester without a toggle method is BLOCKED.

## plan (re-plan after a scope change)

Edit `delivery/plan.md` (stories, branches, units, map) with the rationale in `decisions.md`; `turnstile plan-submitted`
(voids the old plan entry, opens a new one); the lead approves again. Stories past `PLANNED` keep their state and
evidence; a started story cannot be dropped.

## REWORK (a human thread, changes requested, or a push after the send)

Lead rule 2026-10-14: a thread the agent resolved itself is answered at once; only threads that need the lead stop.
1. `turnstile status` proposes `pass pr … REWORK --reason …` (no entry opens); dispatch `comments-handler` (`COMMENTS-<n>`,
   `--var sent_at=<evidence.human.sent_at> --var approved_replies=none`).
2. The agent fixes, then classifies every human thread from GitHub facts: `turnstile threads <repo#n> --self-resolved <ids>
   --needs-lead <ids> --report reports/COMMENTS-<n>.md`. `self_resolved` (fixed, or justified in code) → it replies on the thread
   at once through the guarded REST replies route. `needs_lead` (decision, direction, a recorded decision, another team) → a
   `reply` entry per thread; show the lead the draft and the approve line; once approved, post exactly that text (yourself or a
   `COMMENTS-<n>-r2` dispatch with `approved_replies=<ah-ids>`). A reviewer's follow-up needs a new classification first.
3. Gate and Copilot on the new head (no new deep review); `turnstile status` lists what the threads still need.
4. Re-request (lead rule 2026-10-14: "replied to all comments and Copilot passed again → ping the reviewer to look again"): once
   every thread has its reply and Copilot reviewed the GitHub head with 0 open threads (repos without Copilot: the gate check
   green on it), `turnstile status` prints the exact `gh api -X POST repos/<org>/<repo>/pulls/<n>/requested_reviewers -f
   'reviewers[]=<login>'` for the thread authors (the reviewers who commented on the threads in this round). The comments-handler
   (or you) runs it — no lead approval; the guard allows exactly that request and refuses non-authors, an open Copilot thread, a
   stale head and any other human request. Slack sends go out on the lead's word in chat only.
5. `pass pr … ON_HUMAN_REVIEW --head <new> --ci success --gate … --rerequested <logins>` — no Slack message, no `--slack`: the replies
   and the re-request are the notification; the pass checks GitHub (`reviewRequests`, request newer than the replies). A push-only
   rework (no reviewer comment since the PR last went to humans) takes no `--rerequested`: it records `reviewer_notified: false`,
   the board reads "reviewers not notified", and you tell the lead, who decides whether to ping.

## Token discipline (lead rules 2026-10-19, 2026-10-26)

- Agents run on the cheapest model that does the job: the `AGENT:` line of `turnstile brief` decides (no Opus outside the two
  review agents unless the lead's config says so). Agents start one at a time; in parallel only across different repositories.
- Waiting on GitHub, CI or a deploy goes through `Monitor` or one background command that re-invokes you when it exits;
  never a cron, a loop skill or a watchdog. No interim "still waiting" messages to the lead: report when there is a fact.
- The repo gate (`pdf-review` or the repo's review skill) runs once per head; re-run it only for P1/P2 (`blocker`/`major`)
  findings — minor fixes land without a re-review. Leftovers go to human review.
- You dispatch; you never read a diff, run a suite or paste agent output into the chat.

## Bugs on the board

Viewers with write access change a bug's status in the board's dropdown; it lands in the artifact db (`bugs/<id>`),
not in `state.json`. At `status` time read the `bugs` collection with `ArtifactData` and fold changes back with
`turnstile bug set <id> --state <s>` so git stays the source of truth.
