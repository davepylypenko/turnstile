import copy, json, pathlib, re
from typing import List, Optional, Tuple
from . import state as st_mod
from .errors import TurnstileError

BLOCK_RX = re.compile(r"```json[ \t]+turnstile-stories[ \t]*\n(.*?)\n```", re.S)
ID_RX = re.compile(r"^S\d+$")
REQUIRED = ("title", "tickets", "repos", "branch")
DEFAULTS = {"after": [], "parallel_with": [], "test_cases": [], "figma": [], "env_slot": {}, "human_review_units": []}
KEEP = ("state", "evidence", "next_action", "last_reason")

def stories_from_plan(text: str) -> dict:
    m = BLOCK_RX.search(text or "")
    if not m:
        raise TurnstileError("plan.md has no ```json turnstile-stories block")
    try:
        raw = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise TurnstileError("turnstile-stories block is not valid JSON: %s" % e)
    if not isinstance(raw, dict) or not raw:
        raise TurnstileError("turnstile-stories must be a non-empty object keyed by story id")
    out = {}
    for sid, s in raw.items():
        if not ID_RX.match(sid):
            raise TurnstileError("story id %r must look like S1" % sid)
        if not isinstance(s, dict):
            raise TurnstileError("story %s must be an object" % sid)
        for k in REQUIRED:
            if not s.get(k):
                raise TurnstileError("story %s lacks %r" % (sid, k))
        full = copy.deepcopy(DEFAULTS); full.update(copy.deepcopy(s))
        out[sid] = full
    for sid, s in out.items():
        for key in ("after", "parallel_with"):
            for ref in s[key]:
                if ref not in out:
                    raise TurnstileError("story %s.%s references unknown story %s" % (sid, key, ref))
    return out

def merge_stories(existing: dict, planned: dict) -> Tuple[dict, List[str]]:
    """Stories past PLANNED keep their state and evidence; their branch cannot change (the stack is on it); a change of
    tickets or repos is allowed with a WARN line (2026-10-14 minor 9)."""
    merged, warnings = {}, []
    for sid, s in planned.items():
        cur = existing.get(sid)
        merged[sid] = dict(s)
        if cur:
            merged[sid].update({k: cur[k] for k in KEEP if k in cur})
            if cur.get("state") != "PLANNED":
                if cur.get("branch") and s.get("branch") != cur.get("branch"):
                    raise TurnstileError("story %s is %s: its branch cannot change from %s to %s in a re-plan (finish or reopen it first)"
                                         % (sid, cur.get("state"), cur.get("branch"), s.get("branch")))
                for key in ("tickets", "repos"):
                    if cur.get(key) is not None and s.get(key) != cur.get(key):
                        warnings.append("WARN %s is %s: %s changed from %s to %s" % (sid, cur.get("state"), key, cur.get(key), s.get(key)))
        else:
            merged[sid].update({"state": "PLANNED", "evidence": {}, "next_action": ""})
    for sid, cur in existing.items():
        if sid not in planned and cur.get("state") != "PLANNED":
            raise TurnstileError("cannot drop story %s in state %s; keep it in plan.md" % (sid, cur.get("state")))
    return merged, warnings

def run(delivery, io=None, no_commit: bool = False) -> int:
    from .pass_cmd import IO, _side_effects, _open_entry, _ensure_start_story_entries, _recompute_next_actions, _now
    io = io or IO()
    delivery = pathlib.Path(delivery)
    try:
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json"); data = st.data
            plan_path = delivery / "plan.md"
            if not plan_path.exists():
                raise TurnstileError("no plan.md in %s" % delivery)
            text = plan_path.read_text()
            planned = stories_from_plan(text)
            before = set(data.get("stories") or {})
            data["stories"], warnings = merge_stories(data.get("stories") or {}, planned)
            digest = st_mod.digest(text)
            data["epic"]["plan"] = {"path": "plan.md", "submitted_at": _now(), "digest": digest}
            extra = []
            for a in data.setdefault("awaiting_human", []):
                if a.get("type") == "plan" and not a.get("voided_at"):
                    a["voided_at"] = _now(); extra.append("voided %s (plan: superseded by a new submission)" % a["id"])
            entry = _open_entry(data, "plan", payload="plan.md", digest=digest)
            _ensure_start_story_entries(data)
            _recompute_next_actions(data)
            new = sorted(set(planned) - before)
            summary = "plan submitted: %d stories (%d new%s), approval %s" % (len(planned), len(new), ": " + ", ".join(new) if new else "", entry["id"])
            _side_effects(delivery, st, [summary] + extra + warnings, io, no_commit)
        for w in warnings:
            print(w)
        print("PLAN: %d stories (%d new)" % (len(planned), len(new)))
        print("APPROVAL: the lead types: ! TURNSTILE_LEAD=1 turnstile approve %s" % entry["id"])
        print("OK " + summary)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
