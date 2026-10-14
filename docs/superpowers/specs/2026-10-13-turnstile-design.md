# Turnstile — design spec (2026-10-13)

*A turnstile lets one through at a time, only with a valid ticket. Here the ticket is evidence for the current head.*

Claude Code plugin that runs the delivery of a multi-repo epic through a strict, evidence-based flow.
Owner: Davyd Pylypenko. Canonical source: Davyd's personal GitHub repository; a vendored copy lives in
`pdffiller/pdffiller-knowledge` for the team. First consumer: epic MYD-16538 (L2F editor funnel), migrated mid-flight.

## 1. Goals

1. **Session-independent source of truth.** Any orchestrator session, or another person, resumes the epic from files in
   git, with no context carried between sessions. Two people can run different repos or stories of the same epic in
   parallel.
2. **Flow as hard rules.** Every PR and every story moves through named states with a Definition of Ready (DoR) on entry
   and a Definition of Done (DoD) on exit. A transition without recorded evidence for the current head is refused by a
   script, not by a rule in prose. "AI review" and "human review" are distinct states and cannot blur.
3. **Side effects happen as part of the transition, every time.** Jira status, the PR board artifact, the ledger and the
   git commit of the state are performed by the same command that changes the state. There is no separate
   "update the board later".
4. **Story checkpoints.** After every story (business slice) the orchestrator stops: whole-story deep review, then
   environment testing against the test plan and the Figma design, pixel-level, by a dedicated tester agent. Human review
   receives only stories that passed both gates.
5. **Human review is the bottleneck, so it gets reviewable units.** PRs sent to humans are sized at roughly 400 lines
   of logic (tests and markup excluded), planned at epic kick-off.

