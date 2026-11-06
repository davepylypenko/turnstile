# Brief — {{agent}} — {{brief_name}} — {{today}}

Epic {{epic_key}} · delivery `{{delivery}}` · report → `{{report_path}}` · reply ≤ 8 lines.
Read first: the role rules you were launched with, then this brief, then every file listed below. The brief wins on specifics.

## Story and environment
{{story_id}} — {{story_title}}. Mode: {{mode}} (`full` or `rerun`; rerun cases: {{rerun_cases}}).
Feature flag: `{{flag}}` · arm: `{{arm}}` (treatment = flag on, control = flag off; toggle it per the recipe § Feature flag — an unknown toggle method is `BLOCKED`, never a guess; `none` = no flag, single arm).
Environment: variant `{{variant}}`, desk `{{desk}}`, builds {{builds}} (stack-top head {{stack_head}}). Recipe: `{{skill_dir}}/{{env_recipe}}`. Figma tool mapping: `{{skill_dir}}/references/tools/figma.md` (resolve first; none → BLOCKED). Test user: {{test_user}}. Repo worktrees (read-only, for test files and selectors): {{repo_paths}}. Password: from your environment at login (`$TURNSTILE_TEST_PASSWORD`, else keychain `turnstile-test-password`), per the role rules; never in this brief, the report or any file.

## Test cases
{{test_cases}}

## Screens and states → Figma frames
{{figma_frames}}
Parity tolerance: {{tolerance}}. Copy source: {{copy_source}}.
Reference images: `evidence/{{story_id}}/<case>/figma.png` fetched with `curl -o` from the `__download_assets` export URL (png, scale 2), else the `__get_screenshot` URL, else the Figma REST export with `FIGMA_TOKEN` from your environment (if the lead exported it; it is never written anywhere). None works → `not_testable_here: no figma reference` for the affected rows and `--figma-parity not_testable_here`; never parity `pass` without `figma.png` (`{{skill_dir}}/references/tools/figma.md`).

## Evidence
`evidence/{{story_id}}/<case>/` per `references/evidence.md`.

Report → `{{report_path}}` § Env test; list every fail in the `turnstile bug add --story {{story_id}} [--arm {{arm}}] …` form; totals as pass / fail / not_testable_here (the orchestrator records them with `--arm {{arm}} --cases-pass --cases-fail --cases-not-testable`; a full run's three counts add up to the story's cases for that arm).

## Don'ts
No Slack, no Jira, no PR comments, no reviewer requests, no "ready", no merges, no rebase or force-push, no subagents,
no `Co-Authored-By`, no generated-with footer, never `turnstile approve`. Wait for CI, a deploy or a gate with ONE blocking command (`gh run watch <id> --exit-status`, `gh pr checks <n> --watch`, the deploy workflow's `wait_for_ready`), never a sleep/poll loop (pass the Bash tool's `timeout` parameter, up to 600000 ms, on that call; if the watch is still running when the timeout expires, call it again instead of polling with short status checks), and never end the turn with an interim "waiting" message — report only when there is a fact. Report at
`{{report_path}}` per `references/reports.md` (Write tool); keep it updated as you go.
