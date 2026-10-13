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

Design spec: [`docs/superpowers/specs/2026-10-13-turnstile-design.md`](docs/superpowers/specs/2026-10-13-turnstile-design.md).

## Status

Pre-alpha. Being extracted from a live epic delivery; the first consumer migrates mid-flight.

## License

MIT
