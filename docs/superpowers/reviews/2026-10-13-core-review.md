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

## Round 2 (2026-10-13)

Scope: `f2612e0..b640fdf` against the Resolution table above, spec §3/§4.2/§6. Every bypass below was probed with a
script (pass runs through `FakeIO`, hooks through the real `guard_*.py` with a JSON payload). Suite: 119 → 122 tests,
green on Python 3.9.6.

### Resolutions verified

Closed as claimed: 1 (unknown / unapproved / consumed / wrong-type ids refused; reuse after consume refused), 4, 5, 6
(single use per approval, channel check), 8, 9, 10, 11, 13 (Edit/Write path), 15, 16, 17, 19, 20, 21, 22, 23, 24, 25, 26.
Not closed or regressed: **2** (R2-1), **3** (stale head through the send approval, offline APPROVED/MERGED: fixed below),
**7** (REWORK proposal refused: fixed below), **12/13** (Bash write paths: R2-2, R2-11), **14** (flock: fixed below).

### Fixes applied in this round (signed, pushed to `main`)

| Commit | Fix |
|---|---|
| `9ed1411` | **state:** `locked()` flocked `state.json` itself, but `write_atomic` swaps its inode with `os.replace`, so after the first save a new process locked the new inode while the holder still ran. Probe: three processes A/B/C were inside the critical section at the same time. The lock now sits on a stable file in the temp dir keyed by the delivery path; the probe serialises. |
| `57a8599` | **pass:** a `send` approval is bound to the head it was opened for. Before, the lead approved head A, the agent pushed B and passed `READY → ON_HUMAN_REVIEW --head B --ci … --deep-review … --gate …` with the old approval (probe passed). `APPROVED` and `MERGED` now require `head_verified` (before, `--offline --approvals nobody` reached APPROVED and `--offline --merged-sha x` reached MERGED and moved Jira to On Hold). A failed `git commit` now runs `git reset -q -- .`, so the refused transition no longer stays staged in the index. |
| `98d10b0` | **reconcile:** the push-after-send proposal `pass … REWORK --reason …` carried no `--head`, so the online head check in `pass` refused it (probe: exit 2). It now carries `--head <new>` and the dry run applies it. |
| `0208d55` | **hooks:** blocked now: `git -C "/my dir" push --force`, `"git" push --force`, `g\it …`, `gh --repo=o/r pr merge`, `gh pr --repo o/r merge`, `gh "pr" merge`, `gh pr 'merge'`, `gh api --method=PUT …/merge`, `-XPUT`, `git pull --rebase` / `-r`, `turnstile --delivery=x approve`. Rules run on the command as typed and on a copy with quotes and backslashes stripped. |

### Findings

**Blockers**

1. **R2-1 The lead gate can be typed by any agent.** `TURNSTILE_LEAD=1 turnstile approve ah-N` and
   `env TURNSTILE_LEAD=1 …` pass `guard_bash.py:49` and the CLI check `pass_cmd.py:311` (probe). Any literal the lead
   can type, the model can type; resolution 2 does not gate on a human. **Fix:** for every `APPROVE` match,
   `guard_bash` prints `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"lead approval of <ah-id>"}}`
   and exits 0 (never allow by literal). Before relying on it, verify on a throwaway session that `ask` still prompts in
   bypassPermissions mode and that a background subagent gets a denial, not a silent allow (the hooks docs do not state
   either). If `ask` does not hold in bypass mode, approvals must come from outside the agent: the lead runs
   `turnstile approve` in their own terminal and the guard blocks it from Bash outright.
