import json, subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .errors import TurnstileError
from .rules import same_head

BOT = "copilot-pull-request-reviewer"
BOT_LOGINS = {BOT, "Snyk-Agent", "application-pdffiller"}
QUERY = """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ pullRequest(number:$n){
  isDraft merged mergeCommit{oid} headRefOid reviewDecision
  latestReviews(first:30){nodes{author{__typename login} state commit{oid}}}
  reviewThreads(first:100){nodes{isResolved comments(first:1){nodes{author{__typename login}}}}}
  commits(last:1){nodes{commit{oid signature{isValid} statusCheckRollup{state contexts(first:100){totalCount nodes{
    ... on CheckRun{name conclusion status} ... on StatusContext{context state}}}}}}} } } }"""

FAILURE = {"failure", "cancelled", "timed_out", "action_required", "error", "startup_failure", "stale"}
PENDING = {"pending", "in_progress", "queued", "expected", "waiting", "requested", "none"}
RANK = {"failure": 3, "pending": 2, "success": 1, "skipped": 0}

@dataclass
class PrFacts:
    id: str
    head: str
    merged: bool
    merged_sha: Optional[str]
    draft: bool
    ci: str
    checks: Dict[str, str] = field(default_factory=dict)
    checks_complete: bool = True
    approvals: List[str] = field(default_factory=list)
    changes_requested: List[str] = field(default_factory=list)
    human_threads_open: int = 0
    copilot_threads_open: int = 0
    head_signed: Optional[bool] = None

def _low(x: Optional[str]) -> str:
    return (x or "unknown").lower()

def _norm(value: str) -> str:
    v = _low(value)
    if v == "success":
        return "success"
    if v in FAILURE:
        return "failure"
    if v in PENDING:
        return "pending"
    if v in ("skipped", "neutral"):
        return "skipped"
    return "pending"

def is_bot(author: Optional[dict]) -> bool:
    a = author or {}
    login = a.get("login") or ""
    return (a.get("__typename") == "Bot" or login.endswith("[bot]") or login in BOT_LOGINS
            or login.lower().startswith("sonarqube"))

def parse(pr_id: str, pr: dict) -> PrFacts:
    last = ((pr.get("commits") or {}).get("nodes") or [{}])[0].get("commit") or {}
    rollup = last.get("statusCheckRollup") or {}
    ci = {"success": "success", "failure": "failure", "error": "failure", "pending": "pending", "expected": "pending"}.get(_low(rollup.get("state")), "unknown")
    checks: Dict[str, str] = {}
    contexts = rollup.get("contexts") or {}
    nodes = contexts.get("nodes") or []
    for c in nodes:
        if "name" in c:
            name, value = c["name"], c.get("conclusion") or c.get("status")
        elif "context" in c:
            name, value = c["context"], c.get("state")
        else:
            continue
        v = _norm(value)
        if RANK[v] >= RANK.get(checks.get(name, "skipped"), 0):
            checks[name] = v
    total = contexts.get("totalCount")
    checks_complete = total is None or total <= len(nodes)
    head = pr.get("headRefOid") or ""
    approvals, changes = [], []
    for r in (pr.get("latestReviews") or {}).get("nodes") or []:
        if is_bot(r.get("author")):
            continue
        login = (r.get("author") or {}).get("login", "")
        oid = (r.get("commit") or {}).get("oid")
        if r.get("state") == "APPROVED" and same_head(oid, head):
            approvals.append(login)
        if r.get("state") == "CHANGES_REQUESTED":
            changes.append(login)
    human_open = copilot_open = 0
    for t in (pr.get("reviewThreads") or {}).get("nodes") or []:
        if t.get("isResolved"):
            continue
        first = ((t.get("comments") or {}).get("nodes") or [{}])[0]
        author = first.get("author") or {}
        if author.get("login") == BOT:
            copilot_open += 1
        elif not is_bot(author):
            human_open += 1
    sig = last.get("signature")
    return PrFacts(id=pr_id, head=head, merged=bool(pr.get("merged")),
                   merged_sha=(pr.get("mergeCommit") or {}).get("oid"), draft=bool(pr.get("isDraft")), ci=ci, checks=checks,
                   checks_complete=checks_complete, approvals=sorted(approvals), changes_requested=sorted(changes),
                   human_threads_open=human_open, copilot_threads_open=copilot_open,
                   head_signed=(bool(sig.get("isValid")) if isinstance(sig, dict) else None))

def fetch(pr_id: str, org: str) -> PrFacts:
    repo, num = pr_id.split("#", 1)
    out = subprocess.run(["gh", "api", "graphql", "-f", "query=" + QUERY, "-f", "o=" + org, "-f", "r=" + repo, "-F", "n=" + num],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise TurnstileError("gh api failed for %s: %s" % (pr_id, out.stderr.strip()[:200]))
    pr = json.loads(out.stdout)["data"]["repository"]["pullRequest"]
    return parse(pr_id, pr)
