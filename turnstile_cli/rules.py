import re
from typing import Dict, List, Optional
from .errors import TurnstileError

PR_STATES = ["DEV", "AI_REVIEW", "READY", "ON_HUMAN_REVIEW", "REWORK", "APPROVED", "MERGED"]
STORY_STATES = ["PLANNED", "IN_PROGRESS", "INTEGRATION_REVIEW", "ENV_TESTING", "DONE"]
JIRA_FOR_PR_STATE = {"DEV": "In progress", "AI_REVIEW": "In progress", "READY": "In progress",
                     "ON_HUMAN_REVIEW": "On Review", "REWORK": "On Review", "APPROVED": "On Review",
                     "MERGED": "On Hold"}

# target -> allowed sources. AI_REVIEW re-enters itself: a push is a new head and the old evidence is void.
PR_FROM = {
    "DEV": ["AI_REVIEW", "REWORK"],
    "AI_REVIEW": ["DEV", "AI_REVIEW", "REWORK", "READY"],
    "READY": ["AI_REVIEW"],
    "ON_HUMAN_REVIEW": ["READY", "REWORK"],
    "REWORK": ["ON_HUMAN_REVIEW", "APPROVED"],
    "APPROVED": ["ON_HUMAN_REVIEW"],
    "MERGED": ["APPROVED"],
}
HEAD_RX = re.compile(r"^[0-9a-f]{8,40}$")
SLACK_PERMALINK_RX = re.compile(r"^https://[\w-]+\.slack\.com/archives/")

def valid_head(h: Optional[str]) -> bool:
    return bool(h) and bool(HEAD_RX.match(h.lower()))

def require_org(data: dict) -> str:
    org = ((data.get("epic") or {}).get("github_org") or "").strip()
    if not org:
        raise TurnstileError("epic.github_org is not set; add it to state.json (turnstile init sets it)")
    return org

