import json, os, pathlib, shutil, subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from . import state as st_mod, ledger
from .errors import TurnstileError

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
PLAN_TEMPLATE = ROOT / "skills" / "turnstile" / "references" / "plan.md"
REPO_REQUIRED = ("name", "base", "epic_branch", "slack")
REPO_KEYS = REPO_REQUIRED + ("gate", "gate_check", "ci_ignore", "copilot", "branch_prefix")

@dataclass
class InitOptions:
    epic: str
    workitem: str
    knowledge: str
    lead: str
    lead_github: str
    github_org: str
    repos: List[str] = field(default_factory=list)
    variant: Optional[str] = None
    desk: Optional[str] = None
    board_url: Optional[str] = None
    workspace: str = "."
    knowledge_base: str = "main"
    pm: Optional[str] = None
    design: Optional[str] = None
    recipe: str = "references/env/pdffiller-dev.md"
    chat_language: str = "English"
    agent_github: Optional[str] = None

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
    cfg = {"base": raw["base"], "epic_branch": raw["epic_branch"], "slack": raw["slack"], "gate": gate, "gate_check": gate_check,
           "ci_ignore": list(raw["ci_ignore"]) if "ci_ignore" in raw else ([gate_check] if gate_check else []),
           "copilot": bool(raw.get("copilot", False))}
    if raw.get("branch_prefix"):
        cfg["branch_prefix"] = raw["branch_prefix"]
    return raw["name"], cfg

def epic_branch_name(key: str) -> str:
    return "epic/" + key.lower()

def build_state(o: InitOptions) -> dict:
    data = json.loads((TEMPLATES / "state.json").read_text())
    e = data["epic"]
    e["key"] = o.epic; e["workitem"] = o.workitem; e["github_org"] = o.github_org
    e["roles"] = {"lead": o.lead, "lead_github": o.lead_github, "agent_github": o.agent_github, "pm": o.pm, "design": o.design}
    e["repos"] = dict(parse_repo(s) for s in o.repos)
    e["environment"] = {"variant": o.variant, "desk": o.desk, "recipe": o.recipe}
    e["chat_language"] = o.chat_language
    e["board"] = {"artifact_url": o.board_url, "capabilities": ["db", "user"]}
    e["plan"] = {"path": "plan.md", "submitted_at": None, "digest": None}
    return data

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

def run(o: InitOptions, io: Optional[InitIO] = None) -> int:
    from .pass_cmd import _ensure_repo_files
    io = io or InitIO()
    try:
        ws = pathlib.Path(o.workspace).resolve()
        knowledge = pathlib.Path(o.knowledge).resolve()
        if not (knowledge / ".git").exists():
            raise TurnstileError("%s is not a git clone (no .git)" % knowledge)
        if not o.repos:
            raise TurnstileError("at least one --repo is required")
        data = build_state(o)  # validates every --repo before anything is created
        wt = ws / knowledge.name
        delivery = wt / "context" / "workitems" / o.workitem / "delivery"
        if (delivery / "state.json").exists():
            raise TurnstileError("already initialised: %s (state.json exists; run turnstile status)" % delivery)
        marker = ws / ".turnstile"
        if marker.exists() and marker.read_text().strip() != os.path.relpath(str(delivery), str(ws)):
            raise TurnstileError("%s points at another delivery (%s); one epic per workspace" % (marker, marker.read_text().strip()))
        branch = _ensure_worktree(o, io, knowledge, wt)
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
            text = (TEMPLATES / "CLAUDE.md.workspace").read_text().replace("{{epic_key}}", o.epic).replace("{{delivery}}", rel).replace("{{chat_language}}", o.chat_language)
            target = ws / "CLAUDE.md"
            if target.exists():
                target = ws / "CLAUDE.md.turnstile"
            target.write_text(text); created.append(target)
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
        print("WORKTREE: %s (%s)" % (wt, branch)); print("DELIVERY: %s" % delivery); print("CLAUDE_MD: %s" % target)
        print("NEXT: write %s per references/kickoff.md, then: turnstile plan-submitted" % (delivery / "plan.md"))
        print("OK init %s" % o.epic)
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
