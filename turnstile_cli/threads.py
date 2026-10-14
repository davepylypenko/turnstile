"""Human review threads (lead rule 2026-10-14): a reviewer thread the agent resolved itself — fixed in code or answered with a
code-level justification — is `self_resolved` and gets the agent's reply at once, with no awaiting entry; a thread that needs
the lead's decision or involvement is `needs_lead` and its reply waits for a lead-approved `reply` entry of its own.

The classification is recorded on the PR (`prs.<id>.threads.<thread id>`) by `turnstile threads`, from GitHub facts, and is
bound to the reviewer's last comment it judged (`last_reviewer_at`): a later reviewer comment needs a new classification
before anyone replies again. REWORK → ON_HUMAN_REVIEW requires, for every human thread opened since the send and every
unresolved one, a reply on GitHub newer than the thread's last reviewer comment (`replies_missing`)."""
import datetime, pathlib
from typing import Callable, Dict, List, Optional, Tuple
from . import github, rules, state as st_mod
from .errors import TurnstileError

SELF, LEAD = "self_resolved", "needs_lead"
LEAD_HINT = "the lead types `! TURNSTILE_LEAD=1 turnstile approve %s` in the Claude Code prompt"
_MIN = datetime.datetime.min

def _ts(s: Optional[str]) -> datetime.datetime:
    return github.ts(s) or _MIN

def logins(roles: Optional[dict]) -> Tuple[str, str]:
    """(agent, lead): the GitHub login the agents post as (`epic.roles.agent_github`, default the lead's) and the lead's."""
    roles = roles or {}
    lead = roles.get("lead_github") or ""
    return (roles.get("agent_github") or lead), lead

def reviewer_comments(t: dict, ours) -> List[dict]:
    return [c for c in t.get("comments") or [] if not c.get("bot") and c.get("login") and c.get("login") not in ours]

def last_reviewer_at(t: dict, ours) -> Optional[str]:
    rc = reviewer_comments(t, ours)
    return max(rc, key=lambda c: _ts(c.get("at"))).get("at") if rc else None

def send_since(pr: dict, awaiting: Optional[List[dict]]) -> Optional[datetime.datetime]:
    """When the PR went to humans: the earlier of `evidence.human.sent_at` and the send entry's `used_at` (the Slack send)."""
    h = (pr.get("evidence") or {}).get("human") or {}
    e = rules.find_entry(awaiting, h.get("approved")) if h.get("approved") else None
    times = [x for x in (github.ts(h.get("sent_at")), github.ts((e or {}).get("used_at"))) if x]
    return min(times) if times else None

def in_scope(t: dict, since: Optional[datetime.datetime], ours) -> bool:
    """A human thread with a reviewer comment that is unresolved or was opened since the send (the same minute counts)."""
    if not t.get("human") or not reviewer_comments(t, ours):
        return False
    return not t.get("resolved") or (since is not None and _ts(t.get("opened_at")) >= since)

def _open(a: dict) -> bool:
    return not a.get("voided_at") and not a.get("consumed_at")

def approved_reply(awaiting: Optional[List[dict]], pid: str, tid: str) -> Optional[dict]:
    for a in reversed(awaiting or []):
        if a.get("type") == "reply" and a.get("pr") == pid and a.get("thread") == tid and a.get("approved_at") and _open(a):
            return a
    return None

def open_replies(awaiting: Optional[List[dict]], pid: str, tid: str) -> List[dict]:
    return [a for a in awaiting or [] if a.get("type") == "reply" and a.get("pr") == pid and a.get("thread") == tid and _open(a)]

def reply_route(org: str, pid: str, comment_id) -> str:
    repo, n = pid.split("#", 1)
    return "gh api -X POST repos/%s/%s/pulls/%s/comments/%s/replies -f body=…" % (org or "<org>", repo, n, comment_id or "<comment id>")

