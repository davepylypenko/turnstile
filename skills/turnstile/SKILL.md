---
name: turnstile
description: Run or resume the delivery of a multi-repo epic through turnstile's evidence-gated flow — PR states DEV→AI_REVIEW→READY→ON_HUMAN_REVIEW→APPROVED→MERGED, story gates (integration review, environment testing), role agents, the lead's approvals. Use at the start of every orchestrator session and whenever a PR, story, review, deploy or bug changes state; also on "start epic", "continue epic", "почни епік", "продовж епік", "status", "send for review", "start story", "re-plan".
---

# Turnstile

The state is `delivery/state.json` in the knowledge worktree (found through `.turnstile` in the workspace or the registry `turnstile start` writes, `references/workspace.md`). Only `turnstile` commands write it. You sequence; the CLI enforces. Every state change is
one command whose side effects (ledger, board, commit, Jira instruction) happen inside it — never "later". Read once per session: `references/lifecycle.md` (DoR/DoD per state with the exact
`turnstile pass` call). Templates: `references/pr-body.md`, `references/slack.md`, `references/reports.md`, `references/evidence.md`; env recipes in `references/env/`. The CLI is
`${CLAUDE_PLUGIN_ROOT}/scripts/turnstile`; `turnstile …` below means that path, or the bare name when the lead installed the PATH shim (`scripts/install-cli.sh`). The Bash guard treats both
spellings alike. Every write is committed to the epic branch and pushed to origin; `status` opens with `SYNC:`. On `NOT PUSHED` or "behind origin" run `turnstile sync` (fetch, fast-forward, push;
never rebase or force — diverged histories go to the lead). `--no-push` only for offline work.

## Rules that never bend

- A human's word is an `awaiting_human` entry approved **by a member typing** `! TURNSTILE_LEAD=1 turnstile approve <ah-id>`
  in the Claude Code prompt (any member of `epic.members`, from their own terminal; the `!` runs outside the model; the ledger
  records who). You report the pending ids (`turnstile status`) and ask for that line; you never run it, no agent runs it,
  and the Bash guard refuses any spelling of it.
- A reply on a `needs_lead` thread, merge, story start, story completion, plan approval: all go through such an entry.
- Slack sends are gated by the lead's word in chat only (2026-11-05): compose the message through the send skill (`## pass`),
  show it, send it when the lead says so. The plugin records the send (a ledger line from the PostToolUse hook, `send`
  evidence via `pass … --slack`) and never blocks, asks or demands a command before it.
- Two brakes are human, nothing else: `turnstile approve` (the `awaiting_human` entries) and merging a PR. Every other GitHub and terminal command you run yourself, without asking the lead to paste it: `gh pr ready <n>` and `--undo`, review requests and re-requests (`gh api -X POST|DELETE repos/<org>/<repo>/pulls/<n>/requested_reviewers -f 'reviewers[]=<login>'` or `gh pr edit --add-reviewer`, only for logins in `epic.members` or `epic.reviewers`; never teams or bots; `turnstile config set reviewers=a,b [--epic]`, an empty list opens it to any human login), `gh run rerun|watch`, `gh pr checks`, every read-only `gh` call, the epic-branch merge (`turnstile sync`), and the reply on a review thread from any member's login in any PR state (`## REWORK`; the thread must be classified, a `needs_lead` one needs its approved `reply` entry). Still refused for everyone: `turnstile approve` in any spelling, `gh pr merge` / GraphQL merge, force-push, rebase, unsigned commits, bare `git stash`, issue comments and review submissions (the repo gate's `<!-- pdf-review:… -->` marker comments excepted), resolving a human thread, `rm -rf`-class deletions and writes (`>`, `tee`, `sed -i`, `rm`, `mv`, `cp` into it) in `delivery/` outside `evidence/`, `reports/`, `briefs/` and `boards/`. Words such as `gate` or `S10` in a read-only command never trip the guard.
- A question from the lead is a question: answer and propose, act on a command.
- Delegate all implementation, review, testing and deployment to the `turnstile:*` agents (`## dispatch`). Never read
  a diff or run a suite yourself; your context is for coordination.
