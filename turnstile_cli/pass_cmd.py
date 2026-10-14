import copy, datetime, os, pathlib, subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional
from . import state as st_mod, rules, ledger
from .errors import TurnstileError, StaleStateError

GITATTRIBUTES = "ledger.md merge=union\n"
GITIGNORE = ".*.tmp\n"
HEAD_VERIFIED_TARGETS = ("READY", "ON_HUMAN_REVIEW", "APPROVED", "MERGED")
APPROVED_VIA = "lead-terminal"  # the lead types the approve command in the Claude Code prompt with the `!` prefix

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
    companions: Optional[str] = None
    offline: bool = False
    full: bool = False
    no_commit: bool = False

class IO:
    """Everything that touches the world; injectable so tests stay offline."""
    def git_commit(self, delivery: pathlib.Path, message: str) -> None:
        subprocess.run(["git", "add", "-A", "."], cwd=str(delivery), check=True, capture_output=True, text=True)
        r = subprocess.run(["git", "commit", "-q", "-m", message, "--", "."], cwd=str(delivery), capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.run(["git", "reset", "-q", "--", "."], cwd=str(delivery), capture_output=True)
            raise TurnstileError((r.stderr or r.stdout).strip()[:300] or "git commit exited %d" % r.returncode)
    def render_board(self, data: dict) -> Optional[str]:
        try:
            from . import board
        except ImportError:
            return None
        return board.render_html(data)
    def github_facts(self, pr_id: str, org: str):
        from . import github
        return github.fetch(pr_id, org)

def _now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")

def _check_report(delivery: pathlib.Path, rel: Optional[str]) -> None:
    if rel and not (pathlib.Path(delivery) / rel).is_file():
        raise TurnstileError("report file %s not found under %s" % (rel, delivery))

def _apply_pr_evidence(pr: dict, o: Options) -> None:
    if o.head:
        if not rules.valid_head(o.head):
            raise TurnstileError("--head must be 8–40 hex characters (got %r)" % o.head)
        pr["head"] = o.head.lower()
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
    if o.approvals is not None or o.open_threads is not None:
        human = ev.setdefault("human", {"head": h, "sent_head": h, "approvals": [], "open_threads": 0})
        if o.approvals is not None:
            human["approvals"] = [x for x in o.approvals.split(",") if x]
        if o.open_threads is not None:
            human["open_threads"] = o.open_threads
    if o.merged_sha:
        pr["merged_sha"] = o.merged_sha

def _facts_mismatches(pr: dict, target: str, facts, repo_cfg: dict) -> List[str]:
    """R2-5: self-reported evidence must equal what GitHub says for the PR's head. Pure; shared with the reconcile dry run."""
    out: List[str] = []
    h = pr.get("head")
    ev = pr.get("evidence") or {}
    def for_head(key):
        e = ev.get(key)
        return e if e and rules.same_head(e.get("head"), h) else None
    # the gate's GitHub context: `gate_check` (null for a skill gate that posts no check, e.g. pr-review), default the gate name
    gate_check = repo_cfg["gate_check"] if "gate_check" in repo_cfg else repo_cfg.get("gate")
    if target in ("AI_REVIEW", "READY", "ON_HUMAN_REVIEW"):
        ci = for_head("ci")
        # entering AI_REVIEW the gate has not run yet: CI there excludes the gate's contexts; READY onward needs the whole rollup
        actual_ci = facts.ci_without(repo_cfg.get("ci_ignore", [gate_check] if gate_check else [])) if target == "AI_REVIEW" else facts.ci
        if ci and ci.get("status") == "success" and actual_ci != "success":
            out.append("MISSING CI success on GitHub for head %s (is %s); evidence says success" % (h, actual_ci))
        if facts.unsigned:
            out.append("MISSING every commit signed (unsigned: %s)" % ", ".join(facts.unsigned))
        if pr.get("base") and facts.base and facts.base != pr.get("base"):
            out.append("MISSING PR base %s on GitHub (is %s): ticket PRs go into the planned story/epic branch" % (pr.get("base"), facts.base))
    if target in ("READY", "ON_HUMAN_REVIEW"):
        g = for_head("gate")
        if gate_check and g and g.get("result") == "pass":
            actual = facts.checks.get(gate_check)
            if actual != "success":
                out.append("MISSING gate %s == success on GitHub for head %s (is %s); evidence says pass" % (gate_check, h, actual or "absent"))
        c = for_head("copilot")
        if repo_cfg.get("copilot") and c and c.get("open_threads") == 0 and facts.copilot_threads_open != 0:
            out.append("MISSING Copilot threads == 0 on GitHub for head %s (has %d); evidence says 0" % (h, facts.copilot_threads_open))
    if target == "APPROVED":
        human = ev.get("human") or {}
        for login in human.get("approvals") or []:
            if login not in facts.approvals:
                out.append("MISSING approval by %s in GitHub latestReviews for head %s (has %s)" % (login, h, ", ".join(facts.approvals) or "none"))
        if facts.human_threads_open != 0:
            out.append("MISSING 0 unresolved human threads on GitHub (has %d)" % facts.human_threads_open)
        if facts.changes_requested:
            out.append("MISSING no changes requested on GitHub (changes requested by %s)" % ", ".join(facts.changes_requested))
    if target == "MERGED":
        if not facts.merged:
            out.append("MISSING merged on GitHub (the PR is not merged)")
        elif facts.merged_sha and pr.get("merged_sha") and not rules.same_head(facts.merged_sha, pr.get("merged_sha")):
            out.append("MISSING merged_sha == GitHub merge commit %s (has %s)" % (facts.merged_sha, pr.get("merged_sha")))
    return out

def _verify_against_github(pr: dict, ident: str, target: str, repo_cfg: dict, org: str, o: Options, io: IO, notes: List[str]) -> List[str]:
    """Bind the evidence to the PR's real head and to GitHub's facts: GitHub decides, not the caller."""
    h = pr.get("head")
    ev = pr.setdefault("evidence", {})
    if o.offline:
        notes.append("WARN --offline: head %s of %s NOT verified against GitHub; READY/ON_HUMAN_REVIEW/APPROVED/MERGED stay refused until an online pass" % (h, ident))
        ev["head_verified"] = {"head": h, "verified": False}
        return []
    try:
        facts = io.github_facts(ident, org)
    except Exception as e:
        raise TurnstileError("GitHub head for %s unavailable (%s); fix gh or use --offline (refuses READY/ON_HUMAN_REVIEW)" % (ident, e))
    if not rules.same_head(facts.head, h):
        raise TurnstileError("head %s on GitHub for %s: it is %s (push changed it? pass --head %s)" % (h, ident, facts.head, facts.head[:12]))
    ev["head_verified"] = {"head": h, "verified": True, "at": _now()}
    return _facts_mismatches(pr, target, facts, repo_cfg)

def _apply_story_evidence(story: dict, o: Options) -> None:
    ev = story.setdefault("evidence", {})
    if o.build:
        ev["deploy"] = {"build": o.build, "head": o.head.lower() if o.head else None, "at": _now()}
    env_flags = (o.figma_parity, o.cases_pass, o.cases_fail)
    if any(x is not None for x in env_flags):
        if o.cases_pass is None or o.cases_fail is None:
            raise TurnstileError("--cases-pass and --cases-fail are both required when recording env_test (explicit counts from the report)")
        if o.figma_parity is None:
            raise TurnstileError("--figma-parity is required when recording env_test")
        run = {"report": o.report, "cases": {"pass": o.cases_pass, "fail": o.cases_fail}, "figma_parity": o.figma_parity, "full": bool(o.full), "at": _now()}
        ev.setdefault("env_runs", []).append(run)
        ev["env_test"] = run
    elif o.report:
        ev["integration_review"] = {"report": o.report, "head": o.head.lower() if o.head else None, "rounds": o.rounds or 1, "clean": not o.not_clean}

def _recompute_next_actions(data: dict) -> None:
    for pid, pr in data["prs"].items():
        repo = data["epic"]["repos"].get(pid.split("#", 1)[0], {})
        pr["next_action"] = rules.next_action_pr(pr, repo)
    for sid, s in data["stories"].items():
        s["next_action"] = rules.next_action_story(s, data["prs"])

def _next_ah_id(data: dict) -> str:
    nums = []
    for a in data.get("awaiting_human", []):
        tail = str(a.get("id", "")).split("-", 1)
        if len(tail) == 2 and tail[0] == "ah" and tail[1].isdigit():
            nums.append(int(tail[1]))
    return "ah-%d" % (max(nums or [0]) + 1)

def _open_entry(data: dict, type_: str, **keys) -> dict:
    e = {"id": _next_ah_id(data), "owner": "lead", "type": type_, "created_at": _now(), "payload": None, "approved_at": None}
    e.update(keys)
    data.setdefault("awaiting_human", []).append(e)
    return e

def _has_open_entry(data: dict, type_: str, key: str, ident: str) -> bool:
    return any(a.get("type") == type_ and a.get(key) == ident and not a.get("consumed_at") and not a.get("voided_at")
               for a in data.get("awaiting_human", []))

def _ensure_start_story_entries(data: dict) -> None:
    for sid, s in data.get("stories", {}).items():
        if rules.startable(s, data["stories"]) and not _has_open_entry(data, "start_story", "story", sid):
            _open_entry(data, "start_story", story=sid)

def _ensure_repo_files(delivery: pathlib.Path) -> None:
    ga = pathlib.Path(delivery) / ".gitattributes"
    if not ga.exists() or "ledger.md merge=union" not in ga.read_text():
        ga.write_text((ga.read_text() if ga.exists() else "") + GITATTRIBUTES)
    lock = pathlib.Path(delivery) / st_mod.LOCK_NAME
    if not lock.exists():
        lock.touch()  # tracked and empty: flock never changes its content
    gi = pathlib.Path(delivery) / ".gitignore"
    have = gi.read_text() if gi.exists() else ""
    missing = [ln for ln in GITIGNORE.splitlines() if ln not in have.splitlines()]
    if missing:
        gi.write_text(have + ("" if not have or have.endswith("\n") else "\n") + "\n".join(missing) + "\n")

class _Snapshot:
    NAMES = ("state.json", "ledger.md", "board.html")
    def __init__(self, delivery: pathlib.Path):
        self.delivery = pathlib.Path(delivery)
        self.before: Dict[str, Optional[str]] = {n: (self.delivery / n).read_text() if (self.delivery / n).exists() else None for n in self.NAMES}
    def restore(self) -> None:
        for n, text in self.before.items():
            p = self.delivery / n
            if text is None:
                if p.exists():
                    p.unlink()
            else:
                st_mod.write_atomic(p, text)

def _side_effects(delivery: pathlib.Path, st: "st_mod.State", lines: List[str], io: IO, no_commit: bool) -> None:
    """validate happened → render board in memory → write state + ledger + board → git commit; on commit
    failure restore the three files from the in-memory snapshot so the disk equals the last committed state."""
    delivery = pathlib.Path(delivery)
    try:
        html = io.render_board(st.data)
    except Exception as e:
        raise TurnstileError("board render failed: %s" % e)
    snap = _Snapshot(delivery)
    st_mod.save(st)  # stale check happens here, before any other write
    try:
        for line in lines:
            ledger.append(delivery, line)
        if html is not None:
            st_mod.write_atomic(delivery / "board.html", html)
        _ensure_repo_files(delivery)
        if not no_commit:
            io.git_commit(delivery, "turnstile: " + lines[0])
    except Exception as e:
        snap.restore()
        st.loaded_digest = st_mod.digest(snap.before["state.json"] or "")
        raise TurnstileError("git commit failed: %s" % e)

def run(delivery: pathlib.Path, kind: str, ident: str, target: str, o: Options, io: Optional[IO] = None) -> int:
    io = io or IO()
    delivery = pathlib.Path(delivery)
    notes: List[str] = []
    try:
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            data = st.data
            org = rules.require_org(data)
            awaiting = data.setdefault("awaiting_human", [])
            _check_report(delivery, o.deep_review); _check_report(delivery, o.report)
            extra: List[str] = []
            if kind == "pr":
                pr = st_mod.pr(st, ident)
                repo = st_mod.repo_cfg(st, ident)
                trial = copy.deepcopy(pr); trial["_id"] = ident
                _apply_pr_evidence(trial, o)
                missing = _verify_against_github(trial, ident, target, repo, org, o, io, notes)
                missing += rules.check_pr(trial, target, repo, data["prs"], reason=o.reason, awaiting=awaiting, stories=data["stories"])
                if missing:
                    print("\n".join(notes + missing)); return 2
                src = pr["state"]
                del trial["_id"]
                data["prs"][ident] = pr = trial
                pr["state"] = target
                if o.reason:
                    pr["last_reason"] = o.reason
                jira_target = rules.JIRA_FOR_PR_STATE[target]
                jira_line = None
                if (pr.get("jira") or {}).get("status") != jira_target:
                    pr["jira"] = {"status": jira_target, "synced": False}
                    jira_line = "JIRA: %s → %s" % (pr["ticket"], jira_target)
                if target == "ON_HUMAN_REVIEW":
                    rules.find_entry(awaiting, o.approved)["consumed_at"] = _now()
                if target == "READY" and not _has_open_entry(data, "send", "pr", ident):
                    extra_keys = {"companions": [x for x in o.companions.split(",") if x]} if o.companions else {}
                    _open_entry(data, "send", pr=ident, head=pr.get("head"), **extra_keys)
                if target == "AI_REVIEW" and src == "READY":
                    for a in awaiting:
                        if a.get("type") == "send" and a.get("pr") == ident and not a.get("consumed_at") and not a.get("voided_at"):
                            a["voided_at"] = _now()
                            extra.append("voided %s (send for %s: head changed to %s)" % (a["id"], ident, pr.get("head")))
                if target == "REWORK":
                    pr["rework_since"] = {"head": pr.get("head"), "at": _now(), "reason": o.reason}
                    _open_entry(data, "reply", pr=ident, head=pr.get("head"))
                if target == "DEV":
                    pr.pop("rework_since", None)  # a re-implementation: deep review is required again (R2-7)
                    for a in awaiting:  # the reply word was for that rework, not a later one (R3-7)
                        if a.get("type") == "reply" and a.get("pr") == ident and not a.get("consumed_at") and not a.get("voided_at"):
                            a["voided_at"] = _now(); extra.append("voided %s (reply for %s: PR went back to DEV)" % (a["id"], ident))
                if target == "APPROVED":
                    _open_entry(data, "merge", pr=ident, head=pr.get("head"))
                if target == "MERGED":
                    unblocked = [p for p, v in data["prs"].items() if v.get("blocked_by") == ident]
                    if unblocked:
                        extra.append("unblocked for sending by %s: %s" % (ident, ", ".join(unblocked)))
                    sid = pr.get("story")
                    mine = [p for p, v in data["prs"].items() if v.get("story") == sid]
                    if sid and mine and all(data["prs"][p].get("state") == "MERGED" for p in mine):
                        extra.append("story %s: every PR merged (%s); re-evaluate the story DoD (state %s)"
                                     % (sid, ", ".join(mine), (data["stories"].get(sid) or {}).get("state")))
                summary = "pass pr %s %s → %s (head %s)%s%s" % (ident, src, target, pr.get("head"), " — " + o.reason if o.reason else "",
                                                             " [offline, head not verified]" if o.offline else "")
            elif kind == "story":
                story = st_mod.story(st, ident)
                trial = copy.deepcopy(story); trial["_id"] = ident
                _apply_story_evidence(trial, o)
                if target == "ENV_TESTING" and story.get("state") == "ENV_TESTING" and o.cases_fail is None:
                    raise TurnstileError("--report, --cases-pass, --cases-fail and --figma-parity to record a test run (ENV_TESTING re-entry records a run)")
                if o.cases_fail is not None:  # the bugs that existed when the run was recorded: the next failing run counts only newer ones
                    trial["evidence"]["env_runs"][-1]["bug_ids"] = sorted(b.get("id") for b in data.get("bugs") or [] if b.get("story") == ident)
                plan_missing = None
                if target == "IN_PROGRESS" and story.get("state") == "PLANNED":
                    plan_path = delivery / "plan.md"
                    plan_missing = rules.plan_approval_missing(data, st_mod.digest(plan_path.read_text()) if plan_path.exists() else None)
                missing = rules.check_story(trial, target, data["prs"], data["stories"], reason=o.reason,
                                            bugs=data.get("bugs"), awaiting=awaiting, approved=o.approved, plan_missing=plan_missing)
                if missing:
                    print("\n".join(notes + missing)); return 2
                src = story["state"]
                del trial["_id"]
                data["stories"][ident] = story = trial
                story["state"] = target
                if o.reason:
                    story["last_reason"] = o.reason
                jira_line = None
                if src == "ENV_TESTING" and target not in ("DONE", "ENV_TESTING"):  # the story_done word was for that test run (R2-6)
                    for a in awaiting:
                        if a.get("type") == "story_done" and a.get("story") == ident and not a.get("consumed_at") and not a.get("voided_at"):
                            a["voided_at"] = _now()
                            extra.append("voided %s (story_done for %s: story left ENV_TESTING)" % (a["id"], ident))
                if target == "ENV_TESTING" and not _has_open_entry(data, "story_done", "story", ident):
                    _open_entry(data, "story_done", story=ident)
                etype = "start_story" if (target == "IN_PROGRESS" and src == "PLANNED") else "story_done" if target == "DONE" else None
                if etype:
                    e = rules.find_entry(awaiting, o.approved) or rules.latest_entry(awaiting, etype, "story", ident)
                    if e and e.get("approved_at") and not e.get("consumed_at") and not e.get("voided_at"):
                        e["consumed_at"] = _now()
                summary = "pass story %s %s → %s%s" % (ident, src, target, " — " + o.reason if o.reason else "")
            else:
                raise TurnstileError("kind must be pr or story")
            _ensure_start_story_entries(data)
            _recompute_next_actions(data)
            _side_effects(delivery, st, [summary] + extra, io, o.no_commit)
        for n in notes:
            print(n)
        if jira_line:
            print(jira_line)
        print("BOARD: publish %s" % (delivery / "board.html"))
        print("OK " + summary)
        return 0
    except StaleStateError as e:
        print("\n".join(notes + ["MISSING fresh state: %s" % e])); return 2
    except TurnstileError as e:
        print("\n".join(notes + ["MISSING %s" % e])); return 2

def jira_synced(delivery: pathlib.Path, ident: str, status: str, io: Optional[IO] = None) -> int:
    io = io or IO()
    delivery = pathlib.Path(delivery)
    try:
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            pr = st_mod.pr(st, ident)
            expected = rules.JIRA_FOR_PR_STATE.get(pr.get("state"))
            if status != expected:
                raise TurnstileError("Jira status for %s in state %s is %r, not %r" % (ident, pr.get("state"), expected, status))
            pr["jira"] = {"status": status, "synced": True}
            summary = "jira %s → %s (synced)" % (pr["ticket"], status)
            _side_effects(delivery, st, [summary], io, False)
        print("OK jira %s synced" % ident)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2

def approve(delivery: pathlib.Path, ah_id: str, io: Optional[IO] = None) -> int:
    """The lead said the word for an awaiting_human entry. Only the lead runs this, with TURNSTILE_LEAD=1 typed
    in the same command (the Bash guard refuses the command without it)."""
    io = io or IO()
    delivery = pathlib.Path(delivery)
    try:
        if os.environ.get("TURNSTILE_LEAD") != "1":
            raise TurnstileError("approve is the lead's action: the lead types `TURNSTILE_LEAD=1 turnstile approve %s` themself" % ah_id)
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            entry = rules.find_entry(st.data.get("awaiting_human", []), ah_id)
            if entry is None:
                raise TurnstileError("unknown awaiting_human id %s" % ah_id)
            if entry.get("voided_at"):
                raise TurnstileError("%s was voided at %s (head changed); a new entry is opened on the next READY" % (ah_id, entry["voided_at"]))
            if entry.get("approved_at"):
                print("OK %s already approved at %s" % (ah_id, entry["approved_at"])); return 0
            entry["approved_at"] = _now()
            entry["approved_via"] = APPROVED_VIA
            summary = "approved %s (%s %s by %s) approved_via: %s" % (ah_id, entry.get("type"), entry.get("pr") or entry.get("story"),
                                                                     entry.get("owner"), APPROVED_VIA)
            _side_effects(delivery, st, [summary], io, False)
        print("OK " + summary)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
