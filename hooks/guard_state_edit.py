import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload

def main():
    fp = ((read_payload().get("tool_input") or {}).get("file_path") or "")
    if fp.endswith("/state.json"):
        print("turnstile: state.json is written only by 'turnstile pass'; run 'turnstile reconcile' to see what you changed.")
    sys.exit(0)

if __name__ == "__main__":
    main()
