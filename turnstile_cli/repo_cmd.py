import os, pathlib
from typing import List
from . import state as st_mod, workspace
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

def add_hint(name: str) -> str:
    return "turnstile repo add '{\"name\":\"%s\",\"base\":\"main\",\"slack\":\"…\"}'" % name

def add(delivery, spec: str, io=None, init_io=None, no_commit: bool = False, no_push: bool = False) -> int:
    from .pass_cmd import IO, _side_effects, _recompute_next_actions, _ensure_repo_files
    from .init_cmd import InitIO, parse_repo, clone_overrides, write_workspace_claude_md
    io = io or IO(); init_io = init_io or InitIO(); delivery = pathlib.Path(delivery)
    try:
        name, cfg = parse_repo(spec); cfg["path"] = name
        override = clone_overrides([spec]).get(name)
        epic = st_mod.load(delivery / "state.json").data["epic"]
        if name in (epic.get("repos") or {}):
            raise TurnstileError("%s is already an epic repo; edit it with turnstile repo set %s key=value" % (name, name))
        rec = workspace.load(delivery)
        if not rec or not rec.get("clone_root") or not rec.get("workspace") or not rec.get("knowledge"):
            raise TurnstileError("no .workspace.json in %s: run turnstile start %s on this machine first" % (delivery, epic.get("key") or "<KEY>"))
        key = epic["key"]; root = pathlib.Path(rec["clone_root"]); ws = pathlib.Path(rec["workspace"])
        clone = pathlib.Path(override).expanduser().resolve() if override else root / name
        if not workspace._is_clone(clone):
            if override:
                raise TurnstileError("%s is not a git clone (no .git)" % clone)
            org = epic.get("github_org")
            if not org:
                raise TurnstileError("no clone of %s at %s and epic.github_org is empty; clone it there first" % (name, clone))
            print("CLONE: gh repo clone %s/%s %s" % (org, name, clone))
            init_io.gh_clone(org, name, clone)
            if not workspace._is_clone(clone):
                raise TurnstileError("gh repo clone %s/%s left no clone at %s" % (org, name, clone))
        wts = workspace.ensure_repo_worktrees(ws, {name: clone}, {name: cfg}, key, init_io)
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            repos = st.data["epic"].setdefault("repos", {})
            if name in repos:
                raise TurnstileError("%s is already an epic repo; edit it with turnstile repo set %s key=value" % (name, name))
            repos[name] = cfg
            _recompute_next_actions(st.data)
            summary = "repo %s added (base %s)" % (name, cfg["base"])
            _side_effects(delivery, st, [summary], io, no_commit, no_push)
            data = st.data
        all_paths = {r: pathlib.Path(p) for r, p in (rec.get("repos") or {}).items()}; all_paths[name] = wts[name]
        workspace.record(delivery, ws, root, pathlib.Path(rec["knowledge"]), all_paths, member=rec.get("member"))
        rel = os.path.relpath(str(delivery), str(ws))
        write_workspace_claude_md(ws, key, rel, data["epic"].get("chat_language") or "English", workspace.claude_md_repos(data["epic"]["repos"], all_paths, key))
        _ensure_repo_files(delivery)
        for line in workspace.repo_lines({name: cfg}, {name: wts[name]}, key):
            print(line)
        print("OK " + summary); return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
