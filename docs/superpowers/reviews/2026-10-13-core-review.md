# Turnstile core: whole-branch review (2026-10-13)

Scope: `a77ea98..11d04dd` (12 commits) against `specs/2026-10-13-turnstile-design.md` §3, §4.2, §5, §6 and
`plans/2026-10-13-turnstile-core.md`, including its Deviations. I read every file in `turnstile_cli/`, `hooks/`,
`templates/`, `scripts/` and `tests/`, and I probed each suspected bypass with a script before listing it.

Suite: `python3 -m unittest discover -s tests -v` passes on **Python 3.9.6**: 48 tests before the fixes, 52 after.
No 3.10+ syntax was found (no `|` unions, no `match`, no runtime `list[...]`/`dict[...]` annotations, no `removeprefix`).

## Fixes applied in this review (signed, pushed to `main`)

| Commit | Fix |
|---|---|
| `685af0f` | **Board:** the embedded state now escapes every `<` as `<`. The old `</`-only escape let `<!--<script>` in a state value break the page's script parsing. PR hrefs now go through `esc()`, so a PR id containing `"` can no longer inject attributes. Slack permalinks link only when they start with `https://`, which blocks `javascript:` links. |
| `fac383b` | **Hooks:** both guards now block (fail closed) on any unexpected exception. Before, a crash exited 1, which Claude Code treats as non-blocking. The Slack matcher now also covers `slack_schedule_message`, which was an unguarded way to send. The force-push rule now catches `-fu`/`-uf` and quoted `"--force"`, and it stops at `;`, `&` and `\|`, so `git push … && rm -f x` and `git push …; echo +1` are no longer blocked by mistake. The empty-tag rule no longer blocks quoted non-empty tags (`service_github_tag='v1.2'`) and now catches `=''`, `=""` and `"service_github_tag="`. Tests added. |
| `32f423a` | **pass:** `--head` is stored lowercase, so the board's JS head check (case-sensitive) matches `rules.same_head`. |

## Findings

### Blockers

1. **`pass … ON_HUMAN_REVIEW --approved <id>` does not verify the approval, and it approves the id itself.**
   `pass_cmd.py:62-64` sets `approved_at` on whatever id is passed, and `rules.py:83` only checks that the id is truthy.
   Probes confirmed two cases:
   - `--approved ah-NOPE` (an id that does not exist) passes.
   - `--approved ah-1` with `approved_at=null` passes, and the pass writes `approved_at`. From then on the Slack guard
     lets sends through for that PR.

   **Fix:** in `run()`, look up the entry and require all of the following:
   - it exists;
   - `pr == ident` and `type in (send, reply)`;
   - `approved_at` is already set (only `turnstile approve` may set it);
   - it is not already marked consumed.

   Then mark it `consumed_at`. Delete lines 62-64.

2. **`turnstile approve` is not gated on the lead.** Any agent can run `turnstile approve ah-N` and then post to Slack.
   The Slack guard only checks a field that the agent can write itself. **Fix:** in `guard_bash.py`, match
   `\bturnstile\s+approve\b` and return a PreToolUse JSON `permissionDecision: "ask"` instead of exit 2. The human then
   has to confirm every approve in the permission prompt, including in bypass mode, and including from subagents.

3. **Evidence is bound to the head stored in `state.json`, not to the PR's real head.** `pass` never asks GitHub for the
   head. `--head` accepts any string (probe: `READY --head ffffffffffffffff` passed). With no `--head`, the stored head
   stays put even after a push, so `READY → ON_HUMAN_REVIEW` succeeds on an unreviewed head. Only `reconcile`, which is
   advisory, would notice. **Fix:** add `IO.github_head(pr_id)`, injectable so tests stay offline. For targets `READY`,
   `ON_HUMAN_REVIEW`, `APPROVED` and `MERGED`, require `same_head(gh_head, o.head or pr.head)`. If `gh` fails, fail
   closed. Add `--offline --reason` only as an override that is recorded in the ledger.

