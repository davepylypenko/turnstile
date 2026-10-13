import json, pathlib
from dataclasses import dataclass
from typing import Dict, List, Optional
from . import rules, state as st_mod, github

@dataclass
class Proposal:
    pr: str
    kind: str
    message: str
    suggested_cmd: Optional[str]

def _ev_for_head(pr: dict, key: str) -> Optional[dict]:
    ev = (pr.get("evidence") or {}).get(key)
    return ev if ev and rules.same_head(ev.get("head"), pr.get("head")) else None

def compare(data: dict, facts: Dict[str, github.PrFacts]) -> List[Proposal]:
    out: List[Proposal] = []
    for pid, pr in data["prs"].items():
        f = facts.get(pid)
        if f is None:
            continue
        st = pr.get("state")
        repo = data["epic"]["repos"].get(pid.split("#", 1)[0], {})
        if f.merged and st != "MERGED":
            out.append(Proposal(pid, "merged", "merged on GitHub (%s)" % (f.merged_sha or "")[:8],
                                "turnstile pass pr %s MERGED --merged-sha %s" % (pid, f.merged_sha)))
            continue
        if st == "MERGED":
            continue
        if not rules.same_head(f.head, pr.get("head")):
            if st in ("ON_HUMAN_REVIEW", "APPROVED"):
                cmd = 'turnstile pass pr %s REWORK --reason "push after send (%s)"' % (pid, f.head[:8])
            else:
                cmd = "turnstile pass pr %s AI_REVIEW --head %s --ci %s" % (pid, f.head, f.ci)
            out.append(Proposal(pid, "head_changed", "head is %s, state has %s" % (f.head[:8], (pr.get("head") or "")[:8]), cmd))
            continue
        if st == "ON_HUMAN_REVIEW" and f.human_threads_open > 0:
            out.append(Proposal(pid, "human_thread", "%d unresolved human thread(s)" % f.human_threads_open,
                                'turnstile pass pr %s REWORK --reason "%d human thread(s)"' % (pid, f.human_threads_open)))
        elif st == "ON_HUMAN_REVIEW" and f.approvals and f.human_threads_open == 0:
            out.append(Proposal(pid, "approved", "approved by %s" % ", ".join(f.approvals),
                                "turnstile pass pr %s APPROVED --approvals %s --open-threads 0" % (pid, ",".join(f.approvals))))
        cp = _ev_for_head(pr, "copilot")
        if cp and cp.get("open_threads") == 0 and f.copilot_threads_open > 0:
            out.append(Proposal(pid, "copilot_thread", "%d open Copilot thread(s) but evidence says 0" % f.copilot_threads_open, None))
        g = _ev_for_head(pr, "gate")
        gate_name = repo.get("gate")
        if g and gate_name and f.checks.get(gate_name) not in (None, "success") and g.get("result") == "pass":
            out.append(Proposal(pid, "gate_red", "check %s is %s on GitHub but evidence says pass" % (gate_name, f.checks.get(gate_name)), None))
        ci = _ev_for_head(pr, "ci")
        if ci and ci.get("status") == "success" and f.ci == "failure":
            out.append(Proposal(pid, "ci_red", "CI is red on GitHub but evidence says success", None))
        if (pr.get("jira") or {}).get("synced") is False:
            out.append(Proposal(pid, "jira_unsynced", "Jira not moved to %s" % pr["jira"].get("status"),
                                'turnstile jira-synced %s "%s"' % (pid, pr["jira"].get("status"))))
        if f.draft and st in ("ON_HUMAN_REVIEW", "APPROVED"):
            out.append(Proposal(pid, "draft_mismatch", "PR is still a draft on GitHub", None))
    return out

def cli(delivery: pathlib.Path, as_json: bool = False, status: bool = False) -> int:
    st = st_mod.load(pathlib.Path(delivery) / "state.json")
    org = st.data["epic"].get("github_org", "pdffiller")
    facts = {}
    for pid, pr in st.data["prs"].items():
        if pr.get("state") == "MERGED":
            continue
        try:
            facts[pid] = github.fetch(pid, org)
        except Exception as e:  # network/gh problems must not hide the rest
            print("WARN %s: %s" % (pid, e))
    props = compare(st.data, facts)
    if as_json:
        print(json.dumps([p.__dict__ for p in props], indent=2)); return 0
    if status:
        print("== %s" % st.data["epic"]["key"])
        for sid, s in st.data["stories"].items():
            print("story %s [%s] %s — %s" % (sid, s.get("state"), s.get("title"), s.get("next_action", "")))
        for pid, pr in st.data["prs"].items():
            print("pr %-28s [%s] %s" % (pid, pr.get("state"), pr.get("next_action", "")))
        pending = [a for a in st.data.get("awaiting_human", []) if not a.get("approved_at")]
        print("awaiting humans: %d" % len(pending))
        for a in pending:
            print("  %s %s %s %s" % (a["id"], a["owner"], a["type"], a.get("pr") or a.get("story")))
    print("== reconcile: %d discrepancy(ies)" % len(props))
    for p in props:
        print("%s %s: %s" % (p.pr, p.kind, p.message))
        if p.suggested_cmd:
            print("    → " + p.suggested_cmd)
    return 0
