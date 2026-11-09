import datetime, json, pathlib
from typing import Dict, List, Optional
from . import state as st_mod
from .errors import TurnstileError

FILE = ".workspace.json"
DEFAULT_KNOWLEDGE = "pdffiller-knowledge"
OWN_ENTRIES = {".turnstile", "CLAUDE.md", "CLAUDE.md.turnstile", ".claude", ".DS_Store"}

def ws_branch(key: str) -> str:
    return "ws/" + key.lower()

def load(delivery) -> Optional[dict]:
    p = pathlib.Path(delivery) / FILE
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("repos"), dict) else None

def record(delivery, workspace: pathlib.Path, clone_root: pathlib.Path, knowledge_wt: pathlib.Path, repos: Dict[str, pathlib.Path], member: Optional[str] = None) -> dict:
    rec = {"workspace": str(workspace), "clone_root": str(clone_root), "knowledge": str(knowledge_wt),
           "repos": {r: str(p) for r, p in sorted(repos.items())}, "at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
    if member:
        rec["member"] = member
    st_mod.write_atomic(pathlib.Path(delivery) / FILE, json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return rec

def _is_clone(p: pathlib.Path) -> bool:
    return (p / ".git").exists()

def _origin(io, clone: pathlib.Path) -> str:
    try:
        return io.git(["remote", "get-url", "origin"], clone).strip()
    except TurnstileError:
        return ""

def _repo_basename(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return tail[:-4] if tail.endswith(".git") else tail

def _is_knowledge_clone(cwd: pathlib.Path, knowledge: Optional[pathlib.Path], io) -> bool:
    if not _is_clone(cwd):
        return False
    if knowledge is not None:
        if cwd.resolve() == knowledge.resolve():
            return True
        a, b = _origin(io, cwd), _origin(io, knowledge)
        return bool(a) and a == b
    return cwd.name == DEFAULT_KNOWLEDGE or _repo_basename(_origin(io, cwd)) == DEFAULT_KNOWLEDGE

def detect_root(cwd: pathlib.Path, clone_root: Optional[str], knowledge: Optional[str], repo_names: List[str], io) -> pathlib.Path:
    """The folder that holds the clones: --clone-root, else walking up from the cwd the first folder that is the knowledge clone's
    parent or holds a named clone, else the parent of an explicit --knowledge."""
    cwd = cwd.resolve()
    if clone_root:
        root = pathlib.Path(clone_root).expanduser().resolve()
        if not root.is_dir():
            raise TurnstileError("--clone-root %s is not a directory" % root)
        return root
    kn = pathlib.Path(knowledge).expanduser().resolve() if knowledge else None
    names = [kn.name if kn else DEFAULT_KNOWLEDGE] + list(repo_names)
    for d in ([cwd] + list(cwd.parents)) if kn is None else []:
        if (d / ".git").is_dir() and _is_knowledge_clone(d, kn, io):
            return d.parent
        if any((d / n / ".git").is_dir() for n in names):
            return d
    if _is_knowledge_clone(cwd, kn, io):
        return cwd.parent
    if any(_is_clone(cwd / n) for n in names):
        return cwd
    if kn is not None:
        return kn.parent
    raise TurnstileError("no clone root: %s is not a clone of the knowledge repo and holds no clone named %s; run from the folder that "
                         "holds the clones, or pass --clone-root <dir>" % (cwd, ", ".join(names)))

def resolve_knowledge(root: pathlib.Path, knowledge: Optional[str]) -> pathlib.Path:
    if knowledge:
        p = pathlib.Path(knowledge).expanduser().resolve()
        if not _is_clone(p):
            raise TurnstileError("%s is not a git clone (no .git)" % p)
        return p
    p = root / DEFAULT_KNOWLEDGE
    if not _is_clone(p):
        raise TurnstileError("no %s clone in %s; pass --knowledge <clone>" % (DEFAULT_KNOWLEDGE, root))
    return p

def default_workspace(root: pathlib.Path, key: str) -> pathlib.Path:
    return root / key.lower()

def foreign_entries(ws: pathlib.Path, known: List[str]) -> List[str]:
    if not ws.exists():
        return []
    return sorted(p.name for p in ws.iterdir() if p.name not in OWN_ENTRIES and p.name not in known)

def clone_paths(root: pathlib.Path, repos: Dict[str, dict], overrides: Dict[str, str]) -> Dict[str, pathlib.Path]:
    out = {}
    for name in repos:
        p = pathlib.Path(overrides[name]).expanduser().resolve() if overrides.get(name) else root / name
        if not _is_clone(p):
            raise TurnstileError("no clone of %s at %s (expected a git clone; pass --clone-root <dir> or --repo '{\"name\":\"%s\",…,\"path\":\"<clone>\"}')"
                                 % (name, p, name))
        out[name] = p
    return out

def ensure_repo_worktrees(ws: pathlib.Path, clones: Dict[str, pathlib.Path], repos: Dict[str, dict], key: str, io) -> Dict[str, pathlib.Path]:
    branch = ws_branch(key); out = {}
    for name, clone in sorted(clones.items()):
        wt = ws / name; base = repos[name]["base"]
        if wt.exists():
            current = io.git(["branch", "--show-current"], wt).strip()
            if current != branch:
                raise TurnstileError("%s exists on branch %r, not %s; move it aside" % (wt, current, branch))
        elif io.git(["branch", "--list", branch], clone).strip():
            io.git(["worktree", "add", str(wt), branch], clone)
        else:
            try:
                io.git(["fetch", "origin", base], clone); start = "origin/" + base
            except TurnstileError as e:
                try:
                    io.git(["rev-parse", "--verify", "--quiet", "origin/" + base], clone); start = "origin/" + base
                except TurnstileError:
                    start = base
                print("WARN %s; cutting %s for %s from the local %s, which may be stale" % (e, branch, name, start))
            io.git(["worktree", "add", "-b", branch, str(wt), start], clone)
        out[name] = wt
    return out

def repo_lines(repos: Dict[str, dict], paths: Dict[str, pathlib.Path], key: str) -> List[str]:
    return ["REPO: %s → %s (%s from origin/%s)" % (r, paths[r], ws_branch(key), repos[r]["base"]) for r in sorted(paths)]

def claude_md_repos(repos: Dict[str, dict], paths: Dict[str, pathlib.Path], key: str) -> str:
    return ", ".join("`%s/` (%s from `origin/%s`)" % (r, ws_branch(key), repos[r]["base"]) for r in sorted(paths)) or "none"
