# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## Story and environment
{{story_id}} — {{story_title}}. Mode: {{mode}} (`full` or `rerun`; rerun cases: {{rerun_cases}}).
Environment: variant `{{variant}}`, desk `{{desk}}`, builds {{builds}} (stack-top head {{stack_head}}). Recipe: `{{skill_dir}}/{{env_recipe}}`. Figma tool mapping: `{{skill_dir}}/references/tools/figma.md` (resolve first; none → BLOCKED). Credentials: in your launch prompt, not here (briefs are committed to git); never write them to a file or report.

## Test cases
{{test_cases}}

## Screens and states → Figma frames
{{figma_frames}}
Parity tolerance: {{tolerance}}. Copy source: {{copy_source}}.

## Evidence
`evidence/{{story_id}}/<case>/` per `references/evidence.md`.

Report → `{{report_path}}` § Env test; list every fail in the `turnstile bug add --story {{story_id}} …` form.

## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Poll ≤ 2 min, never silent > 5 min. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
