"""PostToolUse for Slack sends: a recorder, never a gate. When the tool result carries a message_ts the message went out, so a
ledger line is written, an open `send` entry of a mentioned PR (old state files) is marked used, the board rendered and
delivery/ committed. Outside a workspace, without a message_ts or with unreadable state nothing is recorded. A send that went
out but could not be recorded is reported to the model as a systemMessage. Exit code is always 0."""
import contextlib, datetime, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from _common import read_payload, delivery_dir, plugin_root, managed
from _slack import prs_in, open_send_entry, message_text, channel_of

TS_RX = re.compile(r"message_ts\W{1,8}(\d+\.\d+)")
LOCK_WAIT_ENV = "TURNSTILE_LOCK_WAIT"
LOCK_WAIT_DEFAULT = 5.0
LOCK_POLL = 0.1
SEEN = {"ts": ""}

def message_ts(response) -> str:
    text = response if isinstance(response, str) else json.dumps(response)
    m = TS_RX.search(text or "")
    return m.group(1) if m else ""

def warn(msg: str) -> None:
    sys.stderr.write("turnstile: " + msg + "\n")

def unrecorded(ts: str, reason: str) -> None:
    warn("Slack message sent (ts %s) but not recorded: %s" % (ts, reason))
    print(json.dumps({"systemMessage": "turnstile: Slack message sent (ts %s) but not recorded: %s; add the ledger line by hand" % (ts, reason)}))

def lock_wait() -> float:
    try:
        return max(0.0, float(os.environ.get(LOCK_WAIT_ENV) or LOCK_WAIT_DEFAULT))
    except ValueError:
        return LOCK_WAIT_DEFAULT

def acquire(stack, st_mod, delivery):
    deadline = time.monotonic() + lock_wait()
    while True:
        try:
            stack.enter_context(st_mod.locked(delivery, wait=False)); return None
        except Exception as e:
            if time.monotonic() >= deadline:
                return "%s: %s" % (type(e).__name__, e)
            time.sleep(LOCK_POLL)

def main():
    p = read_payload(); ti = p.get("tool_input") or {}
    cwd = p.get("cwd"); cwd = cwd if isinstance(cwd, str) and cwd else "."
    if not isinstance(ti, dict) or not managed(cwd):
        return
    ts = SEEN["ts"] = message_ts(p.get("tool_response"))
    if not ts:
        return
    ids = sorted(prs_in(message_text(ti))); channel = channel_of(ti) or "?"
    try:
        delivery = delivery_dir(cwd)
        sys.path.insert(0, str(plugin_root()))
        from turnstile_cli import state as st_mod, ledger, pass_cmd
        if not (delivery / "state.json").exists():
            return
    except Exception:
        return
    with contextlib.ExitStack() as stack:
        reason = acquire(stack, st_mod, delivery)
        if reason:
            unrecorded(ts, "state lock not acquired within %.1fs (%s)" % (lock_wait(), reason)); return
        try:
            st = st_mod.load(delivery / "state.json")
        except Exception:
            return
        now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
        line = "slack send to %s ts %s" % (channel, ts) + (" for %s" % ", ".join(ids) if ids else "")
        for pid in ids:
            entry = open_send_entry(st.data, pid)
            if entry is not None:
                entry["used_at"] = now; entry["used_channel"] = channel; entry["message_ts"] = ts
                line += " (%s used)" % entry.get("id")
        st_mod.save(st)
        ledger.append(delivery, line)
        io = pass_cmd.IO()
        try:
            pass_cmd._ensure_repo_files(delivery)
            html = io.render_board(st.data)
            if html is not None:
                st_mod.write_atomic(delivery / "board.html", html)
            io.git_commit(delivery, "turnstile: " + line)
        except Exception as e:
            warn("send recorded in state.json and ledger.md but not committed (%s); the next pass commits delivery/." % e)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        unrecorded(SEEN["ts"] or "?", "post-send hook crashed (%s: %s)" % (type(e).__name__, e))
    sys.exit(0)
