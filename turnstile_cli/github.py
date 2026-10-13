import json, subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .errors import TurnstileError

BOT = "copilot-pull-request-reviewer"
QUERY = """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ pullRequest(number:$n){
  isDraft merged mergeCommit{oid} headRefOid reviewDecision
  latestReviews(first:30){nodes{author{login} state}}
  reviewThreads(first:100){nodes{isResolved comments(first:1){nodes{author{login}}}}}
  commits(last:1){nodes{commit{statusCheckRollup{state contexts(first:50){nodes{
    ... on CheckRun{name conclusion status} ... on StatusContext{context state}}}}}}} } } }"""

@dataclass
class PrFacts:
    id: str
    head: str
    merged: bool
    merged_sha: Optional[str]
    draft: bool
    ci: str
    checks: Dict[str, str] = field(default_factory=dict)
    approvals: List[str] = field(default_factory=list)
    changes_requested: List[str] = field(default_factory=list)
    human_threads_open: int = 0
    copilot_threads_open: int = 0

def _low(x: Optional[str]) -> str:
    return (x or "unknown").lower()

def parse(pr_id: str, pr: dict) -> PrFacts:
    rollup = ((pr.get("commits") or {}).get("nodes") or [{}])[0].get("commit", {}).get("statusCheckRollup") or {}
    ci = {"success": "success", "failure": "failure", "error": "failure", "pending": "pending", "expected": "pending"}.get(_low(rollup.get("state")), "unknown")
    checks: Dict[str, str] = {}
    for c in (rollup.get("contexts") or {}).get("nodes") or []:
        if "name" in c:
            checks[c["name"]] = _low(c.get("conclusion") or c.get("status"))
        elif "context" in c:
            checks[c["context"]] = _low(c.get("state"))
    approvals, changes = [], []
    for r in (pr.get("latestReviews") or {}).get("nodes") or []:
        login = (r.get("author") or {}).get("login", "")
        if login.endswith("[bot]") or login == BOT or login == "Snyk-Agent":
            continue
        if r.get("state") == "APPROVED": approvals.append(login)
        if r.get("state") == "CHANGES_REQUESTED": changes.append(login)
    human_open = copilot_open = 0
    for t in (pr.get("reviewThreads") or {}).get("nodes") or []:
        if t.get("isResolved"): continue
        first = ((t.get("comments") or {}).get("nodes") or [{}])[0]
        if ((first.get("author") or {}).get("login")) == BOT: copilot_open += 1
        else: human_open += 1
    return PrFacts(id=pr_id, head=pr.get("headRefOid") or "", merged=bool(pr.get("merged")),
                   merged_sha=(pr.get("mergeCommit") or {}).get("oid"), draft=bool(pr.get("isDraft")), ci=ci, checks=checks,
                   approvals=sorted(approvals), changes_requested=sorted(changes),
                   human_threads_open=human_open, copilot_threads_open=copilot_open)

def fetch(pr_id: str, org: str) -> PrFacts:
    repo, num = pr_id.split("#", 1)
    out = subprocess.run(["gh", "api", "graphql", "-f", "query=" + QUERY, "-f", "o=" + org, "-f", "r=" + repo, "-F", "n=" + num],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise TurnstileError("gh api failed for %s: %s" % (pr_id, out.stderr.strip()[:200]))
    pr = json.loads(out.stdout)["data"]["repository"]["pullRequest"]
    return parse(pr_id, pr)
