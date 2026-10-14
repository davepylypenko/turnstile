# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## PR
{{pr_id}} — {{ticket_key}} · head `{{head}}` · worktree `{{worktree}}` · gate `{{gate}}` via `{{gate_skill}}` · Copilot: {{copilot}}.
Rework started at {{rework_since}} (threads open at that time need the lead's reply before the PR goes back to humans).

## Threads to handle
{{threads}}

## Context the reviewers may lack
{{context}}

Human threads: verdict + fix + draft reply only (per `references/slack.md` § Reply drafts). Copilot threads: fix or justify, resolve, re-request, loop.
Report → `{{report_path}}` § Comments.

## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Poll ≤ 2 min, never silent > 5 min. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
