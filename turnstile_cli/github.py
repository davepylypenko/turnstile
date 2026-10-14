import datetime, json, re, subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .errors import TurnstileError
from .rules import same_head

BOT = "copilot-pull-request-reviewer"
BOT_LOGINS = {BOT, "Snyk-Agent", "application-pdffiller"}
QUERY = """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ pullRequest(number:$n){
  isDraft merged mergeCommit{oid} headRefOid baseRefName reviewDecision body
  allCommits: commits(last:100){totalCount nodes{commit{oid message signature{isValid}}}}
  latestReviews(first:30){nodes{author{__typename login} state commit{oid} submittedAt}}
  reviewRequests(first:50){nodes{requestedReviewer{__typename ... on User{login}}}}
  timelineItems(last:50, itemTypes:[REVIEW_REQUESTED_EVENT]){nodes{... on ReviewRequestedEvent{createdAt requestedReviewer{__typename ... on User{login}}}}}
  reviewThreads(first:100){nodes{id isResolved comments(first:100){totalCount nodes{databaseId author{__typename login} createdAt}}}}
  commits(last:1){nodes{commit{oid signature{isValid} statusCheckRollup{state contexts(first:100){totalCount nodes{
    ... on CheckRun{name conclusion status completedAt} ... on StatusContext{context state createdAt}}}}}}} } } }"""
TRAILER_RX = re.compile(r"Co-Authored-By|Generated with \[Claude Code\]", re.I)
FOOTER_RX = re.compile(r"Generated with \[Claude Code\]", re.I)

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
    changes_requested_heads: Dict[str, str] = field(default_factory=dict)  # login -> the commit the CHANGES_REQUESTED review was on
    human_threads_open: int = 0
    copilot_threads_open: int = 0
    head_signed: Optional[bool] = None
    base: Optional[str] = None
    unsigned: List[str] = field(default_factory=list)  # every commit of the PR without a valid signature (spec §3 DEV DoD)
    # {id, resolved, human, opened_at, author, comment_id (REST id of the top-level comment), comment_ids, truncated,
    #  comments: [{id, login, at, bot}], replies: [{login, at}] (comments after the first)}
    threads: List[dict] = field(default_factory=list)
    trailered: List[str] = field(default_factory=list)  # commits whose message carries a trailer or the generated-with footer
    body_footer: bool = False
    # re-request rule (2026-10-14): who is requested now, when each user was last requested, every human's latest review head,
    # Copilot's latest review (head + time) and when each check context last completed
    review_requests: List[str] = field(default_factory=list)
    review_requested_at: Dict[str, str] = field(default_factory=dict)
    review_heads: Dict[str, str] = field(default_factory=dict)
    copilot_review_head: Optional[str] = None
    copilot_review_at: Optional[str] = None
    check_times: Dict[str, str] = field(default_factory=dict)

    def ci_without(self, names) -> str:
        """CI over the check contexts minus the repo gate's own contexts (the gate runs in AI_REVIEW, so it cannot be part of
        the CI that AI_REVIEW requires). Falls back to the rollup when the context list is truncated or holds nothing else."""
        rest = [v for k, v in self.checks.items() if k not in set(names or [])]
        if not self.checks_complete or not rest:
            return self.ci
        return "failure" if "failure" in rest else "pending" if "pending" in rest else "success"

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