def _thread_missing(pid: str, pr: dict, t: dict, agent: str, lead: str, awaiting, org: str) -> Optional[str]:
    ours = {agent, lead} - {""}
    tid, lr = t.get("id"), last_reviewer_at(t, ours)
    if t.get("truncated"):
        return "MISSING thread %s has more than 100 comments; the facts are truncated, so its replies are verified by hand (the lead decides)" % tid
    rec = (pr.get("threads") or {}).get(tid)
    if rec is None:
        return ("MISSING classification of thread %s (opened by %s at %s): the comments-handler records it with turnstile threads %s "
                "--self-resolved %s or --needs-lead %s" % (tid, t.get("author"), t.get("opened_at"), pid, tid, tid))
    if _ts(lr) > _ts(rec.get("last_reviewer_at")):
        return ("MISSING re-classification of thread %s: the reviewer commented at %s, after it was classified %s on %s (turnstile threads %s …)"
                % (tid, lr, rec.get("class"), rec.get("last_reviewer_at"), pid))
    replies = [c for c in t.get("comments") or [] if c.get("login") in ours and _ts(c.get("at")) > _ts(lr)]
    if rec.get("class") == SELF:
        if not replies:
            return ("MISSING reply by %s on self_resolved thread %s newer than the reviewer's last comment (%s): post it now with %s"
                    % (agent, tid, lr, reply_route(org, pid, rec.get("comment_id") or t.get("comment_id"))))
        return None
    if lead and lead != agent and any(c.get("login") == lead for c in replies):
        return None  # the lead answered in person
    e = approved_reply(awaiting, pid, tid)
    if e is None:
        pending = open_replies(awaiting, pid, tid)
        ah = pending[-1]["id"] if pending else None
        return ("MISSING the lead's word on needs_lead thread %s: %s, then the approved reply goes out (%s)"
                % (tid, LEAD_HINT % ah if ah else "no reply entry is open; record the thread with turnstile threads %s --needs-lead %s" % (pid, tid),
                   reply_route(org, pid, rec.get("comment_id"))))
    if not any(_ts(c.get("at")) >= _ts(e.get("approved_at")) for c in replies):
        return ("MISSING reply on needs_lead thread %s after the lead approved %s at %s (newer than the reviewer's last comment %s): %s"
                % (tid, e.get("id"), e.get("approved_at"), lr, reply_route(org, pid, rec.get("comment_id"))))
    return None

def replies_missing(pr: dict, pid: str, facts_threads: List[dict], roles: Optional[dict], awaiting: Optional[List[dict]], org: str) -> List[str]:
    """Spec §3 REWORK DoD after 2026-10-14: every human thread opened since the send, and every unresolved one, has a reply
    newer than its last reviewer comment — from the agent for self_resolved threads, after the lead's approved `reply`
    entry (or from the lead in person) for needs_lead ones. Fails closed without logins or a send time."""
    agent, lead = logins(roles)
    if not agent:
        return ["MISSING epic.roles.agent_github or epic.roles.lead_github (the GitHub login the replies come from)"]
    since = send_since(pr, awaiting)
    out = [] if since else ["MISSING a parsable evidence.human.sent_at (has %r): the send time bounds the threads that need replies"
                            % ((pr.get("evidence") or {}).get("human") or {}).get("sent_at")]
    ours = {agent, lead} - {""}
    for t in facts_threads or []:
        if in_scope(t, since, ours):
            m = _thread_missing(pid, pr, t, agent, lead, awaiting, org)
            if m:
                out.append(m)
    return out

def classification_for_comment(pr: dict, comment_id: str) -> Tuple[Optional[str], Optional[dict]]:
    for tid, rec in (pr.get("threads") or {}).items():
        if str(comment_id) == str(rec.get("comment_id")) or str(comment_id) in [str(x) for x in rec.get("comment_ids") or []]:
            return tid, rec
    return None, None

