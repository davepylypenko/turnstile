# Report templates (one file per agent run under `delivery/reports/`)

Every report starts with `# <TYPE> — <subject> — <date>` and a `Status:` line (`DONE` / `DONE_WITH_CONCERNS` /
`NEEDS_CONTEXT` / `BLOCKED`), then the sections below. Paste real command output summary lines, never paraphrase them.

## Ticket
`reports/<KEY>.md` — PR URL · branch · head · base · files changed · commands run → summary lines · Copilot threads
(id → verdict → commit) · signatures verified · deviations from the brief · open questions · backlog notes.

## Review
`reports/REVIEW-<n>.md` — PR · head · base · worktree · rounds (round → head → findings count) · findings table
(# · severity · file:line · claim · verification · fix · status) · gate run URL + verdict · fixes applied by the reviewer
(commits) · `clean: true|false`.

## Story review
`reports/STORY-<S>-review.md` — stack top SHA (= `evidence.deploy.head`) · PRs in order · rounds · findings table with a
`target PR` column · cross-ticket seams checked · test cases traced · `clean: true|false`.

## Stack
`reports/STACK-<date>.md` — table PR → old head → new head → CI → gate → Copilot · conflicts (files, how resolved) ·
`turnstile pass` lines to run.

## Comments
`reports/COMMENTS-<n>.md` — thread table (id · author · human/Copilot · opened at · verdict · commit · resolved?) · Copilot
loop rounds · draft replies (per `references/slack.md`) for the lead to post · new head · gate state.

## Investigation
`reports/INVESTIGATE-<slug>.md` — question · hypotheses · evidence per hypothesis (file:line / command → output) ·
answer · recommendation + cost if wrong · not verified.

## Env test
`reports/ENV-<S>.md` — environment (variant, desk, build number and stack-top head tested, routing proof: `x-server-name`, static host) · mode (`full` /
`rerun` + cases) · case table (case · verdict · evidence path · note) · parity table (screen/state · Figma node · max
deviation px / colour · verdict) · fails as `turnstile bug add --story <S> --case <case id> --title "…" --source "tester <date>"
--figma <node>` lines · `not_testable_here` reasons · totals (pass / fail / not_testable_here) · the failed case ids on one line.

## Deploy
`reports/DEPLOY-<slug>-<date>.md` — table repo → ref → workflow run → build / image tag → health check result ·
variant tag kept · stack-top SHA deployed · traps hit.
