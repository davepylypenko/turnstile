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

def usable(entry: dict, pid: str, prs: dict) -> bool:
    return (entry.get("pr") == pid and entry.get("type") in STATE_FOR_TYPE and bool(entry.get("approved_at"))
            and not entry.get("used_at") and not entry.get("consumed_at") and not entry.get("voided_at")
            and prs.get(pid, {}).get("state") == STATE_FOR_TYPE[entry["type"]])

def choose(data: dict, ids, channel: str) -> dict:
    """pid -> the approved, unused send/reply entry that allows this message; blocks (exit 2) when any PR lacks one."""
    prs, repos = data["prs"], data["epic"]["repos"]
    awaiting = data.get("awaiting_human", [])
    chosen = {}
    for pid in sorted(ids):
        want = repos[pid.split("#", 1)[0]].get("slack")
        if not want or channel != want:
            block("channel %s is not the review channel of %s (%s); nothing sent." % (channel or "?", pid, want or "unset"))
        used = [a for a in awaiting if a.get("pr") == pid and a.get("type") in STATE_FOR_TYPE and a.get("approved_at") and a.get("used_at")]
        entry = next((a for a in awaiting if usable(a, pid, prs)), None)
        if entry is None:
            hint = " (%s already used at %s: one send per approval)" % (used[-1]["id"], used[-1]["used_at"]) if used else ""
            block("no usable (approved, unused) send/reply for %s in awaiting_human (state %s)%s. %s"
                  % (pid, prs.get(pid, {}).get("state"), hint, LEAD_HINT))
        chosen[pid] = entry
    return chosen

def message_text(ti: dict) -> str:
    return ti.get("text") or ti.get("message") or ""

def channel_of(ti: dict) -> str:
    return ti.get("channel_id") or ti.get("channel") or ""
