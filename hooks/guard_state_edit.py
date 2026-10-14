import os, pathlib, sys
sys.path.insert(0, os.path.dirname(__file__))
from _common import read_payload, block

# 2026-10-14 finding 1: inside the delivery dir the Write/Edit tools may touch evidence/, reports/, briefs/ (the tester's
# figma.png from the Figma MCP result lands here), plus plan.md and decisions.md (the orchestrator's). Everything else in
# the delivery dir (state.json, ledger.md, board.html, .state.lock, the root) is the CLI's. Outside it, only the two
# names stay refused (defence in depth). Paths are resolved, so `..` and symlinks cannot reach the root.
WRITABLE_SUBDIRS = ("evidence", "reports", "briefs")
ROOT_FILES = {"plan.md", "decisions.md"}
NAMES_ANYWHERE = ("state.json", "ledger.md")

def _refusal(fp: str, cwd: str):
    name = pathlib.PurePath(fp).name
    if name in NAMES_ANYWHERE:
        return "%s is written only by 'turnstile pass' (state changes only through a transition)" % name
    from _common import delivery_dir
    target = fp if os.path.isabs(fp) else os.path.join(cwd or ".", fp)
    root = None
    for start in (cwd or ".", os.path.dirname(target)):  # round 2: a cwd outside the workspace must not unlock board.html/.state.lock
        try:
            root = os.path.realpath(str(delivery_dir(start))); break
        except Exception:
            continue
    if root is None:
        return None
    rel = os.path.relpath(os.path.realpath(target), root)
    parts = rel.split(os.sep)
    if parts[0] == "..":
        return None
    if len(parts) == 1:
        if parts[0] in ROOT_FILES:
            return None
        return "%s resolves to the delivery root (%s); only plan.md and decisions.md are written there by the Write tool" % (fp, rel)
    if parts[0] in WRITABLE_SUBDIRS and not any(p in NAMES_ANYWHERE for p in parts):
        return None
    return "%s resolves to %s in the delivery dir; the Write/Edit tools write only evidence/, reports/, briefs/, plan.md and decisions.md" % (fp, rel)

def main():
    p = read_payload(); ti = p.get("tool_input") or {}
    fp = ti.get("file_path") if isinstance(ti, dict) else ""
    if isinstance(fp, str) and fp and os.environ.get("TURNSTILE_MIGRATION") != "1":
        why = _refusal(fp, p.get("cwd") or ".")
        if why:
            block(why + ". For a one-off migration run the tool with TURNSTILE_MIGRATION=1 in the environment, then 'turnstile reconcile'.")
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block("guard crashed (%s); failing closed." % e)
