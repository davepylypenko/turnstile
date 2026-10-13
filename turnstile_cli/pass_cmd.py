import copy, datetime, pathlib, subprocess
from dataclasses import dataclass
from typing import List, Optional
from . import state as st_mod, rules, ledger
from .errors import TurnstileError, StaleStateError

@dataclass
class Options:
    head: Optional[str] = None
    ci: Optional[str] = None
    deep_review: Optional[str] = None
    rounds: Optional[int] = None
    not_clean: bool = False
    gate: Optional[str] = None
    copilot: Optional[int] = None
    slack: Optional[str] = None
    reviewers: Optional[str] = None
    approved: Optional[str] = None
    approvals: Optional[str] = None
    open_threads: Optional[int] = None
    reason: Optional[str] = None
    merged_sha: Optional[str] = None
    report: Optional[str] = None
    build: Optional[str] = None
    cases_pass: Optional[int] = None
    cases_fail: Optional[int] = None
    figma_parity: Optional[str] = None
    no_commit: bool = False

class IO:
    def git_commit(self, delivery: pathlib.Path, message: str) -> None:
        subprocess.run(["git", "add", "-A", "."], cwd=str(delivery), check=True)
        subprocess.run(["git", "commit", "-q", "-m", message], cwd=str(delivery), check=True)
    def renderer(self, data: dict, delivery: pathlib.Path) -> None:
        try:
            from . import board
        except ImportError:
            return
        board.render(data, delivery)

def _now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")

def _apply_pr_evidence(pr: dict, o: Options, awaiting: List[dict]) -> None:
    if o.head:
        pr["head"] = o.head
    h = pr.get("head")
    ev = pr.setdefault("evidence", {})
    if o.ci:
        ev["ci"] = {"head": h, "status": o.ci}
    if o.deep_review:
        ev["deep_review"] = {"head": h, "report": o.deep_review, "rounds": o.rounds or 1, "clean": not o.not_clean}
    if o.gate:
        parts = o.gate.split(":")
        ev["gate"] = {"name": parts[0], "head": h, "result": parts[1] if len(parts) > 1 else "pass",
                      "run": ":".join(parts[2:]) if len(parts) > 2 else None}
    if o.copilot is not None:
        ev["copilot"] = {"head": h, "open_threads": o.copilot}
    if o.slack:
        ev["human"] = {"head": h, "slack_permalink": o.slack, "reviewers": o.reviewers.split(",") if o.reviewers else [],
                       "sent_head": h, "approved": o.approved, "open_threads": 0, "approvals": [], "sent_at": _now()}
        for a in awaiting:
            if a.get("id") == o.approved:
                a["approved_at"] = a.get("approved_at") or _now()
    if o.approvals is not None or o.open_threads is not None:
        human = ev.setdefault("human", {"head": h, "sent_head": h, "approvals": [], "open_threads": 0})
        if o.approvals is not None:
            human["approvals"] = [x for x in o.approvals.split(",") if x]
        if o.open_threads is not None:
            human["open_threads"] = o.open_threads
    if o.merged_sha:
        pr["merged_sha"] = o.merged_sha

def _apply_story_evidence(story: dict, o: Options) -> None:
    ev = story.setdefault("evidence", {})
    if o.build:
        ev["deploy"] = {"build": o.build, "at": _now()}
    if o.report and o.figma_parity is None and o.cases_fail is None:
        ev["integration_review"] = {"report": o.report, "head": o.head, "rounds": o.rounds or 1, "clean": not o.not_clean}
    if o.figma_parity is not None or o.cases_fail is not None:
        ev["env_test"] = {"report": o.report, "cases": {"pass": o.cases_pass or 0, "fail": o.cases_fail or 0},
                          "figma_parity": o.figma_parity}

def _recompute_next_actions(data: dict) -> None:
    for pid, pr in data["prs"].items():
        repo = data["epic"]["repos"].get(pid.split("#", 1)[0], {})
        pr["next_action"] = rules.next_action_pr(pr, repo)
    for sid, s in data["stories"].items():
        s["next_action"] = rules.next_action_story(s, data["prs"])

def _next_ah_id(data: dict) -> str:
    n = 1 + max([int(a["id"].split("-")[1]) for a in data.get("awaiting_human", []) if a.get("id", "").startswith("ah-")] or [0])
    return "ah-%d" % n

def _side_effects(delivery: pathlib.Path, st: "st_mod.State", summary: str, io: IO, o: Options) -> None:
    st_mod.save(st)
    ledger.append(delivery, summary)
    io.renderer(st.data, delivery)
    if not o.no_commit:
        io.git_commit(delivery, "turnstile: " + summary)

