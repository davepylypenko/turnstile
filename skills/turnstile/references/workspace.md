# Workspaces — `start`, `init`, `attach`, `repo add`, the registry, `--delivery`

The **clone root** is the folder that holds the clones side by side (`pdffiller-knowledge/`, `jsfiller/`, …). An epic's **workspace** is
`<root>/<key-lower>/`: the knowledge worktree on `epic/<key>` (holding `context/workitems/<workitem>/delivery/`), one worktree per
`epic.repos` clone on the parking branch `ws/<key-lower>` (cut from `origin/<base>` after a fetch; agents cut ticket branches from
`origin/<base>` or the story branch, never from `ws/*`), `.turnstile` (→ the delivery dir), the workspace `CLAUDE.md` and the
git-ignored `delivery/.workspace.json` (this machine's absolute paths and `member`; `state.json` keeps only `epic.repos.<r>.path`).

## `turnstile start <KEY>`

Run from the root, the knowledge clone, any repo clone under the root or an existing workspace (a workspace walks up to its root through
`.workspace.json`). Every flag is optional: `--clone-root`, `--knowledge` (when the clone is not `<root>/pdffiller-knowledge`), `--workitem`,
`--github`, `--name`, `--variant`, `--desk`, `--board-url`, `--chat-language`, `--jira-base-url`, `--story-mode stack|trunk`, `--flag`, `--no-push`.

1. `<root>/<key-lower>` already holds this epic → the attach refresh (member entry updated from the flags passed), then `status`.
2. Else `git ls-remote --heads origin epic/<key>` in the knowledge clone: the branch exists → `attach`; it does not → `init` with derived values:
   `lead_github` = `gh api user --jq .login`, `lead` = `gh api user --jq .name` or the login, `github_org` = the owner in the knowledge clone's
   origin URL, `agent_github` = the login, `variant` = `<key-lower>-<login-lower>`, `chat_language` = the user config key (`turnstile config set
   chat_language=uk`) else `English`; the **workitem** is the folder under `context/workitems/` on `origin/main` whose name contains the key or
   whose top-level `*.md` mention it as a whole word — exactly one; several → `MISSING several workitems mention <KEY>: a, b — pass --workitem
   <name>`; none → `MISSING no workitem folder under context/workitems mentions <KEY>; create one (…) or pass --workitem <name>`.
   `init` creates the workspace with the knowledge worktree only (`epic.repos = {}`); repos come with `repo add`.
3. Both paths register the workspace (below), set it as the root's active epic and end with `OK start <KEY>` plus one `NEXT:` line:
   new epic → `NEXT: kickoff — read the workitem docs per references/kickoff.md, add each repo with turnstile repo add, write delivery/plan.md,
   then turnstile plan-submitted`; existing → `NEXT: turnstile status`. Nothing says `cd`: the session that ran `start` drives the epic.

## `turnstile repo add '<json>'`

JSON keys as `init --repo`: `name, base, slack` required; `epic_branch` (default the base), `gate`, `gate_check` (`null` for a skill gate),
`ci_ignore`, `copilot`, `branch_prefix`, `path` (the clone when it is not `<root>/<name>`). It validates, clones a missing `<root>/<name>` with
`gh repo clone <org>/<name>` (`CLONE:` line), creates `<workspace>/<name>` on `ws/<key-lower>`, writes `epic.repos.<name>` through the normal
writer (ledger, board, commit, push), updates `.workspace.json` and the repo lines of the workspace `CLAUDE.md`. A name that exists is refused
(`turnstile repo set <name> key=value …` edits it). `plan-submitted` refuses a story whose `repos` names a repo missing from `epic.repos`:
`MISSING story S1 names repo x — run: turnstile repo add '{"name":"x","base":"main","slack":"…"}'`.

## `turnstile init` and `turnstile attach` (the flag-level commands `start` drives)

`turnstile init --epic <KEY> --workitem <slug> --lead <name> --lead-github <login> --github-org <org> [--repo '<json>']… [--knowledge <clone>]
[--clone-root <dir>] [--workspace <dir>] [--variant <v>] [--desk <d>] [--board-url <url>] [--chat-language <l>] [--agent-github <login>]
[--jira-base-url <url>] [--story-mode stack|trunk] [--flag <name>] [--models '<json>'] [--knowledge-base main] [--no-push]`: the workspace, the
knowledge worktree cut from `origin/<knowledge-base>`, a worktree per `--repo` (a missing clone is refused with its expected path; `init` with
no `--repo` is fine), `delivery/` (`state.json`, `plan.md` from `references/plan.md`, `decisions.md`, `ledger.md`, `briefs/`, `reports/`,
`evidence/`), `.turnstile`, `CLAUDE.md`, `.workspace.json`; commits and pushes `epic/<key>`. A non-empty folder that is not this epic's workspace
is refused; one that already is attaches. It prints `WORKSPACE`, `WORKTREE`, `REPO:` lines, `DELIVERY`, `CLAUDE_MD`, `SYNC:`, `CONFIG:`, `SEND_SKILL:`.

`turnstile attach --epic <KEY> [--knowledge] [--clone-root] [--workspace] [--workitem] [--chat-language] [--github <login>] [--name] [--variant]
[--desk] [--board-url] [--no-push]`: fetches `origin/epic/<key>`, adds the knowledge worktree (fast-forwarded; behind origin → `WARN … turnstile
sync`), finds the delivery dir (`--workitem` when the branch holds several), a `ws/<key>` worktree per `epic.repos` clone, `.turnstile`,
`.workspace.json`, `CLAUDE.md` (an existing foreign one is kept; `CLAUDE.md.turnstile` is written), writes `epic.members.<login>` (variant default
`<key-lower>-<login-lower>`; attaching again updates only the flags passed), prints `MEMBER: <login> · variant <v> · desk <d|none> · board <url|new
artifact>`, `OK attach <KEY>` and `status`. No `NEXT:` lines.

## The registry and how a delivery is found

`~/.config/turnstile/workspaces.json` (next to the user config; `$TURNSTILE_USER_CONFIG`'s directory when that is set):
`{"epics": {"<KEY>": {"workspace", "clone_root", "delivery"}}, "active": {"<clone_root>": "<KEY>"}}`. Written by `init`, `attach`, `start`
(which also sets `active`) and by any command that resolves a delivery through a `.turnstile` marker and finds it unregistered. Only
`turnstile` commands write under `~/.config/turnstile/`: the Bash guard refuses shell writes there everywhere (rule `user-config-write`).

Resolution order of every command and hook: `--delivery <dir>` → the `.turnstile` marker walking up from the cwd (hooks: from
`CLAUDE_PROJECT_DIR` first, then the Bash cwd) → `$TURNSTILE_EPIC=<KEY>` → the registry entries whose `clone_root` is the cwd or an ancestor
of it (one → it; several → `active[<root>]`, else `MISSING several epics in <root>: KEY1, KEY2 — run turnstile start <KEY>`). Nothing →
`MISSING no .turnstile found … run turnstile start <KEY> or pass --delivery <dir>`; `status` alone prints `NO EPIC: say "start epic <KEY>" —
known here: <keys registered for this root, or none>` and exits 2. The hooks are active wherever that resolution finds a workspace, so a
session in the clone root or in any clone under it is guarded like one opened in the workspace folder; the workspace `CLAUDE.md` stays for
people who do open Claude there.
