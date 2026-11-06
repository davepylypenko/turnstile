# 2026-11-06 — 0.4.3 review trail (Opus xhigh) and the follow-up list

Commits reviewed: 3801c7c (send skill as a resolved name, default `/send-pr-review`), 836bf85 (board Progress tab),
4e720b0 (0.4.3); fixes 64da71e, 2ca6af7. Full review of d04d186..4e720b0: 0 P1, 3 P2 (re-plan dropped `state_since`;
`skill_path` raised on unreadable dirs / deleted cwd; persisted hints carried the user-layer skill name and a broken user
file blocked every writer), 8 P3; all three P2s and most P3s fixed before the tag. Delta review of the fixes: 0 P1, 0 P2.
Decisions: the send skill is referenced by name, never vendored (Davyd 06.11); the Progress tab is a snapshot, no history;
Jira status names stay hard-coded. Verdict: tag 0.4.3. Open P3s:

1. A broken user config file stops `status`, `attach`, `init` (exit 2 after the workspace is written and pushed) and
   `config apply` (writes the epic change, then exits 2). Add `config.user_or_warn()` (WARN + ignore the user layer) at
   `reconcile.py` status, `init_cmd.py`, `attach_cmd.py` and the final print of `config apply`; keep `config list`,
   user-layer `config set` and `brief` strict. One test: status and apply with a broken file exit 0 with the WARN.
2. Single-module test runs skip the package patch in `tests/__init__.py` (`discover -s tests -p test_init.py` reads the
   real user file). Document `python3 -m unittest discover -s tests -t .` or `import tests` in `test_init` / `test_pass`.
3. `CLAUDE_CONFIG_DIR=~unknownuser/x` raises `RuntimeError` from `Path.expanduser()` in `config.skill_path`; use
   `os.path.expanduser`.
4. The plugin-cache lookup sorts versions alphabetically and picks the oldest cached version; prefer the newest or read
   `plugins/installed_plugins.json`.
5. README says the plugin lookup searches "at any depth below the version folder"; it is up to four folders.
6. Nits: `_recompute_next_actions` in `config set --epic` is a no-op (the value changes at apply); `SKILL_RX` with `$`
   lets `"/x\n"` through (`fullmatch` / `\Z`); `attach`'s NEXT line does not ask about the send skill.
7. From the 0.4.2 list, still open: SKILL.md byte cap, hash deep links on the real claude.ai artifact, JS-run board tests,
   `jira_unsynced` placement vs the head-drift check. The 0.4.1 list (7 P3s) is also still open.