def same_head(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b or len(a) < 8 or len(b) < 8:
        return False
    a, b = a.lower(), b.lower()
    return a.startswith(b) if len(a) >= len(b) else b.startswith(a)

def _ev(pr: dict, key: str) -> Optional[dict]:
    return (pr.get("evidence") or {}).get(key)

def _need_head(pr: dict, key: str, out: List[str]) -> Optional[dict]:
    ev = _ev(pr, key)
    if ev is None:
        out.append("MISSING evidence.%s" % key)
        return None
    if not same_head(ev.get("head"), pr.get("head")):
        out.append("MISSING evidence.%s for current head %s (has %s)" % (key, pr.get("head"), ev.get("head")))
    return ev

def _head_verified(pr: dict, out: List[str]) -> None:
    hv = _ev(pr, "head_verified")
    if hv is None or not same_head(hv.get("head"), pr.get("head")):
        out.append("MISSING evidence.head_verified for current head %s (pass verifies it against GitHub; not with --offline)" % pr.get("head"))
    elif hv.get("verified") is not True:
        out.append("MISSING evidence.head_verified == true (last pass ran --offline; re-run online)")

def _ai_review_done(pr: dict, repo_cfg: dict, out: List[str]) -> None:
    ci = _need_head(pr, "ci", out)
    if ci and ci.get("status") != "success":
        out.append("MISSING evidence.ci.status == success (has %s)" % ci.get("status"))
    if not pr.get("rework_since"):  # deep review is not repeated after human review (spec §3)
        dr = _need_head(pr, "deep_review", out)
        if dr and not dr.get("clean"):
            out.append("MISSING evidence.deep_review.clean == true")
    gate_name = repo_cfg.get("gate")
    if gate_name:
        g = _need_head(pr, "gate", out)
        if g:
            if g.get("name") != gate_name:
                out.append("MISSING evidence.gate.name == %s (has %s)" % (gate_name, g.get("name")))
            if g.get("result") != "pass":
                out.append("MISSING evidence.gate.result == pass (has %s)" % g.get("result"))
    if repo_cfg.get("copilot"):
        c = _need_head(pr, "copilot", out)
        if c and c.get("open_threads", 1) != 0:
            out.append("MISSING evidence.copilot.open_threads == 0 (has %s)" % c.get("open_threads"))

def find_entry(awaiting: Optional[List[dict]], ah_id: Optional[str]) -> Optional[dict]:
    for a in awaiting or []:
        if a.get("id") == ah_id:
            return a
    return None

def latest_entry(awaiting: Optional[List[dict]], type_: str, key: str, ident: Optional[str]) -> Optional[dict]:
    """The newest awaiting_human entry of this type for this PR/story that is neither voided nor consumed (R2-6)."""
    for a in reversed(awaiting or []):
        if a.get("type") == type_ and a.get(key) == ident and not a.get("voided_at") and not a.get("consumed_at"):
            return a
    return None

def plan_approval_missing(data: dict, plan_digest: Optional[str]) -> Optional[str]:
    plan = (data.get("epic") or {}).get("plan") or {}
    if not plan.get("digest"):
        return "MISSING plan.md submitted and approved (turnstile plan-submitted; the lead approves the printed ah-id)"
    if plan_digest != plan.get("digest"):
        return "MISSING plan.md changed since it was submitted; run turnstile plan-submitted and get the lead's approval again"
    e = latest_entry(data.get("awaiting_human"), "plan", "payload", "plan.md")
    if e is None or not e.get("approved_at"):
        return "MISSING lead approval of plan.md (the lead types: ! TURNSTILE_LEAD=1 turnstile approve %s)" % ((e or {}).get("id") or "<ah-id from turnstile status>")
    if e.get("digest") and e.get("digest") != plan_digest:  # defence in depth: the entry was approved for another version of the plan
        return "MISSING plan approval for this plan.md: %s was approved for another version (digest %s…); run turnstile plan-submitted again" % (e.get("id"), str(e.get("digest"))[:12])
    return None

def check_approved_entry(ah_id: Optional[str], expected_type: str, key: str, ident: Optional[str],
                         awaiting: Optional[List[dict]], out: List[str]) -> Optional[dict]:
    """The lead's word for an action: an awaiting_human entry of the right type for this PR/story,
    approved by `turnstile approve` (never by pass), not yet consumed or voided."""
    if not ah_id:
        out.append("MISSING --approved <ah-id> (awaiting_human entry of type %s for %s approved by the lead)" % (expected_type, ident))
        return None
    e = find_entry(awaiting, ah_id)
    if e is None:
        out.append("MISSING awaiting_human entry %s (unknown id)" % ah_id)
        return None
    if e.get("type") != expected_type:
        out.append("MISSING awaiting_human %s of type %s (is %s)" % (ah_id, expected_type, e.get("type")))
    if e.get(key) != ident:
        out.append("MISSING awaiting_human %s for %s (is for %s)" % (ah_id, ident, e.get(key)))
    if e.get("voided_at"):
        out.append("MISSING awaiting_human %s not voided (voided at %s: the head changed after the lead's word)" % (ah_id, e.get("voided_at")))
    if e.get("consumed_at"):
        out.append("MISSING awaiting_human %s not consumed yet (consumed at %s)" % (ah_id, e.get("consumed_at")))
    if not e.get("approved_at"):
        out.append("MISSING awaiting_human %s (%s for %s) approved_at — the lead runs: TURNSTILE_LEAD=1 turnstile approve %s"
                   % (ah_id, expected_type, ident, ah_id))
    return e

def _story_gates_passed(pr: dict, stories: Optional[Dict[str, dict]], out: List[str], prs: Optional[Dict[str, dict]] = None) -> None:
    """Human review receives only stories that passed integration review and env testing (spec §1.4, §4.2). A lead-set
    `human_review: "per_pr"` on the story (recorded in plan.md) exempts a migrated/legacy story."""
    sid = pr.get("story")
    if not sid:
        return
    s = (stories or {}).get(sid)
    if s is None:
        out.append("MISSING story %s in state (the PR's story is unknown, so its gates cannot be verified)" % sid)
    elif s.get("state") != "DONE" and s.get("human_review") != "per_pr":
        out.append("MISSING story %s to be DONE (is %s): human review receives only stories that passed integration review and env testing "
                   "(lead-set human_review: per_pr in plan.md exempts a legacy story)" % (sid, s.get("state")))
    elif s.get("state") == "DONE" and s.get("human_review") != "per_pr":  # a push after DONE reaches humans untested otherwise
        _deploy_is_stack_top(dict(s, _id=sid), prs or {}, out)

def check_pr(pr: dict, target: str, repo_cfg: dict, prs: Dict[str, dict], reason: Optional[str] = None,
             awaiting: Optional[List[dict]] = None, stories: Optional[Dict[str, dict]] = None) -> List[str]:
    out: List[str] = []
    if target not in PR_STATES:
        return ["MISSING valid target state (one of %s)" % ", ".join(PR_STATES)]
    src = pr.get("state")
    if src not in PR_FROM[target]:
        return ["MISSING allowed transition: %s from %s (allowed from %s)" % (target, src, ", ".join(PR_FROM[target]))]
    if target == "DEV" or target == "REWORK":
        if not reason:
            out.append("MISSING --reason for %s" % target)
        return out
    if target == "AI_REVIEW":
        ci = _need_head(pr, "ci", out)
        if ci and ci.get("status") != "success":
            out.append("MISSING evidence.ci.status == success")
        return out
    if target == "READY":
        _head_verified(pr, out)
        _ai_review_done(pr, repo_cfg, out)
        return out
    if target == "ON_HUMAN_REVIEW" and src == "REWORK":
        # back to the same reviewers (lead rule 2026-10-14): gate + Copilot on the new head; the replies on every reviewer thread are
        # checked against GitHub by pass (threads.replies_missing); no Slack message and no blanket lead approval
        _head_verified(pr, out)
        _ai_review_done(pr, repo_cfg, out)
        if not (_ev(pr, "human") or {}).get("sent_at"):
            out.append("MISSING evidence.human.sent_at (the send this rework answers; the replies are counted from it)")
        b = pr.get("blocked_by")
        if b and (prs.get(b) or {}).get("state") != "MERGED":
            out.append("MISSING blocked_by %s to be MERGED before sending (is %s)" % (b, (prs.get(b) or {}).get("state")))
        return out
    if target == "ON_HUMAN_REVIEW":
        _head_verified(pr, out)
        _ai_review_done(pr, repo_cfg, out)
        h = _ev(pr, "human") or {}
        if not h.get("slack_permalink"):
            out.append("MISSING evidence.human.slack_permalink")
        elif not SLACK_PERMALINK_RX.match(h["slack_permalink"]):
            out.append("MISSING evidence.human.slack_permalink of the form https://<workspace>.slack.com/archives/… (has %s)" % h["slack_permalink"])
        if not same_head(h.get("sent_head"), pr.get("head")):
            out.append("MISSING evidence.human.sent_head == current head")
        _story_gates_passed(pr, stories, out, prs)
        e = check_approved_entry(h.get("approved"), "send", "pr", pr.get("_id"), awaiting, out)
        if e and not e.get("used_at"):
            out.append("MISSING awaiting_human %s used_at (no Slack message went through the guarded tool for it)" % e.get("id"))
        if e and e.get("type") == "send" and e.get("head") and not same_head(e.get("head"), pr.get("head")):
            out.append("MISSING awaiting_human %s approved for head %s, not the current head %s (re-run AI_REVIEW → READY)" % (e.get("id"), e.get("head"), pr.get("head")))
        b = pr.get("blocked_by")
        if b and (prs.get(b) or {}).get("state") != "MERGED":
            out.append("MISSING blocked_by %s to be MERGED before sending (is %s)" % (b, (prs.get(b) or {}).get("state")))
        return out
    if target == "APPROVED":
        _head_verified(pr, out)
        h = _ev(pr, "human") or {}
        if not same_head(h.get("sent_head"), pr.get("head")):
            out.append("MISSING evidence.human.sent_head == current head (push after send → REWORK)")
        if not h.get("approvals"):
            out.append("MISSING evidence.human.approvals (at least one)")
        if h.get("open_threads", 1) != 0:
            out.append("MISSING evidence.human.open_threads == 0 (has %s)" % h.get("open_threads"))
        return out
    if target == "MERGED":
        _head_verified(pr, out)
        if not pr.get("merged_sha"):
            out.append("MISSING merged_sha")
        return out
    return out

def next_action_pr(pr: dict, repo_cfg: dict) -> str:
    s = pr.get("state")
    if s == "DEV":
        return "open draft PR, get CI green, then pass AI_REVIEW"
    if s == "AI_REVIEW":
        missing = check_pr(pr, "READY", repo_cfg, {})
        if any("deep_review" in m for m in missing):
            return "run deep review (reviewer agent) on head %s" % pr.get("head")
        if any("gate" in m for m in missing):
            return "run repo gate %s on head %s" % (repo_cfg.get("gate"), pr.get("head"))
        if any("copilot" in m for m in missing):
            return "request Copilot review, close its threads"
        return "pass READY"
    if s == "READY":
        return "wait for the lead's word to send" + (" (blocked by %s)" % pr["blocked_by"] if pr.get("blocked_by") else "")
    if s == "ON_HUMAN_REVIEW":
        return "wait for human approval; reconcile for threads/pushes"
    if s == "REWORK":
        return ("fix and push; classify the reviewer threads (turnstile threads); reply to self_resolved ones at once; the lead approves each "
                "needs_lead reply; gate/copilot on the new head; then pass ON_HUMAN_REVIEW")
    if s == "APPROVED":
        return "wait for the lead to merge"
    return "done"

STORY_FROM = {
    "PLANNED": [],
    "IN_PROGRESS": ["PLANNED", "INTEGRATION_REVIEW", "ENV_TESTING", "DONE"],
    "INTEGRATION_REVIEW": ["IN_PROGRESS", "ENV_TESTING", "INTEGRATION_REVIEW"],  # re-entry records a redeploy after fixes
    "ENV_TESTING": ["INTEGRATION_REVIEW", "ENV_TESTING"],
    "DONE": ["ENV_TESTING"],
}
PR_AT_LEAST_READY = ["READY", "ON_HUMAN_REVIEW", "REWORK", "APPROVED", "MERGED"]

ACTIVE_STORY_STATES = ("IN_PROGRESS", "INTEGRATION_REVIEW", "ENV_TESTING")

def _parallel(a_id: str, a: dict, b_id: str, b: dict) -> bool:
    return b_id in (a.get("parallel_with") or []) or a_id in (b.get("parallel_with") or [])

def _start_blockers(sid: str, story: dict, stories: Dict[str, dict]) -> List[str]:
    """Spec §4.2 stop rule, 2026-10-14 finding 2: `after` stories must be DONE and an active story blocks the start unless
    the approved plan lists the two as `parallel_with` (either direction). No --reason override exists."""
    out = []
    for dep in story.get("after") or []:
        if (stories.get(dep) or {}).get("state") != "DONE":
            out.append("MISSING story %s to be DONE first (after: in plan.md; is %s)" % (dep, (stories.get(dep) or {}).get("state")))
    for oid, other in stories.items():
        if oid != sid and other.get("state") in ACTIVE_STORY_STATES and not _parallel(sid, story, oid, other):
            out.append("MISSING story %s to be DONE (is %s), or %s listed as parallel_with %s in the approved plan.md (edit plan.md, "
                       "turnstile plan-submitted, the lead approves again)" % (oid, other.get("state"), sid, oid))
    return out

def startable(story: dict, stories: Dict[str, dict], sid: Optional[str] = None) -> bool:
    return story.get("state") == "PLANNED" and not _start_blockers(sid or story.get("_id"), story, stories)

def _prs_at_least_ready(story: dict, prs: Dict[str, dict], out: List[str]) -> None:
    for pid, p in prs.items():
        if p.get("story") == story.get("_id") and p.get("state") not in PR_AT_LEAST_READY:
            out.append("MISSING PR %s at least READY (is %s)" % (pid, p.get("state")))

def _stacked_into_story_branch(story: dict, prs: Dict[str, dict], out: List[str]) -> None:
    """Spec §4.2 IN_PROGRESS DoD: every ticket PR of the story is stacked or merged into the story branch. A PR's base is
    the story branch or the branch of another PR of the same story (a stack); MERGED PRs are exempt."""
    sid = story.get("_id"); sb = story.get("branch")
    if not sb:
        out.append("MISSING stories.%s.branch (the story branch the ticket PRs stack into; set it in plan.md and re-run plan-submitted)" % sid)
        return
    mine = {pid: p for pid, p in prs.items() if p.get("story") == sid}
    for pid, p in mine.items():
        if p.get("state") == "MERGED":
            continue
        allowed = {sb} | {q.get("branch") for qid, q in mine.items() if qid != pid and q.get("branch")}
        if p.get("base") not in allowed:
            out.append("MISSING PR %s based on the story branch %s or on another PR of the story (base is %s)" % (pid, sb, p.get("base")))

def stack_tops(sid: str, prs: Dict[str, dict]) -> List[tuple]:
    """(pr id, head) of every open PR of the story that no other open PR of the story is based on: the stack top per repo.
    Empty when every PR is merged (the story branch is the top; not derivable from state)."""
    mine = {pid: p for pid, p in prs.items() if p.get("story") == sid and p.get("state") != "MERGED"}
    bases = {p.get("base") for p in mine.values()}
    return sorted((pid, p.get("head")) for pid, p in mine.items() if p.get("branch") not in bases)

def open_heads(sid: str, prs: Dict[str, dict]) -> Dict[str, str]:
    return {pid: p.get("head") for pid, p in prs.items() if p.get("story") == sid and p.get("state") != "MERGED"}

def _deploy_is_stack_top(story: dict, prs: Dict[str, dict], out: List[str]) -> None:
    """2026-10-14 finding 4: evidence.deploy.head must be the current stack top, else fixes made after the deploy are tested
    by nobody. Round 2: deploy.heads snapshots every open PR of the story (all repos) at the deploy; any later head change,
    in any repo, or a PR added since, voids the deploy."""
    sid = story.get("_id"); dp = (story.get("evidence") or {}).get("deploy") or {}
    snap = dp.get("heads")
    if isinstance(snap, dict):
        for pid, h in sorted(open_heads(sid, prs).items()):
            if not same_head(snap.get(pid), h):
                out.append("MISSING PR %s head %s to be the one deployed (deploy.heads has %s): redeploy and record it with pass story %s "
                           "INTEGRATION_REVIEW --build <n> --head <sha>" % (pid, h, snap.get(pid), sid))
    tops = stack_tops(sid, prs)
    if dp.get("head") and tops and not any(same_head(dp.get("head"), h) for _, h in tops):
        out.append("MISSING evidence.deploy.head %s to be the current stack top (%s): redeploy the stack top and record it with "
                   "pass story %s INTEGRATION_REVIEW --build <n> --head <sha>" % (dp.get("head"), ", ".join("%s %s" % x for x in tops), sid))

def _deploy_heads_verified(story: dict, out: List[str]) -> None:
    """Round 2 R2-7: DONE needs the deploy.heads snapshot and its confirmation on GitHub by an online story pass."""
    dp = (story.get("evidence") or {}).get("deploy") or {}
    if not isinstance(dp.get("heads"), dict):
        out.append("MISSING evidence.deploy.heads (the deploy predates the snapshot; re-record it: pass story %s INTEGRATION_REVIEW --build <n> --head <sha>)" % story.get("_id"))
    elif (dp.get("head_verified") or {}).get("verified") is not True:
        out.append("MISSING evidence.deploy.head_verified == true (every PR head in deploy.heads confirmed on GitHub by an online story pass, not --offline)")

def _run_bound_to_deploy(story: dict, out: List[str], label: str) -> None:
    ev = story.get("evidence") or {}
    run, dp = last_env_run(story) or {}, ev.get("deploy") or {}
    if not run.get("head") or not run.get("build"):
        out.append("MISSING %s.build and %s.head (every recorded run names the build and head it tested: --build --head)" % (label, label))
    elif not same_head(run.get("head"), dp.get("head")):
        out.append("MISSING %s.head == evidence.deploy.head (%s vs %s): the run tested a build the state does not know; record the redeploy "
                   "first (pass story %s INTEGRATION_REVIEW --build <n> --head <sha>), then a review round, then the run"
                   % (label, run.get("head"), dp.get("head"), story.get("_id")))

def _review_head_bound(story: dict, out: List[str]) -> None:
    ev = story.get("evidence") or {}
    ir, dp = ev.get("integration_review") or {}, ev.get("deploy") or {}
    if not ir.get("clean") or not ir.get("head"):
        out.append("MISSING evidence.integration_review.clean with head")
    elif not same_head(ir.get("head"), dp.get("head")):
        out.append("MISSING evidence.integration_review.head == evidence.deploy.head (%s vs %s)" % (ir.get("head"), dp.get("head")))

def last_env_run(story: dict) -> Optional[dict]:
    ev = story.get("evidence") or {}
    runs = ev.get("env_runs") or []
    return runs[-1] if runs else (ev.get("env_test") or None)

def _full_run_covers_every_case(story: dict, out: List[str]) -> None:
    """Round 2 R2-10: --full is not self-declared. A full run's pass + fail + not_testable_here equals the story's test-case
    count from the approved plan; a story without test cases cannot have a full run."""
    run = last_env_run(story) or {}
    if not run.get("full"):
        return
    cases = run.get("cases") or {}
    total = (cases.get("pass") or 0) + (cases.get("fail") or 0) + (cases.get("not_testable_here") or 0)
    n = len(story.get("test_cases") or [])
    if n == 0:
        out.append("MISSING stories.%s.test_cases (plan.md lists the story's cases; a --full run is measured against them)" % story.get("_id"))
    elif total != n:
        out.append("MISSING --full run to cover the story's %d test case%s: pass + fail + not_testable_here is %d (--cases-not-testable counts the "
                   "cases with verdict not_testable_here)" % (n, "" if n == 1 else "s", total))

def _fails_became_bugs(story: dict, bugs: Optional[List[dict]], out: List[str]) -> None:
    """Spec §4.2 ENV_TESTING DoD, 2026-10-14 finding 5: every failed case of the last run has a bug keyed by story + case id
    that is not done (new, still open, or reopened by the run record). The count must equal the list."""
    runs = (story.get("evidence") or {}).get("env_runs") or []
    if not runs:
        return
    last = runs[-1]; sid = story.get("_id")
    n = (last.get("cases") or {}).get("fail") or 0
    failed = last.get("failed_cases") or []
    if n != len(failed):
        out.append("MISSING --cases-fail %d to equal the number of --failed-cases ids (%d: %s)" % (n, len(failed), ", ".join(failed) or "none"))
    open_cases = {b.get("case") for b in bugs or [] if b.get("story") == sid and b.get("case") and b.get("state") != "done"}
    for case in failed:
        if case not in open_cases:
            out.append("MISSING a bug for failed case %s of %s (turnstile bug add --story %s --case %s --title … --source …; a done bug of the "
                       "same case is reopened when the run is recorded)" % (case, sid, sid, case))

def check_story(story: dict, target: str, prs: Dict[str, dict], stories: Dict[str, dict], reason: Optional[str] = None,
                bugs: Optional[List[dict]] = None, awaiting: Optional[List[dict]] = None, approved: Optional[str] = None,
                plan_missing: Optional[str] = None, recording_run: bool = False) -> List[str]:
    out: List[str] = []
    if target not in STORY_STATES:
        return ["MISSING valid target state (one of %s)" % ", ".join(STORY_STATES)]
    src = story.get("state")
    if src not in STORY_FROM[target]:
        return ["MISSING allowed transition: %s from %s" % (target, src)]
    sid = story.get("_id")
    if target == "IN_PROGRESS":
        if src != "PLANNED":
            if not reason:
                out.append("MISSING --reason to reopen a story")
            return out
        if plan_missing:  # spec §4.1: without the lead's plan approval no story leaves PLANNED
            out.append(plan_missing)
        out.extend(_start_blockers(sid, story, stories))
        entry = latest_entry(awaiting, "start_story", "story", sid)  # the lead's word, full stop: no --reason bypass (2026-10-14 finding 2)
        check_approved_entry(approved or (entry or {}).get("id"), "start_story", "story", sid, awaiting, out)
        return out
    if target == "INTEGRATION_REVIEW":
        _prs_at_least_ready(story, prs, out)
        _stacked_into_story_branch(story, prs, out)
        dp = (story.get("evidence") or {}).get("deploy") or {}
        if not dp.get("build"):
            out.append("MISSING evidence.deploy.build (stack top deployed to the story env slot)")
        if not dp.get("head"):
            out.append("MISSING evidence.deploy.head (stack-top sha that was deployed; pass --head)")
        _deploy_is_stack_top(story, prs, out)
        return out
    if target == "ENV_TESTING":
        _prs_at_least_ready(story, prs, out)
        _review_head_bound(story, out)
        _deploy_is_stack_top(story, prs, out)
        if recording_run:
            _run_bound_to_deploy(story, out, "env_runs[-1]")
            _full_run_covers_every_case(story, out)
        _fails_became_bugs(story, bugs, out)
        return out
    if target == "DONE":
        _prs_at_least_ready(story, prs, out)
        _review_head_bound(story, out)
        _deploy_is_stack_top(story, prs, out)
        _deploy_heads_verified(story, out)
        _run_bound_to_deploy(story, out, "env_test")
        et = last_env_run(story) or {}
        cases = et.get("cases") or {}
        if not et.get("report"):
            out.append("MISSING evidence.env_test.report")
        if "fail" not in cases:
            out.append("MISSING evidence.env_test.cases.fail (explicit count from the tester report)")
        elif cases.get("fail") != 0:
            out.append("MISSING evidence.env_test.cases.fail == 0 (has %s)" % cases.get("fail"))
        if et.get("figma_parity") != "pass":
            out.append("MISSING evidence.env_test.figma_parity == pass (has %s)" % et.get("figma_parity"))
        if not et.get("full"):
            out.append("MISSING evidence.env_runs[-1].full (DONE needs one full final run: pass story %s ENV_TESTING … --full)" % sid)
        _full_run_covers_every_case(story, out)
        for b in bugs or []:
            if b.get("story") == sid and b.get("state") != "done":
                out.append("MISSING bug %s to be done (is %s)" % (b.get("id"), b.get("state")))
        entry = latest_entry(awaiting, "story_done", "story", sid)
        check_approved_entry(approved or (entry or {}).get("id"), "story_done", "story", sid, awaiting, out)
        return out
    return out

def next_action_story(story: dict, prs: Dict[str, dict]) -> str:
    s = story.get("state")
    return {"PLANNED": "wait for the lead to start it",
            "IN_PROGRESS": "bring every PR to READY, deploy the stack top, then pass INTEGRATION_REVIEW",
            "INTEGRATION_REVIEW": "run the story-reviewer agent until clean, then pass ENV_TESTING",
            "ENV_TESTING": "run the tester agent; fix bugs; re-run; then pass DONE",
            "DONE": "wait for the lead's word to send the story's units to humans"}.get(s, "")
