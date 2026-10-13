"""PreToolUse for Slack sends: checks only. The approval is consumed by post_slack.py once the tool reports a message_ts,
so a denied or failed send leaves the approval intact (R2-4)."""
import json, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload, block, delivery_dir, plugin_root
from _slack import prs_in, choose, message_text, channel_of

def main():
    p = read_payload(); ti = p.get("tool_input") or {}
    if not isinstance(ti, dict):
        block("malformed hook payload; failing closed.")
    if "schedule" in str(p.get("tool_name") or ""):
        block("scheduled Slack messages are not allowed: one approval allows one immediate send that the PostToolUse hook can record.")
    ids = prs_in(message_text(ti))
    if not ids:
        block("Slack sends must reference the PR they are about and be approved (no PR id found).")
    try:
        delivery = delivery_dir(p.get("cwd") or ".")
        sys.path.insert(0, str(plugin_root()))
        from turnstile_cli import state as st_mod
        data = st_mod.load(delivery / "state.json").data
        choose(data, ids, channel_of(ti))
    except SystemExit:
        raise
    except Exception as e:
        block("cannot read the delivery state (%s); failing closed." % e)
    # the state allows it; the lead still confirms this exact message in the UI (README "Threat model"; R3-1)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": "turnstile: lead, confirm this Slack send for %s" % ", ".join(sorted(ids))}}))
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block("guard crashed (%s); failing closed." % e)