- After every agent report, record its facts (`pass`, `bug`, `jira-synced`) before you reply to the lead.

## status

`turnstile status` → reconcile against GitHub + plan state + next actions + what awaits the lead (exit 1 when `gh` facts are missing). Run it first in every session
and after every batch of agent reports; run the proposed `turnstile pass` lines it prints (dry-run checked); show the lead the anomalies (`turnstile reconcile
--json` for the raw list). A `WARN: send skill … not found` line means the lead must name the skill that sends PRs to review (`## preferences`).
`status` prints `MEMBER: <login> · variant <v> · desk <d|none> · board <url|none> · board file boards/<login>.html` after `SYNC:` (this machine's developer, from `delivery/.workspace.json` → `epic.members`; `member_unknown` in
the reconcile list means the login is not in `epic.members`: run the `attach` line it proposes; `owner_unknown` means a PR or story owner is not in `epic.members`: re-own it with `turnstile pr add … --owner <login>` / `turnstile pass story <S> IN_PROGRESS --owner <login>` or record a note).
A member whose variant has no record yet (no story `deploy` by them, no `turnstile board-url`) gets `ONBOARD: variant <v> not created — dispatching the deployer is the next step (turnstile brief deployer DEPLOY-env-<login> …)` in `status`: dispatch that deployer **without asking**, then ask the one `## preferences` question. `PLUGIN: <loaded version> (restart the session to load <newer> if `claude plugin list` shows it)` appears only when the hooks of this session (version recorded by the guard in `.workspace.json`) differ from `turnstile --version`: a mid-session plugin update; tell the lead to restart the session. `turnstile repo set <name> key=value …` edits `epic.repos.<name>` (keys `gate, gate_check, slack, ci_ignore, copilot, branch_prefix, base, epic_branch`; `null` clears `gate`, `gate_check`, `branch_prefix`) through the normal writer. `CANCELLED` check runs: one with a newer run of the same check on the head is a superseded duplicate and is ignored; one without is pending, and `status` prints `ci_cancelled_dup` with the exact `gh run rerun <id>` to run. Checks named in `ci_ignore` never block any transition: every pass and `status` compute CI without them, and an ignored CANCELLED run gets no `ci_cancelled_dup`. `turnstile status --brief` prints only `SYNC:`, `MEMBER:`, the PRs and stories whose state or head changed since the previous `status` (snapshot in
`delivery/.status-cache.json`, not in `state.json`), the awaiting list and the anomalies: use it for every call after the first of a session.

## pass (one transition)

