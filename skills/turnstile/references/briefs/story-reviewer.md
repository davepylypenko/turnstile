# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## Story
{{story_id}} — {{story_title}} · epic branch `{{epic_branch}}` · story branch `{{story_branch}}` · stack top {{stack_top_pr}} @ `{{head}}` · worktree `{{worktree}}`.
Tickets: {{tickets}}. PRs in merge order: {{prs}}.

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

## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Poll ≤ 2 min, never silent > 5 min. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
