# Kick-off analysis (once, before any code)

Output: `delivery/plan.md` from `references/plan.md`. Approval gate: `turnstile plan-submitted` → the lead's approve line.

1. Read, in this order, and list each in plan.md § 1: the decomposition (ticket map, decisions), the PRD, the design
   brief + Figma file (collect `file:node` per screen and state), the test plan (case ids, preconditions), every target
   repo's `CLAUDE.md` / `AGENTS.md` / testing guide, the precedent epic if the decomposition names one.
2. Stories: business slices testable and releasable on their own. If the decomposition is by repo or by wave, define
   the slices yourself and write the rationale. For each: tickets, repos, **story branch** (`stories.<S>.branch`, the
   branch the ticket PRs stack into; the epic branch for a single-story epic or a legacy story), `after` (must be DONE
   first), `parallel_with` (explicitly allowed), env slot (variant / desk), Figma frames, test cases.
3. Merge order per story and the stack; file overlaps between parallel stories and which merge order resolves them. Every repo a
   story names is in `epic.repos`: `turnstile repo add '{"name":…,"base":…,"slack":…}'` for each missing one (it clones a missing
   clone and adds the worktree); `plan-submitted` refuses a story whose repo is unknown.
4. Human-review units: ~400 lines of logic each (tests and markup excluded). A story goes to humans as its story PR or
   2–3 PRs split by subsystem (state + API / UI / tests). Estimate from the ticket scopes; refine after the PRs exist.
5. Inputs from humans (PM report, design copy, credentials) with the date each is needed and which story it blocks.
6. Fill the `turnstile-stories` JSON block (§ 7 of the template) — ids `S1…`, keys `title, tickets, repos, branch,
   after, parallel_with, test_cases, figma, env_slot, human_review_units`, optional `human_review: "per_pr"` (lead-set).
   `plan-submitted` validates it.
7. Show the lead, in one message: the story table, the unit table, the open inputs, the approve line and the one preferences question
   (SKILL.md `## preferences`, with the current `turnstile config list`; "defaults apply if you only approve"). Wait. Record the answer in `decisions.md`.

Re-plan (`## plan` in SKILL.md): same steps on the delta; never drop a started story.
