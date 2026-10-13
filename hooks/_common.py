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
    sys.path.insert(0, str(plugin_root()))
    from turnstile_cli import paths
    return paths.find_delivery(pathlib.Path(cwd or "."), None)

def load_state(cwd: str):
    sys.path.insert(0, str(plugin_root()))
    from turnstile_cli import state
    return state.load(delivery_dir(cwd) / "state.json").data
