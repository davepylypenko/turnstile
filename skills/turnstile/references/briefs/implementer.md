# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## Ticket
{{ticket_key}} — {{ticket_title}}
Repo `{{repo}}` (org `{{github_org}}`), worktree `{{worktree}}`, base branch `{{base_branch}}`, branch `{{branch}}`.
Read the repo's `CLAUDE.md` and {{repo_guides}} first.

## Scope (implement exactly this)
{{scope}}

## Anchors (verify before editing)
{{anchors}}

## Tests required
{{tests}}

## Verify commands (paste the summary lines)
{{verify_commands}}

## Commit and PR
Commit `{{commit_message}}` (signed, no trailer). Draft PR into `{{base_branch}}`, title `{{pr_title}}`, body per
`references/pr-body.md` with `Related: {{jira_url}}`. Copilot loop: {{copilot}} (`true` → REST request + loop until clean).

## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Poll ≤ 2 min, never silent > 5 min. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
