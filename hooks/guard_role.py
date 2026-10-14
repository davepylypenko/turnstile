"""PreToolUse for Jira writes under any MCP prefix (transition / edit / create / comment): the orchestrator performs them
and records them with `turnstile jira-synced`; a turnstile agent (role from TURNSTILE_ROLE, set by the agent's own
frontmatter hooks, or the agent name in the payload) is refused. Round 2 R2-12."""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload, block, agent_role

def main():
    p = read_payload()
    role = agent_role(p) or ("subagent %s" % (p.get("agent_type") or "?") if p.get("agent_id") else "")  # round 3: any subagent
    if role and role != "orchestrator":
        block("blocked by rule role-jira. The %s role cannot write Jira (%s): report the transition in your reply; the orchestrator performs "
              "it and records it with 'turnstile jira-synced'." % (role, p.get("tool_name") or "Jira write"))
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block("guard crashed (%s); failing closed." % e)