### Major

4. **Atomicity is broken.** `pass_cmd.py:95-100` saves the state, then appends the ledger, then renders, then commits. If
   `git commit` fails (signing agent locked, hook rejects), the probe shows state.json and ledger.md already written and
   a `CalledProcessError` traceback with exit 1. In addition:
   - On `MERGED`, `pass_cmd.py:134` appends to the ledger *before* the stale check in `save`.
   - The `JIRA:` line at `:123` is printed before any write can fail.
   - The same pattern exists in `approve` and `jira_synced`.

   **Fix:**
   - Snapshot `state.json`, `ledger.md` and `board.html`.
   - Collect the extra ledger lines in a list.
   - Do the stale check, then write each file to a temp file and `os.replace` it.
   - Render, then commit.
   - On any exception: restore the snapshots, run `git reset -q -- .` in the delivery dir, print `MISSING side effect
     failed: …` and exit 2.
   - Print `JIRA:` only after the commit succeeds.

   Test: a FakeIO whose `git_commit` raises.

5. **`REWORK → ON_HUMAN_REVIEW` demands a new deep review, which contradicts spec §3** ("deep_review is not repeated
   after human review"). `rules.py:76-77` reuses `_ai_review_done`; probed: the transition is refused for a new head with
   gate and Copilot evidence. **Fix:** when `src == "REWORK"`, require ci, gate and copilot on the head, but not
   deep_review. Also require an approved `reply` entry, because REWORK's DoD says "lead approved replies; replies posted".

6. **No `reply` entry ever exists in `awaiting_human`.** Nothing creates `type: reply`, so the REWORK flow can never
   pass the Slack guard legitimately. Also, once a `reply` entry is approved it unlocks unlimited messages for that PR,
   forever and to any channel (probed). **Fix:** create a `reply` entry on `→ REWORK`. Make entries single-use: the
   guard or the pass sets `consumed_at`. Also check `tool_input.channel_id` against `epic.repos[repo].slack`.

7. **Reconcile proposes commands that `pass` refuses.** For a PR in `DEV` or `AI_REVIEW` whose head changed, it proposes
   `pass … AI_REVIEW …`, but AI_REVIEW cannot be entered from AI_REVIEW. It emits `--ci pending`/`unknown`, which
   argparse rejects. For `REWORK` it proposes `AI_REVIEW`, which drops the "after send" semantics, and for `merged` it
   proposes MERGED from states where MERGED is not allowed.

   **Fix:**
   - Add a non-transition `turnstile pass pr X evidence --head … [--ci …]` (or allow same-state passes) for recording
     evidence.
   - In REWORK, propose evidence only.
   - Emit `--ci` only when the value is success or failure.
   - For `merged`, propose MERGED only from APPROVED/ON_HUMAN_REVIEW; otherwise report it as an anomaly.

8. **Bot detection in `github.parse` is wrong for GraphQL.** In GraphQL, `Bot.login` has no `[bot]` suffix (for
   example `github-actions`), so bot approvals count as human approvals and bot threads as human threads. That produces
   false APPROVED and REWORK proposals (probed). **Fix:** query `author{__typename login}` in `latestReviews` and in
   thread comments and skip `__typename == "Bot"`. Keep the Copilot login check for the Copilot count.

9. **`changes_requested` is collected and never used.** Spec §3 says "changes requested → REWORK". **Fix:** in
   `reconcile.compare`, when the PR is ON_HUMAN_REVIEW and `f.changes_requested` is not empty, propose REWORK.
   Also add `latestReviews{commit{oid}}`, and count an approval only when its commit is the current head.

10. **The story `DONE` gate can be bypassed.**
    - `_apply_story_evidence` writes `fail: o.cases_fail or 0`, so `pass story S1 DONE --figma-parity pass --report r`
      records 0 failures that nobody reported. The probe passed with the fixture's PRs in DEV and AI_REVIEW.
    - `ENV_TESTING` and `DONE` never re-check that the story's PRs are still at least READY after integration fixes.
    - Neither checks for open bugs in the story.
    - `DONE` has no lead approval (§4.2 "lead … said send").

    **Fix:**
    - Require `--cases-pass` and `--cases-fail` explicitly whenever `env_test` is recorded.
    - Repeat the PR ≥ READY check for ENV_TESTING and DONE.
    - Require `bugs[story==S].state == done`.
    - Require an approved `awaiting_human` entry of type `send` for the story.

11. **The story stop rule and plan approval are not enforced.** `PLANNED → IN_PROGRESS` needs no lead word (§4.1 step 3,
    §4.2 stop rule). Also, `--reason` serves both to reopen a story and to override `after`, so a reopen silently skips
    the dependencies. **Fix:** require an approved `start_story` entry. Split the override into its own flag, for
    example `--override-after "<lead quote>"`.

12. **The Bash guard is easy to bypass.** It does not catch a global option before the subcommand
    (`git -C dir push --force`, `git -c x=y rebase`, `gh -R o/r pr merge 1`), and it does not catch the REST and GraphQL
    routes:
    - `gh api -X PUT …/pulls/N/merge`
    - `mutation{markPullRequestReadyForReview}` / `mergePullRequest`
    - `git -c commit.gpgsign=false commit`
    - a `requested_reviewers` POST that lists Copilot together with a human

    It also has false positives: `Co-Authored-By` blocks `git log --grep Co-Authored-By`, and `requested_reviewers`
    blocks GETs. **Fix:**
    - Use the prefixes `GIT=r"\bgit(?:\s+(?:-[Cc]\s+\S+|--?[\w.-]+(?:=\S+)?))*\s+"` and
      `GH=r"\bgh(?:\s+(?:-R|--repo)\s+\S+)*\s+"`.
    - Add rules for `pulls/\d+/merge`, `markPullRequestReadyForReview|mergePullRequest|requestReviews` and
      `commit\.gpgsign\s*=\s*false`.
    - For `requested_reviewers` with `POST`, block any `reviewers[]=` value other than the Copilot bot.
    - Apply the trailer rule only to `git commit` and `gh pr create|edit`.

13. **`guard_state_edit` reaches neither the model nor all write paths.** It prints to stdout with exit 0, which a
    PostToolUse hook does not show to Claude. It does not run reconcile (§6). It does not cover Bash writes
    (`cat > state.json`, `sed -i … state.json`), and this workspace edits files through Bash. **Fix:** emit
    `{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":…}}` (or exit 2 with stderr). In
    `guard_bash`, block redirections to, or `sed -i`/`tee` on, `delivery/state.json`.

### Minor

14. **The stale-file guard covers only one process, and only between `load` and `save`.**
    - There is a time-of-check-to-time-of-use (TOCTOU) window between the digest re-read and `write_text`.
    - `write_text` truncates the file before writing it, so a concurrent hook can read a partial file. It fails closed,
      but it is noisy.
    - Two people in two clones are not protected at all; git merge is.

    **Fix:** take `fcntl.flock` on `delivery/.lock` from `load` to commit, use temp file + `os.replace`, and add
    `.gitattributes`: `ledger.md merge=union`. Add a test with two `State` objects loaded from one file and saved in
    turn.
15. **`MERGED` is allowed from `ON_HUMAN_REVIEW`** (`rules.py:16`; probe passed with no approvals), which skips the
    APPROVED DoD. Allow it only from APPROVED, or require `--reason`. `AI_REVIEW` is also allowed from
    `ON_HUMAN_REVIEW`, which lets a sent PR leave REWORK (the "reviewer not notified" state). Remove that edge.
16. **Report files are not checked.** `--deep-review`/`--report` paths are never checked for existence under
    `delivery/` (tests create `reports/R.md` but never rely on it). Check `(delivery/path).is_file()`.
17. **`gate_red` reports pending checks as red.** It fires on `pending`, `in_progress`, `queued` and `skipped`; only
    `failure`, `cancelled`, `timed_out`, `action_required` and `error` should count. Duplicate check names overwrite
    each other in arbitrary order. With more than 50 contexts the gate can be missing, and then the check silently
    passes.
18. **DoR/DoD items not covered:**
    - DEV DoD: signed commits, no trailer, PR body. Fetch `commits{signature{isValid}}` in reconcile.
    - The MERGED side effect "re-evaluate the story DoD".
    - The board legend with the Jira mapping (§5 render-board).
    - The REWORK note "reviewer not notified".
    - Jira status in reconcile, which only checks the `synced` flag.
19. **The integration review head is bound to nothing.** `integration_review.head` (from `--head` in a story pass) is
    stored but never compared with the stack top or the epic branch head. Check the head again at ENV_TESTING/DONE, or
    record the stack-top SHA at `deploy` and require them to be equal.
20. **Untested transitions:**
    - PR: `→ APPROVED` success, `→ MERGED`, `→ DEV`, `→ REWORK` without a reason.
    - PR: `ci=failure`, `deep_review --not-clean`, `gate result=fail` and `gate name mismatch` at READY.
    - Story: reopen without a reason.
    - `same_head` with uppercase input.
    - Reconcile: `ci_red`, `draft_mismatch`, `copilot_thread`.
21. **`reconcile`/`status` return 0 when every `gh` call failed** (they only print WARN). `status` should return a
    non-zero code when facts are missing for any PR that is not merged.

### Nits

22. `paths.find_delivery` crashes with an `IndexError` when `.turnstile` is empty, and `_next_ah_id` crashes with a
    `ValueError` on an id like `ah-x`.
23. `same_head` accepts non-hex strings (`zzzzzzzz`). Validate `[0-9a-f]{8,40}` when storing `--head`.
24. Board:
    - Story and bug badges are always grey, because `COLORS` holds only PR states.
    - `--merged:#111827` is almost invisible on the dark card.
    - `e.env_test.cases.fail` throws when `cases` is missing, which stops the Bugs and Awaiting tabs from rendering.
    - The tabs have no `role="tab"`/`aria-selected`.
25. `guard_bash` allows a malformed hook payload (`{}` → exit 0); make it block instead. If `python3` is missing, the
    hooks exit 127, which Claude Code treats as non-blocking, so they fail open. Document this, or wrap the hooks in
    `sh -c '… || exit 2'`.
26. `jira-synced` accepts any status text. Validate it against `JIRA_FOR_PR_STATE[pr.state]`.

## Coverage map: spec §3 / §4.2 → code → test

| Rule | Code | Test |
|---|---|---|
| AI_REVIEW entry: CI green on head | `rules.py:68-72` | indirect (`test_head_change_voids_old_evidence`) |
| AI_REVIEW DoD: deep_review clean, gate pass, Copilot 0 (when enabled), all on head | `rules.py:37-55` | `ToReady.*` (clean / result=fail / name mismatch: no test) |
| READY → send: `blocked_by` merged | `rules.py:85-87` | `test_blocked_by_unmerged` |
| ON_HUMAN_REVIEW: permalink, `sent_head`, lead approval | `rules.py:78-84` | `test_needs_permalink_and_approval`, approval not verified (finding 1) |
| APPROVED: approvals ≥ 1, threads 0, `sent_head` | `rules.py:89-97` | `test_push_after_send_voids` (failure only) |
| REWORK DoD (gate/Copilot only, replies) | missing (finding 5, 6) | none |
| MERGED: `merged_sha`, Jira On Hold, `blocked_by` | `rules.py:98-101`, `pass_cmd.py:131-134` | none |
| Story IN_PROGRESS: `after` DONE | `rules.py:143-149` | `test_planned_waits_for_after_unless_reason` |
| Story INTEGRATION_REVIEW: PRs ≥ READY, deploy | `rules.py:150-157` | `test_to_integration_review_needs_all_prs_ready_and_deploy` |
| Story ENV_TESTING: integration_review clean + head | `rules.py:158-162` | `test_to_env_testing` |
| Story DONE: report, fail 0, Figma parity | `rules.py:163-172` | `test_to_done_requires_clean_env_test` (bypass: finding 10) |
| Story DONE: lead "send"; stop rule | missing (finding 10, 11) | none |

## Resolution (2026-10-13)

Every blocker, major, minor and nit was addressed; nothing was deferred. Suite: 52 → 119 tests, green on Python 3.9.6.

| # | Finding | Resolution | Commit |
|---|---|---|---|
| 1 | `--approved` not verified, pass approves | `rules.check_approved_entry`: entry must exist, match type (`send` from READY / `reply` from REWORK) and PR, be approved by `turnstile approve`, not consumed, not voided; the pass sets `consumed_at`; `pass` never writes `approved_at` | `04a0537` |
| 2 | `turnstile approve` not gated on the lead | CLI refuses without `TURNSTILE_LEAD=1` in the environment; Bash guard blocks any `turnstile`/`turnstile_cli … approve` without the literal `TURNSTILE_LEAD=1` in the same command (README documents that the lead types it) | `04a0537`, `7c7bd36` |
| 3 | Evidence bound to the stored head, not GitHub's | Every PR pass calls `IO.github_head` (injectable, `github.fetch`); mismatch or `gh` failure refuses; `--offline` prints `WARN`, records `evidence.head_verified: false`, and `rules` requires `head_verified` true for the current head at READY/ON_HUMAN_REVIEW | `04a0537` |
| 4 | Atomicity | validate → render board in memory → `state.save` (stale check) → ledger → board → `git commit`; on failure restore all three files from the snapshot, exit 2 `MISSING git commit failed: …`; JIRA/BOARD/OK print after the commit; MERGED ledger lines are collected, not appended early; `approve` and `jira-synced` share the path | `04a0537` |
| 5 | REWORK → ON_HUMAN_REVIEW demanded a new deep review | `rework_since` marker set on REWORK; `_ai_review_done` skips `deep_review` when it is set; gate/copilot/ci still required on the new head; an approved `reply` entry is required | `04a0537` |
| 6 | No `reply` entry; approvals unlimited | REWORK opens `type: reply`; Slack guard allows one message per approval by writing `used_at`/`used_channel` and a ledger line, checks `channel_id` against `epic.repos[repo].slack`, `send` only for READY and `reply` only for REWORK, consumed/voided entries do not unlock | `04a0537`, `7c7bd36` |
| 7 | Reconcile proposed refused commands | AI_REVIEW re-enters itself for a new head; every proposal is dry-run through `_apply_pr_evidence` + `rules.check_pr` on a copy and dropped (with the refusal text) when it would fail; `--ci` only for success/failure; REWORK/DEV get notes; MERGED proposed only from APPROVED, otherwise an anomaly | `2f0d79e` |
| 8 | GraphQL bot detection | `author{__typename login}` on reviews and thread comments; `__typename == Bot`, `[bot]`, Copilot, `Snyk-Agent`, `sonarqube*`, `application-pdffiller` ignored | `2f0d79e` |
| 9 | `changes_requested` unused; stale approvals | `changes_requested` proposal → REWORK; `latestReviews{commit{oid}}`, approvals count only for the current head | `2f0d79e` |
| 10 | Story DONE bypass | `--cases-pass`/`--cases-fail`/`--figma-parity` all required to record `env_test`; `cases.fail` must be present and 0; ENV_TESTING and DONE re-check PRs ≥ READY; open bugs of the story block; approved `story_done` entry (opened on entering ENV_TESTING) required and consumed | `04a0537` |
| 11 | Stop rule / plan approval not enforced | PLANNED → IN_PROGRESS needs an approved `start_story` entry (opened automatically when `after` stories are DONE) or a `--reason` naming the lead (`\blead\b`); reopen needs any reason and does not skip `after` | `04a0537` |
| 12 | Bash guard bypasses | `GIT`/`GH` prefixes with global options; REST `pulls/N/merge` writes, GraphQL `mergePullRequest|markPullRequestReadyForReview|requestReviews`, `ready_for_review`, `commit.gpgsign=false`; `requested_reviewers` writes allow only Copilot values and refuse `--input`; trailer/footer rules scoped to `git commit`, `gh pr create|edit`, `gh api`; GETs pass | `7c7bd36` |
| 13 | `guard_state_edit` ineffective | Now PreToolUse, exit 2 with stderr for `Edit|Write|MultiEdit` on `state.json` unless `TURNSTILE_MIGRATION=1`; Bash guard blocks `state.json` writes via redirection, `sed -i`, `tee`, `python -c`, `cp|mv|rm|install|truncate|dd` unless the command carries `TURNSTILE_MIGRATION=1` | `7c7bd36` |
| 14 | Stale guard single-process, truncating write | `state.write_atomic` (temp + `os.replace`), `state.locked()` flock on `state.json` from load to commit (also in the Slack guard), `delivery/.gitattributes` with `ledger.md merge=union`; test with two `State` objects | `f2612e0`, `04a0537` |
| 15 | MERGED from ON_HUMAN_REVIEW; AI_REVIEW from ON_HUMAN_REVIEW | `PR_FROM`: MERGED only from APPROVED; AI_REVIEW from DEV/AI_REVIEW/REWORK/READY | `04a0537` |
| 16 | Report files unchecked | `--deep-review`/`--report` must exist under `delivery/` | `04a0537` |
| 17 | Pending checks counted as red | failure/cancelled/timed_out/action_required/error → red; pending/in_progress/queued → pending; duplicates keep the worst; `contexts(first:100){totalCount}` and `gate_unknown` when truncated | `2f0d79e` |
| 18 | DoR/DoD gaps | `commits{signature{isValid}}` → `unsigned` proposal; board legend with the Jira mapping and a Note column (`reviewer not notified` on REWORK, `last_reason`); MERGED side effect re-evaluates stories (ledger note); Jira status itself stays outside the CLI (no API token by decision, spec §11) | `2f0d79e`, `fa2e596` |
| 19 | Integration review head bound to nothing | `deploy.head` recorded at INTEGRATION_REVIEW (`--head` required); ENV_TESTING and DONE require `integration_review.head == deploy.head` | `04a0537` |
| 20 | Untested transitions | Tests for APPROVED/MERGED/DEV/REWORK-without-reason, ci failure, deep review not clean, gate fail and name mismatch, reopen without reason, uppercase heads, reconcile `ci_red`/`draft_mismatch`/`copilot_thread`/`unsigned`/`gate_unknown`/`changes_requested` | `04a0537`, `2f0d79e` |
| 21 | `reconcile`/`status` exit 0 on gh failure | exit 1 when facts are missing for any open PR, with a closing line naming them | `04a0537` |
| 22 | `find_delivery`/`_next_ah_id` crashes | empty marker → `TurnstileError`; ids that are not `ah-<n>` are skipped | `f2612e0`, `04a0537` |
| 23 | Non-hex heads | `rules.valid_head` (`[0-9a-f]{8,40}`) enforced on `--head` | `04a0537` |
| 24 | Board badges, merged colour, `cases` crash, tabs a11y | colours for story and bug states, `--merged` readable, `cases` guarded, `role=tablist/tab` + `aria-selected` | `fa2e596` |
| 25 | Malformed payload passes; `python3` missing fails open | non-object payloads and missing `tool_input.command` block; every hook command ends with `\|\| exit 2` | `7c7bd36` |
| 26 | `jira-synced` accepts any status | validated against `JIRA_FOR_PR_STATE[pr.state]` | `04a0537` |
