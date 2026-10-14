# Turnstile

**Evidence-gated delivery for AI agent teams.** A Claude Code plugin that runs a multi-repo epic through a strict
state machine: every PR and every story moves to the next stage only with a valid ticket, and the ticket is evidence
(head SHA + gate result) that a script checks. No ticket, no entry.

Why it exists: when an orchestrating agent coordinates implementers, reviewers and testers across several repositories,
prose rules erode under pressure. Stages blur ("AI review" quietly becomes "human review"), boards go stale, Jira lags,
and context is lost between sessions. Turnstile moves the rules out of prose and into a state file, a transition
command, role-scoped agents and hooks that physically block forbidden actions.

## Install

```
claude plugin marketplace add davepylypenko/turnstile
claude plugin install turnstile
```

(Without a marketplace entry: clone the repo and start Claude Code with `--plugin-dir <path>`.)

## What you get

- `state.json` — a single source of truth for the epic, in git, readable by any session or person.
- `turnstile pass` — the only way to change state; validates DoR/DoD, verifies the PR head against GitHub, then writes
  the ledger, renders the board, commits the state and tells you which Jira transition to make.
- `turnstile reconcile` — read-only drift check against GitHub; every command it proposes is one `pass` would accept.
- `turnstile threads` — records each human review thread as `self_resolved` (the agent replies at once) or `needs_lead`
  (the reply waits for the lead's word on that thread), from GitHub facts.
- `turnstile init` / `plan-submitted` / `brief` / `bug add|set` — the epic skeleton, the lead-approved plan (a re-plan cannot
  move a started story's branch), agent briefs and the bug list (one bug per story + test case), all written through the
  same guarded path as `pass`.
- Skill `turnstile` (`skills/turnstile/SKILL.md`): `init`, `status`, `pass`, `dispatch <agent> <brief>`, `story-gate <S>`,
  `plan`; references for DoR/DoD, kick-off, briefs, PR body, Slack, reports, evidence and env recipes.
- Role agents: implementer, reviewer, story-reviewer, stack-step, comments-handler, investigator, tester, deployer.
- Hooks that block sends, merges, reviewer requests, force pushes, PR comments, review submissions, resolving human
  threads and manual state edits unless the lead approved that exact action; a reply to a reviewer thread passes only for
  a classified thread (at once when the agent resolved it, with the lead's word when it needs the lead), and the re-request
  of a REWORK PR's thread authors passes once every thread has its reply and the head is clean (lead rule 2026-10-14).
- Story gates: whole-story deep review and environment testing against the test plan and the Figma design, before
  anything reaches human review.

## Usage

```
turnstile init --epic MYD-16538 --workitem pdfd-429-l2f-editor-funnel --knowledge ../pdffiller-knowledge \
  --lead davyd.pylypenko --lead-github <login> [--agent-github <login the agents' gh posts as>] --github-org pdffiller \
  --repo '{"name":"jsfiller","base":"develop","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CCGLRULNR","gate":"pdf-review","ci_ignore":["pdf-review","gate / gate"]}' \
  --repo '{"name":"front-link2fill-app","base":"master","epic_branch":"epic_myd-16538_l2f-funnel","slack":"CFZ7EC5BN","gate":"pr-review","gate_check":null,"copilot":true}' \
  --variant l2f-funnel --desk desk05 --chat-language Ukrainian          # the epic branch is cut from origin/<base> after a fetch
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
turnstile pass pr jsfiller#13222 AI_REVIEW --head d2583e9b --ci success
turnstile pass pr jsfiller#13222 READY --head d2583e9b --deep-review reports/REVIEW-13222.md --rounds 3 --gate pdf-review:pass:<run-url>
! TURNSTILE_LEAD=1 turnstile approve ah-3       # the lead types this in the Claude Code prompt; agents never do
turnstile pass pr jsfiller#13222 ON_HUMAN_REVIEW --head d2583e9b --slack <permalink> --reviewers isachivka --approved ah-3
turnstile jira-synced jsfiller#13222 "On Review"
turnstile pass pr jsfiller#13222 REWORK --reason "human thread r4231213730"      # opens no entry
turnstile threads jsfiller#13222 --self-resolved PRRT_kwDOa --needs-lead PRRT_kwDOc --report reports/COMMENTS-13222.md   # one 'reply' entry per needs_lead thread
gh api -X POST repos/pdffiller/jsfiller/pulls/13222/comments/2412345678/replies -f body='Fixed in 9f1c2a3b'   # self_resolved: at once
! TURNSTILE_LEAD=1 turnstile approve ah-5       # the lead's word on the needs_lead thread; then its reply goes out the same way
gh api -X POST repos/pdffiller/jsfiller/pulls/13222/requested_reviewers -f 'reviewers[]=isachivka'   # all replied + head clean: re-request the thread authors
turnstile pass pr jsfiller#13222 ON_HUMAN_REVIEW --head 9f1c2a3b --ci success --gate pdf-review:pass --rerequested isachivka   # no --slack/--approved from REWORK
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
approval; Slack stays lead-approved. `turnstile status` prints that exact command while it has not happened for the head, then the
`--rerequested` pass. A push-only rework (no reviewer comment since the PR last went to humans) pings nobody: the return records
`reviewer_notified: false`, the board reads "reviewers not notified", and the lead decides.

### The lead's word (`awaiting_human`)

`pass` opens entries for the lead: `send` on READY, `merge` on APPROVED, `story_done` when a story
enters ENV_TESTING, `start_story` for every PLANNED story whose `after` stories are DONE. Only the lead approves them
(see "How the lead approves"). `pass … --approved <ah-id>` then requires an entry of the right type for that
PR/story that is approved, not consumed and not voided; the pass consumes it. A `send` is voided when the PR drops
back to AI_REVIEW (the word was for the old head). One approval allows exactly one Slack message, and the message must
have gone out through the guarded tool (`used_at`) before the PR can be passed to ON_HUMAN_REVIEW. `plan` entries are
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

Agents (`agents/`): implementer (sonnet), reviewer (opus, xhigh), story-reviewer (fable), stack-step, comments-handler,
investigator, tester (opus, Figma parity), deployer (sonnet); launched as `turnstile:<name>` with a brief from
`turnstile brief`.

### How the lead approves

The lead approves an `awaiting_human` entry **only by typing the command themself in the Claude Code prompt with the
`!` prefix**:

```
! TURNSTILE_LEAD=1 turnstile approve ah-3
```

The `!` prefix runs the line in the user's shell, outside the model's tool calls, so no hook sees it and no agent can
issue it. `approve` records `approved_via: "lead-terminal"` on the entry and the ledger line says so. The Bash hook
blocks **any** model-issued command that contains `turnstile approve`, `TURNSTILE_LEAD` or `TURNSTILE_MIGRATION`, in
any quoting, `env`, `export`, `bash -c` or heredoc form (the check runs on the command with quotes and backslashes
stripped and whitespace collapsed), and the CLI keeps refusing `approve` without `TURNSTILE_LEAD=1` in its environment.
The orchestrator's job is to report what awaits the lead (`turnstile status`) and ask the lead to run that line; it
never runs it.

### Commands

`init`, `plan-submitted`, `pass` (the writer of transitions), `approve` (lead only), `threads` (thread classification from
GitHub facts), `jira-synced` (validated against the PR's state), `brief` (renders an agent brief; refuses unfilled placeholders and, for every agent but the investigator, an unapproved
plan), `bug add|set`, `reconcile` (read-only, `--json`), `status`, `render-board`.

`pass pr` flags: `--head`, `--ci success|failure`, `--deep-review <report> --rounds N [--not-clean]`,
`--gate <name>:<pass|fail>[:<run-url>]`, `--copilot <open-threads>`, `--slack <permalink> --reviewers a,b
--approved <ah-id>` (READY → ON_HUMAN_REVIEW only), `--rerequested a,b` (REWORK → ON_HUMAN_REVIEW only), `--approvals a,b --open-threads N`, `--merged-sha`, `--reason`, `--companions locales#5` (on READY), `--offline`, `--no-commit`.
`pass story` flags: `--approved`, `--reason`, `--build --head`, `--report --head --rounds [--not-clean]`,
`--report --cases-pass N --cases-fail N [--cases-not-testable N] [--failed-cases a,b] --figma-parity pass|fail|not_testable_here --build --head [--full]`
(a `--full` run's three counts must add up to `stories.<S>.test_cases`). Report paths are
relative to `delivery/` and must exist.

### Hooks

`hooks/hooks.json`, PreToolUse plus one PostToolUse, apply to subagents too, and fail closed (a crash, a malformed payload or a missing
`python3` blocks the call):

- `guard_bash.py` blocks `gh pr merge|ready`, `--add-reviewer`, `gh pr create --reviewer|-r`, human `requested_reviewers`
  requests (the Copilot bot may be requested; `--input` bodies, team reviewers and computed logins or routes are refused; the
  one human exception is below), REST `pulls/N/merge` writes, GraphQL
  `mergePullRequest|markPullRequestReadyForReview|requestReviews*`, `ready_for_review`, `git push --force*`/`-f`/`+ref`,
  `git rebase`, `--no-gpg-sign`, `-c commit.gpgsign=false`, an empty Prometey `service_github_tag=`, a
  `Co-Authored-By` trailer or the "Generated with [Claude Code]" footer in a `git commit` / `gh pr create|edit` /
  `gh api` call — also when they sit in a file given with `-F`/`--file`/`--body-file`/`--input` (the hook reads it) —
  `gh api graphql` with `query=@file` or `--input` (a mutation in a file), `git config pull.rebase true`, the spaced
  `service_github_tag ''` form, every command that contains `turnstile approve`, `TURNSTILE_LEAD` or `TURNSTILE_MIGRATION` (the
  lead's markers; see "How the lead approves"), and **every command that mentions `state.json` (also as a glob) or
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
  main-thread orchestrator (no `agent_id`) passes and records with `jira-synced`.
- `guard_slack.py` (PreToolUse) blocks every Slack send/draft/schedule unless each PR it mentions has an approved,
  unused `send` entry (PR `READY`) in `awaiting_human` (a `reply` entry never unlocks Slack) and the channel is that repo's review
  channel (`epic.repos.<repo>.slack`). A paired PR the same message mentions (a `locales` PR, a repo outside
  `epic.repos`) needs no entry of its own when the send entry lists it in `companions` (`pass pr <main> READY
  --companions locales#5`); every refusal names the id it is about. For a DONE story it also asks GitHub for the head of
  every PR in the story's `deploy.heads` and refuses when one moved (a push without `pass pr`); `gh` failing fails closed. It
  only checks; missing or broken state fails closed.
- `post_slack.py` (PostToolUse, same matcher) records the send once the tool result carries a `message_ts`: `used_at`,
  `used_channel` and `message_ts` on the entry (one send per approval), a ledger line, a board render and a git commit
  of `delivery/`. A denied or failed send leaves the approval usable. `pass … ON_HUMAN_REVIEW` requires the entry's
  `used_at` and a permalink of the form `https://<workspace>.slack.com/archives/…`.
- `guard_state_edit.py` blocks Edit/Write/MultiEdit on `state.json` and `ledger.md` unless the environment has
  `TURNSTILE_MIGRATION=1`.

### Threat model

The hooks, the ledger and `turnstile reconcile` are **defence in depth, not proof**. Everything runs as one OS user:
an agent that finds a write path the Bash guard does not recognise can edit `state.json`, and the lead's markers are
only blocked for commands that pass through the model's tool calls. What holds the line:

- the lead's approval never passes through the model (`!`-prefixed prompt line), so no agent can produce one;
- every writer the plugin knows (`pass`, `approve`, the Slack PostToolUse hook) leaves a ledger line and a git commit,
  so a write that did not come through them is visible as drift: `turnstile reconcile` flags every `approved_at` whose
  ledger line is missing or lacks `approved_via: lead-terminal` (`approval_unlogged`), heads, checks, approvals and
  threads are compared with GitHub, and `status` lists uncommitted changes in `delivery/`;
- the Slack guard checks the state **and** returns `permissionDecision: "ask"`, so the lead confirms every send in the UI;
  a forged approval still needs the lead to click. This is the one control an agent cannot forge; approvals of
  `start_story`/`story_done`/`send` entries in `state.json` are forgeable by a script file the guard never sees.

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