`turnstile pass pr <repo#n> <STATE> --head <sha> [evidence flags]` / `turnstile pass story <S> <STATE> [flags]`; flags per `references/lifecycle.md`. Every PR pass verifies the head
and the evidence against GitHub; `--offline` only records. On `OK` it prints `JIRA: <ticket> → <status>[ · assignee: you]`: transition through the Atlassian MCP `transitionJiraIssue`.
When the line says `assignee: you` (or `status` lists `jira_unassigned`), first read the issue's assignee (`getJiraIssue`, `fields: ["assignee"]`): empty → read your own account
with `atlassianUserInfo` (no arguments; `account_id`, `name`), set it with `editJiraIssue` (`fields: {"assignee": {"accountId": "<account_id>"}}`) and run
`turnstile jira-synced <repo#n> "<status>" --assignee <account_id> --assignee-name "<name>"`; held by someone → leave Jira alone, record that person with the same flags.
Plain `turnstile jira-synced <repo#n> "<status>"` once it is recorded. The ticket stays with whoever took it into work; the line is plain on MERGED and when a PR of the ticket already
carries an assignee. It also prints `BOARD: publish <delivery>/boards/<login>.html → <url>`: the member's own file (their stories, PRs, bugs and awaiting entries) and the board artifact of this machine's member (`epic.members.<login>.board`; Artifact tool, that `url`; a first publish loads `artifact-capabilities`
and declares `db` + `user`; with no url the line says `new artifact … — then: turnstile board-url <url>`, and you run that after the publish). A deploy record (`pass story … INTEGRATION_REVIEW --build --head`)
stores `deploy.variant` and `deploy.by` of the member. On `MISSING …` nothing was written: get the evidence, do not argue with the gate. A PR the implementer opened enters the state as `DEV` with
`turnstile pr add <repo#n> --story <S> --ticket <KEY>` (head, branch, base from GitHub; refused without the brief or when the base is neither the story branch nor another PR of the story).
**Sending a READY PR to humans:** invoke the configured send skill — `<send_skill> <pr url> …` (`send_skill` in `turnstile config list`, default `/send-pr-review`); it picks the channel
and the format and shows the draft; when the epic sets `epic.repos.<repo>.slack`, tell it that channel explicitly (the explicit channel wins over the skill's own routing). The lead's word
in chat is still the only gate. Then `turnstile pass pr <repo#n> ON_HUMAN_REVIEW --head <sha> --slack <permalink> --reviewers a,b`. When the skill is not installed (`start`/`status`
say so), the templates in `references/slack.md` are the fallback and you ask the lead which skill to install or use.

## start (a new or an existing epic, from wherever the session is)

"Start epic MYD-X", "Continue epic MYD-X", "почни епік MYD-X", "продовж епік MYD-X" → `turnstile start <KEY>` from the folder the session is in: the **clone root** (the folder
holding `pdffiller-knowledge/`, `jsfiller/`, …), the knowledge clone, any repo clone under the root or an existing workspace. No `cd`, no other flag (`references/workspace.md`: the
flags, `init`/`attach`/`repo add`, `init --models`, the registry, `--delivery`). It looks up `origin/epic/<key>`: present → attaches (`<root>/<key-lower>` with the knowledge worktree, a `ws/<key-lower>`
worktree per `epic.repos` clone cut from `origin/<base>`, `.turnstile`, `.workspace.json` (this machine's paths and `member`; `brief --var repo=<name>` renders them), the workspace `CLAUDE.md`,
your `epic.members` entry with variant `<key-lower>-<login>`, then `status`); absent →
creates the epic from the clone alone (login and name from `gh api user`, org from the knowledge clone's origin, the `context/workitems` folder that mentions the key, `chat_language`
from the user config) with the knowledge worktree only — repos come with `repo add`. Both paths register the workspace in `~/.config/turnstile/workspaces.json`, so **this session
drives the epic**: the hooks and every `turnstile` command resolve the workspace through the registry from the root and from inside any clone (no epic resolvable → `status` prints
`NO EPIC: say "start epic <KEY>" — known here: …`). It ends with `OK start <KEY>` and one `NEXT:` line; a `MISSING` names what to pass (`--workitem <name>` when none or several match).
- New epic (`NEXT: kickoff …`): run `references/kickoff.md` at once — read the workitem docs (decomposition, PRD, design, test plan, every repo's `CLAUDE.md`), then `turnstile repo add
  '{"name":…,"base":…,"slack":…[,"gate","gate_check","ci_ignore","copilot","branch_prefix","path"]}'` for each repo the decomposition names (a missing clone is cloned with `gh repo clone`;
  that plumbing is yours, never the lead's), write `delivery/plan.md` from its template (stories with a story branch each, merge order, human-review units ≈ 400 logic lines, test-case
  map, Figma frames, human inputs, env slots, the `turnstile-stories` block), `turnstile plan-submitted` (stories enter `PLANNED`, a `plan` entry opens; a story naming a repo missing from
  `epic.repos` is refused with the `repo add` line). Then **one message** to the members: the plan summary (story table, unit table, open inputs), the approve line, and the
  `## preferences` question with the current `turnstile config list` values ("defaults apply if you only approve"). Wait; record the answer in `decisions.md`. After a member approved
  the plan and the first `start_story` entry: `turnstile pass story S1 IN_PROGRESS --approved <ah-id>`, then dispatch implementers per the merge order. No story leaves `PLANNED` unapproved (no `--reason`).
- Existing epic (`NEXT: turnstile status`): `status`, then its `ONBOARD:` / `NEXT:` lines as today — dispatch the deployer **without asking** when `ONBOARD:` says the variant is not
  created, then the one `## preferences` question when this person's user file is empty. A worktree behind origin is merged by the next writer or `turnstile sync`.

## preferences (right after start, and whenever the lead asks)

Layers, highest first: the lead's user file (`~/.config/turnstile/config.json` or `$TURNSTILE_USER_CONFIG`, never in git) > epic state (`epic.models`, `epic.review_skill`,
`epic.story_review_skill`, `epic.send_skill`) > plugin defaults. Ask the lead **one** batched question, in the plan message for a new epic — "Do you use your own review skill (name it), which skill sends PRs to Slack
review (`start` printed `SEND_SKILL:`; if it is not found on this machine, which one to install or use), and do you want a different model/effort for any agent? Current effective
values:" + the output of `turnstile config list` — then record: `turnstile config set models.<agent>=<model>[:<effort>]`, `config set review_skill=/my-review`, `config set chat_language=uk`,
`config set story_review_skill=…`, `config set send_skill=/my-send`, `config set jira_base_url=https://<site>.atlassian.net` (the Jira site every ticket key on the board links to; the user layer wins over `epic.jira_base_url`, default `https://pdffiller.atlassian.net`; `status` prints `JIRA: <base>`) (user layer, at once; `--epic` — only when the lead says it is for the whole epic or team — opens a `config` entry
a member approves with the usual line, then `turnstile config apply <ah-id>`; `=default` / `config unset` resets) and show `turnstile config list` again. Later chat instructions
("use my /x-review skill", "reviewer on sonnet", "send with /x") map to the same commands; never ask what the user file already answers; `turnstile status` prints the effective line.
`review_skill` is the `reviewer`'s deep-review skill (`--deep-review` report), `story_review_skill` the story-reviewer's, `send_skill` what posts a PR for review (`## pass`); the brief
prints the exact invocation (`/code-review` takes the agent's effort as its level, `/code-review high` by default for the reviewer, `xhigh` for the story-reviewer; other skills run bare); an agent set without an effort (`models.reviewer=sonnet`)
runs at its default effort and the `AGENT:` line prints that resolved effort. Neither review skill replaces the repo gate (`epic.repos.<r>.gate` / `gate_check` stay the READY evidence).

## members

Every developer runs `turnstile start <KEY>` on their own machine (onboarding is three lines: `claude plugin install turnstile@turnstile`, open Claude in the folder with the clones, say "Continue epic <KEY>").
It writes `epic.members.<login>` (login from `gh api user`; variant default `<key lower>-<login lower>`, e.g. `myd-16539-ivanov`; desk and board url optional), commits and pushes it so every machine sees it, records
`member` in `.workspace.json`, and prints `MEMBER: <login> · variant <v> · desk <d|none> · board <url|new artifact>`; running it again with the same login updates only the flags passed, never duplicates. The variant is
created by the deployer through the prometey-variant skill (`ONBOARD:` in `status`): every developer deploys to their own variant, so deploys never overwrite another one's.
`turnstile board-url <https://claude.ai/artifact/… | https://claude.ai/code/artifact/…>` records the member's board artifact (the lead's also lands in `epic.board`) and that the variant exists. Any member approves from their own terminal.

## sync

`turnstile sync` fetches origin and fast-forwards the epic branch; when it diverged it runs `git merge --no-edit origin/<branch>`. A conflict only in `delivery/board.html` or `delivery/boards/*.html` is resolved by re-rendering them from the merged `state.json` (commit, push, ledger line `sync: merged origin/<branch> (<n> theirs, <m> ours)`). A conflict in `state.json`, `ledger.md`, `plan.md` or `decisions.md` aborts the merge and stops with `MISSING histories diverged …` naming the files: the humans merge by hand, then `turnstile sync`. Every writer that finds the branch behind origin runs the same routine before refusing, so the next call sees the merged state. Never rebase, never force.

Boards per member: `turnstile pr add` and `turnstile pass story <S> IN_PROGRESS` record the machine's member as `owner` (override: `--owner <login>`, a known member); bugs follow their story's owner; older state gets the lead as owner on load. Every write renders `delivery/board.html` (everything, with an owner column) and `delivery/boards/<login>.html` for each member (only that member's rows; lead-only entries such as the plan approval show on every board). Publish your own file, never someone else's.

## dispatch <agent> <brief>

1. `turnstile brief <agent> <NAME> --var k=v …` renders `references/briefs/<agent>.md`; it refuses unfilled
   placeholders, so pass every agent-specific variable listed in the template, and refuses every agent but the
   `investigator` while `plan.md` is unapproved (spec §4.1: no agent starts before the plan). Names: `<KEY>` for tickets,
   `GATE-<n>`, `REVIEW-<n>`, `STORY-<S>-review`, `ENV-<S>`, `FIX-<n>-<slug>`, `STACK-<date>`, `COMMENTS-<n>`,
   `INVESTIGATE-<slug>`, `DEPLOY-<slug>-<date>`. A repeat of the same job (a second review round, a rerun) gets a round
   suffix — `REVIEW-<n>-r2`, `STORY-<S>-review-r2`, `ENV-<S>-r2` — so the first round's brief and report survive; `--force`
   overwrites them and is for a brief that was never dispatched.
2. Launch with the Agent tool: `subagent_type: "turnstile:<agent>"`, prompt = the `PROMPT:` line the command printed.
   For `tester` pass `--var test_user=<address>`; the password is never in the prompt or the brief — the tester reads
   `TURNSTILE_TEST_PASSWORD` or the keychain item `turnstile-test-password` itself at login (`references/env/pdffiller-dev.md`
   § Credentials); the tester resolves its Figma tools per `references/tools/figma.md` and comes back `BLOCKED` when the
   environment has none. Model and effort come from the `AGENT:` line the command printed (`AGENT: turnstile:reviewer
   model=opus effort=high`, resolved per `## preferences`): pass `model` and, when the line carries one, `effort` to the
   Agent tool — never pick a model yourself. The reviewer briefs carry the resolved review skill and the agent's effort as its argument. One agent per task;
   parallel agents only across different repositories (`## Token discipline`). On a fresh head dispatch the `gate-runner` (`GATE-<n>`,
   sonnet; vars `pr_id head repo repo_path base_branch gate gate_skill previous_reports scope`) first, then the `reviewer`, whose brief
   carries `previous_reports` = the `reports/GATE-<n>.md` and so must not re-run the gate unless it pushes a commit (`references/lifecycle.md`).
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
6. Report to the lead per `references/slack.md` § Story report and **stop**: the next story waits for a member's
   `start_story` approval (there is no `--reason` way to start a story, and a parallel start needs `parallel_with` in the
   approved plan); the sends of this story's units go out through the send skill on the lead's word in chat (`## pass`).

## trunk mode (`stories.<S>.mode: trunk`, `epic.flag`)

PRs merge into the repo base behind the one epic flag and reach humans on their own (`pr add` wants the repo base; `--stacked-on`
for a deliberate stack). After every PR of the story is MERGED: deploy the base, `pass story S INTEGRATION_REVIEW --build <n>
--head <base sha>` (GitHub compare proves the merges are in it), story-reviewer on the merged diff, then two tester runs on the
same head — `ENV-S-treatment` (`--var arm=treatment`) and `ENV-S-control` (`--var arm=control`, flag off, `control_cases`) —
recorded with `--arm`; `DONE` needs both arms full and clean. The brief carries `{{flag}}`; a tester without a toggle method is BLOCKED.

## plan (re-plan after a scope change)

Edit `delivery/plan.md` (stories, branches, units, map) with the rationale in `decisions.md`; `turnstile plan-submitted`
(voids the old plan entry, opens a new one); a member approves again. Stories past `PLANNED` keep their state and
evidence; a started story cannot be dropped.

## REWORK (a human thread, changes requested, or a push after the send)

Lead rule 2026-10-14: a thread the agent resolved itself is answered at once; only threads that need the lead stop.
1. `turnstile status` proposes `pass pr … REWORK --reason …` (no entry opens); dispatch `comments-handler` (`COMMENTS-<n>`,
   `--var sent_at=<evidence.human.sent_at> --var approved_replies=none`).
2. The agent fixes, then classifies every human thread from GitHub facts: `turnstile threads <repo#n> --self-resolved <ids>
   --needs-lead <ids> --report reports/COMMENTS-<n>.md`. `self_resolved` (fixed, or justified in code) → it replies on the thread
   at once through the guarded REST replies route. `needs_lead` (decision, direction, a recorded decision, another team) → a
   `reply` entry per thread; show the members the draft and the approve line; once approved, post exactly that text (yourself or a
   `COMMENTS-<n>-r2` dispatch with `approved_replies=<ah-ids>`). A reviewer's follow-up needs a new classification first.
   The reply comes from any member's login (`epic.members`), the lead's or the agent login. A thread whose latest comment is a
   member's reply (the lead answering in person included) counts as answered without an entry.
3. Gate and Copilot on the new head (no new deep review); `turnstile status` lists what the threads still need.
4. Re-request (lead rule 2026-10-14: "replied to all comments and Copilot passed again → ping the reviewer to look again"): once
   every thread has its reply and Copilot reviewed the GitHub head with 0 open threads (repos without Copilot: the gate check
   green on it; without either, the review-request event alone), `turnstile status` prints the exact `gh api -X POST
   repos/<org>/<repo>/pulls/<n>/requested_reviewers -f 'reviewers[]=<login>'` for the thread authors (the reviewers who commented on the
   threads in this round). The comments-handler (or you) runs it — no lead approval, and the guard checks only the login (`epic.members`
   or `epic.reviewers`, no team, no bot), not the PR state; the pass then verifies the rule against GitHub. Slack sends go out on the lead's word in chat only.
   Never re-request a thread author whose last review on the current head is APPROVED (the guard refuses it: a re-request resets that
   approval, and the approval is the evidence); `status` drops them from the list and the pass takes no `--rerequested` for them.
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
- Read an agent's ≤ 8-line reply, never its report in full; open a report only at the section the next brief needs.
- Publish the board at most once per batch of passes, through a `haiku` subagent so the artifact read stays out of your context
  (`references/board.md`).
- Start a new orchestrator session each day (`turnstile status` restores everything) and run `/compact` once the context passes ~150 k.
- Agents wait on CI, a deploy or a gate with one blocking command and report when there is a fact; a "waiting" reply wakes you for nothing.

## Bugs on the board

Viewers with write access change a bug's status in the board's dropdown; it lands in the artifact db (`bugs/<id>`), not in
`state.json`. At `status` time read the `bugs` collection with `ArtifactData` and fold changes back with `turnstile bug set <id>
--state <s>` so git stays the source of truth. The board's Progress tab is a snapshot of `state.json` (completion, per-story bars, ageing).
