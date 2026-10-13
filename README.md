# Turnstile

**Evidence-gated delivery for AI agent teams.** A Claude Code plugin that runs a multi-repo epic through a strict
state machine: every PR and every story moves to the next stage only with a valid ticket, and the ticket is evidence
(head SHA + gate result) that a script checks. No ticket, no entry.

Why it exists: when an orchestrating agent coordinates implementers, reviewers and testers across several repositories,
prose rules erode under pressure. Stages blur ("AI review" quietly becomes "human review"), boards go stale, Jira lags,
and context is lost between sessions. Turnstile moves the rules out of prose and into a state file, a transition
command, role-scoped agents and hooks that physically block forbidden actions.

## What you get

- `state.yaml` — a single source of truth for the epic, in git, readable by any session or person.
- `turnstile pass` — the only way to change state; validates DoR/DoD, then writes the ledger, renders the board,
  commits the state and tells you which Jira transition to make.
- `turnstile reconcile` — read-only drift check against GitHub and Jira.
- Role agents: implementer, reviewer, story-reviewer, stack-step, comments-handler, investigator, tester, deployer.
- Hooks that block sends, merges, reviewer requests and force pushes unless the lead approved that exact action.
- Story gates: whole-story deep review and environment testing against the test plan and the Figma design, before
  anything reaches human review.

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

Commands: `pass` (the only writer of `state.json`), `reconcile` (read-only drift check against GitHub, `--json`),
`status` (reconcile + next actions + what awaits humans), `render-board`, `approve`, `jira-synced`.

Hooks (`hooks/hooks.json`, apply to subagents too):

- `guard_bash.py` blocks `gh pr merge`, `gh pr ready`, `--add-reviewer`, human `requested_reviewers` requests (Copilot allowed),
  `git push --force*`/`-f`, `git rebase`, `--no-gpg-sign`, `Co-Authored-By`, the "Generated with" footer and an empty
  Prometey `service_github_tag=`.
- `guard_slack.py` blocks every Slack send unless each PR it mentions has an approved `send`/`reply` entry in
  `awaiting_human` (and, for `send`, the PR is `READY`); missing or broken state fails closed.
- `guard_state_edit.py` warns after a manual edit of `state.json`.

Tests: `python3 -m unittest discover -s tests -v` (stdlib only, no network).

Design spec: [`docs/superpowers/specs/2026-10-13-turnstile-design.md`](docs/superpowers/specs/2026-10-13-turnstile-design.md).

## Status

Pre-alpha. Being extracted from a live epic delivery; the first consumer migrates mid-flight.

## License

MIT
