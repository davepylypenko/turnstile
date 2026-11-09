# Publishing the board

`render-board` and every `pass` write `delivery/board.html` (everything) and `delivery/boards/<login>.html` per member, and print `BOARD: publish <delivery>/boards/<login>.html → <url>` for the current member. The artifact read that a
publish needs is large, so it never runs in the orchestrator: publish at most once per batch of passes, through one `haiku` subagent
(`Agent` tool, `model: "haiku"`, no `subagent_type`) whose prompt carries the `<path>` and `<url>` of the last `BOARD:` line and these steps:

1. `Artifact` with `action: "read"` and `url: <url>` (the first publish of a board also loads the `artifact-capabilities` skill and declares `db` + `user`).
2. `Artifact` with `file_path: <path>` and `url: <url>` (publish; on a conflict re-read and publish again, never `force`).
3. Reply with one line: `OK <url>` or the refusal text.

The orchestrator does not read the artifact and does not wait on the reply before the next step.
