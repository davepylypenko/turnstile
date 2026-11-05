# Slack messages

Channels come from `state.json` (`epic.repos.<repo>.slack`). Reviewer logins come from the PR (`gh pr view <n> --repo
<org>/<repo> --json reviewRequests --jq '.reviewRequests[].login'`, people only — skip team entries); resolve a login to a
Slack user through the Slack MCP user search by name/email; never guess. Every message is composed, shown to the lead, and
sent only on the lead's word in chat — that word is the only gate (2026-11-05). The plugin records the send (a ledger line
from the PostToolUse hook, `evidence.human` via `pass pr … ON_HUMAN_REVIEW --slack <permalink> --reviewers …`); it never blocks,
asks or demands a command before it.

## Review request (front repos)

```
Reviewers: <@USER_ID_1> <@USER_ID_2>
PR: <https://github.com/<org>/<repo>/pull/<n>>
Task description: <PR title with the conventional prefix stripped>
Estimate review: +<additions>-<deletions>
```

- Wrap every URL in angle brackets (Slack's auto-linker otherwise swallows the newline).
- A front PR and its paired locales PR go in **one** message with a `Locales: <url>` line under `PR:`; the estimate sums
  both.
- One repo per message; several repos → consecutive messages, each on the lead's word.
- Search the channel for the PR URL first; if a request exists, reply in that thread instead.

## Review request (backend / bare link channels)

```
<https://github.com/<org>/<repo>/pull/<n>>
```

## Thread replies (GitHub review threads, not Slack; lead rule 2026-10-14)

Posted on the reviewer's own thread through `gh api -X POST repos/<org>/<repo>/pulls/<n>/comments/<top-level comment id>/replies
-f body=…`, never as an issue comment or a review. A `self_resolved` thread (fixed in code or answered with a code-level
justification) gets the comments-handler's reply at once; a `needs_lead` thread gets a draft in the report and is posted only
after the lead approved that thread's `reply` entry, word for word. The reply text:

```
<what changed> in `<sha>` (<file or test that shows it>)            ← fixed
Kept as is: <code-level reason, file:line or test>                  ← justified
```

The report lists each one as `<thread id> — <reviewer>: <one-line restatement> → <reply text>`. No Slack message goes with
them: GitHub notifies the reviewer. Once every thread has its reply and Copilot
reviewed the head with 0 open threads (repos without Copilot: the gate green), the thread authors are re-requested on GitHub
(`requested_reviewers`, lead rule 2026-10-14) — still no Slack. A push-only rework pings nobody; the lead decides.

## Story report to the lead (after `pass story <S> DONE`)

```
Story <S> "<title>": integration review clean (<r> rounds, reports/STORY-<S>-review.md), env test <pass>/<total> cases
in the final full run, Figma parity pass (reports/ENV-<S>.md), bugs: <n> found, all done. Units ready to send:
<unit → PRs>. Say the word and they go to review.
```
