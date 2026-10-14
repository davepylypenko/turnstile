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
   For `tester` append the lead's test credentials to the prompt only (briefs are committed); the tester resolves its Figma
   tools per `references/tools/figma.md` and comes back `BLOCKED` when the environment has none. Models: implementer and
   deployer sonnet, reviewer opus xhigh, story-reviewer fable, the rest opus. One agent per task; parallel agents only across different
   repos or stories.
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
   reports/ENV-S.md --cases-pass <n> --cases-fail <n> --failed-cases <id,…> --figma-parity pass|fail --build <build>
   --head <stack top> --full` (the head must be `deploy.head`). Fixes via `implementer` → gates → `stack-step` →
   `deployer` → `pass story S INTEGRATION_REVIEW --build --head` (records the redeploy) → review round → `pass story S
   ENV_TESTING --report … --head …`; `turnstile bug set bNN --state testing` after the deploy; `tester` in mode `rerun`
   (`ENV-S-r2`) for the failed cases (recorded without `--full`); `bug set bNN --state done`; then one full run.
5. `turnstile pass story S DONE --approved <story_done ah-id>` — needs the last run `--full` with 0 fails, parity pass,
   `env_test.head == deploy.head ==` the current stack top, every bug of the story `done`, every PR ≥ READY.
6. Report to the lead per `references/slack.md` § Story report and **stop**: the next story and the sends of this
   story's units wait for the lead's words (`start_story` / `send` entries — there is no `--reason` way to start a story,
   and a parallel start needs `parallel_with` in the approved plan; then `pass pr … ON_HUMAN_REVIEW --head …
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
