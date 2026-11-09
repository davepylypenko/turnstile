import pathlib
from typing import List
from . import state as st_mod
from .errors import TurnstileError

KEYS = ("gate", "gate_check", "slack", "ci_ignore", "copilot", "branch_prefix", "base", "epic_branch")
NULLABLE = ("gate", "gate_check", "branch_prefix")

def _parse(key: str, value: str):
    if key == "copilot":
        if value.lower() not in ("true", "false"):
            raise TurnstileError("copilot takes true or false (got %r)" % value)
        return value.lower() == "true"
    if key == "ci_ignore":
        return [x.strip() for x in value.split(",") if x.strip()]
    if key in NULLABLE and value.lower() in ("null", "none"):
        return None
    if not value.strip():
        raise TurnstileError("%s needs a value (null clears gate, gate_check and branch_prefix)" % key)
    return value

def set_(delivery, name: str, assignments: List[str], io=None, no_commit: bool = False, no_push: bool = False) -> int:
    from .pass_cmd import IO, _side_effects, _recompute_next_actions
    io = io or IO(); delivery = pathlib.Path(delivery)
    try:
        if not assignments:
            raise TurnstileError("repo set <name> key=value … (keys: %s)" % ", ".join(KEYS))
        parsed = {}
        for a in assignments:
            key, sep, value = a.partition("=")
            if not sep or key.strip() not in KEYS:
                raise TurnstileError("%r is not key=value with a key of %s" % (a, ", ".join(KEYS)))
            parsed[key.strip()] = _parse(key.strip(), value)
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            repos = st.data["epic"].setdefault("repos", {})
            if name not in repos:
                raise TurnstileError("%s is not an epic repo (%s)" % (name, ", ".join(sorted(repos)) or "none"))
            repos[name].update(parsed)
            _recompute_next_actions(st.data)
            summary = "repo %s set %s" % (name, " ".join("%s=%s" % (k, parsed[k]) for k in parsed))
            _side_effects(delivery, st, [summary], io, no_commit, no_push)
        print("OK " + summary); return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
