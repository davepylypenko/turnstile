import re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload, block, load_state

PR_RX = re.compile(r"github\.com/[^/\s]+/([^/\s]+)/pull/(\d+)|\b([a-z0-9-]+)#(\d+)\b", re.I)

def prs_in(text: str):
    out = set()
    for m in PR_RX.finditer(text or ""):
        repo, n = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        out.add("%s#%s" % (repo, n))
    return out

def main():
    p = read_payload(); ti = p.get("tool_input") or {}
    text = ti.get("text") or ti.get("message") or ""
    ids = prs_in(text)
    if not ids:
        block("Slack sends must reference the PR they are about and be approved (no PR id found).")
    try:
        data = load_state(p.get("cwd") or ".")
    except Exception as e:
        block("cannot read the delivery state (%s); failing closed." % e)
    for pid in sorted(ids):
        ok = False
        for a in data.get("awaiting_human", []):
            if a.get("pr") == pid and a.get("type") in ("send", "reply") and a.get("approved_at"):
                if a["type"] == "reply" or (data.get("prs", {}).get(pid, {}).get("state") == "READY"):
                    ok = True
        if not ok:
            block("no approved send/reply for %s in awaiting_human (state %s). Get the lead's word, then: turnstile approve <ah-id>."
                  % (pid, data.get("prs", {}).get(pid, {}).get("state")))
    sys.exit(0)

if __name__ == "__main__":
    main()
