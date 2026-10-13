from typing import Dict, List, Optional

PR_STATES = ["DEV", "AI_REVIEW", "READY", "ON_HUMAN_REVIEW", "REWORK", "APPROVED", "MERGED"]
STORY_STATES = ["PLANNED", "IN_PROGRESS", "INTEGRATION_REVIEW", "ENV_TESTING", "DONE"]
JIRA_FOR_PR_STATE = {"DEV": "In progress", "AI_REVIEW": "In progress", "READY": "In progress",
                     "ON_HUMAN_REVIEW": "On Review", "REWORK": "On Review", "APPROVED": "On Review",
                     "MERGED": "On Hold"}

PR_FROM = {
    "DEV": ["AI_REVIEW", "REWORK"],
    "AI_REVIEW": ["DEV", "REWORK", "READY", "ON_HUMAN_REVIEW"],
    "READY": ["AI_REVIEW"],
    "ON_HUMAN_REVIEW": ["READY", "REWORK"],
    "REWORK": ["ON_HUMAN_REVIEW", "APPROVED"],
    "APPROVED": ["ON_HUMAN_REVIEW"],
    "MERGED": ["APPROVED", "ON_HUMAN_REVIEW"],
}

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

def _ai_review_done(pr: dict, repo_cfg: dict, out: List[str]) -> None:
    ci = _need_head(pr, "ci", out)
    if ci and ci.get("status") != "success":
        out.append("MISSING evidence.ci.status == success (has %s)" % ci.get("status"))
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

def check_pr(pr: dict, target: str, repo_cfg: dict, prs: Dict[str, dict], reason: Optional[str] = None) -> List[str]:
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
        _ai_review_done(pr, repo_cfg, out)
        return out
    if target == "ON_HUMAN_REVIEW":
        _ai_review_done(pr, repo_cfg, out)
        h = _ev(pr, "human") or {}
        if not h.get("slack_permalink"):
            out.append("MISSING evidence.human.slack_permalink")
        if not same_head(h.get("sent_head"), pr.get("head")):
            out.append("MISSING evidence.human.sent_head == current head")
        if not h.get("approved"):
            out.append("MISSING evidence.human.approved (awaiting_human id the lead approved)")
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
