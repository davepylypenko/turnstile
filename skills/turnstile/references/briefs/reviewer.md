# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## PR
{{pr_id}} — {{ticket_key}} {{ticket_title}} · head `{{head}}` · base `{{base_branch}}` · worktree `{{worktree}}` · repo gate `{{gate}}` via `{{gate_skill}}`.
Deep review skill: `{{review_skill}}` — run it on the head after your own reading; it is the lead's choice (`turnstile config`), not a
replacement for the repo gate above. If it cannot be invoked, stop with `BLOCKED: review skill {{review_skill}} not available`.

## Ticket scope to check against
{{scope}}

## Invariants
{{invariants}}

## Design
{{figma_frames}}

## Earlier rounds
{{previous_reports}}

Report → `{{report_path}}` § Review; include the gate run URL and `clean: true|false`.

## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Poll ≤ 2 min, never silent > 5 min. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
