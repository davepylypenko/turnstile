# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## PR
{{pr_id}} — {{ticket_key}} · head `{{head}}` · worktree `{{worktree}}` · gate `{{gate}}` via `{{gate_skill}}` · Copilot: {{copilot}}.
Sent to humans at {{sent_at}} · rework since {{rework_since}}. Every human thread opened since the send, and every unresolved one,
needs a reply newer than the reviewer's last comment before the PR goes back to humans.

## Threads to handle
{{threads}}

## Context the reviewers may lack
{{context}}

## How to answer (lead rule 2026-10-14)
1. Verdict per thread; fix → test → signed commit → push.
2. Classify every human thread from GitHub facts: `turnstile threads {{pr_id}} --self-resolved <ids> --needs-lead <ids> --report {{report_path}}`.
   `self_resolved` = fixed in code or answered with a code-level justification; `needs_lead` = a product / design / scope /
   architecture decision, a disagreement on direction, a conflict with `decisions.md` or the plan, another team. In doubt: needs_lead.
3. Reply to each self_resolved thread at once: `gh api -X POST repos/{{github_org}}/<repo>/pulls/<n>/comments/<top-level comment id>/replies -f body=…`
   (literal route; text per `references/slack.md` § Thread replies).
4. needs_lead: the draft goes in the report, word for word; name the `ah-<n>` ids in your reply. Lead-approved entries to post now: {{approved_replies}}.
5. Copilot threads: fix or justify, resolve (literal `PRRT_…` id), re-request, loop.
Report → `{{report_path}}` § Comments.

## Don'ts
No Slack, no Jira, no issue comments (`gh pr comment`), no review submissions (`gh pr review`), never resolve a human thread,
no reply to a needs_lead thread without its approved entry, no reviewer requests, no "ready", no merges, no rebase or force-push,
no subagents, no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Poll ≤ 2 min, never silent > 5 min. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
