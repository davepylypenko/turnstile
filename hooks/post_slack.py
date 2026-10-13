"""PostToolUse for Slack sends: when the tool result carries a message_ts the message went out, so the approval that
allowed it is marked used (one send per approval), a ledger line is written, the board rendered and delivery/ committed.
Without a message_ts nothing is recorded: the approval stays usable (R2-4, R2-14)."""
import datetime, json, re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload, delivery_dir, plugin_root
from _slack import prs_in, choose, message_text, channel_of

TS_RX = re.compile(r"message_ts\W{1,8}(\d+\.\d+)")

def message_ts(response) -> str:
    text = response if isinstance(response, str) else json.dumps(response)
    m = TS_RX.search(text or "")
    return m.group(1) if m else ""

def fail(msg: str) -> None:
    sys.stderr.write("turnstile: " + msg + "\n"); sys.exit(2)

def main():
    p = read_payload(); ti = p.get("tool_input") or {}
    if not isinstance(ti, dict):
        sys.exit(0)
    ts = message_ts(p.get("tool_response"))
    if not ts:
        sys.exit(0)  # not sent: the approval is not consumed
    ids = prs_in(message_text(ti)); channel = channel_of(ti)
    delivery = delivery_dir(p.get("cwd") or ".")
    sys.path.insert(0, str(plugin_root()))
    from turnstile_cli import state as st_mod, ledger, pass_cmd
    with st_mod.locked(delivery):
        st = st_mod.load(delivery / "state.json")
        chosen = choose(st.data, ids, channel)  # blocks (exit 2, loud) when a send slipped past without a usable entry
        now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
        lines = []
        for pid, entry in chosen.items():
            entry["used_at"] = now; entry["used_channel"] = channel; entry["message_ts"] = ts
            lines.append("slack send for %s via %s (%s) to %s ts %s" % (pid, entry["id"], entry["type"], channel, ts))
        st_mod.save(st)
        for line in lines:
            ledger.append(delivery, line)
        io = pass_cmd.IO()
        try:
            pass_cmd._ensure_repo_files(delivery)
            html = io.render_board(st.data)
            if html is not None:
                st_mod.write_atomic(delivery / "board.html", html)
            io.git_commit(delivery, "turnstile: " + lines[0])
        except Exception as e:
            fail("send recorded in state.json and ledger.md but not committed (%s); run `turnstile status` and commit delivery/ through the next pass." % e)
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        fail("post-send hook crashed (%s); the message may be sent but unrecorded — run `turnstile status`." % e)
