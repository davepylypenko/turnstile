import datetime, json, pathlib
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
    b = (((data or {}).get("epic") or {}).get("knowledge") or {}).get("branch")
    return b or io.current_branch(delivery)

def line(rec: Optional[dict]) -> str:
    if not rec:
        return "SYNC: unknown (no push recorded on this machine yet) — run: turnstile sync"
    if rec.get("pushed"):
        return "SYNC: pushed %s at %s" % (rec.get("head"), rec.get("at"))
    return "SYNC: NOT PUSHED since %s (%s) — run: turnstile sync" % (rec.get("at"), rec.get("reason") or "?")

def missing_for(delivery, gated: bool) -> list:
    rec = load(delivery)
    if gated and rec and rec.get("pushed") is False:
        return ["MISSING epic branch on origin: not pushed since %s (%s) — run: turnstile sync, then re-run" % (rec.get("at"), rec.get("reason") or "?")]
    return []

def _head(io, delivery) -> Optional[str]:
    try:
        return io.head_sha(delivery)
    except Exception:
        return None

def guard_behind(io, delivery, br: str) -> None:
    try:
        io.git_fetch(delivery, br)
    except Exception as e:
        print("WARN fetch origin %s failed (%s): proceeding on local facts" % (br, str(e)[:120])); return
    behind, ahead = io.behind_ahead(delivery, br)
    if behind:
        raise TurnstileError("epic branch %s behind origin by %d commit(s)%s — run: turnstile sync" % (br, behind, " (and ahead by %d)" % ahead if ahead else ""))

def push(io, delivery, br: str, no_push: bool = False) -> dict:
    head = _head(io, delivery)
    if no_push:
        print("WARN: not pushed: --no-push"); return record(delivery, False, head, "--no-push")
    try:
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
            if behind and ahead:
                raise TurnstileError("histories diverged on %s: local %s ahead by %d, origin %s ahead by %d; turnstile never rebases or forces — "
                                     "merge origin/%s by hand (the lead), then: turnstile sync" % (br, _head(io, delivery), ahead, io.sha(delivery, "origin/" + br), behind, br))
            if behind:
                io.git_ff(delivery, br); print("fast-forwarded %s by %d commit(s) from origin" % (br, behind))
            rec = push(io, delivery, br)
        if not rec["pushed"]:
            print("MISSING " + line(rec)); return 2
        print("OK sync %s → origin/%s" % (rec["head"], br)); return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
