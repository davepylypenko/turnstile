import json, os, pathlib, shutil, subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from . import state as st_mod, ledger, models, config, sync, workspace
from .errors import TurnstileError

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
PLAN_TEMPLATE = ROOT / "skills" / "turnstile" / "references" / "plan.md"
REPO_REQUIRED = ("name", "base", "slack")
REPO_KEYS = REPO_REQUIRED + ("epic_branch", "gate", "gate_check", "ci_ignore", "copilot", "branch_prefix", "path")

@dataclass
class InitOptions:
    epic: str
    workitem: str
    lead: str
    lead_github: str
    github_org: str
    knowledge: Optional[str] = None
    clone_root: Optional[str] = None
    repos: List[str] = field(default_factory=list)
    variant: Optional[str] = None
    desk: Optional[str] = None
    board_url: Optional[str] = None
    workspace: Optional[str] = None
    knowledge_base: str = "main"
    pm: Optional[str] = None
    design: Optional[str] = None
    recipe: str = "references/env/pdffiller-dev.md"
    chat_language: str = "English"
    agent_github: Optional[str] = None
    models: Optional[str] = None
    flag: Optional[str] = None
    story_mode: str = "stack"

class InitIO:
    def git(self, args: List[str], cwd: pathlib.Path) -> str:
        out = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True)
        if out.returncode != 0:
            raise TurnstileError("git %s failed: %s" % (" ".join(args), out.stderr.strip()[:200]))
        return out.stdout

def parse_repo(spec: str) -> Tuple[str, dict]:
    try:
        raw = json.loads(spec)
    except json.JSONDecodeError as e:
        raise TurnstileError("--repo must be a JSON object (%s): %r" % (e, spec))
    if not isinstance(raw, dict):
        raise TurnstileError("--repo must be a JSON object with %s" % ", ".join(REPO_REQUIRED))
    for k in REPO_REQUIRED:
        if not raw.get(k):
            raise TurnstileError("--repo lacks %r: %r" % (k, spec))
    unknown = sorted(set(raw) - set(REPO_KEYS))
    if unknown:
        raise TurnstileError("--repo has unknown key(s) %s (allowed: %s)" % (", ".join(unknown), ", ".join(REPO_KEYS)))
    gate = raw.get("gate") or None
    gate_check = raw["gate_check"] if "gate_check" in raw else gate
    cfg = {"base": raw["base"], "epic_branch": raw.get("epic_branch") or raw["base"], "slack": raw["slack"], "gate": gate, "gate_check": gate_check,
           "ci_ignore": list(raw["ci_ignore"]) if "ci_ignore" in raw else ([gate_check] if gate_check else []),
           "copilot": bool(raw.get("copilot", False))}
    if raw.get("branch_prefix"):
        cfg["branch_prefix"] = raw["branch_prefix"]
    return raw["name"], cfg

def clone_overrides(specs: List[str]) -> Dict[str, str]:
    out = {}
    for spec in specs:
        raw = json.loads(spec)
        if raw.get("path"):
            out[raw["name"]] = raw["path"]
    return out

def epic_branch_name(key: str) -> str:
    return "epic/" + key.lower()

def build_state(o: InitOptions) -> dict:
    data = json.loads((TEMPLATES / "state.json").read_text())
    e = data["epic"]
    e["key"] = o.epic; e["workitem"] = o.workitem; e["github_org"] = o.github_org
    e["roles"] = {"lead": o.lead, "lead_github": o.lead_github, "agent_github": o.agent_github, "pm": o.pm, "design": o.design}
    e["repos"] = dict(parse_repo(s) for s in o.repos)
    for name, cfg in e["repos"].items():
        cfg["path"] = name
    e["environment"] = {"variant": o.variant, "desk": o.desk, "recipe": o.recipe}
    e["chat_language"] = o.chat_language
    e["board"] = {"artifact_url": o.board_url, "capabilities": ["db", "user"]}
    e["plan"] = {"path": "plan.md", "submitted_at": None, "digest": None}
    e["models"] = models.parse(o.models)
    e["knowledge"] = {"branch": epic_branch_name(o.epic), "remote": "origin"}
    if o.story_mode not in ("stack", "trunk"):
        raise TurnstileError("--story-mode must be stack or trunk (got %r)" % o.story_mode)
    e["flag"] = (o.flag or "").strip() or None; e["story_mode"] = o.story_mode
    return data

