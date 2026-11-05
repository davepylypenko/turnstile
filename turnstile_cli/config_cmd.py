import pathlib
from typing import Optional
from . import state as st_mod, config, models
from .errors import TurnstileError

def _print_effective(data: Optional[dict], key: Optional[str] = None) -> None:
    eff = config.effective(data)
    for line in config.lines(eff):
        if key is None or line.startswith(key + " "):
            print(line)

def list_(delivery: Optional[pathlib.Path]) -> int:
    try:
        p = config.user_path(); print("USER_CONFIG: %s%s" % (p, "" if p.exists() else " (absent)"))
        if delivery is None:
            print("EPIC: none (no delivery found: user and default layers only)")
        _print_effective(st_mod.load(pathlib.Path(delivery) / "state.json").data if delivery else None)
        print("OK config list"); return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2

def _apply_epic(e: dict, key: str, parsed, reset: bool) -> None:
    section, agent = config.parse_key(key)
    if section == "models":
        m = e.setdefault("models", {})
        if reset:
            m.pop(agent, None)
        else:
            m[agent] = parsed
    else:
        e[key] = None if reset else parsed

def _epic_value(e: dict, key: str):
    section, agent = config.parse_key(key)
    return (e.get("models") or {}).get(agent) if section == "models" else e.get(key)

def set_(delivery: Optional[pathlib.Path], assignment: str, epic: bool = False, io=None, no_commit: bool = False, no_push: bool = False) -> int:
    from .pass_cmd import IO, _side_effects, _open_entry
    io = io or IO()
    try:
        if "=" not in assignment:
            raise TurnstileError("config set needs key=value (keys: %s)" % config.KEYS_HELP)
        key, value = assignment.split("=", 1); key = key.strip()
        section, agent = config.parse_key(key)
        if key == "flag" and not epic:
            raise TurnstileError("flag is epic state (one flag per epic): turnstile config set flag=<name> --epic")
        reset = value.strip() == "default"
        parsed = None if reset else config.parse_value(key, value)
        verb = "unset" if reset else "set"
        if epic:
            if delivery is None:
                raise TurnstileError("--epic needs a delivery (no .turnstile found upward; pass --delivery)")
            delivery = pathlib.Path(delivery)
            with st_mod.locked(delivery):
                st = st_mod.load(delivery / "state.json")
                entry = _open_entry(st.data, "config", payload=key, old=_epic_value(st.data["epic"], key), new=parsed, reset=reset)
                _side_effects(delivery, st, ["config %s %s proposed for the epic (%s awaits the lead)" % (verb, key if reset else assignment, entry["id"])], io, no_commit, no_push)
            print("APPROVAL: the lead types: ! TURNSTILE_LEAD=1 turnstile approve %s" % entry["id"])
            print("THEN: turnstile config apply %s" % entry["id"])
            print("OK config %s %s proposed (epic, %s)" % (verb, key, entry["id"])); return 0
        u = config.load_user()
        if section == "models":
            m = u.setdefault("models", {})
            if reset:
                m.pop(agent, None)
            else:
                m[agent] = parsed
            if not m:
                u.pop("models")
        elif reset:
            u.pop(key, None)
        else:
            u[key] = parsed
        config.save_user(u)
        _print_effective(st_mod.load(delivery / "state.json").data if delivery else None, key)
        print("OK config %s %s (user)" % (verb, key)); return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2

def apply(delivery: pathlib.Path, ah_id: str, io=None, no_commit: bool = False, no_push: bool = False) -> int:
    from .pass_cmd import IO, _side_effects, _now
    from . import rules
    io = io or IO()
    try:
        if delivery is None:
            raise TurnstileError("config apply needs a delivery (no .turnstile found upward; pass --delivery)")
        delivery = pathlib.Path(delivery)
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json"); e = st.data["epic"]
            entry = rules.find_entry(st.data.get("awaiting_human"), ah_id)
            key = (entry or {}).get("payload")
            missing = []
            rules.check_approved_entry(ah_id, "config", "payload", key, st.data.get("awaiting_human"), missing)
            if missing:
                raise TurnstileError("; ".join(m[len("MISSING "):] for m in missing))
            if _epic_value(e, key) != entry.get("old"):
                raise TurnstileError("%s changed since %s was proposed (was %r, now %r): propose again" % (key, ah_id, entry.get("old"), _epic_value(e, key)))
            _apply_epic(e, key, entry.get("new"), bool(entry.get("reset")))
            entry["consumed_at"] = _now()
            verb = "unset" if entry.get("reset") else "set"
            shown = key if entry.get("reset") else "%s=%s" % (key, config.fmt_model(entry["new"]) if isinstance(entry.get("new"), dict) else entry.get("new"))
            _side_effects(delivery, st, ["config %s %s (epic, approved %s)" % (verb, shown, ah_id)], io, no_commit, no_push)
            data = st.data
        _print_effective(data, key)
        print("OK config %s %s (epic, %s)" % (verb, key, ah_id)); return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2

def unset(delivery: Optional[pathlib.Path], key: str, epic: bool = False, io=None, no_commit: bool = False, no_push: bool = False) -> int:
    return set_(delivery, key + "=default", epic=epic, io=io, no_commit=no_commit, no_push=no_push)