Non-goals: replacing the repos' own review skills (`pdf-review`, `crit-review`, `pr-review`, `review`), replacing
Prometey/variant tooling (`prometey-variant` skill stays), automating anything the lead decides (send, a reply that needs
the lead's decision, merge, start next story).

## 2. Artefacts and state

### 2.1 Location

A git worktree of `pdffiller-knowledge` inside the epic workspace, on branch `epic/<epic-key-slug>`, merged into `main`
only when the epic ends. Path: `context/workitems/<workitem>/delivery/` (next to the existing `decomposition.md`).

```
delivery/
  state.json      # single source of truth; written only by `turnstile pass` (see §5)
  ledger.md       # append-only event log, written by `turnstile pass`
  plan.md         # kick-off analysis output: stories, PR plan, merge order, test-case map (lead-approved)
  decisions.md    # decisions taken + open questions for humans
  briefs/         # agent briefs
  reports/        # agent reports (reviews, tests, investigations)
  evidence/       # tester screenshots next to Figma frames, per story/case
  board.html      # rendered board; the claude.ai artifact is published from it
```

The workspace `CLAUDE.md` shrinks to: role (orchestrator), path to `delivery/`, plugin name, chat language. All
epic facts live in `state.json` and `decisions.md`.

### 2.2 `state.json` schema (shown as YAML for readability; the file is JSON, 2-space indent, sorted keys)

```yaml
epic:
  key: MYD-16538
  workitem: pdfd-429-l2f-editor-funnel
  roles: { lead: davyd.pylypenko, lead_github: ..., agent_github: ..., pm: ..., design: ... }   # roles, not names in prose;
                                                       # agent_github = the login thread replies come from (default lead_github)
  repos:
    jsfiller:  { base: develop, epic_branch: epic_myd-16538_l2f-funnel, slack: CCGLRULNR, gate: pdf-review, copilot: false }
    docs-platform: { base: main, epic_branch: ..., slack: CFZ7EC5BN, gate: pdf-review, copilot: true }
    pdffiller: { base: master, epic_branch: l2f-funnel, slack: G8S415WG6, gate: pdf-review, copilot: true, branch_prefix: "l2f-funnel-myd-" }
  board: { artifact_url: ..., capabilities: [db, user] }
  environment: { variant: l2f-funnel, desk: desk05, recipe: references/env/pdffiller-dev.md }

stories:
  S1:
    title: "Create form header + activation flow"
    tickets: [MYD-18079, MYD-18085, ...]
    repos: [jsfiller]
    after: []            # stories that must be DONE first
    parallel_with: [S3]  # explicitly allowed to run concurrently
    state: PLANNED | IN_PROGRESS | INTEGRATION_REVIEW | ENV_TESTING | DONE
    test_cases: [TP-001, TP-004, ...]
    figma: [ "KOew9XK7uPLPCBqBn0ba8Z:9098-41434", ... ]
    env_slot: { variant: l2f-funnel, desk: desk05 }
    human_review_units: [ { title: "...", prs: [jsfiller#13222, jsfiller#13223] } ]   # from plan.md
    evidence:
      integration_review: { report: reports/STORY-S1-review.md, head: <epic or stack-top sha>, rounds: 2, clean: true }
      env_test: { report: reports/ENV-S1.md, build: 173111, cases: { pass: 31, fail: 0, not_testable_here: 2 }, figma_parity: pass }

prs:
  jsfiller#13222:
    ticket: MYD-18075
    story: S1
    branch: feature/MYD-18075-l2f-state
    base: epic_myd-16538_l2f-funnel
    state: DEV | AI_REVIEW | READY | ON_HUMAN_REVIEW | REWORK | APPROVED | MERGED
    head: d2583e9b
    blocked_by: jsfiller#13195 | null       # merge order; never blocks AI_REVIEW
    evidence:
      ci:          { head: d2583e9b, status: success }
      deep_review: { head: d2583e9b, report: reports/REVIEW-13222.md, rounds: 3, clean: true }
      gate:        { name: pdf-review, head: d2583e9b, result: pass, run: <url> }
      copilot:     { head: d2583e9b, open_threads: 0 }          # omitted when repo.copilot=false
      human:       { sent_at: ..., slack_permalink: ..., reviewers: [isachivka], sent_head: d2583e9b,
                     open_threads: 0, approvals: [], returned_at: ...,     # returned_at: back from REWORK
                     rerequested: { logins: [isachivka], head: 9f1c2a3b, at: ... },   # thread authors re-requested on GitHub (2026-10-14)
                     reviewer_notified: true | false }                   # false: push-only rework, nobody pinged (the lead decides)
    threads:                                  # human review threads, classified from GitHub facts by `turnstile threads` (2026-10-14)
      PRRT_kwDOabc: { class: self_resolved | needs_lead, comment_id: "2412345678", comment_ids: [...], reviewer: isachivka,
                      last_reviewer_at: 2026-10-14T09:12:03Z, classified_at: ..., report: reports/COMMENTS-13222.md }
    jira: { status: "On Review", synced: true }
    next_action: "wait for human approval"    # computed by the script, never typed by hand

bugs:
  - { id: b03, story: S1, title: ..., source: "lead 2026-10-08", pr: front-link2fill-app#1205, figma: ..., state: todo|ai|testing|done }

awaiting_human:
  - { id: ah-12, owner: lead, type: send|reply|merge|decision|start_story, pr: jsfiller#13222, created_at: ..., payload: reports/...,
      approved_at: null }
  - { id: ah-13, owner: lead, type: reply, pr: jsfiller#13222, thread: PRRT_kwDOabc, last_reviewer_at: ..., payload: reports/COMMENTS-13222.md,
      approved_at: null }                     # one per needs_lead thread; the lead's word for that thread's GitHub reply only
```

Invariant: **every piece of evidence carries the `head` it was produced for.** A push changes `head`; `turnstile reconcile`
detects it and the PR drops to `REWORK` (after being sent) or `AI_REVIEW` (before). "Ready only with Copilot closed" and
"On human review only while the sent head is unchanged" are consequences of the schema, not rules to remember.

## 3. PR lifecycle

```
DEV ──► AI_REVIEW ──► READY ──► ON_HUMAN_REVIEW ──► APPROVED ──► MERGED
          ▲               │             │
          └───────────────┴──── REWORK ◄┘   (human comment or any push after the send)
```

| State | DoR (entry) | DoD (exit) | Side effects on transition |
|---|---|---|---|
| **DEV** | ticket in an approved story plan; brief exists; branch cut from the epic/story branch | draft PR into the epic/story branch; CI green; commits signed, no trailer; PR body per template | Jira → In progress; ledger; board |
| **AI_REVIEW** | DEV done | **loop until clean on one head**: `deep_review.clean` + `gate.result=pass` + `copilot.open_threads=0` (where enabled), all with `head == pr.head`; CI green | ledger; board (AI-gate column shows heads) |
| **READY** | AI_REVIEW done | head unchanged; `blocked_by` null or MERGED *for sending* | ledger; board; `awaiting_human: send` for lead |
| **ON_HUMAN_REVIEW** | lead approved the send; Slack message posted; `human.sent_head == head` | ≥1 approval; 0 unresolved human threads | Jira → On Review; permalink stored; board |
| **REWORK** | any of: push after send, new human thread, changes requested | fixes pushed; `gate` and `copilot` pass again on the new head (deep_review is **not** repeated after human review); every human thread opened since the send, and every unresolved one, is classified (`self_resolved` / `needs_lead`, from GitHub facts) and has a reply on GitHub newer than the thread's last reviewer comment — `self_resolved`: from the agent's account (`roles.agent_github`), posted at once; `needs_lead`: posted only after the lead approved that thread's `reply` entry (or by the lead in person); no Slack message, no blanket approval (2026-10-14); a **thread-driven** rework (a reviewer commented on a thread since the PR last went to humans) then re-requests review on GitHub from exactly those reviewers, after the replies and once Copilot reviewed the new head with 0 open threads (repos without Copilot: the gate check green on it) — `requested_reviewers` POST, no lead approval — and the pass records it with `--rerequested <logins>`, verified against GitHub (`reviewRequests`, a request event newer than the replies and the clean signal); a **push-only** rework re-requests nobody and records `reviewer_notified: false` (the lead decides) | ledger; `reply` entry per needs_lead thread; board shows "reviewer not notified" until replies are posted; then → ON_HUMAN_REVIEW (`sent_head` = new head, thread entries consumed, `evidence.human.rerequested` + `reviewer_notified: true`, or `reviewer_notified: false` and "reviewers not notified" on the board) |
| **APPROVED** | ON_HUMAN_REVIEW done | lead merged | `awaiting_human: merge` for lead |
| **MERGED** | squash-merged into the epic/story branch | — | Jira → On Hold; board; re-evaluate `blocked_by` of other PRs; re-evaluate the story DoD |

AI_REVIEW is composed of three sources, run in this order on the same head, and **recursive**: any finding from any
source → fix → re-run deep review **and** the repo gate → until both are clean on one head.

1. `deep_review` — the reviewer agent reads the whole diff against the base: scope vs ticket, control arm, tests'
   assertions, invariants, design fidelity. Output: findings list; one-line fixes may be applied by the reviewer.
2. `gate` — the repo's own review skill, run separately and mandatorily where the repo has one: `pdf-review`
   (jsfiller, docs-platform, pdffiller), `crit-review` where still used, `pr-review` / `review` / `run-lint` +
   `run-unit-tests` elsewhere. Its own PR comments and labels are the only allowed PR comments.
3. `copilot` — where connected, after every push.

Rules above the table:
- A push is a new head; evidence for the old head is void. `turnstile reconcile` moves the PR, nobody decides "this one is small".
- AI_REVIEW never waits for anything. `blocked_by` only affects sending and merging.
- Only READY goes to humans. No "the gate will catch up".
- Human threads (lead rule 2026-10-14): a thread the agent resolved itself — fixed in code or answered with a code-level
  justification — is `self_resolved` and gets the agent's reply at once, without asking; a thread that needs the lead's
  decision or involvement (product/design/scope/architecture, a disagreement on direction, a conflict with a recorded
  decision, another team) is `needs_lead` and its reply waits for the lead's word on that thread. A reviewer's comment
  newer than the classification needs a new one. Human threads are resolved by the reviewer or the lead only, never by an
  agent. Copilot threads are resolved only after a fix or a recorded justification.
- Re-request (lead rule 2026-10-14): "if you replied to all comments on a PR and Copilot passed again, ping the reviewer to look
  again". Once every human thread in scope has our latest reply and Copilot reviewed the current head with 0 open threads (repos
  without Copilot: the repo gate's check is green on it), the agents re-request review on GitHub from the reviewers who commented on
  the threads in this round (`gh api -X POST repos/<org>/<repo>/pulls/<n>/requested_reviewers -f 'reviewers[]=<login>'`). No lead
  approval is needed for that; Slack stays lead-approved. A push-only rework (no reviewer comment since the PR last went to humans)
  pings nobody: the return records `reviewer_notified: false`, the board says "reviewers not notified", and the lead decides.
- One transition = one `turnstile pass` call, which performs Jira, ledger, board and the git commit of the state.

## 4. Story lifecycle and kick-off analysis

### 4.1 Kick-off (once, before any code)

1. The orchestrator reads the decomposition, PRD, design, test plan and every target repo's `CLAUDE.md`.
2. It writes `plan.md`: stories (business slices testable/releasable on their own; if the decomposition is not by story,
   the orchestrator defines its own slices with a rationale); per story: tickets, repos, dependencies (`after`,
   `parallel_with`), merge order, **PR plan for human review** sized at ~400 lines of logic per unit (ticket PRs go into a
   story branch; humans get the story PR or 2–3 PRs split by subsystem, e.g. state+API / UI / tests), test-case map,
   Figma frames per story, inputs needed from humans and when, environment slots.
3. The lead approves `plan.md`. Without approval no story leaves PLANNED and no agent starts.

### 4.2 Story states

| State | DoD | Who |
|---|---|---|
| **PLANNED** | in approved `plan.md` | — |
| **IN_PROGRESS** | every ticket PR of the story ≥ AI_REVIEW done, stacked or merged into the story branch; the stack top deployed to the story's environment slot | orchestrator + agents |
| **INTEGRATION_REVIEW** | the whole-story diff against the epic branch passed a deep review (story-reviewer agent), recursive until clean; fixes land in the ticket PRs, whose gates are re-run | story-reviewer |
| **ENV_TESTING** | tester agent ran every story test case on the environment plus Figma parity for every screen/state; report has 0 open discrepancies; every fail became a bug → fixed → re-run (failed cases only, then one full final run) | tester |
| **DONE** | lead received the report and said "send" → the story's human-review units move to ON_HUMAN_REVIEW | lead |

**Stop rule (per story):** after DONE the orchestrator does **not** start another story until the lead says so. The
rule is per story: a finished story waits for the word, but never blocks stories already authorised. Parallel stories
are a property of the plan (`parallel_with`) or of an explicit lead instruction; each has its own story branch, stack,
environment slot and tester run; file overlaps between parallel stories are flagged in the plan and resolved by merge
order.

Human review happens **before** merge into the epic branch, on the story's units (decision 2026-10-13): human review is
the scarcest resource, so it receives already integrated, tested code.

## 5. Commands

Shipped as one CLI `turnstile` in the plugin (Python 3.9+, standard library only + `gh`; state is JSON so no YAML dependency), invoked by the skill. The orchestrator never edits
`state.json` by hand.

### `turnstile pass`

```
turnstile pass pr jsfiller#13222 AI_REVIEW --head d2583e9b --deep-review reports/REVIEW-13222.md --rounds 3 --gate pdf-review:pass:<run> --copilot 0
turnstile pass pr jsfiller#13222 ON_HUMAN_REVIEW --slack <permalink> --reviewers isachivka --approved ah-12
turnstile pass story S1 ENV_TESTING --report reports/ENV-S1.md
turnstile pass pr jsfiller#13222 REWORK --reason "human thread r4231213730"
turnstile pass pr jsfiller#13222 ON_HUMAN_REVIEW --head 9f1c2a3b --ci success --gate pdf-review:pass --rerequested isachivka   # back from REWORK: no --slack/--approved; --rerequested only after a thread-driven rework
```

Always in this order: validate DoD of the current state and DoR of the target, including `head` equality of all
evidence → on failure print exactly what is missing and exit non-zero → on success write `state.json`, append to
`ledger.md`, render `board.html` from `state.json`, commit `delivery/` on the epic branch of the knowledge worktree,
print the artifact publish instruction and the Jira transition to perform. The skill then publishes the artifact and
performs the Jira transition through the Atlassian MCP (no API token; decision 2026-10-13) and records `jira.synced`.
The command's last line is a one-line summary for the lead's message.

### `turnstile reconcile`

Read-only. For every PR: GitHub head, check-runs (CI, gate), approvals, unresolved threads (human vs Copilot),
draft/ready, merged state; Jira status. Compares with `state.json` and prints a list of discrepancies with the proposed
`turnstile pass` for each unambiguous case: push after send → REWORK; a human thread whose last reviewer comment has no newer
reply → REWORK (2026-10-14: a replied thread stays unresolved until the reviewer resolves it); changes requested on the
current head → REWORK (one on an older head was answered by the rework's push); approval + 0 threads →
APPROVED; merged → MERGED; gate red on the current head → evidence void; REWORK with every reviewer thread replied and a clean
head (Copilot's review of it with 0 open threads, else the gate check) → the exact `requested_reviewers` re-request of the thread
authors until GitHub shows it after the replies, then the `--rerequested` pass; a push-only REWORK → "nobody is re-requested, the
lead decides" (2026-10-14). It changes nothing. Runs at session start and on demand (`status`).

### `turnstile threads`

```
turnstile threads jsfiller#13222 --self-resolved PRRT_kwDOa,2412345678 --needs-lead PRRT_kwDOc --report reports/COMMENTS-13222.md
```

REWORK only. Reads the PR's review threads from GitHub; every id (a `PRRT_…` thread id or a REST comment id of the thread)
must be a human thread with a reviewer comment. Records `prs.<id>.threads.<thread>` with the class, the top-level comment id
and the reviewer's last comment time; opens one `reply` entry per `needs_lead` thread (voids an entry whose classification
changed); prints the replies route for every `self_resolved` thread and the approve line for every `needs_lead` one; ledger,
board, commit. Without ids it lists the threads in scope and their class, and writes nothing.

### `turnstile render-board`

`state.json` → `board.html` (tiles per state, repo tables with PR / Slack permalink / AI gate heads / blocked-by /
note, story tiles with gate evidence, bugs tab with the db-backed status dropdowns, legend with the Jira mapping).
Called by `turnstile pass`; also standalone.

### Skill commands

`init` (worktree + `delivery/` + kick-off analysis → `plan.md`), `status` (reconcile + where-we-are + `awaiting_human`),
`turnstile pass`, `dispatch <agent> <brief>` (standardised agent launch with the brief template), `story-gate <S>`
(integration review then env testing, with the transitions in between), `plan` (re-plan after a scope change, needs
lead approval again).

## 6. Hooks (physical guards; apply to subagents too)

- PreToolUse `slack_send_message` / `slack_send_message_draft`: blocked unless `awaiting_human` has a `send` entry
  for that PR with `approved_at` set (set by `turnstile approve` after the lead's word). A `reply` entry never unlocks Slack.
- PreToolUse Bash: block `gh pr merge`, `gh pr ready`, `gh pr edit --add-reviewer`, `gh pr create --reviewer`, GraphQL
  `requestReviews*`, `requested_reviewers` writes for humans (Copilot bot allowed), `git push --force*`, `git rebase` on
  epic/story branches, `--no-gpg-sign`, Prometey `ensure` with an empty `service_github_tag`. One exception (2026-10-14): a
  `gh api` POST to the literal `repos/<org>/<repo>/pulls/<n>/requested_reviewers` route with literal `-f 'reviewers[]=<login>'`
  fields passes for a REWORK PR of the epic when every classified thread has its reply (as for the pass), the logins are exactly
  the reviewers who commented on the threads in this round (none for a push-only rework → refused), and Copilot reviewed the
  GitHub head with 0 open threads (repos without Copilot: the gate check is green on it); team reviewers, JSON bodies and computed
  logins or routes are refused.
- PreToolUse Bash, PR conversation (2026-10-14), for every caller: issue comments (`gh pr|issue comment`, `issues/<n>/comments`
  writes and edits — the repo gate's `<!-- pdf-review:… -->` / `<!-- crit-review:… -->` marker comments excepted), review
  submissions (`gh pr review`, `pulls/<n>/reviews…` writes), new or edited review comments (`pulls/<n>/comments` incl.
  `in_reply_to`, `pulls/comments/<id>`), GraphQL review/comment mutations, and resolving a thread whose opener is not a bot
  (the guard asks GitHub) are refused. `POST repos/<org>/<repo>/pulls/<n>/comments/<id>/replies` passes only for a thread
  classified in `state.json` on a REWORK PR — `self_resolved` at once, `needs_lead` with an approved `reply` entry for that
  thread — and only while GitHub shows no reviewer comment newer than the classification; the route is named literally.
- Commit message: block `Co-Authored-By`. PR body (`gh pr create/edit`): block the "Generated with" footer.
- PostToolUse Edit/Write on `state.json`: warn "state changes only through transition" and run `turnstile reconcile`.

## 7. Agents

Each agent is a file with model, effort, allowed tools and the role's rules baked in; briefs carry only task specifics.

| Agent | Model / effort | Does | Cannot |
|---|---|---|---|
| implementer | sonnet / default | ticket per brief: branch from epic/story branch, code + tests, tsc/lint/jest, draft PR per template, signed commits | Slack, Jira, resolving threads, ready, other repos, subagents |
| reviewer | opus / **xhigh** | PR deep review (scope, control arm, tests, invariants, design), then runs the repo gate skill; one-line fixes itself; recursive to clean | merge, replies to humans, Slack |
| story-reviewer | fable / default | whole-story integration review, recursive to clean; findings routed to ticket PRs | same as reviewer |
| stack-step | opus / default | ripple fixes up the stack (merge only, signed), re-run gates above, report heads | rebase/force-push, ready, Slack |
| comments-handler | opus / default | human + Copilot threads: verify → fix or justify → classify human threads (`turnstile threads`) → reply at once to `self_resolved` ones, draft `needs_lead` ones for the lead → Copilot loop → re-request exactly the thread authors on GitHub once every thread has its reply and the head is clean; resolves Copilot threads only | resolving human threads, issue comments, reviews, a `needs_lead` reply without the lead's entry, any other reviewer request (push-only rework, non-authors, `--add-reviewer`), Slack |
| investigator | opus / default | read-only investigations with a recommendation | any push or comment |
| tester | opus / default | see §7.1 | code, push, Slack |
| deployer | sonnet / default | variant/desk delivery via `prometey-variant` and desk workflows with explicit tags; health check after deploy | `ensure` without tag (hook), prod |

Common rules in every agent's system prompt: short polls (≤2 min), never silent >5 min, state in a file for cheap
resume after limits/watchdog, report in `reports/` per template, ≤8 lines back to the orchestrator, no subagents.

### 7.1 Tester

- Input: story id, its test cases from the test plan, Figma frames from `plan.md`, environment slot and the product's
  environment recipe (`references/env/<product>.md`: domain, test users, cookies for variant routing, desk cookie).
- Tools: isolated headless Playwright with its own profile (never the user's Chrome, never the shared chrome-devtools
  MCP); Figma MCP (`get_screenshot`, `get_design_context`, `get_variable_defs`) for the reference.
- Design parity per screen/state: environment screenshot next to the Figma frame in `evidence/<story>/<case>/`, plus a
  numeric DOM check (spacing, sizes, fonts, colours against Figma variables) with the tolerance from the plan (default
  1 px, exact colour); copy compared verbatim against Figma/locale.
- Output: `reports/ENV-<story>.md`: case → pass / fail / not_testable_here (with reason) → evidence. Every fail becomes a
  bug in `state.json` (story, screen, Figma node). Re-runs cover failed cases only; the final run is full.

## 8. Packaging

Plugin `turnstile`:

```
.claude-plugin/plugin.json
skills/turnstile/SKILL.md            # short: states, commands, when what; links to references
skills/turnstile/references/          # DoR/DoD tables, templates (plan, brief, PR body, Slack messages, reports, evidence), env recipes
scripts/turnstile (subcommands: pass, reconcile, render-board, status)
agents/{implementer,reviewer,story-reviewer,stack-step,comments-handler,investigator,tester,deployer}.md
hooks/hooks.json + hooks/*.sh
templates/state.json  templates/CLAUDE.md.workspace  templates/board.html
docs/superpowers/specs/                   # this spec and future ones
```

- **Canonical repo:** Davyd's personal GitHub repository (outside the pdffiller organisation). Versioned by tags.
- **Team copy:** vendored into `pdffiller/pdffiller-knowledge` (path to agree, e.g. `plugins/turnstile/`) by tag,
  the way skill sources live in the playground today; the team installs from there.
- Personal items (greeting, channels, reviewer logins, dev recipe) are removed from the plugin: channels and roles live
  in `state.json`, environment recipes in `references/env/`. `prometey-variant` and `front-release` stay separate skills
  the plugin references.

## 9. Migration of MYD-16538 (without stopping the current work)

1. Knowledge worktree in the workspace on `epic/myd-16538-l2f-funnel`; `MYD-16538-docs/` moves to
   `context/workitems/pdfd-429-l2f-editor-funnel/delivery/` as is (ledger, briefs, reports, board).
2. An agent generates `state.json` from the board + GitHub (`turnstile reconcile` fills heads, checks, threads); stories of the
   current epic = the dispatch-plan waves; `decisions.md` from the `CLAUDE.md` table.
3. The workspace `CLAUDE.md` shrinks to the pointer at `delivery/` and the plugin.
4. From then on every transition goes through `turnstile pass`; the first `turnstile reconcile` shows where the state and reality differ.
5. The remaining stories (jsfiller stack 13359→13384, MyDocs, module) finish under the new flow, including the tester
   gate before anything else is sent to humans.

## 10. Testing the plugin itself

- `turnstile pass`/`turnstile reconcile`/`turnstile render-board`: unit tests on fixture `state.json` files (`unittest`, no third-party packages) (every DoR/DoD branch, head mismatch,
  parallel stories, blocked_by resolution, idempotent re-runs); `turnstile reconcile` tested against recorded `gh` JSON.
- Hooks: shell tests that forbidden commands are blocked and allowed ones pass.
- Agents: one dry run each on a throwaway branch in a sandbox repo before the first real use.
- Migration: `turnstile reconcile` on the generated MYD-16538 state must report zero unexplained discrepancies before cut-over.

## 11. Decisions log (2026-10-13; dated lines added later)

- Enforcement model: state machine + command + role agents + hooks (option B), not prose-only, not event-driven bots.
- State lives in git (`pdffiller-knowledge`, epic branch, merged at epic end), not in the artifact db, not in Jira.
- Jira is updated through the Atlassian MCP within the transition step; no API token.
- AI review is recursive; after human review only the repo gate and Copilot are re-run.
- Story gates (integration review + env testing) run on the stack top **before** sending to humans.
- Human-review unit ≈ 400 lines of logic; planned at kick-off; ticket = PR into the story branch.
- Reviewer = opus at xhigh; story-reviewer = fable; others default effort.
- Parallel stories allowed by plan or by the lead's instruction; the stop rule is per story.
- Canonical plugin repo is personal; team gets a vendored copy.
- 2026-10-14 (lead): a reviewer thread the agent resolved itself (`self_resolved`: fixed in code or justified in code) gets
  the agent's reply immediately, without asking; only threads that need the lead's decision or involvement (`needs_lead`)
  wait for a lead-approved `reply` entry of their own. The classification is recorded from GitHub facts (`turnstile
  threads`); REWORK → ON_HUMAN_REVIEW needs a reply newer than each thread's last reviewer comment, gate + Copilot on the
  new head, and no Slack message or blanket approval. Issue comments, review submissions and resolving human threads stay
  refused for everyone.
- 2026-10-14 (lead, re-request): "if you replied to all comments on a PR and Copilot passed again, ping the reviewer to look
  again". Once every human thread has our latest reply and Copilot reviewed the current head with 0 open threads (repos without
  Copilot: the gate green on the current head), the agents re-request review on GitHub from the reviewers who commented on those
  threads in this round, without the lead's approval; the Bash guard allows exactly that `requested_reviewers` POST and nothing
  else; REWORK → ON_HUMAN_REVIEW needs `--rerequested <logins>` verified against GitHub for a thread-driven rework. A push-only
  rework pings nobody and records `reviewer_notified: false` (the lead decides). Slack stays lead-approved.

## 12. Open questions

1. Path and name of the vendored copy inside `pdffiller-knowledge` (`plugins/turnstile/` vs playground).
2. Tolerance defaults for Figma parity per product (1 px / exact colour proposed).
3. Whether `init` should create the Jira "story" issues when the decomposition lacks them, or only reference them in `plan.md`.