CLAUDE_MD_MARKER = "— orchestrator workspace"

def _ours(path: pathlib.Path) -> bool:
    if not path.exists():
        return True
    first = (path.read_text().splitlines() or [""])[0]
    return first.startswith("# ") and first.endswith(CLAUDE_MD_MARKER)

def write_workspace_claude_md(ws: pathlib.Path, epic_key: str, rel: str, chat_language: str, repos: str = "none") -> pathlib.Path:
    text = (TEMPLATES / "CLAUDE.md.workspace").read_text().replace("{{epic_key}}", epic_key).replace("{{delivery}}", rel) \
        .replace("{{chat_language}}", chat_language).replace("{{cli}}", shutil.which("turnstile") or str(ROOT / "scripts" / "turnstile")) \
        .replace("{{repos}}", repos).replace("{{ws_branch}}", workspace.ws_branch(epic_key))
    target = ws / "CLAUDE.md"
    if not _ours(target):
        target = ws / "CLAUDE.md.turnstile"
        if not _ours(target):
            raise TurnstileError("%s exists and is not turnstile's own (first line lacks %r); move it aside" % (target, CLAUDE_MD_MARKER))
    target.write_text(text); return target

def _ensure_worktree(o: InitOptions, io: InitIO, knowledge: pathlib.Path, wt: pathlib.Path) -> str:
    branch = epic_branch_name(o.epic)
    if wt.exists():
        current = io.git(["branch", "--show-current"], wt).strip()
        if current != branch:  # e.g. --knowledge points at a clone inside the workspace: never write the epic onto its branch
            raise TurnstileError("%s exists on branch %r, not %s; pass a --knowledge clone outside the workspace or move it" % (wt, current, branch))
        return branch
    if io.git(["branch", "--list", branch], knowledge).strip():
        io.git(["worktree", "add", str(wt), branch], knowledge)
    else:
        try:  # minor 12: the local base may be stale; cut from the fetched remote base
            io.git(["fetch", "origin", o.knowledge_base], knowledge); start = "origin/" + o.knowledge_base
        except TurnstileError as e:
            print("WARN %s; cutting %s from the local %s, which may be stale" % (e, branch, o.knowledge_base)); start = o.knowledge_base
        io.git(["worktree", "add", "-b", branch, str(wt), start], knowledge)
    return branch

def _same_epic(ws: pathlib.Path, key: str) -> bool:
    marker = ws / ".turnstile"
    if not marker.exists():
        return False
    target = (marker.read_text().splitlines() or [""])[0].strip()
    sj = (ws / target) / "state.json"
    try:
        return sj.exists() and st_mod.load(sj).data["epic"].get("key") == key
    except Exception:
        return False

def next_lines(ws: pathlib.Path, cwd: pathlib.Path) -> List[str]:
    return ["NEXT: cd %s && claude — the hooks and .turnstile live in that folder; this session (in %s) cannot drive the epic" % (ws, cwd)]

