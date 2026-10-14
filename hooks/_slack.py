"""Shared by guard_slack.py (PreToolUse: checks only) and post_slack.py (PostToolUse: records the send)."""
import re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import block

PR_RX = re.compile(r"github\.com/[^/\s]+/([^/\s]+)/pull/(\d+)|\b([a-z0-9-]+)#(\d+)\b", re.I)
STATE_FOR_TYPE = {"send": "READY", "reply": "REWORK"}
LEAD_HINT = "Get the lead's word; the lead runs `! TURNSTILE_LEAD=1 turnstile approve <ah-id>` in the Claude Code prompt."

def prs_in(text: str):
    out = set()
    for m in PR_RX.finditer(text or ""):
        repo, n = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        out.add("%s#%s" % (repo, n))
    return out

def story_ready(pid: str, prs: dict, stories: dict, org: str = None, live: bool = True) -> bool:
    """R3-3: a first send goes out only for a DONE story (or a lead-set human_review: per_pr), as pass requires."""
    sid = prs.get(pid, {}).get("story")
    s = (stories or {}).get(sid) or {}
    if not sid or s.get("human_review") == "per_pr":
        return True
    if s.get("state") != "DONE":
        return False
    from _common import plugin_root  # round 2: a push after DONE (deploy.heads / stack top no longer current) is not sent
    sys.path.insert(0, str(plugin_root())); from turnstile_cli import rules
    out = []; rules._deploy_is_stack_top(dict(s, _id=sid), prs, out)
    if out:
        return False
    snap = ((s.get("evidence") or {}).get("deploy") or {}).get("heads")
    if live and isinstance(snap, dict) and snap:  # round 2 R2-7: state.json may be stale after a push without `pass pr`; ask GitHub
        from turnstile_cli import github
        for p, h in sorted(snap.items()):
            try:
                head = github.fetch(p, org or "").head
            except Exception as e:
                block("cannot verify the deployed head of %s on GitHub (%s); nothing sent." % (p, e))
            if not rules.same_head(head, h):
                block("%s: PR %s head on GitHub is %s, the story's deploy has %s (a push without `pass pr`); human review receives only "
                      "stories tested on their current heads. Run turnstile status, pass pr %s AI_REVIEW --head %s, redeploy; nothing sent."
                      % (pid, p, (head or "")[:12], (h or "")[:12], p, (head or "")[:12]))
    return True

def usable(entry: dict, pid: str, prs: dict, stories: dict = None, org: str = None, live: bool = True) -> bool:
    return (entry.get("pr") == pid and entry.get("type") in STATE_FOR_TYPE and bool(entry.get("approved_at"))
            and not entry.get("used_at") and not entry.get("consumed_at") and not entry.get("voided_at")
            and prs.get(pid, {}).get("state") == STATE_FOR_TYPE[entry["type"]]
            and (entry["type"] != "send" or story_ready(pid, prs, stories, org, live)))

def choose(data: dict, ids, channel: str, live: bool = True) -> dict:
    """pid -> the approved, unused send/reply entry that allows this message; blocks (exit 2) when any PR lacks one.
    A PR listed in a chosen entry's `companions` (a paired locales PR, a repo outside epic.repos) needs no entry of
    its own (R2-12); every refusal names the id it is about. `live` asks GitHub for the deployed heads (PreToolUse);
    the PostToolUse record skips the network so a transient gh failure never leaves a sent message unrecorded."""
    prs, repos = data["prs"], data["epic"]["repos"]
    awaiting = data.get("awaiting_human", [])
    org = (data.get("epic") or {}).get("github_org") or ""
    chosen, companions = {}, set()
    for pid in sorted(ids):
        entry = next((a for a in awaiting if usable(a, pid, prs, data.get("stories"), org, live)), None)
        if entry is not None:
            chosen[pid] = entry; companions.update(entry.get("companions") or [])
    for pid in sorted(ids):
        if pid in chosen:
            want = repos.get(pid.split("#", 1)[0], {}).get("slack")
            if not want or channel != want:
                block("channel %s is not the review channel of %s (%s); nothing sent." % (channel or "?", pid, want or "unset"))
            continue
        if pid in companions:
            continue
        repo = pid.split("#", 1)[0]
        if repo not in repos:
            block("%s: repo %s is not in epic.repos. A paired PR goes into the send entry's companions "
                  "(turnstile pass pr <main> READY --companions %s); nothing sent." % (pid, repo, pid))
        used = [a for a in awaiting if a.get("pr") == pid and a.get("type") in STATE_FOR_TYPE and a.get("approved_at") and a.get("used_at")]
        hint = " (%s already used at %s: one send per approval)" % (used[-1]["id"], used[-1]["used_at"]) if used else ""
        if not story_ready(pid, prs, data.get("stories"), org, live):
            hint += (" (story %s is not DONE, or a PR head changed after its deploy: human review receives only stories that passed their "
                     "gates on the current heads)" % prs.get(pid, {}).get("story"))
        block("no usable (approved, unused) send/reply for %s in awaiting_human (state %s)%s. %s"
              % (pid, prs.get(pid, {}).get("state"), hint, LEAD_HINT))
    return chosen

def message_text(ti: dict) -> str:
    return ti.get("text") or ti.get("message") or ""

def channel_of(ti: dict) -> str:
    return ti.get("channel_id") or ti.get("channel") or ""
