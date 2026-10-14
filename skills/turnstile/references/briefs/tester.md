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
Reference images: `evidence/{{story_id}}/<case>/figma.png` fetched with `curl -o` from the `__download_assets` export URL (png, scale 2), else the `__get_screenshot` URL, else the Figma REST export with `FIGMA_TOKEN` from your environment (if the lead exported it; it is never written anywhere). None works → `not_testable_here: no figma reference` for the affected rows and `--figma-parity not_testable_here`; never parity `pass` without `figma.png` (`{{skill_dir}}/references/tools/figma.md`).

## Evidence
`evidence/{{story_id}}/<case>/` per `references/evidence.md`.

Report → `{{report_path}}` § Env test; list every fail in the `turnstile bug add --story {{story_id}} …` form; totals as pass / fail / not_testable_here (the orchestrator records them with `--cases-pass --cases-fail --cases-not-testable`; a full run's three counts add up to the story's test cases).

## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Poll ≤ 2 min, never silent > 5 min. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
