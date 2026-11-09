import json, os, pathlib, tempfile
from typing import Dict, List, Optional, Tuple
from .errors import TurnstileError

MARKER = ".turnstile"
REGISTRY = "workspaces.json"
EPIC_ENV = "TURNSTILE_EPIC"

def registry_path() -> pathlib.Path:
    from . import config
    try:
        return config.user_path().parent / REGISTRY
    except TurnstileError:
        return config.default_user_dir() / REGISTRY

def _empty() -> dict:
    return {"epics": {}, "active": {}}

def load_registry() -> dict:
    p = registry_path()
    if not p.exists():
        return _empty()
    try:
        data = json.loads(p.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    epics = {k: v for k, v in (data.get("epics") or {}).items() if isinstance(v, dict)} if isinstance(data.get("epics"), dict) else {}
    active = data.get("active") if isinstance(data.get("active"), dict) else {}
    return {"epics": epics, "active": active}

def save_registry(reg: dict) -> pathlib.Path:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".%s." % p.name, suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(reg, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, str(p))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return p

def register(key: str, workspace, clone_root, delivery, active: bool = False) -> dict:
    reg = load_registry()
    reg["epics"][key] = {"workspace": str(workspace), "clone_root": str(clone_root), "delivery": str(delivery)}
    if active:
        reg["active"][str(clone_root)] = key
    save_registry(reg)
    return reg

def set_active(clone_root, key: str) -> None:
    reg = load_registry()
    reg["active"][str(clone_root)] = key
    save_registry(reg)

def _covers(root: str, cur: pathlib.Path) -> bool:
    try:
        r = pathlib.Path(root).resolve()
    except (OSError, RuntimeError):
        return False
    return cur == r or r in cur.parents

def entries_for(start: pathlib.Path, reg: Optional[dict] = None) -> List[Tuple[str, dict]]:
    reg = reg if reg is not None else load_registry()
    cur = pathlib.Path(start).resolve()
    return [(k, e) for k, e in sorted(reg["epics"].items()) if e.get("clone_root") and e.get("delivery") and _covers(e["clone_root"], cur)]

def resolve_registry(start: pathlib.Path, reg: Optional[dict] = None) -> Optional[Tuple[str, dict]]:
    reg = reg if reg is not None else load_registry()
    hits = entries_for(start, reg)
    if not hits:
        return None
    deepest = max((e["clone_root"] for _, e in hits), key=lambda r: len(pathlib.Path(r).resolve().parts))
    hits = [h for h in hits if pathlib.Path(h[1]["clone_root"]).resolve() == pathlib.Path(deepest).resolve()]
    if len(hits) == 1:
        return hits[0]
    active = reg["active"].get(deepest) or reg["active"].get(str(pathlib.Path(deepest).resolve()))
    for k, e in hits:
        if k == active:
            return k, e
    raise TurnstileError("several epics in %s: %s — run turnstile start <KEY>" % (deepest, ", ".join(k for k, _ in hits)))

def marker_delivery(cur: pathlib.Path) -> Optional[pathlib.Path]:
    for d in [cur] + list(cur.parents):
        marker = d / MARKER
        if marker.exists():
            lines = [ln.strip() for ln in marker.read_text().splitlines() if ln.strip()]
            if not lines:
                raise TurnstileError("%s is empty; it must hold the delivery dir path" % marker)
            target = lines[0]
            return (d / target).resolve() if not pathlib.Path(target).is_absolute() else pathlib.Path(target)
    return None

def _registered_delivery(key: str, entry: dict, hint: str) -> pathlib.Path:
    d = pathlib.Path(entry.get("delivery") or "")
    if not (d / "state.json").exists():
        raise TurnstileError("the registered workspace of %s has no state.json at %s (%s); run turnstile start %s" % (key, d, hint, key))
    return d

def find_delivery(start: pathlib.Path, override: Optional[str]) -> pathlib.Path:
    if override:
        p = pathlib.Path(override).expanduser().resolve()
        if not (p / "state.json").exists():
            raise TurnstileError("no state.json in %s" % p)
        return p
    cur = start.resolve()
    found = marker_delivery(cur)
    if found is not None:
        return found
    reg = load_registry()
    env_key = os.environ.get(EPIC_ENV)
    if env_key:
        entry = reg["epics"].get(env_key)
        if not entry:
            raise TurnstileError("%s=%s names no registered epic (known: %s); run turnstile start %s" % (EPIC_ENV, env_key, ", ".join(sorted(reg["epics"])) or "none", env_key))
        return _registered_delivery(env_key, entry, EPIC_ENV)
    hit = resolve_registry(cur, reg)
    if hit:
        return _registered_delivery(hit[0], hit[1], "registry")
    raise TurnstileError("no %s found from %s upward and no epic registered for it; run turnstile start <KEY> or pass --delivery <dir>" % (MARKER, cur))

def known_keys(start: pathlib.Path) -> List[str]:
    try:
        return [k for k, _ in entries_for(start)]
    except TurnstileError:
        return []

def ensure_registered(delivery: pathlib.Path) -> None:
    """A workspace resolved through its marker registers itself once, so the next session needs no cd into it."""
    try:
        from . import state as st_mod, workspace
        rec = workspace.load(delivery)
        if not rec or not rec.get("clone_root") or not rec.get("workspace"):
            return
        key = (st_mod.load(pathlib.Path(delivery) / "state.json").data.get("epic") or {}).get("key")
        if not key:
            return
        reg = load_registry()
        want = {"workspace": rec["workspace"], "clone_root": rec["clone_root"], "delivery": str(pathlib.Path(delivery).resolve())}
        if reg["epics"].get(key) != want:
            reg["epics"][key] = want
            save_registry(reg)
    except Exception:
        return
