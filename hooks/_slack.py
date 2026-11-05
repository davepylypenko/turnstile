"""Shared by post_slack.py (PostToolUse: records a Slack send). Slack sends are gated by the lead's word in chat only."""
import re

PR_RX = re.compile(r"github\.com/[^/\s]+/([^/\s]+)/pull/(\d+)|\b([a-z0-9-]+)#(\d+)\b", re.I)

def prs_in(text: str):
    out = set()
    for m in PR_RX.finditer(text or ""):
        repo, n = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        out.add("%s#%s" % (repo, n))
    return out

def open_send_entry(data: dict, pid: str):
    for a in data.get("awaiting_human") or []:
        if (isinstance(a, dict) and a.get("type") == "send" and a.get("pr") == pid
                and not a.get("used_at") and not a.get("consumed_at") and not a.get("voided_at")):
            return a
    return None

def message_text(ti: dict) -> str:
    return ti.get("text") or ti.get("message") or ""

def channel_of(ti: dict) -> str:
    return ti.get("channel_id") or ti.get("channel") or ""
