# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## Question
{{question}}

## Where to look
{{where}}
Repo worktrees (read-only): {{repo_paths}}.

## Hypotheses already on the table
{{hypotheses}}

## What a good answer looks like
{{answer_shape}}

Time box: {{time_box}}. Read-only. Report → `{{report_path}}` § Investigation.

## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Wait for CI, a deploy or a gate with ONE blocking command (`gh run watch <id> --exit-status`, `gh pr checks <n> --watch`, the deploy workflow's `wait_for_ready`), never a sleep/poll loop (pass the Bash tool's `timeout` parameter, up to 600000 ms, on that call; if the watch is still running when the timeout expires, call it again instead of polling with short status checks), and never end the turn with an interim "waiting" message — report only when there is a fact. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