2. **R2-2 The Slack guard trusts a file the agents can still write.** These all pass `guard_bash` (probe):
   `perl -pi -e … delivery/state.json`, `node -e "fs.writeFileSync('delivery/state.json',…)"`, `ruby -e`,
   `python3 - <<EOF` with the path built from pieces, `git checkout HEAD~3 -- delivery/state.json`, `sed -i … state.*`,
   and any write prefixed `TURNSTILE_MIGRATION=1` (`guard_bash.py:48`). Writing `approved_at` unlocks
   `guard_slack.py:44`, so the Slack hard rule falls with it. A regex blocklist cannot close this. **Fix:**
   `guard_slack` returns `permissionDecision: "ask"` after the state checks pass, so a human confirms every send in the
   UI. The state check stays as the "is it allowed at all" filter. Same `ask` for a Bash command that carries
   `TURNSTILE_MIGRATION=1`. Keep `STATE_WRITE` as best effort; add `perl|node|ruby` and `git (checkout|restore) … state.json`.
3. **R2-3 Sending to humans is not gated on the story (§1.4, §4.2).** `rules.check_pr` ON_HUMAN_REVIEW
   (`rules.py:123-135`) never looks at the story. Probe: jsfiller#1 went READY → ON_HUMAN_REVIEW while S1 was
   IN_PROGRESS. `human_review_units` is never read. **Fix:** pass `stories` into `check_pr`; from READY require
   `stories[pr.story].state == "DONE"`. Open the `send` entry when the story reaches DONE (one per unit), not at PR READY.
   For the migration, mark the stories whose PRs are already on human review as DONE with a lead `--reason`.

**Major**

