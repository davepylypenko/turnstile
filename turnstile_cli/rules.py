import re
from typing import Dict, List, Optional

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
LEAD_RX = re.compile(r"\blead\b", re.I)

def valid_head(h: Optional[str]) -> bool:
    return bool(h) and bool(HEAD_RX.match(h.lower()))

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

def check_pr(pr: dict, target: str, repo_cfg: dict, prs: Dict[str, dict], reason: Optional[str] = None,
             awaiting: Optional[List[dict]] = None) -> List[str]:
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
    if target == "ON_HUMAN_REVIEW":
        _head_verified(pr, out)
        _ai_review_done(pr, repo_cfg, out)
        h = _ev(pr, "human") or {}
        if not h.get("slack_permalink"):
            out.append("MISSING evidence.human.slack_permalink")
        if not same_head(h.get("sent_head"), pr.get("head")):
            out.append("MISSING evidence.human.sent_head == current head")
        check_approved_entry(h.get("approved"), "reply" if src == "REWORK" else "send", "pr", pr.get("_id"), awaiting, out)
        b = pr.get("blocked_by")
        if b and (prs.get(b) or {}).get("state") != "MERGED":
            out.append("MISSING blocked_by %s to be MERGED before sending (is %s)" % (b, (prs.get(b) or {}).get("state")))
        return out
    if target == "APPROVED":
        h = _ev(pr, "human") or {}
        if not same_head(h.get("sent_head"), pr.get("head")):
            out.append("MISSING evidence.human.sent_head == current head (push after send → REWORK)")
        if not h.get("approvals"):
            out.append("MISSING evidence.human.approvals (at least one)")
        if h.get("open_threads", 1) != 0:
            out.append("MISSING evidence.human.open_threads == 0 (has %s)" % h.get("open_threads"))
        return out
    if target == "MERGED":
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
        return "fix, re-run gate/copilot on the new head, draft replies, get the lead's word, then pass ON_HUMAN_REVIEW"
    if s == "APPROVED":
        return "wait for the lead to merge"
    return "done"

STORY_FROM = {
    "PLANNED": [],
    "IN_PROGRESS": ["PLANNED", "INTEGRATION_REVIEW", "ENV_TESTING", "DONE"],
    "INTEGRATION_REVIEW": ["IN_PROGRESS", "ENV_TESTING"],
    "ENV_TESTING": ["INTEGRATION_REVIEW"],
    "DONE": ["ENV_TESTING"],
}
PR_AT_LEAST_READY = ["READY", "ON_HUMAN_REVIEW", "REWORK", "APPROVED", "MERGED"]

def is_lead_override(reason: Optional[str]) -> bool:
    return bool(reason) and bool(LEAD_RX.search(reason))

def startable(story: dict, stories: Dict[str, dict]) -> bool:
    return story.get("state") == "PLANNED" and all((stories.get(d) or {}).get("state") == "DONE" for d in story.get("after") or [])

def _prs_at_least_ready(story: dict, prs: Dict[str, dict], out: List[str]) -> None:
    for pid, p in prs.items():
        if p.get("story") == story.get("_id") and p.get("state") not in PR_AT_LEAST_READY:
            out.append("MISSING PR %s at least READY (is %s)" % (pid, p.get("state")))

def _review_head_bound(story: dict, out: List[str]) -> None:
    ev = story.get("evidence") or {}
    ir, dp = ev.get("integration_review") or {}, ev.get("deploy") or {}
    if not ir.get("clean") or not ir.get("head"):
        out.append("MISSING evidence.integration_review.clean with head")
    elif not same_head(ir.get("head"), dp.get("head")):
        out.append("MISSING evidence.integration_review.head == evidence.deploy.head (%s vs %s)" % (ir.get("head"), dp.get("head")))

def check_story(story: dict, target: str, prs: Dict[str, dict], stories: Dict[str, dict], reason: Optional[str] = None,
                bugs: Optional[List[dict]] = None, awaiting: Optional[List[dict]] = None, approved: Optional[str] = None) -> List[str]:
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
        override = is_lead_override(reason)
        if reason and not override:
            out.append("MISSING --reason naming the lead's override (contains 'lead'), or an approved start_story entry")
        for dep in story.get("after") or []:
            if (stories.get(dep) or {}).get("state") != "DONE" and not override:
                out.append("MISSING story %s to be DONE first (or --reason with the lead's override)" % dep)
        if not override:
            entry = next((a for a in awaiting or [] if a.get("type") == "start_story" and a.get("story") == sid), None)
            check_approved_entry(approved or (entry or {}).get("id"), "start_story", "story", sid, awaiting, out)
        return out
    if target == "INTEGRATION_REVIEW":
        _prs_at_least_ready(story, prs, out)
        dp = (story.get("evidence") or {}).get("deploy") or {}
        if not dp.get("build"):
            out.append("MISSING evidence.deploy.build (stack top deployed to the story env slot)")
        if not dp.get("head"):
            out.append("MISSING evidence.deploy.head (stack-top sha that was deployed; pass --head)")
        return out
    if target == "ENV_TESTING":
        _prs_at_least_ready(story, prs, out)
        _review_head_bound(story, out)
        return out
    if target == "DONE":
        _prs_at_least_ready(story, prs, out)
        _review_head_bound(story, out)
        et = (story.get("evidence") or {}).get("env_test") or {}
        cases = et.get("cases") or {}
        if not et.get("report"):
            out.append("MISSING evidence.env_test.report")
        if "fail" not in cases:
            out.append("MISSING evidence.env_test.cases.fail (explicit count from the tester report)")
        elif cases.get("fail") != 0:
            out.append("MISSING evidence.env_test.cases.fail == 0 (has %s)" % cases.get("fail"))
        if et.get("figma_parity") != "pass":
            out.append("MISSING evidence.env_test.figma_parity == pass (has %s)" % et.get("figma_parity"))
        for b in bugs or []:
            if b.get("story") == sid and b.get("state") != "done":
                out.append("MISSING bug %s to be done (is %s)" % (b.get("id"), b.get("state")))
        entry = next((a for a in awaiting or [] if a.get("type") == "story_done" and a.get("story") == sid), None)
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
