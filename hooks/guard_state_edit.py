import os, pathlib, sys
sys.path.insert(0, os.path.dirname(__file__))
from _common import read_payload, block

def main():
    ti = read_payload().get("tool_input") or {}
    fp = ti.get("file_path") if isinstance(ti, dict) else ""
    if isinstance(fp, str) and pathlib.PurePath(fp).name == "state.json" and os.environ.get("TURNSTILE_MIGRATION") != "1":
        block("state.json is written only by 'turnstile pass' (state changes only through a transition). "
              "For a one-off migration run the tool with TURNSTILE_MIGRATION=1 in the environment, then 'turnstile reconcile'.")
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block("guard crashed (%s); failing closed." % e)
