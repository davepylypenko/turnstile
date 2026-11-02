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

def set_(delivery: Optional[pathlib.Path], assignment: str, epic: bool = False, io=None, no_commit: bool = False) -> int:
    from .pass_cmd import IO, _side_effects
    io = io or IO()
    try:
        if "=" not in assignment:
            raise TurnstileError("config set needs key=value (keys: %s)" % config.KEYS_HELP)
        key, value = assignment.split("=", 1); key = key.strip()
        section, agent = config.parse_key(key)
        reset = value.strip() == "default"
        parsed = None if reset else config.parse_value(key, value)
        verb = "unset" if reset else "set"
        if epic:
            if delivery is None:
                raise TurnstileError("--epic needs a delivery (no .turnstile found upward; pass --delivery)")
            delivery = pathlib.Path(delivery)
            with st_mod.locked(delivery):
                st = st_mod.load(delivery / "state.json"); e = st.data["epic"]
                if section == "models":
                    e.setdefault("models", models.defaults())[agent] = dict(models.DEFAULTS[agent]) if reset else parsed
                else:
                    e[key] = None if reset else parsed
                _side_effects(delivery, st, ["config %s %s (epic)" % (verb, key if reset else assignment)], io, no_commit)
                data = st.data
        else:
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
            data = st_mod.load(delivery / "state.json").data if delivery else None
        _print_effective(data, key)
        print("OK config %s %s (%s)" % (verb, key, "epic" if epic else "user")); return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2

def unset(delivery: Optional[pathlib.Path], key: str, epic: bool = False, io=None, no_commit: bool = False) -> int:
    return set_(delivery, key + "=default", epic=epic, io=io, no_commit=no_commit)
