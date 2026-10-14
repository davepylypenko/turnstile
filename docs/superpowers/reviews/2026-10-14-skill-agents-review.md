# Turnstile plan 2 (skill, agents, workflow commands): review (2026-10-14)

Scope: `0037a9d..c8ff77e` (tag `v0.2.0-skill`) against spec §4.1/§4.2/§5/§7/§7.1/§8, the plan with its `## Deviations`,
and the round 1–3 invariants of `2026-10-13-core-review.md`. Method: full read of the new CLI modules, agents, skill,
references, templates and board; probes of the real Bash guard (JSON payloads, throwaway workspace), the real `init`
against a real git clone, and `rules.check_story` on crafted state; the Claude Code 2.1.296 agent-frontmatter parser
read from the binary. Suite: 208 → 209 tests, green. `claude plugin validate .` passes (it does not check agent
frontmatter; a probe agent with `foo: bar` and `effort: bogus` also passes, so the validator proves nothing here).

## Fixes applied in this review (signed, pushed to `main`)

| Commit | Fix |
|---|---|
| `487c98a` | `init`: an existing worktree path must be on `epic/<key>`, else refuse. Probe before the fix: `--knowledge pdffiller-knowledge` with the clone inside the workspace made `wt == knowledge`, so `init` wrote `delivery/` into the main clone and committed `turnstile: init` **on `main`** while printing `(epic/myd-1)`. Also refuses a `.turnstile` that points at another delivery (the deviation's "init overwrites .turnstile"). Test `test_init_refuses_knowledge_clone_inside_workspace_and_foreign_marker`. |
| `3fd2d58` | Tester credentials: the brief template had `Credentials: {{credentials}}`, and `turnstile brief` commits `briefs/` to the knowledge repo, so the dev password would land in git (the env recipe says "never in git"). Now they go in the launch prompt only (`briefs/tester.md`, `agents/tester.md`, SKILL.md `## dispatch`). SKILL.md also listed the deployer as opus; it is sonnet. |

## Findings

### Blockers

1. **The tester cannot write its evidence (spec §7.1, `references/evidence.md`).** `guard_bash.py:138` (`delivery-write`)
   refuses every command that names the delivery dir and is not read-only. Probed: `mkdir -p …/delivery/evidence/S1/TP-1`,
   `node shot.mjs --out …/evidence/…/env.png` and `npx playwright screenshot … …/evidence/…/env.png` all exit 2. The Write tool
   cannot write PNGs. `figma.png` cannot be saved at all: `get_screenshot` returns the image to the model, not a file. So
   the story gate's evidence layout is impossible as specified.
   **Fix:** allow writes when every delivery path the command names is under `evidence/` (and nothing names `state.json`,
   `ledger.md`, `board.html` or `.state.lock`), with hook tests. Alternative: the tester writes into its scratchpad and a
   new `turnstile evidence import <S> <dir>` copies and commits. Drop `figma.png` or take it from Figma's REST image
   export. The tester's Figma tools cover the reference side only.

### Major

2. **The story stop rule can be self-approved with `--reason "… lead …"`** (`rules.py:303`, `rules.py:309`). Probe: a
   PLANNED story with an approved plan and **no** `start_story` entry gives `check_story(..., reason="per lead") == []`.
   `references/lifecycle.md` says the reason overrides "the dependency only", but the code skips the `start_story`
   approval too. Any agent can type that reason. This predates plan 2 (round 1 #11 resolution), but it is exactly the
   threat model of item (5).
   **Fix:** always require an approved `start_story` entry. Let `--reason` only waive `after`. Open `start_story` entries
   for every PLANNED story once the plan is approved, not only for `startable` ones (`pass_cmd._ensure_start_story_entries`).
3. **The story gate stalls after integration-review fixes** (SKILL.md `## story-gate` step 2→3, `rules.py:226`, `rules.py:258`).
   Fixes move the stack top, so `integration_review.head` (step 3's `--head`) no longer equals `evidence.deploy.head`, and
   ENV_TESTING is refused. INTEGRATION_REVIEW cannot re-enter itself to record a new deploy, and the skill does not say
   what to do.
   **Fix:** either let INTEGRATION_REVIEW re-enter with `--build/--head` (re-records the deploy), or document the path:
   redeploy → `pass story S IN_PROGRESS --reason "integration fixes"` → `INTEGRATION_REVIEW --build --head`.
4. **Env runs are not bound to a build or head; DONE can pass on a stale review** (`pass_cmd._apply_story_evidence`,
   `rules.py:258`). Fixes made during ENV_TESTING change the PR heads. The PRs re-pass READY, but `env_runs[]` records
   neither `build` nor `head`, and DONE only compares `integration_review.head` with `deploy.head`, both still the
   pre-fix values. Result: the story is DONE with an integration review and a "full clean run" that may describe an
   older stack than the one sent to humans.
   **Fix:** require `--build` and `--head` on every recorded run. At DONE, require the last full run's head to equal the
   current stack top (the newest head among the story's PRs). A head change during ENV_TESTING should force
   ENV_TESTING → INTEGRATION_REVIEW, or at least a new review round recorded for that head.
5. **"Every fail became a bug" needs duplicate bugs for a persisting fail** (`rules.py:281`). Only bugs created after the
   previous run count. If a fix did not work and the tester re-fails the same case, the orchestrator must file a
   duplicate bug instead of reopening the existing one (`bug set bNN --state todo`).
   **Fix:** count the story's bugs that are new since the previous run **or** not `done` at record time.
6. **Board bug overrides never expire** (`templates/board.html:89`). Once `bugs/<id>` exists in the db it always beats
   `state.json`, even after `bug set` folded it in and the state later moved on (for example, reopened by the tester).
   **Fix:** write `{status, base: b.state}` and apply the override only while `b.state === base`. Alternatively, the
   SKILL.md fold step deletes the db doc after `bug set`.
7. **Tester tool allowlist is tied to one Figma connector name** (`agents/tester.md:5`: `mcp__claude_ai_Figma__*`).
   A team member with the Figma plugin MCP (`mcp__plugin_figma_figma__*`) or another connector name gets a tester with
   no Figma tools, and the parity gate silently degrades. This is a personal item (spec §8) and must be resolved before
   vendoring in plan 3.
   **Fix:** list both spellings, or drop `tools` for MCP and use `disallowedTools` for the dangerous ones (Slack, Agent,
   Atlassian transitions).

### Minor

8. `rules.plan_approval_missing` (`rules.py:99`) does not compare the approved entry's `digest` with `epic.plan.digest`.
   This holds today because `plan-submitted` voids the old entries, but it is a one-line defence in depth.
9. `plan_cmd.merge_stories` takes `branch`, `tickets` and `repos` from the new plan for stories already past PLANNED. A
   re-plan can retarget an IN_PROGRESS story's branch without a check. Either refuse a `branch` change after PLANNED, or
   print a WARN.
10. Board tile "Awaiting humans" (`board.html:55`) counts voided and consumed-but-unapproved entries. Every re-plan adds a
    voided `plan` entry, so the tile overcounts. Filter on `!voided_at && !consumed_at`.
11. `templates/CLAUDE.md.workspace:14` hard-codes "Chat with the lead in Ukrainian". Spec §8 says personal items stay out
    of the plugin; take the language from `init` (`--chat-language`) or from `state.json`.
12. `init` cuts the epic branch from the local `main` (`init_cmd.py:84`), which may be stale; use `origin/<base>` after a
    fetch. A failure after `state.json` is written (for example, the commit) leaves a half-initialised delivery that the
    next run refuses as "already initialised"; print the recovery step.
13. `turnstile brief` refuses an existing name without `--force`, so a second review round (`REVIEW-<n>`) overwrites the
    first round's brief and report. SKILL.md should name rounds (`REVIEW-<n>-r2`) or document `--force`.
14. Live checks still owed, from core round 3 R3-1 and spec §10:
    - `ask` under `bypassPermissions`, a background subagent's send, and `!` lines skipping hooks;
    - one dry run per agent in a sandbox repo;
    - confirm that the repo gate skills (`pdf-review`, `crit-review`) run without the `Agent` tool, which no agent has.

### Nits

15. `turnstile bug` with no subcommand: `parser.parse_args(["bug", "--help"])` raises `SystemExit(0)` before `return 2`
    (`main.py:71`), so it exits 0. This matches the deviation note, but the code reads as if it meant 2.
16. `approve`/`status` print `plan None` for plan entries (known, deviation 7).
17. Board: a db snapshot re-renders the bugs table and destroys a dropdown the viewer has open.

## Coverage map (spec → code → test)

| Spec item | Where | Test |
|---|---|---|
| §4.1 kick-off, plan approval gate, edited plan voids | `plan_cmd.py`, `rules.plan_approval_missing` | `test_plan_cmd` (`test_edited_plan_voids_approval`) |
| §4.2 stacked into story branch | `rules._stacked_into_story_branch` | `test_story_branch` |
| §4.2 fails → bugs, full final run | `rules._fails_became_bugs`, DONE `full` | `test_env_runs` (finding 4 untested) |
| §3 REWORK "replies posted" | `pass_cmd._facts_mismatches` | `test_replies_trailer` (incl. fail-closed `rework_since.at`) |
| R3-10 trailer/footer on GitHub | `github.parse` `trailered`/`body_footer` | `test_replies_trailer` |
| §5 init / dispatch / story-gate / plan / status | `init_cmd`, `brief_cmd`, SKILL.md | `test_init`, `test_brief`, `test_skill_files` |
| §7 eight agents, models, effort, no Agent/Slack/Jira tools | `agents/*.md` | `test_agents` |
| §7 common rules (polls, resume file, ≤ 8 lines, signed, no trailer, no subagents) | each agent's `## Common rules` + brief Don'ts | `test_agents` (text) |
| §7.1 tester evidence | `references/evidence.md` | none; blocked by finding 1 |
| Board bug overlay, XSS | `board.html` (`esc` on every field, status allow-listed, `prUrl` prefixed `https://github.com/`, `<` escaped in the embedded JSON) | `test_board_bugs` |

Agent frontmatter: Claude Code 2.1.296's agent parser accepts `name, description, tools, disallowedTools, model, effort,
permissionMode, mcpServers, hooks, maxTurns, skills, memory, background, isolation, …`, with `effort ∈ {low, medium, high,
xhigh, max}` or an integer. So `effort: xhigh` on the reviewer is valid and `fable` is an accepted model alias. Every
allowlist lacks `Agent`, Slack and Atlassian tools. The role rules do not contradict the hooks, except for the tester's
evidence writes (finding 1). The board overlay is XSS-safe as far as I can tell. It degrades cleanly without `db`
(controls disabled, nothing thrown) and matches the 0.2.74 `db`/`user` contracts (`doc().set`,
`collection().onSnapshot(next, error)`, `user.can('data.write')` → `null` treated as writable).

The env recipe matches the global rules: `www.pdffillers.com`; `+testerN` users; the `pdffiller-autotests` UA for the
login only; `jsfillerEnv=deskNN`; `Forward-Variant-pdffiller` + `developer_access` cookies on `.pdffillers.com`, never as
a header; an isolated headless browser.

## Verdict

**Ready for plan 3: not yet. Two conditions.**

1. Finding 1 (tester evidence) must be fixed, or the migration's first story gate cannot produce what ENV_TESTING
   requires.
2. Finding 2 (self-approvable story start) must be fixed before the stop rule is relied on.

Findings 3–5 should land in the same round. Without them the story gate either stalls or reports DONE on a stale stack.
Everything else can travel with plan 3. Item 7 belongs to the vendoring part of plan 3 anyway.

## Resolution (2026-10-14, after the review)

Lead decisions applied: (1) evidence writes allowed under `evidence/`, `reports/`, `briefs/` for any command and the Write
tool, the rest of the delivery dir stays protected, `figma.png` is saved through Write from the Figma MCP result; (2) no
`--reason` bypass for PLANNED→IN_PROGRESS, `parallel_with` is the only pre-authorisation of a parallel start; (3)
INTEGRATION_REVIEW re-entry records a redeploy, runs record `{build, head}`, DONE needs `env_test.head == deploy.head ==`
stack top, a persisting fail reopens its bug (key story + case); (4) a db bug status older than the state.json bug loses;
(5) Figma tools resolved per environment through `references/tools/figma.md`. Suite: 209 → **231 tests, `OK`** on Python 3.9.6.

| # | Finding | Commit | Note |
|---|---|---|---|
| 1 | Tester cannot write evidence | `0acec8d` | `guard_bash.py` `_writable_segment` (literal paths, `..` normalised, symlinks resolved, no `git`/`ln`, no `cd`); `guard_state_edit.py` resolves the path and allows the three folders + `plan.md`/`decisions.md`; tests for allowed vs blocked incl. `../` and symlink tricks; `references/evidence.md` and `agents/tester.md` updated |
| 2 | Story start self-approvable with `--reason` | `7b33047` | `is_lead_override` removed; `after` must be DONE; an active story blocks unless `parallel_with` (either direction); `startable()` applies the same checks before opening `start_story` entries |
| 3 | Story gate stalls after integration-review fixes | `a2fe332` | `INTEGRATION_REVIEW` ∈ `STORY_FROM["INTEGRATION_REVIEW"]`; re-entry requires `--build --head` and re-records `evidence.deploy = {build, head, at}`; ENV_TESTING entry still needs `integration_review.head == deploy.head` |
| 4 | Env runs not bound to a build/head | `a2fe332` | `rules.stack_tops()` (open PRs no other PR of the story is based on; one per repo); `evidence.deploy.head` must be a current top at INTEGRATION_REVIEW / ENV_TESTING / DONE; a run records `{build, head, failed_cases}` and is refused when `head != deploy.head`; DONE requires `env_test.head == deploy.head`. Builds are recorded, not compared (a same-head redeploy needs no new review round) |
| 5 | Duplicate bugs for a persisting fail | `a2fe332` | `bug add --case`; `--failed-cases` on the run record (count must match); an open bug for story + case satisfies the fail; `_reopen_bugs_for_run` appends `runs` and sets a done bug back to `todo` with a ledger line; `bug add` refuses a duplicate case |
| 6 | Board overrides never expire | `6ec8538` | override renders only while `updatedAt` is newer than the bug's `updated_at`/`created_at` (stamped by `bug add`/`set` and by a reopen) |
| 7 | Tester tied to one Figma connector | `b7cc9c2` | `references/tools/figma.md` (suffix mapping, resolution steps, BLOCKED message); tester inherits tools with `disallowedTools`; `skill_dir` builtin in briefs |
| 8 | Plan approval not bound to the digest | `63df4e9` | `plan_approval_missing` compares the entry's `digest` |
| 9 | Re-plan retargets a started story | `63df4e9` | `merge_stories` refuses a `branch` change past PLANNED, returns WARN lines for tickets/repos (printed and in the ledger) |
| 10 | "Awaiting humans" overcounts | `6ec8538` | filter `!approved_at && !voided_at && !consumed_at` |
| 11 | Hard-coded chat language | `63df4e9` | `init --chat-language` (default English) → `epic.chat_language` and the workspace `CLAUDE.md` |
| 12 | Epic branch from a stale base; half-initialised delivery | `63df4e9` | `git fetch origin <base>` then `origin/<base>` (local fallback with WARN); a failure after `state.json` removes what init created and says to re-run |
| 13 | Second review round overwrites the first | `63df4e9` (SKILL.md), `a2fe332` (story-gate) | round suffix `-r2`; `--force` only for a never-dispatched brief |
| 14 | Live checks | — | **still owed** before plan 3: `ask` under `bypassPermissions`, a background subagent's send, `!` lines skipping hooks, one dry run per agent, repo gate skills without the `Agent` tool |
| 15 | `turnstile bug` exits 0 without a subcommand | `63df4e9` | help to stderr, exit 2 |
| 16 | `plan None` in approve/status | `63df4e9` | the entry's `payload` is printed |
| 17 | Snapshot destroys an open dropdown | `6ec8538` | re-render deferred until the focused `select.bug` blurs |

Known limitation recorded with finding 4: a multi-repo story has one stack top per repo and a single `deploy.head`; the
check accepts any top, so a head change in the other repo after the deploy is not caught by the CLI (the story-reviewer's
report names every head).

## Round 2 (2026-10-14)

Scope: `0acec8d..a0d6c5a` against the `## Resolution` table, spec §4–§7 and the core-review invariants. Method: the real hooks
run on JSON payloads in a throwaway workspace (with symlinks `evidence/link → ../state.json` and `evidence/up → ..`); `rules`
and `pass` on crafted state. Suite: 231 → **237 tests, `OK`** on Python 3.9.6. Every fix below is signed, has no trailer and is
pushed to `main`.

### Resolutions verified

| # | Verdict | Evidence |
|---|---|---|
| 1 | Closed, with three gaps (R2-1, R2-3, R2-4) | Refused: `delivery/evidence/../state.json`, `…/../ledger.md`, `…/S1/../../ledger.md` (absolute), `evidence/link`, `evidence/up/ledger.md`, `evidence/up/`, `cd delivery/evidence && cp x ../ledger.md`, `git -C delivery/evidence add/commit`, `git add delivery/evidence/a.png`, `ln -s`, `cp -s`. Allowed: `mkdir -p …/evidence/S1/TP-1`, `node shot.mjs --out …/evidence/…/env.png`. The Write tool refuses the same `..`/symlink paths. |
| 2 | Closed | PLANNED → IN_PROGRESS with `--reason "per lead"` and `--approved` set to a plan entry, a `story_done` entry, another story's `start_story` entry, or an unapproved entry is refused every time. No flag and no environment variable skips `check_approved_entry`. |
| 3 | Closed | INTEGRATION_REVIEW re-entry needs `--build --head` and re-records the deploy. |
| 4 | Closed for one repo; multi-repo closed now (R2-2) | A run on a head that is not the deploy head is refused. DONE needs `env_test.head == deploy.head`. |
| 5 | Closed | `bug add --case` refuses a duplicate story + case. A re-fail reopens a done bug and appends to `runs`. |
| 6 | Closed (nit R2-9) | The override applies only while `updatedAt` is newer than the bug's `updated_at`/`created_at`. |
| 7 | Closed for Figma (R2-6 for the rest) | `references/tools/figma.md`; the tester inherits tools and has `disallowedTools`. |
| 8–13, 15–17 | Closed | Read in code and tests. One regression in 12, fixed below as R2-5. |

### Fixes applied in this round

| Commit | Fix |
|---|---|
| `e3c122e` | **R2-2.** Every deploy record (`INTEGRATION_REVIEW --build --head`) snapshots `evidence.deploy.heads = {pr: head}` for every open PR of the story, across all repos. `rules._deploy_is_stack_top` (`rules.py:281`) refuses INTEGRATION_REVIEW, ENV_TESTING and DONE when any open PR's head differs from the snapshot or a PR was added since. `_story_gates_passed` (`rules.py:129`) and the Slack guard `_slack.story_ready` (`hooks/_slack.py:17`) apply the same check to a **DONE** story, so a push after DONE is neither sent nor passed to ON_HUMAN_REVIEW. Tests: `DeployHeadsSnapshot` (2), `test_send_refused_when_a_head_changed_after_the_story_deploy`. Deploys recorded before this change have no `heads` and keep the stack-top check only. |
| `c23cf0e` | **R2-1, R2-3, R2-4.** `guard_bash.check`: a Bash cwd inside the delivery dir counts as a delivery write. The cwd persists across calls, so `cd delivery/evidence` followed by a separate `cp /tmp/x ../ledger.md` call, or `echo > board.html` from `delivery/`, passed before. Inline code (`node -e`, `python3 -c`, `perl -e` …), shells (`sh x.sh`, `bash …`) and `tar -P` get no evidence allowance. Before the fix, `node -e "…join('delivery','ledger.md')…" delivery/evidence/S1/a` passed because it also named an evidence path. `guard_state_edit` resolves the delivery dir from the file path when the cwd has no `.turnstile` above it; before, a `/` cwd let Write reach `board.html` and `.state.lock`. Tests: 2. |
| `16326d2` | Lifecycle reference documents `deploy.heads`. |
| `59f6c14` | **R2-5 (regression of 12, migration blocker).** The rollback `rmtree`-ed the delivery dir even when it existed before `init`. Plan 3 moves `MYD-16538-docs/` there first, so a failed commit would have deleted the migrated ledger, briefs and reports. `init` also overwrote an existing `plan.md`/`decisions.md`. Now only what `init` created is removed (including `state.json`, so a re-run works), and existing `plan.md`/`decisions.md` are kept. Test `test_failed_init_keeps_a_migrated_delivery_dir`. |

### Findings still open

**Major**

- **R2-6. `figma.png` "saved with the Write tool" is not possible** (`references/evidence.md:6,16`, `agents/tester.md:15`).
  - `get_screenshot` returns image content to the model. Write writes text, and the model cannot emit PNG bytes.
  - The tester will either stop (`figma.md` says never mark parity `pass` without `figma.png`) or write a non-PNG file.
  - **Fix (lead decision):**
    - (a) The Figma REST image export: `GET /v1/images/<file>?ids=<node>&format=png`, then `curl -o …/evidence/<S>/<case>/figma.png`. The hook allows this. It needs a Figma token in the tester's environment, never in the brief.
    - (b) Or, if the connector's `download_assets` writes a file, use that.
    - (c) Or drop `figma.png` and record `figma: <file:node>` plus the tester's verdict in `diff.md`.
  - Until one of these is chosen, the first ENV_TESTING of plan 3 stalls.
- **R2-7. Story passes never check GitHub** (`pass_cmd.run`, story branch).
  - A push with no `pass pr` leaves `state.json` stale. `DONE` then passes on the old heads, and the Slack guard (state only) lets the send through.
  - `pass … ON_HUMAN_REVIEW` refuses afterwards, because it verifies the head, but the message is already out. The lead's `ask` prompt is the only stop.
  - **Fix (~15 lines plus fixture updates):** a deploy record, ENV_TESTING entry, a run record and DONE call `io.github_facts` for every open PR of the story and refuse on any head mismatch. `--offline` refuses DONE. Interim rule: run `turnstile reconcile` immediately before `pass story … DONE` and before every send (SKILL.md `## story-gate` step 5).

**Minor**

- **R2-8.** `git checkout|restore|reset` that names no delivery path still passes (`guard_bash.py:204`). Example: `git checkout HEAD~3 -- .` at the knowledge worktree root rolls `state.json` and `ledger.md` back. **Fix:** refuse `GIT_RESTORE` whenever the cwd, or `-C`, is the knowledge worktree that contains the delivery dir (`git rev-parse --show-toplevel` of the delivery dir).
- **R2-9.** Bug timestamps have minute precision (`pass_cmd._now`, `board.html:91`). A board change and a later reopen or `bug set` within the same minute resolve in the board's favour. **Fix:** seconds in `bug.updated_at`, or compare with `>=` against a seconds-precise stamp.
- **R2-10.** `--full` is self-declared. A full run's `cases.pass + cases.fail (+ not_testable_here)` is not compared with `len(stories.<S>.test_cases)`, and `not_testable_here` has no flag (spec §7.1). **Fix:** `--cases-not-testable`, and refuse `--full` unless the sum equals the story's case count.
- **R2-11.** Spec §4.1, "no agent starts" before plan approval: `turnstile brief` does not check `plan_approval_missing`. **Fix:** refuse briefs for every agent except `investigator` while the plan is unapproved.
- **R2-12.** The tester's `disallowedTools` names only `mcp__plugin_slack_slack__*` and `mcp__claude_ai_Atlassian__*`. Under another connector prefix, Jira writes are blocked only in prose. Slack sends still hit `guard_slack`, whose matcher is prefix-agnostic. The tester also inherits Bash, so "no pushes" is prose. **Fix:** a PreToolUse matcher `mcp__.*(transitionJiraIssue|editJiraIssue|createJiraIssue|addCommentToJiraIssue)` that refuses unless the caller is the orchestrator. If agent identity is unavailable in the payload, accept the prose rule and record it.
- **R2-13 (nit).** INTEGRATION_REVIEW re-entry with `--report --build --head` records a review round instead of the deploy: `_apply_story_evidence` checks `--report` first (`pass_cmd.py:200`). Refuse `--report` on that re-entry.

### Spec §4–§7: still unenforced

R2-7 (GitHub facts at story gates), R2-10 (full run equals the test plan; `not_testable_here`), R2-11 (§4.1 "no agent starts"),
§7.1 "copy verbatim" and "0 open discrepancies" (self-reported through `--figma-parity`; accepted), and the §7 tester
"cannot push" (prose, R2-12). §6 is covered except R2-8.

### Verdict

**Ready for plan 3 (migration): yes, with conditions.** R2-5 was the only migration blocker and is fixed. R2-6 does not block
the cut-over, but it blocks the first ENV_TESTING, so the lead must pick (a), (b) or (c) before the first story gate.

What the lead must do live, before the cut-over:

1. With the plugin installed, in a session in **`bypassPermissions`** mode, trigger a guarded Slack send that the state
   allows. Confirm that the `ask` prompt appears. **If it does not appear, the verdict flips to no.**
2. From a **background subagent**, trigger the same allowed send. Confirm that it is denied, not sent.
3. Type `! TURNSTILE_LEAD=1 turnstile approve <ah-id>` in the prompt. Confirm that it runs, which shows that `!` lines skip
   PreToolUse. If the hook blocks it, approve from a separate terminal and update the README.
4. Do one dry run per agent (eight) on a throwaway branch in a sandbox repo. For the reviewer, confirm that `pdf-review` and
   `crit-review` run without the `Agent` tool.
5. Do one tester dry run against the env recipe. It proves the Figma tool resolution in the lead's environment and, depending
   on the R2-6 choice, writes a real `figma.png`.
6. Migration `state.json`:
   - `gate_check: null` for skill-gated repos;
   - `ci_ignore: ["pdf-review", "gate / gate"]` for jsfiller and docs-platform;
   - each PR's real `base`;
   - `stories.<S>.branch`;
   - for each migrated story past IN_PROGRESS, a deploy re-recorded through `INTEGRATION_REVIEW --build --head`, so that
     `deploy.heads` exists.
7. Until R2-7 lands, run `turnstile reconcile` before every `pass story … DONE` and before every send.

## Round 2 resolution (2026-10-14)

Lead decisions applied: (1) the Figma reference is a file fetched from a URL, never a Write-tool artefact; (2) story gates and
the Slack guard ask GitHub, state.json is not trusted for heads; (3) the minors land as hook rules where the hook can know the
caller, as CLI rules otherwise. Suite: 237 → **257 tests, `OK`** on Python 3.9.6. Every commit signed, no trailer, pushed to
`main`; tag `v0.2.1-skill`.

| # | Finding | Commit | Resolution |
|---|---|---|---|
| R2-6 | `figma.png` "saved with the Write tool" impossible | `b8983a3` | The connector's `download_assets` does **not** take an output path: it returns an `export` URL (and `get_screenshot` returns a short-lived URL with curl instructions; both read from the tool schemas). So `references/tools/figma.md` § "The reference image" fixes the order: `__download_assets` (png, scale 2) → `__get_screenshot` → the REST export `GET /v1/images/<file>?ids=<node>&format=png&scale=2` with `X-Figma-Token: $FIGMA_TOKEN` when the variable is in the tester's environment (never in a brief, report or file) — each fetched with `curl -sSf -o /abs/delivery/evidence/<S>/<case>/figma.png "<url>"`; a connector variant that takes a path gets the same evidence path. None works → the affected rows are `not_testable_here: no figma reference`, the run is recorded with `--figma-parity not_testable_here` (new CLI choice; DONE still needs `pass`), the report header names the failed paths. `agents/tester.md` (step 0b), `briefs/tester.md`, `evidence.md` updated. The Bash guard already admits `curl -o` into `evidence/`; test `test_curl_o_writes_the_figma_reference_into_evidence_only` proves it and that `state.json`, `ledger.md`, the root, `..` and `$VAR` paths stay refused. |
| R2-7 | Story passes never check GitHub | `b0a50ef`, `42f8a33` | `IO.github_head` (injectable; `github.fetch(...).head`). `pass story … INTEGRATION_REVIEW` (a deploy record), `ENV_TESTING` (entry and run record) and `DONE` fetch the head of every PR in `evidence.deploy.heads` and refuse on any difference, naming the PR, both heads and the recovery (`pass pr … AI_REVIEW --head`, redeploy, re-record). On success `deploy.head_verified: {verified: true, at}`; `--offline` records `{verified: false}` with a WARN and is refused outright at DONE; a `gh` failure refuses with the `--offline` hint. `rules._deploy_heads_verified`: DONE needs `deploy.heads` (a pre-round-2 deploy must be re-recorded — migration step 6) and `head_verified: true`. The Slack guard's `story_ready` asks GitHub for the same snapshot (`live=True`; the PostToolUse record passes `live=False` so a transient `gh` failure never leaves a sent message unrecorded); `gh` absent fails closed. Tests: `test_story_github.py` (5), `test_send_asks_github_for_the_deployed_heads` (canned `gh` on PATH), rules test. |
| R2-8 | Tree-wide git resets name no delivery path | `fa62124` | `guard_bash._tree_wide_reset`: inside the git worktree that holds the delivery dir (by cwd or `-C`; the delivery dir is also resolved from the `-C` dir), `git checkout|switch|restore|stash|reset|clean` with no pathspec, with a ref (`checkout develop`, `-b`, `reset --hard HEAD~1`, `stash pop`), or with a pathspec that covers the delivery dir (`.`, `..`, `:/`, an ancestor, a glob) is refused (`knowledge-worktree-reset`); a pathspec elsewhere in the worktree, `stash list|show`, `clean -n` pass; the same commands in another repo are untouched. 19 blocked / 9 allowed probes in the test. |
| R2-9 | Minute-precision bug stamps | `fa62124` | `bug.created_at` / `updated_at` (add, set, reopen) carry seconds (`_now_s`); the board's `>` compare is unchanged. |
| R2-10 | `--full` self-declared; no `not_testable_here` | `fa62124` | `--cases-not-testable N` (recorded as `cases.not_testable_here`, default 0). `rules._full_run_covers_every_case`: a `--full` run's `pass + fail + not_testable_here` must equal `len(stories.<S>.test_cases)` (empty list → refused, the plan must list the cases); checked when the run is recorded and again at DONE. |
| R2-11 | Agents start before plan approval | `fa62124` | `turnstile brief` refuses every agent but `investigator` while `rules.plan_approval_missing` holds (no plan, edited plan, unapproved entry). |
| R2-12 | Tester limits are prose under another prefix | `fa62124` | **Hook-enforced where the hook can know the caller.** `agents/tester.md` carries frontmatter `hooks` that run `guard_bash.py` and the new `guard_role.py` with `TURNSTILE_ROLE=tester`; `_common.agent_role` also reads a payload `agent_type: turnstile:<role>` as the fallback. `ROLE_RULES["tester"]`: `git push`, `git commit`, `gh pr|issue comment|review|create|edit|close|reopen|merge|ready`, `gh api` writes → refused. `guard_role.py` (plugin-level matcher `mcp__.*(transitionJiraIssue|editJiraIssue|createJiraIssue|addCommentToJiraIssue)`, prefix-agnostic) refuses Jira writes for any role but the orchestrator. **Caveat, documented in the README:** the identity reaches the hook only through the agent's frontmatter hooks or a payload field; the live check (item 4 below) must confirm that agent-scoped hooks run for a plugin agent and that `${CLAUDE_PLUGIN_ROOT}` expands there. If not, the rule stays prose for the Bash side (`disallowedTools` still removes the known Slack/Jira tools) and the review says so. |
| R2-13 | `--report --build --head` on INTEGRATION_REVIEW records a review round | `fa62124` | `--report` on an INTEGRATION_REVIEW pass is refused with the ENV_TESTING form to use instead. |

Fixture updates that came with R2-7 and R2-10: a deploy written directly into state in tests now carries `heads` (and
`head_verified` in the pure-rules fixtures); stories in the fixtures list as many `test_cases` as the recorded full run counts.

### Spec §4–§7 after this round

R2-7 (GitHub facts at story gates), R2-10 (`--full` equals the plan) and R2-11 (§4.1 "no agent starts") are enforced. The §7
tester "cannot push" is hook-enforced subject to the live check of agent-scoped hooks. Still self-reported: §7.1 "copy
verbatim" and "0 open discrepancies" (through `--figma-parity`; accepted).

### Live checks still owed before the cut-over (unchanged list, one addition)

1–3 as in the verdict above (`ask` under `bypassPermissions`, a background subagent's send, `!` lines). 4. One dry run per
agent; for the **tester** additionally confirm that its frontmatter hooks fire (`git push` from the tester reports
`blocked by rule tester-push`) and that `${CLAUDE_PLUGIN_ROOT}` expands in an agent-scoped hook command — if either fails,
record R2-12 as prose-only. 5. The tester dry run must produce a real `figma.png` through one of the three paths in
`references/tools/figma.md`. 6–7 as above; 7 is now moot (R2-7 landed), `turnstile reconcile` before a send stays good practice.

## Round 3 (2026-10-14)

Scope: `b8983a3..1d8701a` (tag `v0.2.1-skill`) against `## Round 2 resolution` and the core invariants. Method: the real hooks run on
JSON payloads, in a layout that matches plan 3: `.turnstile` at the workspace root, the knowledge worktree a **linked git worktree**
(`.git` is a file) inside the workspace, and a sibling product repo. The Round 2 tests put `.turnstile` inside the worktree. Claude
Code 2.1.296 was read from the installed binary. Suite: 257 → **258 tests, `OK`** on Python 3.9.6. Fix `12beb53` is SSH-signed, has
no trailer and is pushed to `main`.

### Resolutions verified

| # | Verdict | Evidence |
|---|---|---|
| R2-6 | Closed | `curl -o …/evidence/<S>/<case>/figma.png` passes. `curl -o …/evidence/S1/TP-1/../../state.json` and `wget -O …/../ledger.md` are refused. `curl -o /tmp/x` passes: it is outside the delivery dir, so not a delivery write. `--figma-parity not_testable_here` is recorded, and DONE refuses it (`figma_parity == pass (has not_testable_here)`). |
| R2-7 | Closed, with one gap fixed (R3-3) | The canned `gh` reporting a moved head refuses the send and names the PR. Without `gh` the send fails closed. |
| R2-8 | **Was open; fixed (R3-1)** | |
| R2-9, R2-10, R2-13 | Closed | Read in code and tests. |
| R2-11 | Closed | `brief` refuses every agent but `investigator` before plan approval. The test now covers all seven (it listed four). |
| R2-12 | **The mechanism was dead; replaced (R3-2)** | |

### Fixes applied in this round (`12beb53`)

- **R3-1 (major, R2-8 bypasses).** Tree-wide resets of the knowledge worktree passed in these forms:
  - `cd ../kn && git checkout -- .` and `cd /abs/kn && git restore .`, from a sibling repo or from outside the workspace. A `cd` inside the same command was not tracked.
  - `(git checkout -- .)` and `(cd kn; git reset --hard)`.
  - `sh -c '…'`, `bash -c '…'`, `command git …`.
  - `git --work-tree=../kn …` and `GIT_WORK_TREE=../kn git …`.
  - `git read-tree -u --reset HEAD~1`, `git checkout-index -a -f`, `git revert HEAD`. These roll `state.json` back as well.

  Now `_git_call` unwraps parentheses, `command`/`exec`/`sh|bash|zsh -c` and env prefixes, and treats `--work-tree` and `GIT_WORK_TREE` like `-C`. The segment loop follows `cd`/`pushd`. `TREE_SUBS` adds `read-tree`, `checkout-index` and `revert`; for `read-tree` and `revert`, a non-path argument is treated as a ref. Test: `TreeResetRealLayout` (11 blocked, 4 allowed, in the plan-3 layout).
- **R3-2 (major, R2-12).** Claude Code 2.1.x **ignores `hooks`, `mcpServers` and `permissionMode` in plugin agent frontmatter.** The plugin agent loader skips the keys in `K5t=["permissionMode","hooks","mcpServers"]` and warns "Plugin agent file … sets hooks, which is ignored for plugin agents. Use .claude/agents/ for this level of control." So the tester's frontmatter hooks never ran, and `TURNSTILE_ROLE` was never set.
  - The fallback works without them. Since 2.1.x, the common hook input carries `agent_id` and `agent_type` for every tool call inside a subagent (absent on the main thread). A plugin agent's type is `<plugin>:<name>`, here `turnstile:tester`. The plugin-level `guard_bash` and `guard_role` already read it through `_common.agent_role`.
  - Probes with `{agent_id, agent_type: "turnstile:tester"}` are refused: `git push`, `git -C . push`, `command git push`, `sh -c 'git push'`, `git commit`, `gh pr comment|create`, and `gh api` POST/PATCH/graphql.
  - Removed: the dead `hooks:` block in `agents/tester.md`. Prose and README now name the payload mechanism. The test now asserts that no agent carries `hooks`, `mcpServers` or `permissionMode`.
  - `guard_role` now refuses Jira writes from **any** subagent (`agent_id` present). Before, a `general-purpose` subagent passed.
- **R3-3 (minor).** The Slack guard asked GitHub only when the DONE story's deploy had a `heads` snapshot. A DONE story without one (a migrated story, or a deploy recorded before Round 2) was sent unchecked. A live check without `heads` now refuses. The Slack tests answer through a canned `gh` outside the workspace.

### Residual (accepted, regex-guard limits)

These remain open:
- Computed words, e.g. `x=push; git $x`, `x=checkout; git $x -- .`.
- `git worktree remove --force`.
- `git apply -R` / `git am` in the knowledge worktree.
- `git merge` / `git pull` / `git cherry-pick`. These add history and do not restore an old state.

The CLI's commit-per-pass history makes any rollback visible in `git log`, and `turnstile reconcile` compares state with GitHub.

### Verdict for plan 3

**Ready for the migration: yes, with conditions.** Plan 3 must not start before the live checks below are done.

Live checks still owed:
1. `ask` under `bypassPermissions`.
2. A send from a background subagent is denied.
3. `!` lines skip PreToolUse.
4. One dry run per agent. For the tester, `git push` must report `tester-push`. This now proves that the payload carries `agent_type: turnstile:tester`, not that frontmatter hooks run.
5. A real `figma.png`.

Migration step 6 (re-record each migrated story's deploy through `INTEGRATION_REVIEW --build --head`) is now **required for sends**, not only for DONE (R3-3).
