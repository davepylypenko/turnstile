import datetime, re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload, block, delivery_dir, plugin_root

PR_RX = re.compile(r"github\.com/[^/\s]+/([^/\s]+)/pull/(\d+)|\b([a-z0-9-]+)#(\d+)\b", re.I)
STATE_FOR_TYPE = {"send": "READY", "reply": "REWORK"}

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

def main():
    p = read_payload(); ti = p.get("tool_input") or {}
    if not isinstance(ti, dict):
        block("malformed hook payload; failing closed.")
    text = ti.get("text") or ti.get("message") or ""
    channel = ti.get("channel_id") or ti.get("channel") or ""
    ids = prs_in(text)
    if not ids:
        block("Slack sends must reference the PR they are about and be approved (no PR id found).")
    try:
        delivery = delivery_dir(p.get("cwd") or ".")
        sys.path.insert(0, str(plugin_root()))
        from turnstile_cli import state as st_mod, ledger
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            data = st.data
            prs, repos = data["prs"], data["epic"]["repos"]
            chosen = {}
            for pid in sorted(ids):
                want = repos[pid.split("#", 1)[0]].get("slack")
                if not want or channel != want:
                    block("channel %s is not the review channel of %s (%s); nothing sent." % (channel or "?", pid, want or "unset"))
                used = [a for a in data.get("awaiting_human", []) if a.get("pr") == pid and a.get("type") in STATE_FOR_TYPE
                        and a.get("approved_at") and a.get("used_at")]
                entry = next((a for a in data.get("awaiting_human", []) if usable(a, pid, prs)), None)
                if entry is None:
                    hint = " (%s already used at %s: one send per approval)" % (used[-1]["id"], used[-1]["used_at"]) if used else ""
                    block("no approved, unused send/reply for %s in awaiting_human (state %s)%s. Get the lead's word; the lead runs: "
                          "TURNSTILE_LEAD=1 turnstile approve <ah-id>." % (pid, prs.get(pid, {}).get("state"), hint))
                chosen[pid] = entry
            now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
            for pid, entry in chosen.items():
                entry["used_at"] = now; entry["used_channel"] = channel
            st_mod.save(st)
            for pid, entry in chosen.items():
                ledger.append(delivery, "slack send for %s via %s (%s) to %s" % (pid, entry["id"], entry["type"], channel))
    except SystemExit:
        raise
    except Exception as e:
        block("cannot read or update the delivery state (%s); failing closed." % e)
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block("guard crashed (%s); failing closed." % e)