def run(o: InitOptions, io: Optional[InitIO] = None) -> int:
    from .pass_cmd import _ensure_repo_files
    io = io or InitIO()
    try:
        if not o.repos:
            raise TurnstileError("at least one --repo is required")
        data = build_state(o)  # validates every --repo before anything is created
        repos = data["epic"]["repos"]; cwd = pathlib.Path.cwd()
        root = workspace.detect_root(cwd, o.clone_root, o.knowledge, list(repos), io)
        knowledge = workspace.resolve_knowledge(root, o.knowledge)
        clones = workspace.clone_paths(root, repos, clone_overrides(o.repos))
        ws = pathlib.Path(o.workspace).expanduser().resolve() if o.workspace else workspace.default_workspace(root, o.epic)
        if _same_epic(ws, o.epic):
            from .attach_cmd import run as attach_run, AttachOptions
            print("WORKSPACE: %s already holds epic %s; attaching" % (ws, o.epic))
            return attach_run(AttachOptions(epic=o.epic, knowledge=str(knowledge), clone_root=str(root), workspace=str(ws), workitem=o.workitem,
                                            chat_language=o.chat_language), io)
        foreign = workspace.foreign_entries(ws, [knowledge.name] + list(repos))
        if foreign:
            raise TurnstileError("%s exists and is not empty (%s) and is not a turnstile workspace of %s; pass another --workspace"
                                 % (ws, ", ".join(foreign[:5]), o.epic))
        wt = ws / knowledge.name
        delivery = wt / "context" / "workitems" / o.workitem / "delivery"
        if (delivery / "state.json").exists():
            raise TurnstileError("already initialised: %s (state.json exists; run turnstile status)" % delivery)
        marker = ws / ".turnstile"
        if marker.exists() and marker.read_text().strip() != os.path.relpath(str(delivery), str(ws)):
            raise TurnstileError("%s points at another delivery (%s); one epic per workspace" % (marker, marker.read_text().strip()))
        ws.mkdir(parents=True, exist_ok=True)
        branch = _ensure_worktree(o, io, knowledge, wt)
        repo_wts = workspace.ensure_repo_worktrees(ws, clones, repos, o.epic, io)
        created = []  # rolled back when a later step fails, so the next run does not see "already initialised"
        try:
            if not delivery.exists():  # round 2: a migrated delivery dir (ledger, briefs, reports moved in first) is never rolled back
                created.append(delivery)
            delivery.mkdir(parents=True, exist_ok=True)
            for sub in ("briefs", "reports", "evidence"):
                (delivery / sub).mkdir(parents=True, exist_ok=True); (delivery / sub / ".gitkeep").touch()
            st_mod.write_atomic(delivery / "state.json", st_mod.dumps(data)); created.append(delivery / "state.json")
            if not (delivery / "decisions.md").exists(): (delivery / "decisions.md").write_text(
                "# Decisions — %s\n\n| Date | Topic | Decision | Source |\n|---|---|---|---|\n\n## Open questions\n\n"
                "| # | Question | Owner | Asked | Answer |\n|---|---|---|---|---|\n" % o.epic)
            if not (delivery / "plan.md").exists(): (delivery / "plan.md").write_text(PLAN_TEMPLATE.read_text().replace("{{epic_key}}", o.epic))
            _ensure_repo_files(delivery)
            ledger.append(delivery, "init %s (%s) on %s" % (o.epic, o.workitem, branch))
            rel = os.path.relpath(str(delivery), str(ws))
            (ws / ".turnstile").write_text(rel + "\n"); created.append(ws / ".turnstile")
            target = write_workspace_claude_md(ws, o.epic, rel, o.chat_language, workspace.claude_md_repos(repos, repo_wts, o.epic)); created.append(target)
            io.git(["add", "-A", "."], delivery)
            io.git(["commit", "-q", "-m", "turnstile: init %s" % o.epic, "--", "."], delivery)
        except TurnstileError as e:
            for path in reversed(created):
                if path.is_dir():
                    shutil.rmtree(str(path), ignore_errors=True)
                elif path.exists():
                    path.unlink()
            raise TurnstileError("%s — init rolled back (%s removed; the worktree %s stays); fix the cause and re-run the same init command"
                                 % (e, ", ".join(str(c) for c in created) or "nothing", wt))
        workspace.record(delivery, ws, root, wt, repo_wts)
        head = io.git(["rev-parse", "HEAD"], delivery).strip() or None
        try:
            io.git(["push", "-q", "origin", "HEAD:refs/heads/" + branch], delivery); rec = sync.record(delivery, True, head)
        except TurnstileError as e:
            rec = sync.record(delivery, False, head, str(e)[:200]); print("WARN: not pushed: %s" % str(e)[:200])
        print("WORKSPACE: %s (clone root %s)" % (ws, root)); print("WORKTREE: %s (%s)" % (wt, branch))
        for line in workspace.repo_lines(repos, repo_wts, o.epic):
            print(line)
        print("DELIVERY: %s" % delivery); print("CLAUDE_MD: %s" % target); print(sync.line(rec))
        print("NEXT: write %s per references/kickoff.md, then: turnstile plan-submitted" % (delivery / "plan.md"))
        print("CONFIG: " + config.one_line(config.effective(data)))
        print("NEXT: ask the lead once (skill § preferences): own review skill? other model/effort per agent? Record with "
              "turnstile config set <key>=<value> [--epic]; confirm with turnstile config list")
        for line in next_lines(ws, cwd):
            print(line)
        print("OK init %s" % o.epic)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
