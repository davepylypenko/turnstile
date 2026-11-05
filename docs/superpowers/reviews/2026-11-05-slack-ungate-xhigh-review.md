# 2026-11-05 — 0.4.1 review trail (Opus xhigh) and the follow-up list

Commits reviewed: 93d4dac + dd2781e (Slack guard removed, recorder), f85c5f2 (reviewers opus:xhigh, `/code-review xhigh`),
277d36a, 3c888ccf, 5508d322 (fixes from each round). Four rounds; every round's P1/P2 findings were fixed before the tag.
Verdict on 5508d322: tag 0.4.1. Open P3s for a follow-up:

1. `turnstile_cli/config.py` `is_frozen_set` keys on the current `models.DEFAULTS`: a fresh `init --models` naming every agent is
   misread as the pre-0.4.1 full set; adding a 9th agent would stop the rule for old epics. Hard-code the eight 0.4.0 agent names
   and have 0.4.1 writers set `epic.models_schema=2` to turn the rule off.
2. `config_cmd.py` `set_`/`apply` on an old full set: applying one `models.*` proposal marks every other pending `models.*`
   proposal stale. Compute `old` and the stale check on a copy with `drop_frozen_defaults` applied.
3. `state.py` `locked`: raise `LockHeld` only for EWOULDBLOCK/EAGAIN; re-raise other flock errors.
4. `hooks/post_slack.py`: a non-contention lock error is reported as "not acquired within Ns"; say "state lock failed (…)".
5. `config.py` "; effort = agent default" note depends on `effort: null` vs a missing key; base it on a non-null raw effort.
6. `tests/test_init.py:111` comment still says agent models live in `epic.models`.
7. Tests: crash-after-ts test should assert `hookSpecificOutput` too; `tests/test_state.py` lock tests should expect `LockHeld`.
