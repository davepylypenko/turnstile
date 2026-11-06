# 2026-11-06 — 0.4.2 review trail (Opus xhigh) and the follow-up list

Commits reviewed: 1d93d30 (Jira assignee on take-up), 1d93063 (board status tiles as filters, hash deep links), 207a87f
(0.4.2), then 97cfc9d (fixes) and fb7feb3 (help text). One review round on 1fbb2d1..207a87f: 0 P1, 2 P2, 10 P3; both P2s
and eight of the P3s were fixed in 97cfc9d before the tag. Decision taken for P2 #2: the plugin never takes over a ticket
somebody already holds in Jira; on upgrade the orchestrator records the holder instead of replacing them.
Verdict: tag 0.4.2. Open P3s for a follow-up:

1. `tests/test_skill_files.py` caps `SKILL.md` at 190 lines; the § pass lines are now 200-300 characters long, so the cap
   no longer limits size. Add a byte cap or tighten the text.
2. Hash deep links (`#tab=prs&state=REWORK`) are verified in a plain browser and under the artifact skeleton, not on the
   real claude.ai artifact: `replaceState` changes the frame URL, not the address bar, so a copied link may carry no
   hash. Check on the published board before telling anyone shared links work.
3. The board tests only check template strings; the behaviour is verified by hand in a headless browser. A JS runner
   (node + jsdom or Playwright) would pin the tile filter, the bugs overlay under the filter and the hash parsing.
4. `jira_unsynced` is now emitted even when the PR head changed on GitHub (moved before the head-drift `continue`),
   which is right for Jira but differs from the other evidence checks; decide whether those should follow.

Earlier open list (0.4.1): `docs/superpowers/reviews/2026-11-05-slack-ungate-xhigh-review.md`, all seven still open.
