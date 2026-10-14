import pathlib, re
from typing import List, Optional
from . import state as st_mod
from .errors import TurnstileError

STATES = ["todo", "ai", "testing", "done"]
PR_RX = re.compile(r"^[A-Za-z0-9_.-]+#\d+$")

def next_id(bugs: List[dict]) -> str:
    nums = [int(b["id"][1:]) for b in bugs if re.match(r"^b\d+$", str(b.get("id", "")))]
    return "b%02d" % (max(nums or [0]) + 1)

def _check_pr(pr: Optional[str]) -> None:
    if pr and not PR_RX.match(pr):
        raise TurnstileError("pr must look like repo#123 (got %r)" % pr)

def _commit(delivery: pathlib.Path, st, summary: str, io) -> int:
    from .pass_cmd import _side_effects, _recompute_next_actions
    _recompute_next_actions(st.data)
    _side_effects(delivery, st, [summary], io, False)
    print("OK " + summary); return 0

def add(delivery, story: str, title: str, source: str, pr: Optional[str] = None, figma: Optional[str] = None, note: str = "",
        case: Optional[str] = None, io=None) -> int:
    from .pass_cmd import IO, _now_s
    io = io or IO(); delivery = pathlib.Path(delivery)
    try:
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            if story not in (st.data.get("stories") or {}):
                raise TurnstileError("unknown story %s" % story)
            if not (title or "").strip():
                raise TurnstileError("--title is required")
            _check_pr(pr)
            bugs = st.data.setdefault("bugs", [])
            if case:  # 2026-10-14 finding 5: one bug per story + case; a persisting fail reopens it instead of duplicating
                dup = next((b for b in bugs if b.get("story") == story and b.get("case") == case), None)
                if dup:
                    raise TurnstileError("bug %s already covers case %s of %s (state %s): reopen it with 'turnstile bug set %s --state todo', or record the "
                                         "run and it is reopened automatically" % (dup["id"], case, story, dup.get("state"), dup["id"]))
            now = _now_s()
            bug = {"id": next_id(bugs), "story": story, "case": case, "title": title.strip(), "source": source, "pr": pr, "figma": figma,
                   "state": "todo", "note": note or "", "runs": [], "created_at": now, "updated_at": now}
            bugs.append(bug)
            return _commit(delivery, st, "bug %s added (%s%s): %s" % (bug["id"], story, ", case " + case if case else "", bug["title"]), io)
    except TurnstileError as e:
        print("MISSING %s" % e); return 2

def set_(delivery, bug_id: str, state: Optional[str] = None, pr: Optional[str] = None, note: Optional[str] = None, io=None) -> int:
    from .pass_cmd import IO
    io = io or IO(); delivery = pathlib.Path(delivery)
    try:
        if state is None and pr is None and note is None:
            raise TurnstileError("nothing to set: pass --state, --pr or --note")
        if state is not None and state not in STATES:
            raise TurnstileError("state must be one of %s" % ", ".join(STATES))
        _check_pr(pr)
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            bug = next((b for b in st.data.get("bugs", []) if b.get("id") == bug_id), None)
            if bug is None:
                raise TurnstileError("unknown bug %s" % bug_id)
            changes = []
            if state is not None and state != bug.get("state"):
                bug["state"] = state; changes.append("→ %s" % state)
            if pr is not None:
                bug["pr"] = pr; changes.append("pr %s" % pr)
            if note is not None:
                bug["note"] = note; changes.append("note")
            if changes:
                from .pass_cmd import _now_s
                bug["updated_at"] = _now_s()
            return _commit(delivery, st, "bug %s %s" % (bug_id, ", ".join(changes) or "unchanged"), io)
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
