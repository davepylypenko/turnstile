import os, pathlib, re
from dataclasses import dataclass
from typing import Optional
from . import state as st_mod, sync, workspace
from .init_cmd import InitIO, epic_branch_name, write_workspace_claude_md, next_lines
from .errors import TurnstileError

@dataclass
class AttachOptions:
    epic: str
    knowledge: Optional[str] = None
    clone_root: Optional[str] = None
    workspace: Optional[str] = None
    workitem: Optional[str] = None
    chat_language: Optional[str] = None

NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

def _find_delivery(wt: pathlib.Path, workitem: Optional[str]) -> pathlib.Path:
    if workitem:
        if not NAME_RX.match(workitem) or workitem in (".", ".."):
            raise TurnstileError("--workitem must be a folder name like my-epic (got %r)" % workitem)
        d = wt / "context" / "workitems" / workitem / "delivery"
        if not (d / "state.json").exists():
            raise TurnstileError("no state.json in %s" % d)
        return d
    found = sorted(wt.glob("context/workitems/*/delivery/state.json"))
    if len(found) != 1:
        raise TurnstileError("%s delivery dir(s) under %s/context/workitems (%s); pass --workitem <name>"
                             % (len(found) or "no", wt, ", ".join(p.parent.parent.name for p in found) or "none"))
    return found[0].parent

def run(o: AttachOptions, io: Optional[InitIO] = None) -> int:
    from .reconcile import cli as status_cli
    io = io or InitIO()
    try:
        cwd = pathlib.Path.cwd(); root = workspace.detect_root(cwd, o.clone_root, o.knowledge, [], io)
        knowledge = workspace.resolve_knowledge(root, o.knowledge)
        ws = pathlib.Path(o.workspace).expanduser().resolve() if o.workspace else workspace.default_workspace(root, o.epic)
        branch = epic_branch_name(o.epic); wt = ws / knowledge.name; marker = ws / ".turnstile"
        if marker.exists() and not marker.read_text().strip().startswith(knowledge.name + "/context/workitems/"):
            raise TurnstileError("%s points at another delivery (%s); one epic per workspace" % (marker, marker.read_text().strip()))
        try:
            io.git(["fetch", "origin", branch], knowledge)
        except TurnstileError as e:
            raise TurnstileError("origin has no %s to attach to (%s)" % (branch, e))
        synced = True
        if wt.exists():
            current = io.git(["branch", "--show-current"], wt).strip()
            if current != branch:
                raise TurnstileError("%s exists on branch %r, not %s; move it or attach from another workspace" % (wt, current, branch))
            synced = _fast_forward(io, wt, branch)
        else:
            ws.mkdir(parents=True, exist_ok=True)
            if io.git(["branch", "--list", branch], knowledge).strip():
                io.git(["worktree", "add", str(wt), branch], knowledge); synced = _fast_forward(io, wt, branch)
            else:
                io.git(["worktree", "add", "-b", branch, str(wt), "origin/" + branch], knowledge)
        delivery = _find_delivery(wt, o.workitem); rel = os.path.relpath(str(delivery), str(ws))
        if marker.exists() and marker.read_text().strip() != rel:
            raise TurnstileError("%s points at another delivery (%s); one epic per workspace" % (marker, marker.read_text().strip()))
        data = st_mod.load(delivery / "state.json").data; key = data["epic"].get("key"); repos = data["epic"].get("repos") or {}
        if key != o.epic:
            raise TurnstileError("%s belongs to epic %s, not %s" % (delivery, key, o.epic))
        foreign = workspace.foreign_entries(ws, [knowledge.name] + list(repos))
        if foreign:
            raise TurnstileError("%s holds foreign entries (%s); a turnstile workspace holds only the worktrees and its markers" % (ws, ", ".join(foreign[:5])))
        clones = workspace.clone_paths(root, repos, {})
        repo_wts = workspace.ensure_repo_worktrees(ws, clones, repos, key, io)
        marker.write_text(rel + "\n")
        target = write_workspace_claude_md(ws, key, rel, o.chat_language or data["epic"].get("chat_language") or "English",
                                           workspace.claude_md_repos(repos, repo_wts, key))
        workspace.record(delivery, ws, root, wt, repo_wts)
        head = io.git(["rev-parse", "HEAD"], wt).strip() or None
        sync.record(delivery, synced, head, None if synced else "not fast-forwarded to origin/%s" % branch)
        print("WORKSPACE: %s (clone root %s)" % (ws, root)); print("WORKTREE: %s (%s)" % (wt, branch))
        for line in workspace.repo_lines(repos, repo_wts, key):
            print(line)
        print("DELIVERY: %s" % delivery); print("CLAUDE_MD: %s" % target)
        print("NEXT: ask the lead once (skill § preferences): own review skill? other model/effort per agent? Record with "
              "turnstile config set <key>=<value> [--epic]; confirm with turnstile config list")
        for line in next_lines(ws, cwd):
            print(line)
        print("OK attach %s" % key)
        return status_cli(delivery, status=True)
    except TurnstileError as e:
        print("MISSING %s" % e); return 2

def _fast_forward(io: InitIO, wt: pathlib.Path, branch: str) -> bool:
    try:
        io.git(["merge", "-q", "--ff-only", "origin/" + branch], wt); return True
    except TurnstileError as e:
        print("WARN %s not fast-forwarded to origin (%s) — run: turnstile sync" % (branch, e)); return False