def ts(s: Optional[str]) -> Optional[datetime.datetime]:
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ"):
        try:
            return datetime.datetime.strptime(s or "", fmt)
        except ValueError:
            continue
    return None

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
    check_times: Dict[str, str] = {}
    contexts = rollup.get("contexts") or {}
    nodes = contexts.get("nodes") or []
    for c in nodes:
        if "name" in c:
            name, value, at = c["name"], c.get("conclusion") or c.get("status"), c.get("completedAt")
        elif "context" in c:
            name, value, at = c["context"], c.get("state"), c.get("createdAt")
        else:
            continue
        v = _norm(value)
        if RANK[v] >= RANK.get(checks.get(name, "skipped"), 0):
            checks[name] = v
        if at and (ts(at) or datetime.datetime.min) > (ts(check_times.get(name)) or datetime.datetime.min):
            check_times[name] = at
    total = contexts.get("totalCount")
    checks_complete = total is None or total <= len(nodes)
    head = pr.get("headRefOid") or ""
    approvals, changes, changes_heads, review_heads = [], [], {}, {}
    copilot_head = copilot_at = None
    for r in (pr.get("latestReviews") or {}).get("nodes") or []:
        login = (r.get("author") or {}).get("login", "")
        oid = (r.get("commit") or {}).get("oid")
        if login == BOT:
            copilot_head, copilot_at = oid, r.get("submittedAt")
        if is_bot(r.get("author")):
            continue
        review_heads[login] = oid or ""
        if r.get("state") == "APPROVED" and same_head(oid, head):
            approvals.append(login)
        if r.get("state") == "CHANGES_REQUESTED":
            changes.append(login); changes_heads[login] = oid or ""
    human_open = copilot_open = 0
    threads = []
    for t in (pr.get("reviewThreads") or {}).get("nodes") or []:
        conn = t.get("comments") or {}
        comments = conn.get("nodes") or [{}]
        first = comments[0]; author = first.get("author") or {}
        human = author.get("login") != BOT and not is_bot(author)
        cs = [{"id": str(c["databaseId"]) if c.get("databaseId") is not None else None, "login": (c.get("author") or {}).get("login") or "",
               "at": c.get("createdAt") or "", "bot": is_bot(c.get("author"))} for c in comments]
        total = conn.get("totalCount")
        threads.append({"id": t.get("id"), "resolved": bool(t.get("isResolved")), "human": human, "opened_at": first.get("createdAt") or "",
                        "author": author.get("login") or "", "comment_id": cs[0]["id"], "comment_ids": [c["id"] for c in cs if c["id"]],
                        "comments": cs, "truncated": bool(total is not None and total > len(comments)),
                        "replies": [{"login": c["login"], "at": c["at"]} for c in cs[1:]]})
        if t.get("isResolved"):
            continue
        if author.get("login") == BOT:
            copilot_open += 1
        elif human:
            human_open += 1
    sig = last.get("signature")
    unsigned = [((n.get("commit") or {}).get("oid") or "")[:12] for n in (pr.get("allCommits") or {}).get("nodes") or []
                if not ((n.get("commit") or {}).get("signature") or {}).get("isValid")]
    trailered = [((n.get("commit") or {}).get("oid") or "")[:8] for n in (pr.get("allCommits") or {}).get("nodes") or []
                 if TRAILER_RX.search((n.get("commit") or {}).get("message") or "")]
    requests = sorted({(n.get("requestedReviewer") or {}).get("login") for n in (pr.get("reviewRequests") or {}).get("nodes") or []
                       if (n.get("requestedReviewer") or {}).get("__typename") == "User" and (n.get("requestedReviewer") or {}).get("login")})
    requested_at: Dict[str, str] = {}
    for n in (pr.get("timelineItems") or {}).get("nodes") or []:
        who = n.get("requestedReviewer") or {}
        if who.get("__typename") == "User" and who.get("login") and (ts(n.get("createdAt")) or datetime.datetime.min) > (ts(requested_at.get(who["login"])) or datetime.datetime.min):
            requested_at[who["login"]] = n.get("createdAt")
    return PrFacts(review_requests=requests, review_requested_at=requested_at, review_heads=review_heads, copilot_review_head=copilot_head,
                   copilot_review_at=copilot_at, check_times=check_times, threads=threads, trailered=trailered, body_footer=bool(FOOTER_RX.search(pr.get("body") or "")),
                   base=pr.get("baseRefName"), unsigned=unsigned, id=pr_id, head=head, merged=bool(pr.get("merged")),
                   merged_sha=(pr.get("mergeCommit") or {}).get("oid"), draft=bool(pr.get("isDraft")), ci=ci, checks=checks,
                   checks_complete=checks_complete, approvals=sorted(approvals), changes_requested=sorted(changes), changes_requested_heads=changes_heads,
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

NODE_QUERY = "query($id:ID!){ node(id:$id){ ... on PullRequestReviewThread { comments(first:1){ nodes{ author{__typename login} } } } } }"

def thread_author(thread_id: str) -> dict:
    """The author of a review thread's first comment ({__typename, login}); the Bash guard asks it before a resolve."""
    out = subprocess.run(["gh", "api", "graphql", "-f", "query=" + NODE_QUERY, "-f", "id=" + thread_id], capture_output=True, text=True)
    if out.returncode != 0:
        raise TurnstileError("gh api failed for thread %s: %s" % (thread_id, out.stderr.strip()[:200]))
    node = (json.loads(out.stdout).get("data") or {}).get("node") or {}
    nodes = (node.get("comments") or {}).get("nodes") or []
    if not nodes:
        raise TurnstileError("review thread %s not found on GitHub" % thread_id)
    return nodes[0].get("author") or {}
