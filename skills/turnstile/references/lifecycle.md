# Lifecycle — DoR / DoD and the command per transition

Evidence carries the head it was produced for; a push voids it (`turnstile status` shows the drop). Every PR pass checks
the head and the evidence against GitHub (`IO.github_facts`): CI rollup, the gate's `gate_check` context, Copilot threads,
approvals for the head, signed commits, no trailer in commit messages, no generated-with footer in the body, the PR base.

## PR states

| State | DoR (entry) | DoD (exit) | Command that enters it |
|---|---|---|---|
| **DEV** | ticket in the approved `plan.md`; brief exists; branch from the story branch (or the PR below in the stack) | draft PR into that base; CI green (contexts minus `ci_ignore`); every commit signed, no trailer; body per `references/pr-body.md` | `turnstile pass pr <id> DEV --reason "<why back>"` (from AI_REVIEW/REWORK; drops `rework_since`) |
| **AI_REVIEW** | DEV done | **loop until clean on one head**: `deep_review.clean` + `gate.result = pass` (and `gate_check` green on GitHub) + `copilot.open_threads = 0` where `repo.copilot`; all for `head == pr.head` | `turnstile pass pr <id> AI_REVIEW --head <sha> --ci success` (re-enters itself after a push; voids an open `send`) |
| **READY** | AI_REVIEW done, head verified online | head unchanged; `blocked_by` null or MERGED for sending; story DONE (or `human_review: per_pr`) | `turnstile pass pr <id> READY --head <sha> --deep-review reports/REVIEW-<n>.md --rounds <r> --gate <gate>:pass:<run-url> [--copilot 0] [--companions locales#5]` → opens `send` |
| **ON_HUMAN_REVIEW** | lead approved the `send` (bound to the head); message went out through the guarded tool (`used_at`) | ≥ 1 approval for the head; 0 unresolved human threads; no changes requested | `turnstile pass pr <id> ON_HUMAN_REVIEW --head <sha> --slack <permalink> --reviewers a,b --approved <ah-id>` → Jira On Review |
| **REWORK** | push after send, new human thread, or changes requested | fixes pushed; gate + Copilot green on the new head (deep review is **not** repeated: `rework_since` is set); the lead replied on every human thread open at `rework_since.at`; the lead approved the `reply` entry and the reply went out | `turnstile pass pr <id> REWORK --head <sha> --reason "<thread id or push>"` (opens `reply`); back with `ON_HUMAN_REVIEW --head <new> --ci success --gate … --slack <reply permalink> --approved <ah-id>` |
| **APPROVED** | ON_HUMAN_REVIEW done | lead merged | `turnstile pass pr <id> APPROVED --approvals a,b --open-threads 0` → opens `merge` |
| **MERGED** | squash-merged by the lead | — | `turnstile pass pr <id> MERGED --merged-sha <sha>` → Jira On Hold; unblocks dependants; notes the story |

AI review order on one head: deep review (`reviewer` agent) → repo gate (`pdf-review`, `pr-review`, `review`, `run-lint` +
`run-unit-tests`; a skill gate has `gate_check: null` and the report is the evidence) → Copilot where connected. Any finding
→ fix → re-run deep review **and** gate.

## Story states

| State | DoD | Command |
|---|---|---|
| **PLANNED** | listed in the approved `plan.md` (`plan` entry approved, digest unchanged) | `turnstile plan-submitted` + the lead's approve line |
| **IN_PROGRESS** | every ticket PR ≥ READY, each based on `stories.<S>.branch` or on another PR of the story (a stack) or MERGED; stack top deployed to the slot | `turnstile pass story <S> IN_PROGRESS --approved <start_story ah-id>` (also needs the plan approved and `after` stories DONE, or a `--reason` naming the lead for the dependency only) |
| **INTEGRATION_REVIEW** | whole-story diff reviewed by `story-reviewer` until clean; fixes in the ticket PRs with gates re-run | `turnstile pass story <S> INTEGRATION_REVIEW --build <build> --head <stack-top sha>` |
| **ENV_TESTING** | `tester` ran every case + Figma parity; every fail became a bug; fixed; re-run; one full final run | enter: `turnstile pass story <S> ENV_TESTING --report reports/STORY-<S>-review.md --head <sha> --rounds <r>`; record a run (re-entry): `turnstile pass story <S> ENV_TESTING --report reports/ENV-<S>.md --cases-pass <n> --cases-fail <n> --figma-parity pass|fail [--full]` |
| **DONE** | last run `--full` with 0 fails and parity pass; every bug of the story `done`; PRs ≥ READY; the lead's `story_done` word | `turnstile pass story <S> DONE --approved <ah-id>` |

Stop rule: after DONE nothing starts until the lead says so; parallel stories (`parallel_with` or the lead's word) each
have their own branch, stack, slot and tester run. Human review receives a story's units only after DONE (or with
`human_review: per_pr` set by the lead in `plan.md` for a legacy story).

## Jira mapping (printed by `pass`, performed through the Atlassian MCP, recorded with `jira-synced`)

DEV / AI_REVIEW / READY → In progress · ON_HUMAN_REVIEW / REWORK / APPROVED → On Review · MERGED → On Hold.
