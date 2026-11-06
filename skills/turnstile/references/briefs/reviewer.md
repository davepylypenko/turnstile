# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## PR
{{pr_id}} — {{ticket_key}} {{ticket_title}} · head `{{head}}` · base `{{base_branch}}` · worktree `{{repo_path}}` · repo gate `{{gate}}` via `{{gate_skill}}`.
Deep review skill: `{{review_skill}}{{review_effort}}` — invoke it as written, on the head, after your own reading;
it is the lead's choice (`turnstile config`), not a replacement for the repo gate above. The `gate-runner` runs the gate first on a fresh head (see Round mode § Gate). If it cannot be invoked, stop with `BLOCKED: review skill {{review_skill}} not available`.

## Ticket scope to check against
{{scope}}

## Invariants
{{invariants}}

## Design
{{figma_frames}}

## Earlier rounds
{{previous_reports}}

Report → `{{report_path}}` § Review; include the gate run URL and `clean: true|false`.

## Round mode
This brief: {{round_mode}}.
- Round 1 — full review: your own reading of the whole diff, the repo gate, the review skill.
- Round ≥ 2 (the brief name ends `-r<n>`, or `previous_reports` names an earlier round) — delta review: verify the previous
  round's findings against `git diff <last reviewed head>...<head>`, re-run the gate on the head, run the review skill only when
  the delta touches production code or exceeds ~150 lines, no mutation sweeps beyond the changed tests, no re-reading of files the
  delta does not touch, aim ≤ 80 tool calls.
- Gate: when `reports/GATE-<n>.md` (the `gate-runner`'s) lists this head, the gate already ran on it: read its gate line and findings
  and do not re-run it unless you push a commit. With no such report, run the gate yourself.

## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Wait for CI, a deploy or a gate with ONE blocking command (`gh run watch <id> --exit-status`, `gh pr checks <n> --watch`, the deploy workflow's `wait_for_ready`), never a sleep/poll loop (pass the Bash tool's `timeout` parameter, up to 600000 ms, on that call; if the watch is still running when the timeout expires, call it again instead of polling with short status checks), and never end the turn with an interim "waiting" message — report only when there is a fact. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
