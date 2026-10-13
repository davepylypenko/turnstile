import copy, json, pathlib, re, subprocess
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

def _dry_run(data: dict, pid: str, target: str, cmd: str, facts: Optional[github.PrFacts] = None, **flags) -> Optional[str]:
    """Return the refusal text if `turnstile pass pr <pid> <target> <flags>` would be refused; None if it would pass.
    Runs the real evidence application, the GitHub-facts checks and the rules on a deep copy, so nothing is written."""
    from . import pass_cmd
    pr = copy.deepcopy(data["prs"][pid]); pr["_id"] = pid
    o = pass_cmd.Options(**flags)
    try:
        pass_cmd._apply_pr_evidence(pr, o)
    except Exception as e:
        return str(e)
    pr.setdefault("evidence", {})["head_verified"] = {"head": pr.get("head"), "verified": True}
    repo = data["epic"]["repos"].get(pid.split("#", 1)[0], {})
    missing = pass_cmd._facts_mismatches(pr, target, facts, repo) if facts is not None else []
    missing += rules.check_pr(pr, target, repo, data["prs"], reason=o.reason, awaiting=data.get("awaiting_human"), stories=data.get("stories"))
    return "; ".join(missing) if missing else None

def _propose(out: List[Proposal], data: dict, pid: str, kind: str, message: str, target: str, cmd: str, facts: Optional[github.PrFacts] = None, **flags) -> None:
    refusal = _dry_run(data, pid, target, cmd, facts=facts, **flags)
    if refusal:
        out.append(Proposal(pid, kind, "%s — no clean pass available: %s" % (message, refusal), None))
    else:
        out.append(Proposal(pid, kind, message, cmd))

def compare(data: dict, facts: Dict[str, github.PrFacts]) -> List[Proposal]:
    out: List[Proposal] = []
    for pid, pr in data["prs"].items():
        f = facts.get(pid)
        if f is None:
            continue
        st = pr.get("state")
        repo = data["epic"]["repos"].get(pid.split("#", 1)[0], {})
        if f.merged and st != "MERGED":
            msg = "merged on GitHub (%s)" % (f.merged_sha or "")[:8]
            if st == "APPROVED":
                _propose(out, data, pid, "merged", msg, "MERGED", "turnstile pass pr %s MERGED --merged-sha %s" % (pid, f.merged_sha),
                         facts=f, merged_sha=f.merged_sha)
            else:
                out.append(Proposal(pid, "merged", msg + " but state is %s: anomaly, merged without APPROVED; the lead decides" % st, None))
            continue
        if st == "MERGED":
            continue
        if not rules.same_head(f.head, pr.get("head")):
            msg = "head is %s, state has %s" % (f.head[:8], (pr.get("head") or "")[:8])
            if st in ("ON_HUMAN_REVIEW", "APPROVED"):
                reason = "push after send (%s)" % f.head[:8]
                _propose(out, data, pid, "head_changed", msg, "REWORK", 'turnstile pass pr %s REWORK --head %s --reason "%s"' % (pid, f.head, reason), facts=f, reason=reason, head=f.head)
            elif st in ("AI_REVIEW", "READY"):
                ci = f.ci if f.ci in ("success", "failure") else None
                cmd = "turnstile pass pr %s AI_REVIEW --head %s" % (pid, f.head) + (" --ci %s" % ci if ci else "")
                _propose(out, data, pid, "head_changed", msg + " (CI %s)" % f.ci, "AI_REVIEW", cmd, facts=f, head=f.head, ci=ci)
            elif st == "REWORK":
                out.append(Proposal(pid, "head_changed", msg + "; record it with the ON_HUMAN_REVIEW pass (--head %s) once gate/copilot are green" % f.head[:12], None))
            else:
                out.append(Proposal(pid, "head_changed", msg + " (DEV: pushes are expected; pass AI_REVIEW with --head when CI is green)", None))
            continue
        if st == "ON_HUMAN_REVIEW" and f.human_threads_open > 0:
            reason = "%d human thread(s)" % f.human_threads_open
            _propose(out, data, pid, "human_thread", "%d unresolved human thread(s)" % f.human_threads_open, "REWORK",
                     'turnstile pass pr %s REWORK --reason "%s"' % (pid, reason), facts=f, reason=reason)
        elif st == "ON_HUMAN_REVIEW" and f.changes_requested:
            reason = "changes requested by %s" % ", ".join(f.changes_requested)
            _propose(out, data, pid, "changes_requested", reason, "REWORK", 'turnstile pass pr %s REWORK --reason "%s"' % (pid, reason), facts=f, reason=reason)
        elif st == "ON_HUMAN_REVIEW" and f.approvals and f.human_threads_open == 0:
            _propose(out, data, pid, "approved", "approved by %s" % ", ".join(f.approvals), "APPROVED",
                     "turnstile pass pr %s APPROVED --approvals %s --open-threads 0" % (pid, ",".join(f.approvals)),
                     facts=f, approvals=",".join(f.approvals), open_threads=0)
        cp = _ev_for_head(pr, "copilot")
        if cp and cp.get("open_threads") == 0 and f.copilot_threads_open > 0:
            out.append(Proposal(pid, "copilot_thread", "%d open Copilot thread(s) but evidence says 0" % f.copilot_threads_open, None))
        g = _ev_for_head(pr, "gate")
        gate_name = repo.get("gate")
        if g and gate_name and g.get("result") == "pass":
            check = f.checks.get(gate_name)
            if check == "failure":
                out.append(Proposal(pid, "gate_red", "check %s is red on GitHub but evidence says pass" % gate_name, None))
            elif check is None and not f.checks_complete:
                out.append(Proposal(pid, "gate_unknown", "check %s not among the first %d contexts; verify it by hand" % (gate_name, len(f.checks)), None))
        ci = _ev_for_head(pr, "ci")
        if ci and ci.get("status") == "success" and f.ci == "failure":
            out.append(Proposal(pid, "ci_red", "CI is red on GitHub but evidence says success", None))
        if f.head_signed is False:
            out.append(Proposal(pid, "unsigned", "head commit is not signed (DEV DoD: signed commits)", None))
        if (pr.get("jira") or {}).get("synced") is False:
            out.append(Proposal(pid, "jira_unsynced", "Jira not moved to %s" % pr["jira"].get("status"),
                                'turnstile jira-synced %s "%s"' % (pid, pr["jira"].get("status"))))
        if f.draft and st in ("ON_HUMAN_REVIEW", "APPROVED"):
            out.append(Proposal(pid, "draft_mismatch", "PR is still a draft on GitHub", None))
    return out

