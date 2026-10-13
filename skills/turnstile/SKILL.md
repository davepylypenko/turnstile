---
name: turnstile
description: Evidence-gated delivery of a multi-repo epic. Use for every PR or story state change (`turnstile pass`), the session-start drift check (`turnstile status`), and whenever something awaits the lead's word. Stub; the full skill lands with plan 2.
---

# Turnstile (stub)

The orchestrator never changes `state.json` by hand and never performs the lead's actions.

- **Every transition** is one `turnstile pass …` call (see `README.md`, "Usage"). It validates the evidence for the
  current head, writes the ledger, renders the board and commits `delivery/`.
- **Session start:** `turnstile status` — reconcile against GitHub, where we are, what awaits humans.
- **The lead's word.** `awaiting_human` entries (`send`, `reply`, `merge`, `start_story`, `story_done`) are approved
  **only by the lead**, who types the command themself in the Claude Code prompt with the `!` prefix:

  ```
  ! TURNSTILE_LEAD=1 turnstile approve ah-3
  ```

  The orchestrator asks the lead to run exactly that line and waits. It **never** runs `turnstile approve`, never
  sets `TURNSTILE_LEAD` or `TURNSTILE_MIGRATION`, never wraps them in `env`, `bash -c`, a heredoc or a script: the
  Bash hook refuses every such command, and an approval that did not come from the lead's terminal is not an approval
  (`turnstile reconcile` flags it as `approval_unlogged`).
- **Slack, merges, reviewer requests, "ready for review"** stay with the lead; the hooks block them without an
  approved entry.

Design spec: `docs/superpowers/specs/2026-10-13-turnstile-design.md`.
