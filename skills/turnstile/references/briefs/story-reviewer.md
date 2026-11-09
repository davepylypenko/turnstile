# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## Story
{{story_id}} — {{story_title}} · epic branch `{{epic_branch}}` · story branch `{{story_branch}}` · stack top {{stack_top_pr}} @ `{{head}}` · worktrees {{repo_paths}}.
Tickets: {{tickets}}. PRs in merge order: {{prs}}.
Story review skill: `{{story_review_skill}}{{review_effort}}` — invoke it as written, on the stack top, after your own
reading (the lead's choice via `turnstile config`; the repo gate stays separate). If it cannot be invoked, stop with `BLOCKED: review skill {{story_review_skill}} not available`.

## What the story must deliver (plan.md § story)
{{scope}}

## Test cases mapped to the story
{{test_cases}}

## Figma frames
{{figma_frames}}

## Invariants
{{invariants}}

## Earlier reviews of the ticket PRs (do not repeat; verify)
{{previous_reports}}

Report → `{{report_path}}` § Story review, findings tagged with the ticket PR they belong to.

## Round mode
This brief: {{round_mode}}.
- Round 1 — full review: your own reading of the whole story diff, the review skill.
- Round ≥ 2 (the brief name ends `-r<n>`, or `previous_reports` names an earlier round) — delta review: verify the previous
  round's findings against `git diff <last reviewed head>...<head>`, run the review skill only when the delta touches production code or exceeds ~150 lines, no mutation sweeps beyond the changed tests, no re-reading of files the
  delta does not touch, aim ≤ 80 tool calls.

## Don'ts
No Slack, no Jira, no comments in the pushed diff beyond what the code cannot say (no `@ai-generated`/AI markers, no Arrange/Act/Assert, no docblocks restating the signature — role rule § Code comments), no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Wait for CI, a deploy or a gate with ONE blocking command (`gh run watch <id> --exit-status`, `gh pr checks <n> --watch`, the deploy workflow's `wait_for_ready`), never a sleep/poll loop (pass the Bash tool's `timeout` parameter, up to 600000 ms, on that call; if the watch is still running when the timeout expires, call it again instead of polling with short status checks), and never end the turn with an interim "waiting" message — report only when there is a fact. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
