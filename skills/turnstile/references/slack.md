# Slack messages

Channels come from `state.json` (`epic.repos.<repo>.slack`); the guard refuses any other channel. Reviewer logins come
from the PR (`gh pr view <n> --repo <org>/<repo> --json reviewRequests --jq '.reviewRequests[].login'`, people only — skip
team entries); resolve a login to a Slack user through the Slack MCP user search by name/email; never guess. Every message
is composed, shown to the lead, and sent only through the real send tool after the lead approved the entry
(`! TURNSTILE_LEAD=1 turnstile approve <ah-id>`) and confirmed the send in the UI. One approval = one message.

## Review request (front repos)

```
Reviewers: <@USER_ID_1> <@USER_ID_2>
PR: <https://github.com/<org>/<repo>/pull/<n>>
Task description: <PR title with the conventional prefix stripped>
Estimate review: +<additions>-<deletions>
```

- Wrap every URL in angle brackets (Slack's auto-linker otherwise swallows the newline).
- A front PR and its paired locales PR go in **one** message with a `Locales: <url>` line under `PR:`; the estimate sums
  both; the locales PR is a `--companions` entry of the main PR's `send`.
- One repo per message; several repos → consecutive messages, each with its own approved entry.
- Search the channel for the PR URL first; if a request exists, reply in that thread instead.

## Review request (backend / bare link channels)

```
<https://github.com/<org>/<repo>/pull/<n>>
```

## Reply drafts (human threads; written by comments-handler, posted on GitHub by the lead, announced in Slack with the `reply` entry)

```
<thread id> — <reviewer>: <one-line restatement of the point>
→ <what was done / why not>, commit `<sha>` (or: declined because <code-level reason>)
```

## Story report to the lead (after `pass story <S> DONE`)

```
Story <S> "<title>": integration review clean (<r> rounds, reports/STORY-<S>-review.md), env test <pass>/<total> cases
in the final full run, Figma parity pass (reports/ENV-<S>.md), bugs: <n> found, all done. Units ready to send:
<unit → PRs>. Pending your word: <ah-ids>.
```
