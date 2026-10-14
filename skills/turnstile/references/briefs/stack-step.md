# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## Stack (bottom → top)
{{stack}}

Changed PR: {{changed_pr}} (new head `{{head}}`). Repo `{{repo}}`, worktree `{{worktree}}`, gate `{{gate}}` via `{{gate_skill}}`, Copilot: {{copilot}}.

## Conflict policy
{{conflict_policy}}

Report → `{{report_path}}` § Stack with the table PR → old head → new head → CI → gate → Copilot and the `turnstile pass` lines.

## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Poll ≤ 2 min, never silent > 5 min. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