APPROVED_LINE = re.compile(r"\bapproved (ah-\d+) \(.*approved_via: lead-terminal")

def compare_ledger(data: dict, ledger_text: str) -> List[Proposal]:
    """Every approved awaiting_human entry must have a ledger line written by `turnstile approve` from the lead's
    terminal. An approved_at without that line was written some other way: defence in depth, not proof."""
    logged = set(APPROVED_LINE.findall(ledger_text or ""))
    out: List[Proposal] = []
    for a in data.get("awaiting_human", []):
        if a.get("approved_at") and a.get("id") not in logged:
            out.append(Proposal(a.get("id"), "approval_unlogged",
                                "%s (%s %s) has approved_at %s but no ledger line 'approved %s (…) approved_via: lead-terminal'; "
                                "the approval did not come through the lead's terminal — the lead decides"
                                % (a.get("id"), a.get("type"), a.get("pr") or a.get("story"), a.get("approved_at"), a.get("id")), None))
    return out

def uncommitted(delivery: pathlib.Path) -> List[str]:
    """Paths under delivery/ that differ from the last commit (R2-14); [] when git is unavailable or it is not a repo."""
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=str(delivery), capture_output=True, text=True)
    except OSError:
        return []
    if r.returncode != 0:
        return []
    return [ln[3:].strip().split("/")[-1] for ln in r.stdout.splitlines() if ln.strip()]

def cli(delivery: pathlib.Path, as_json: bool = False, status: bool = False) -> int:
    st = st_mod.load(pathlib.Path(delivery) / "state.json")
    ledger_path = pathlib.Path(delivery) / "ledger.md"
    org = st.data["epic"].get("github_org", "pdffiller")
    facts = {}
    unknown = []
    for pid, pr in st.data["prs"].items():
        if pr.get("state") == "MERGED":
            continue
        try:
            facts[pid] = github.fetch(pid, org)
        except Exception as e:  # network/gh problems must not hide the rest
            print("WARN %s: %s" % (pid, e)); unknown.append(pid)
    props = compare(st.data, facts) + compare_ledger(st.data, ledger_path.read_text() if ledger_path.exists() else "")
    rc = 1 if unknown else 0
    if as_json:
        print(json.dumps([p.__dict__ for p in props], indent=2)); return rc
    if status:
        print("== %s" % st.data["epic"]["key"])
        for sid, s in st.data["stories"].items():
            print("story %s [%s] %s — %s" % (sid, s.get("state"), s.get("title"), s.get("next_action", "")))
        for pid, pr in st.data["prs"].items():
            print("pr %-28s [%s] %s" % (pid, pr.get("state"), pr.get("next_action", "")))
        pending = [a for a in st.data.get("awaiting_human", []) if not a.get("approved_at") and not a.get("voided_at")]
        print("awaiting humans: %d" % len(pending))
        for a in pending:
            print("  %s %s %s %s" % (a["id"], a["owner"], a["type"], a.get("pr") or a.get("story")))
        dirty = uncommitted(delivery)
        if dirty:
            print("uncommitted changes in delivery (%d file(s)): %s — a write outside turnstile; the next pass commits it, reconcile it first"
                  % (len(dirty), ", ".join(dirty)))
    print("== reconcile: %d discrepancy(ies)" % len(props))
    for p in props:
        print("%s %s: %s" % (p.pr, p.kind, p.message))
        if p.suggested_cmd:
            print("    → " + p.suggested_cmd)
    if unknown:
        print("== facts missing for %s (gh failed); exit 1" % ", ".join(unknown))
    return rc
