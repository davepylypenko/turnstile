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
