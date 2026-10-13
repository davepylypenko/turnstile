# Turnstile

**Evidence-gated delivery for AI agent teams.** A Claude Code plugin that runs a multi-repo epic through a strict
state machine: every PR and every story moves to the next stage only with a valid ticket, and the ticket is evidence
(head SHA + gate result) that a script checks. No ticket, no entry.

Why it exists: when an orchestrating agent coordinates implementers, reviewers and testers across several repositories,
prose rules erode under pressure. Stages blur ("AI review" quietly becomes "human review"), boards go stale, Jira lags,
and context is lost between sessions. Turnstile moves the rules out of prose and into a state file, a transition
command, role-scoped agents and hooks that physically block forbidden actions.

## What you get

- `state.json` — a single source of truth for the epic, in git, readable by any session or person.
- `turnstile pass` — the only way to change state; validates DoR/DoD, verifies the PR head against GitHub, then writes
  the ledger, renders the board, commits the state and tells you which Jira transition to make.
- `turnstile reconcile` — read-only drift check against GitHub; every command it proposes is one `pass` would accept.
- Role agents: implementer, reviewer, story-reviewer, stack-step, comments-handler, investigator, tester, deployer.
- Hooks that block sends, merges, reviewer requests, force pushes and manual state edits unless the lead approved
  that exact action.
- Story gates: whole-story deep review and environment testing against the test plan and the Figma design, before
  anything reaches human review.

## Usage (core)

```
echo delivery > .turnstile                      # workspace root → delivery dir
turnstile status                                # reconcile with GitHub + where we are (exit 1 when gh facts are missing)
turnstile pass pr jsfiller#13222 AI_REVIEW --head d2583e9b --ci success
turnstile pass pr jsfiller#13222 READY --head d2583e9b --deep-review reports/REVIEW-13222.md --rounds 3 --gate pdf-review:pass:<run-url>
TURNSTILE_LEAD=1 turnstile approve ah-3         # the lead types this after saying "send"; agents never do
turnstile pass pr jsfiller#13222 ON_HUMAN_REVIEW --head d2583e9b --slack <permalink> --reviewers isachivka --approved ah-3
turnstile jira-synced jsfiller#13222 "On Review"
turnstile pass pr jsfiller#13222 REWORK --reason "human thread r4231213730"      # opens a 'reply' entry for the lead
turnstile pass pr jsfiller#13222 ON_HUMAN_REVIEW --head 9f1c2a3b --ci success --gate pdf-review:pass --slack <reply permalink> --approved ah-5
turnstile pass pr jsfiller#13222 APPROVED --approvals isachivka --open-threads 0
turnstile pass pr jsfiller#13222 MERGED --merged-sha <sha>
turnstile pass story S1 IN_PROGRESS --approved ah-1                              # or --reason "lead 2026-10-13: start now"
turnstile pass story S1 INTEGRATION_REVIEW --build 173111 --head <stack-top sha>
turnstile pass story S1 ENV_TESTING --report reports/STORY-S1-review.md --head <stack-top sha> --rounds 2
turnstile pass story S1 DONE --report reports/ENV-S1.md --cases-pass 31 --cases-fail 0 --figma-parity pass --approved ah-9
turnstile render-board
```

Exit code 2 and `MISSING …` lines mean the turnstile did not turn: nothing was written. The state, ledger and board
are written only after the rules pass, and restored if the git commit fails (`MISSING git commit failed: …`).

### Heads and GitHub

Every PR pass asks GitHub for the PR's head (`gh api graphql`). The pass is refused when the recorded `--head` (or the
stored head) is not the real one, and when `gh` fails. `--offline` skips the check with a loud `WARN` line and records
`evidence.head_verified: false`; `READY` and `ON_HUMAN_REVIEW` stay refused until a pass runs online for that head.

### The lead's word (`awaiting_human`)

`pass` opens entries for the lead: `send` on READY, `reply` on REWORK, `merge` on APPROVED, `story_done` when a story
enters ENV_TESTING, `start_story` for every PLANNED story whose `after` stories are DONE. Only the lead approves them,
by typing `TURNSTILE_LEAD=1 turnstile approve <ah-id>`; the Bash hook blocks the command without that literal, and the
CLI refuses it without the variable. `pass … --approved <ah-id>` then requires an entry of the right type for that
PR/story that is approved, not consumed and not voided; the pass consumes it. A `send` is voided when the PR drops
back to AI_REVIEW (the word was for the old head). One approval allows exactly one Slack message.

### Commands

`pass` (the only writer of `state.json`), `reconcile` (read-only drift check against GitHub, `--json`), `status`
(reconcile + next actions + what awaits humans), `render-board`, `approve` (lead only), `jira-synced` (validated
against the PR's state).

`pass pr` flags: `--head`, `--ci success|failure`, `--deep-review <report> --rounds N [--not-clean]`,
`--gate <name>:<pass|fail>[:<run-url>]`, `--copilot <open-threads>`, `--slack <permalink> --reviewers a,b
--approved <ah-id>`, `--approvals a,b --open-threads N`, `--merged-sha`, `--reason`, `--offline`, `--no-commit`.
`pass story` flags: `--approved`, `--reason`, `--build --head`, `--report --head --rounds [--not-clean]`,
`--report --cases-pass N --cases-fail N --figma-parity pass|fail`. Report paths are relative to `delivery/` and must
exist.

### Hooks

`hooks/hooks.json`, all PreToolUse, apply to subagents too, and fail closed (a crash, a malformed payload or a missing
`python3` blocks the call):

- `guard_bash.py` blocks `gh pr merge|ready`, `--add-reviewer`, human `requested_reviewers` requests (only the Copilot
  bot may be requested; `--input` bodies are refused), REST `pulls/N/merge` writes, GraphQL
  `mergePullRequest|markPullRequestReadyForReview|requestReviews`, `ready_for_review`, `git push --force*`/`-f`/`+ref`,
  `git rebase`, `--no-gpg-sign`, `-c commit.gpgsign=false`, an empty Prometey `service_github_tag=`, a
  `Co-Authored-By` trailer or the "Generated with [Claude Code]" footer in a `git commit` / `gh pr create|edit` /
  `gh api` call, writes to `state.json` through redirection, `sed -i`, `tee`, `python -c`, `cp`/`mv`/`rm` (unless
  the command carries `TURNSTILE_MIGRATION=1`), and `turnstile approve` without `TURNSTILE_LEAD=1` in the same
  command. Global options before the subcommand (`git -C dir`, `git -c k=v`, `gh -R owner/repo`) are covered.
- `guard_slack.py` blocks every Slack send/draft/schedule unless each PR it mentions has an approved, unused
  `send` (PR `READY`) or `reply` (PR `REWORK`) entry in `awaiting_human` and the channel is that repo's review
  channel (`epic.repos.<repo>.slack`). It records `used_at` on the entry (one send per approval) and a ledger line;
  missing or broken state fails closed.
- `guard_state_edit.py` blocks Edit/Write/MultiEdit on `state.json` unless the environment has
  `TURNSTILE_MIGRATION=1`.

Tests: `python3 -m unittest discover -s tests -v` (stdlib only, no network; a canned `gh` on `PATH` serves the
end-to-end test).

Design spec: [`docs/superpowers/specs/2026-10-13-turnstile-design.md`](docs/superpowers/specs/2026-10-13-turnstile-design.md).

## Status

Pre-alpha. Being extracted from a live epic delivery; the first consumer migrates mid-flight.

## License

MIT