def reply_refusal(data: dict, org: str, repo: str, number: str, comment_id: str, live_threads: Callable[[str], List[dict]]) -> Optional[str]:
    """The Bash guard's verdict on `POST repos/<org>/<repo>/pulls/<n>/comments/<id>/replies`: None to allow, else the refusal.
    State first (the PR is the epic's and in REWORK; the thread is classified; a needs_lead thread has the lead's approved entry),
    then GitHub (no reviewer comment newer than the classification). `live_threads(pid)` returns the facts' threads."""
    epic = data.get("epic") or {}
    pid = "%s#%s" % (repo, number)
    pr = (data.get("prs") or {}).get(pid)
    if (org or "").lower() != (epic.get("github_org") or "").lower() or pr is None:
        return ("blocked by rule reply-unknown-pr. %s/%s#%s is not a PR of this epic (state.json); replies go only to the epic's review threads."
                % (org, repo, number))
    if pr.get("state") != "REWORK":
        return ("blocked by rule reply-not-rework. %s is %s: thread replies are posted while the PR is in REWORK (turnstile status proposes the "
                "REWORK pass for a new human thread)." % (pid, pr.get("state")))
    tid, rec = classification_for_comment(pr, comment_id)
    if rec is None:
        return ("blocked by rule reply-unclassified. Comment %s is not in a classified thread of %s: record it first with turnstile threads %s "
                "--self-resolved <thread id> (fixed or justified in code) or --needs-lead <thread id> (needs the lead's decision)." % (comment_id, pid, pid))
    if rec.get("class") == LEAD:
        e = approved_reply(data.get("awaiting_human"), pid, tid)
        if e is None:
            pending = open_replies(data.get("awaiting_human"), pid, tid)
            ah = pending[-1]["id"] if pending else "<ah-id>"
            return ("blocked by rule reply-needs-lead. Thread %s of %s needs the lead (needs_lead): its reply waits for the lead's approval of %s — %s. "
                    "Show the lead the draft reply; never run that line." % (tid, pid, ah, LEAD_HINT % ah))
        if e.get("last_reviewer_at") and e.get("last_reviewer_at") != rec.get("last_reviewer_at"):
            return ("blocked by rule reply-needs-lead. %s was approved for thread %s as of the reviewer's comment at %s, not the current "
                    "classification (%s): re-classify and get the lead's word again." % (e.get("id"), tid, e.get("last_reviewer_at"), rec.get("last_reviewer_at")))
    try:
        live = live_threads(pid)
    except Exception as e:
        return "blocked by rule reply-unverified. Cannot read thread %s of %s on GitHub (%s); failing closed." % (tid, pid, e)
    t = next((x for x in live or [] if x.get("id") == tid), None)
    if t is None:
        return "blocked by rule reply-unverified. Thread %s of %s is not on GitHub; failing closed." % (tid, pid)
    agent, lead = logins(epic.get("roles"))
    lr = last_reviewer_at(t, {agent, lead} - {""})
    if _ts(lr) > _ts(rec.get("last_reviewer_at")):
        return ("blocked by rule reply-reclassify. The reviewer commented on thread %s at %s, after it was classified %s (%s): re-classify it with "
                "turnstile threads %s before replying — a pushback may need the lead." % (tid, lr, rec.get("class"), rec.get("last_reviewer_at"), pid))
    return None

def _ids(text: Optional[str]) -> List[str]:
    return [x.strip() for x in (text or "").split(",") if x.strip()]

def _find(facts_threads: List[dict], ident: str) -> Optional[dict]:
    for t in facts_threads or []:
        if ident == t.get("id") or ident in (t.get("comment_ids") or []):
            return t
    return None