4. **R2-4 A denied or failed Slack send burns the approval and deadlocks the PR.** `guard_slack.py:51-53` writes
   `used_at` in PreToolUse, before the send happens. If the user denies the call or the MCP fails, the entry is spent.
   `approve` then answers "already approved" (`pass_cmd.py:320`), and READY never opens a second `send`. The only way
   out is READY → AI_REVIEW → READY. **Fix:** when `approve` is called on a used, not-consumed entry, it opens a fresh
   entry with the same type, PR and head and approves it (the lead's word again). Better: set `used_at` in a PostToolUse
   hook, on success only.
5. **R2-5 Gate, CI and approval evidence is still self-reported.** `pass` checks the head against GitHub
   (`pass_cmd.py:87-101`) but takes `--gate pdf-review:pass`, `--ci success` and `--approvals x` on faith. Only
   `reconcile`, which is advisory, compares them. **Fix:** `IO.github_head` → `IO.github_facts`; for READY and
   ON_HUMAN_REVIEW require `facts.checks[gate] == "success"` and `facts.ci == "success"`; for APPROVED require
   `approvals ⊆ facts.approvals` and `facts.human_threads_open == 0`; for MERGED require `facts.merged`.
6. **R2-6 Story approvals take the first matching entry and are not bound to the evidence.** `rules.py:223` and `:254`,
   and `pass_cmd.py:265`, use `next(...)`. After a reopen (ENV_TESTING → IN_PROGRESS → … → ENV_TESTING):
   - an approved, unconsumed `story_done` from the earlier test run is reused for the new results;
   - or a consumed earlier entry makes DONE fail unless `--approved` is passed.

   **Fix:** void the open `story_done` when a story leaves ENV_TESTING backwards; choose the newest entry that is not
   voided.
7. **R2-7 `rework_since` is never cleared** (`pass_cmd.py:231`). After REWORK → DEV (a real re-implementation), deep
   review is skipped for the life of the PR (`rules.py:55`). **Fix:** `pr.pop("rework_since", None)` when the target is
   DEV.
8. **R2-8 Reconcile ignores threads and changes requested on APPROVED PRs.** `reconcile.py:71-78` checks only
   ON_HUMAN_REVIEW, although `PR_FROM["REWORK"]` allows APPROVED. **Fix:** `st in ("ON_HUMAN_REVIEW", "APPROVED")` for
   the human_thread and changes_requested branches.

**Minor**

9. **R2-9 The lock now depends on `TMPDIR`.** If the hook process and the CLI see different `TMPDIR` values (sandboxed
   sessions set one per session), they do not exclude each other. The digest check in `save` is then the only backstop,
   and it fails as "re-run", not as a lost write. **Fix:** lock `$(git rev-parse --git-common-dir)/turnstile-<hash>.lock`,
   or commit an empty `delivery/.state.lock` at `init` and lock that.
10. **R2-10 `write_atomic` changes the files.** `mkstemp` creates files with mode 0600, so `state.json` and `board.html`
    lose group and other read after the first pass. If `state.json` is a symlink, `os.replace` replaces the link with a
    plain file. **Fix:** `os.chmod(tmp, 0o666 & ~umask)` before the replace, and resolve the path first.
11. **R2-11 The guard still passes content and rules that live in files** (probe):
    - `gh api graphql -F query=@m.graphql` (a mutation in a file);
    - `git commit -F msg.txt` and `gh pr create --body-file b.md` (a trailer or footer in a file);
    - `git config pull.rebase true`;
    - `--service_github_tag ""` (the space form).

    **Fix:**
    - block `query=@` and `--input` with `graphql`;
    - for `-F`, `--file` and `--body-file`, read the file in the hook and apply `CONTENT_RULES`;
    - add `pull\.rebase\s+true`;
    - add `--service_github_tag\s+(?:''|"")`.
12. **R2-12 A Slack message that also links a PR missing from the state is refused with a misleading error.** A paired
    locales PR on a `Locales:` line, if it is not in `state.prs`, or a repo that is missing from `epic.repos`, makes
    `repos[...]` at `guard_slack.py:39` raise `KeyError`. The guard then blocks with "cannot read the delivery state".
    **Fix:** name the unknown id in the refusal, and allow ids that a `send` entry declares in a `companions` list.
13. **R2-13 ON_HUMAN_REVIEW does not check that the message was actually sent.** It takes any `--slack` string, and the
    entry's `used_at` (set when the guard let a send through) is never required. **Fix:** require `entry.used_at` and a
    permalink that matches `^https://[\w-]+\.slack\.com/archives/`.
14. **R2-14 The Slack guard's writes are not committed.** It writes `state.json` and `ledger.md` without a commit or a
    board render (`guard_slack.py:53-55`), and the next unrelated `pass` commits them. **Fix:** commit from the guard,
    or have `status` report uncommitted changes in `delivery/`.

**Spec rules still not enforced**

- §3 DEV DoD: reconcile checks the signature of the head commit only (not every commit), and `pass` never checks it.
- §3 REWORK "replies posted": nothing evidences it.
- §4.2 IN_PROGRESS "stacked or merged into the story branch": not checked.
- §4.2 ENV_TESTING "every fail became a bug": `cases.fail` is not compared with the story's bugs.

### Verdict

Not ready for a real epic yet. R2-1 and R2-2 mean any agent can still unlock a Slack send without the lead, which is
the hard rule the plugin exists to enforce. R2-3 lets PRs reach humans before the story gates. With `ask` decisions in
the two hooks (verified in bypass mode) and the story-DONE check, plan 3 can start. R2-4 to R2-8 should land before
the first REWORK cycle.

## Round 2 resolution (2026-10-13)

Every blocker, major and minor was addressed test-first; suite 122 → 140 tests, green on Python 3.9.6. Design
decisions for the blockers were taken by the lead and are not reopened here.

| # | Finding | Resolution | Commit |
|---|---|---|---|
| R2-1 | Any agent could type the lead gate | The lead approves only by typing `! TURNSTILE_LEAD=1 turnstile approve <ah-id>` in the Claude Code prompt (outside the model's tool calls). `guard_bash` refuses every model-issued command containing `turnstile approve`, `TURNSTILE_LEAD` or `TURNSTILE_MIGRATION` after stripping quotes/backslashes and collapsing whitespace (`env`, `export`, `bash -c`, heredoc, `T\URNSTILE_LEAD` forms tested); the CLI keeps requiring `TURNSTILE_LEAD=1`. `approve` records `approved_via: "lead-terminal"`; the ledger line says so. README "How the lead approves", `skills/turnstile/SKILL.md` stub | `c34bf6d` |
| R2-2 | `state.json` writable through other interpreters; Slack guard trusted that file | Generic rule: a command that mentions `state.json` (also as a glob) or the delivery dir (absolute path, `delivery/`, `cd delivery`) and has any pipeline segment that is not read-only is refused (`delivery-write`); `git checkout/restore/stash/reset` touching it are refused (`delivery-git-restore`); redirects count by target. `turnstile reconcile` adds `approval_unlogged` for an `approved_at` whose ledger line is missing or lacks `approved_via: lead-terminal`. README "Threat model" documents the accepted residual risk (same OS user; hooks + ledger + reconcile are defence in depth) | `c29bf8a` |
| R2-3 | PRs reached humans before the story gates | `rules.check_pr` takes `stories`; READY → ON_HUMAN_REVIEW requires `stories[pr.story].state == "DONE"` unless the story carries `human_review: "per_pr"` (lead-set, recorded in `plan.md`); missing story data fails closed; `pass` and the reconcile dry run pass the stories. Tests cover both branches | `21dcb27` |
| R2-4 | A denied or failed send burned the approval | `guard_slack.py` (PreToolUse) only checks. New `post_slack.py` (PostToolUse, same matcher) sets `used_at`/`used_channel`/`message_ts` only when the tool result carries a `message_ts`, writes the ledger line, renders the board and commits `delivery/` | `09c0485` |
| R2-5 | Gate/CI/approval evidence self-reported | `IO.github_facts` replaces `github_head`; `pass` refuses `--ci success` with a non-success rollup, `--gate x:pass` while the context is pending/failed/absent, `--copilot 0` with open Copilot threads, `--approvals` missing from `latestReviews` for the head, unresolved human threads or changes requested at APPROVED, MERGED while GitHub shows the PR open. The reconcile dry run applies the same checks with the fetched facts. Tests on canned facts | `1a0a5a4` |
| R2-6 | Story approvals reused or stuck after a reopen | Leaving ENV_TESTING backwards voids the open `story_done` (ledger line); `start_story`/`story_done` are consumed on use; rules and pass pick the newest entry that is neither voided nor consumed (`rules.latest_entry`). Two-cycle test | `bd9fa72` |
| R2-7 | `rework_since` never cleared | REWORK → DEV drops it; a new head then requires a deep review again (test) | `bd9fa72` |
| R2-8 | Reconcile ignored threads on APPROVED PRs | `human_thread` and `changes_requested` proposals for `ON_HUMAN_REVIEW` and `APPROVED` | `bd9fa72` |
| R2-9 | Lock depended on `TMPDIR` | Lock is `delivery/.state.lock`, an empty tracked file created at init and repaired by `pass`; test switches `TMPDIR` between two lockers | `18d3ceb`, `73f5327` |
| R2-10 | `write_atomic` changed mode and replaced symlinks | Target resolved first; the temp file gets the existing mode (or `0666 & ~umask`) before `os.replace`; tests for mode, symlink and umask | `18d3ceb` |
| R2-11 | File-borne content and rules passed the guard | `-F`/`--file`/`--body-file`/`--input` files are read on `git commit` / `gh pr create|edit` / `gh api` and the trailer/footer rules applied; `gh api graphql` with `query=@` or `--input` refused; `pull.rebase true` and `service_github_tag ''` (spaced) covered | `72e77e8` |
| R2-12 | Misleading refusal for paired PRs | The Slack guard names the id it refuses (repo not in `epic.repos` / no usable entry); a PR in a chosen send entry's `companions` (`pass … READY --companions locales#5`) needs no entry | `72e77e8` |
| R2-13 | ON_HUMAN_REVIEW did not check the send happened | Requires the entry's `used_at` (set by the PostToolUse hook) and a permalink matching `^https://[\w-]+\.slack\.com/archives/` | `09c0485` |
| R2-14 | Guard writes not committed | The PostToolUse hook commits `delivery/` (board rendered, `.gitattributes`/`.gitignore` ensured); `turnstile status` lists uncommitted changes in `delivery/` | `09c0485` |

Still open (not in this round's scope, unchanged from "Spec rules still not enforced"): signature check of every
commit (reconcile checks the head only), evidence that REWORK replies were posted, "stacked or merged into the story
branch" at IN_PROGRESS, and `cases.fail` against the story's bugs.
