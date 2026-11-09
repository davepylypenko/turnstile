# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## PR
{{pr_id}} · repo `{{repo}}`, worktree `{{repo_path}}`, head `{{head}}`, base `{{base_branch}}` · repo gate `{{gate}}` via `{{gate_skill}}`.

## Ticket scope (for judging findings only)
{{scope}}

## Earlier gate runs
{{previous_reports}}

Report → `{{report_path}}` § Gate: the gate line `gate: {{gate}}:<pass|fail>:<run url>`, the CI result on the final head, the finding list
with severity, what you fixed (blocker/major and one-liners only) and `clean: true|false`.

## Don'ts
No Slack, no Jira, no comments in the pushed diff beyond what the code cannot say (no `@ai-generated`/AI markers, no Arrange/Act/Assert, no docblocks restating the signature — role rule § Code comments), no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Wait for CI, a deploy or a gate with ONE blocking command (`gh run watch <id> --exit-status`, `gh pr checks <n> --watch`, the deploy workflow's `wait_for_ready`), never a sleep/poll loop (pass the Bash tool's `timeout` parameter, up to 600000 ms, on that call; if the watch is still running when the timeout expires, call it again instead of polling with short status checks), and never end the turn with an interim "waiting" message — report only when there is a fact. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
