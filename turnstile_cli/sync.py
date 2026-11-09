import datetime, json, pathlib, re
from typing import Optional
from . import state as st_mod
from .errors import TurnstileError

FILE = ".sync.json"

def load(delivery) -> Optional[dict]:
    p = pathlib.Path(delivery) / FILE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None

def record(delivery, pushed: bool, head: Optional[str], reason: Optional[str] = None) -> dict:
    rec = {"pushed": pushed, "head": head, "at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
    if reason:
        rec["reason"] = reason
    st_mod.write_atomic(pathlib.Path(delivery) / FILE, json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return rec

def branch(io, delivery, data: Optional[dict]) -> str:
    b = (((data or {}).get("epic") or {}).get("knowledge") or {}).get("branch") or io.current_branch(delivery)
    if not b:
        raise TurnstileError("the knowledge worktree is on a detached HEAD and epic.knowledge.branch is unset; check out the epic branch")
    return b

def line(rec: Optional[dict]) -> str:
    if not rec:
        return "SYNC: unknown (no push recorded on this machine yet) — run: turnstile sync"
    if rec.get("pushed"):
        return "SYNC: pushed %s at %s" % (rec.get("head"), rec.get("at"))
    return "SYNC: NOT PUSHED since %s (%s) — run: turnstile sync" % (rec.get("at"), rec.get("reason") or "?")

def missing_for(delivery, gated: bool) -> list:
    if not gated:
        return []
    rec = load(delivery)
    if rec is None:
        return ["MISSING a recorded push of the epic branch on this machine (%s absent or unreadable) — run: turnstile sync, then re-run" % FILE]
    if rec.get("pushed") is not True:
        return ["MISSING epic branch on origin: not pushed since %s (%s) — run: turnstile sync, then re-run" % (rec.get("at"), rec.get("reason") or "?")]
    return []

def _head(io, delivery) -> Optional[str]:
    try:
        return io.head_sha(delivery)
    except Exception:
        return None

GENERATED = re.compile(r"^(?:board\.html|boards/[^/]+\.html)$")

def bring_up_to_date(io, delivery, br: str, behind: int, ahead: int) -> str:
    if not ahead:
        io.git_ff(delivery, br)
        return "sync: fast-forwarded %s by %d commit(s)" % (br, behind)
    conflicts = io.git_merge(delivery, br)
    hard = [c for c in conflicts if not GENERATED.match(c)]
    if hard:
        io.git_merge_abort(delivery)
        raise TurnstileError("histories diverged on %s: local %s ahead by %d, origin %s ahead by %d, and the merge conflicts in %s; turnstile never "
                             "rebases or forces — merge origin/%s by hand, then: turnstile sync" % (br, _head(io, delivery), ahead, io.sha(delivery, "origin/" + br), behind, ", ".join(hard), br))
    if conflicts:
        io.git_finish_generated(delivery, conflicts)
    return "sync: merged origin/%s (%d theirs, %d ours)" % (br, behind, ahead)

def guard_behind(io, delivery, br: str, strict: bool = False) -> None:
    try:
        io.git_fetch(delivery, br)
    except Exception as e:
        if strict:
            raise TurnstileError("fetch failed: %s — fix the network or run with --no-push for local-only work" % str(e)[:160])
        print("WARN fetch origin %s failed (%s): proceeding on local facts" % (br, str(e)[:120])); return
    behind, ahead = io.behind_ahead(delivery, br)
    if behind:
        try:
            entry = bring_up_to_date(io, delivery, br, behind, ahead)
        except TurnstileError as e:
            raise TurnstileError("epic branch %s behind origin by %d commit(s)%s and the merge failed: %s" % (br, behind, " (and ahead by %d)" % ahead if ahead else "", e))
        raise TurnstileError("%s; the delivery changed under this command, so nothing was written — run it again" % entry)

def push(io, delivery, br: str, no_push: bool = False) -> dict:
    head = _head(io, delivery)
    if no_push:
        print("WARN: not pushed: --no-push"); return record(delivery, False, head, "--no-push")
    try:
        current = io.current_branch(delivery)
        if current != br:
            raise TurnstileError("worktree is on %s, not %s (detached HEAD or renamed branch); check out %s first" % (current or "a detached HEAD", br, br))
        io.git_push(delivery, br)
    except Exception as e:
        reason = str(e)[:200]; print("WARN: not pushed: %s" % reason); return record(delivery, False, head, reason)
    return record(delivery, True, head)

def run(delivery, io=None) -> int:
    from .pass_cmd import IO
    io = io or IO(); delivery = pathlib.Path(delivery)
    try:
        with st_mod.locked(delivery):
            br = branch(io, delivery, st_mod.load(delivery / "state.json").data)
            try:
                io.git_fetch(delivery, br)
            except Exception as e:
                raise TurnstileError("fetch origin %s failed: %s" % (br, str(e)[:200]))
            behind, ahead = io.behind_ahead(delivery, br)
            merged = False
            if behind:
                entry = bring_up_to_date(io, delivery, br, behind, ahead)
                if ahead:
                    from . import pass_cmd
                    pass_cmd._side_effects(delivery, st_mod.load(delivery / "state.json"), [entry], io, False, False)
                    print(entry); merged = True
                else:
                    print("fast-forwarded %s by %d commit(s) from origin" % (br, behind))
            rec = (load(delivery) if merged else None) or push(io, delivery, br)
        if not rec["pushed"]:
            print("MISSING " + line(rec)); return 2
        print("OK sync %s → origin/%s" % (rec["head"], br)); return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