def _now_s() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def run(delivery, pid: str, self_resolved: Optional[str], needs_lead: Optional[str], report: Optional[str] = None, io=None,
        no_commit: bool = False) -> int:
    """`turnstile threads <pr> --self-resolved <ids> --needs-lead <ids> [--report reports/COMMENTS-<n>.md]`. Ids are GitHub review
    thread ids (PRRT_…) or the REST id of a comment in the thread. Without ids it lists the classification and writes nothing."""
    from . import pass_cmd
    io = io or pass_cmd.IO(); delivery = pathlib.Path(delivery)
    sids, lids = _ids(self_resolved), _ids(needs_lead)
    try:
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json"); data = st.data
            pr = st_mod.pr(st, pid); org = rules.require_org(data)
            agent, lead = logins((data.get("epic") or {}).get("roles"))
            ours = {agent, lead} - {""}
            awaiting = data.setdefault("awaiting_human", [])
            facts = io.github_facts(pid, org)
            if not sids and not lids:
                since = send_since(pr, awaiting)
                for t in facts.threads:
                    if not in_scope(t, since, ours):
                        continue
                    rec = (pr.get("threads") or {}).get(t.get("id"))
                    stale = rec and _ts(last_reviewer_at(t, ours)) > _ts(rec.get("last_reviewer_at"))
                    print("%s %s · %s · comment %s · last reviewer comment %s" % (t.get("id"), (rec or {}).get("class", "unclassified")
                          + (" (stale: re-classify)" if stale else ""), t.get("author"), t.get("comment_id"), last_reviewer_at(t, ours)))
                print("OK threads %s: listed, nothing written" % pid); return 0
            if pr.get("state") != "REWORK":
                raise TurnstileError("threads are classified while the PR is in REWORK (%s is %s); pass REWORK first" % (pid, pr.get("state")))
            if report and not (delivery / report).is_file():
                raise TurnstileError("report file %s not found under %s" % (report, delivery))
            both = sorted(set(sids) & set(lids))
            if both:
                raise TurnstileError("thread id(s) %s listed as both --self-resolved and --needs-lead" % ", ".join(both))
            picked: Dict[str, Tuple[str, dict]] = {}
            for cls, ids in ((SELF, sids), (LEAD, lids)):
                for ident in ids:
                    t = _find(facts.threads, ident)
                    if t is None:
                        raise TurnstileError("%s is not a review thread (or a comment of one) of %s on GitHub" % (ident, pid))
                    if not t.get("human"):
                        raise TurnstileError("%s is a Copilot/bot thread of %s: fix or justify, then resolve it; it is not classified" % (ident, pid))
                    if not reviewer_comments(t, ours):
                        raise TurnstileError("%s of %s has no reviewer comment (only %s): nothing to classify" % (ident, pid, ", ".join(sorted(ours))))
                    if t["id"] in picked and picked[t["id"]][0] != cls:
                        raise TurnstileError("thread %s listed as both --self-resolved and --needs-lead (via %s)" % (t["id"], ident))
                    picked[t["id"]] = (cls, t)
            now = _now_s(); recs = pr.setdefault("threads", {}); extra: List[str] = []; asks: List[str] = []; replies_now: List[str] = []
            for tid, (cls, t) in picked.items():
                lr = last_reviewer_at(t, ours)
                rc = reviewer_comments(t, ours)
                recs[tid] = {"class": cls, "classified_at": now, "comment_id": t.get("comment_id"), "comment_ids": t.get("comment_ids") or [],
                             "reviewer": rc[0].get("login"), "last_reviewer_at": lr, "report": report}
                keep = []
                for a in open_replies(awaiting, pid, tid):
                    if cls == LEAD and a.get("last_reviewer_at") == lr:
                        keep.append(a); continue
                    a["voided_at"] = pass_cmd._now()
                    extra.append("voided %s (reply for %s thread %s: classified %s as of %s)" % (a["id"], pid, tid, cls, lr))
                if cls == LEAD:
                    e = keep[-1] if keep else pass_cmd._open_entry(data, "reply", pr=pid, thread=tid, comment_id=t.get("comment_id"),
                                                                   last_reviewer_at=lr, head=pr.get("head"), payload=report)
                    if not keep:
                        extra.append("opened %s (reply for %s thread %s, needs_lead)" % (e["id"], pid, tid))
                    asks.append("LEAD: %s — thread %s needs the lead; %s, then the approved reply goes out" % (e["id"], tid, LEAD_HINT % e["id"]))
                else:
                    replies_now.append("REPLY NOW: thread %s — %s" % (tid, reply_route(org, pid, t.get("comment_id"))))
            summary = "threads %s: self_resolved %s; needs_lead %s" % (pid, ", ".join(sorted(t for t, (c, _) in picked.items() if c == SELF)) or "none",
                                                                       ", ".join(sorted(t for t, (c, _) in picked.items() if c == LEAD)) or "none")
            pending = [m for m in replies_missing(pr, pid, facts.threads, (data.get("epic") or {}).get("roles"), awaiting, org)
                       if m.startswith("MISSING classification") or m.startswith("MISSING re-classification")]
            pass_cmd._recompute_next_actions(data)
            pass_cmd._side_effects(delivery, st, [summary] + extra, io, no_commit)
        for line in replies_now + asks:
            print(line)
        for m in pending:
            print("WARN " + m[len("MISSING "):])
        url = ((data.get("epic") or {}).get("board") or {}).get("artifact_url")
        print("BOARD: publish %s → %s" % (delivery / "board.html", url or "new artifact"))
        print("OK " + summary)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