def run(delivery: pathlib.Path, kind: str, ident: str, target: str, o: Options, io: Optional[IO] = None) -> int:
    io = io or IO()
    try:
        st = st_mod.load(pathlib.Path(delivery) / "state.json")
        data = st.data
        if kind == "pr":
            pr = st_mod.pr(st, ident)
            repo = st_mod.repo_cfg(st, ident)
            trial = copy.deepcopy(pr)
            _apply_pr_evidence(trial, o, copy.deepcopy(data.get("awaiting_human", [])))
            missing = rules.check_pr(trial, target, repo, data["prs"], reason=o.reason)
            if missing:
                print("\n".join(missing)); return 2
            src = pr["state"]
            _apply_pr_evidence(pr, o, data.setdefault("awaiting_human", []))
            pr["state"] = target
            if o.reason:
                pr["last_reason"] = o.reason
            jira_target = rules.JIRA_FOR_PR_STATE[target]
            if (pr.get("jira") or {}).get("status") != jira_target:
                pr["jira"] = {"status": jira_target, "synced": False}
                print("JIRA: %s → %s" % (pr["ticket"], jira_target))
            if target == "READY" and not any(a.get("pr") == ident and a.get("type") == "send" and not a.get("approved_at")
                                             for a in data["awaiting_human"]):
                data["awaiting_human"].append({"id": _next_ah_id(data), "owner": "lead", "type": "send", "pr": ident,
                                               "created_at": _now(), "payload": None, "approved_at": None})
            if target == "APPROVED":
                data["awaiting_human"].append({"id": _next_ah_id(data), "owner": "lead", "type": "merge", "pr": ident,
                                               "created_at": _now(), "payload": None, "approved_at": None})
            if target == "MERGED":
                unblocked = [p for p, v in data["prs"].items() if v.get("blocked_by") == ident]
                if unblocked:
                    ledger.append(delivery, "unblocked for sending by %s: %s" % (ident, ", ".join(unblocked)))
            _recompute_next_actions(data)
            summary = "pass pr %s %s → %s (head %s)%s" % (ident, src, target, pr.get("head"), " — " + o.reason if o.reason else "")
        elif kind == "story":
            story = st_mod.story(st, ident)
            trial = copy.deepcopy(story); trial["_id"] = ident
            _apply_story_evidence(trial, o)
            missing = rules.check_story(trial, target, data["prs"], data["stories"], reason=o.reason)
            if missing:
                print("\n".join(missing)); return 2
            src = story["state"]
            _apply_story_evidence(story, o)
            story["state"] = target
            _recompute_next_actions(data)
            summary = "pass story %s %s → %s%s" % (ident, src, target, " — " + o.reason if o.reason else "")
        else:
            raise TurnstileError("kind must be pr or story")
        _side_effects(delivery, st, summary, io, o)
        print("BOARD: publish %s" % (pathlib.Path(delivery) / "board.html"))
        print("OK " + summary)
        return 0
    except StaleStateError as e:
        print("MISSING fresh state: %s" % e); return 2
    except TurnstileError as e:
        print("MISSING %s" % e); return 2

def jira_synced(delivery: pathlib.Path, ident: str, status: str, io: Optional[IO] = None) -> int:
    io = io or IO()
    st = st_mod.load(pathlib.Path(delivery) / "state.json")
    pr = st_mod.pr(st, ident)
    pr["jira"] = {"status": status, "synced": True}
    st_mod.save(st)
    ledger.append(delivery, "jira %s → %s (synced)" % (pr["ticket"], status))
    io.git_commit(delivery, "turnstile: jira %s → %s" % (pr["ticket"], status))
    print("OK jira %s synced" % ident)
    return 0

def approve(delivery: pathlib.Path, ah_id: str, io: Optional[IO] = None) -> int:
    """The lead said the word for an awaiting_human entry: record approved_at so the Slack guard lets it through."""
    io = io or IO()
    try:
        st = st_mod.load(pathlib.Path(delivery) / "state.json")
        entry = next((a for a in st.data.get("awaiting_human", []) if a.get("id") == ah_id), None)
        if entry is None:
            raise TurnstileError("unknown awaiting_human id %s" % ah_id)
        if entry.get("approved_at"):
            print("OK %s already approved at %s" % (ah_id, entry["approved_at"])); return 0
        entry["approved_at"] = _now()
        st_mod.save(st)
        summary = "approved %s (%s %s by %s)" % (ah_id, entry.get("type"), entry.get("pr") or entry.get("story"), entry.get("owner"))
        ledger.append(delivery, summary)
        io.git_commit(delivery, "turnstile: " + summary)
        print("OK " + summary)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
