import json, os, pathlib, sys

def plugin_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or pathlib.Path(__file__).resolve().parents[1])

def read_payload() -> dict:
    """The hook's stdin JSON. Anything that is not an object is returned as {} so the guards fail closed."""
    try:
        p = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}
    return p if isinstance(p, dict) else {}

def block(msg: str) -> None:
    sys.stderr.write("turnstile: " + msg + "\n"); sys.exit(2)

def delivery_dir(cwd: str) -> pathlib.Path:
    """The epic's delivery dir. 2026-10-14 review: resolved from the session's project dir (`CLAUDE_PROJECT_DIR`, set by Claude Code
    for hooks; an agent cannot change it) before the Bash cwd, which an agent controls — else a `.turnstile` + forged state.json in
    a scratch dir would unlock thread replies and re-requests. Falls back to the cwd when the project holds no `.turnstile`."""
    sys.path.insert(0, str(plugin_root()))
    from turnstile_cli import paths
    anchor = os.environ.get("CLAUDE_PROJECT_DIR")
    if anchor:
        try:
            return paths.find_delivery(pathlib.Path(anchor), None)
        except Exception:
            pass
    return paths.find_delivery(pathlib.Path(cwd or "."), None)

def managed(cwd: str, *starts) -> bool:
    """True inside a turnstile workspace: a `.turnstile` marker on or above the session's project dir (`CLAUDE_PROJECT_DIR`), the
    cwd or any extra start, or a workspace the user's registry (`turnstile start`) resolves for one of them. Outside one every
    guard is inert (2026-11-04, lead's decision); a marker that is present but broken keeps the guards failing closed, so only
    the marker's existence is asked here."""
    sys.path.insert(0, str(plugin_root()))
    from turnstile_cli import paths
    anchor = os.environ.get("CLAUDE_PROJECT_DIR")
    dirs = []
    for s in ([anchor] if anchor else []) + [cwd or "."] + [x for x in starts if x]:
        try:
            dirs.append(pathlib.Path(os.path.expanduser(s)).resolve())
        except (OSError, RuntimeError, ValueError):
            continue
    if any((d / paths.MARKER).exists() for cur in dirs for d in [cur] + list(cur.parents)):
        return True
    reg = paths.load_registry()
    env_key = os.environ.get(paths.EPIC_ENV)
    if env_key and env_key in reg["epics"]:
        return True
    for cur in dirs:
        try:
            if paths.resolve_registry(cur, reg) is not None:
                return True
        except Exception:
            continue
    return False

def load_state(cwd: str):
    sys.path.insert(0, str(plugin_root()))
    from turnstile_cli import state
    return state.load(delivery_dir(cwd) / "state.json").data

def agent_role(payload: dict) -> str:
    """Round 2 R2-12: the role the calling agent runs as. An agent's own frontmatter hooks run the guards with TURNSTILE_ROLE
    set; a payload that names the subagent (`agent_type: turnstile:<role>`) is the fallback. Empty for the orchestrator."""
    role = os.environ.get("TURNSTILE_ROLE") or ""
    if not role:
        for key in ("agent_type", "agent_name", "subagent_type"):
            v = payload.get(key)
            if isinstance(v, str) and v.startswith("turnstile:"):
                role = v.split(":", 1)[1]; break
    return role.strip().lower()
