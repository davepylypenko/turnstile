import datetime, pathlib, re
from typing import List, Optional, Tuple
from . import state as st_mod, rules, models, config
from .errors import TurnstileError

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"
BRIEFS = ROOT / "skills" / "turnstile" / "references" / "briefs"
PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

def render(template: str, vars: dict) -> Tuple[str, List[str]]:
    missing = set()
    def sub(m):
        k = m.group(1)
        if k in vars and vars[k] is not None:
            return str(vars[k])
        missing.add(k); return m.group(0)
    return PLACEHOLDER.sub(sub, template), sorted(missing)

def builtins(data: dict, delivery: pathlib.Path, agent: str, name: str, eff: Optional[dict] = None) -> dict:
    epic = data.get("epic") or {}; env = epic.get("environment") or {}; eff = eff or config.effective(data)
    return {"review_skill": eff["review_skill"]["value"], "story_review_skill": eff["story_review_skill"]["value"],
            "review_effort": eff["models"][agent]["effort"] or "",
            "flag": epic.get("flag") or "none", "arm": "treatment",
            "epic_key": epic.get("key") or "", "github_org": epic.get("github_org") or "", "delivery": str(pathlib.Path(delivery).resolve()),
            "variant": env.get("variant") or "", "desk": env.get("desk") or "", "env_recipe": env.get("recipe") or "", "agent": agent,
            "brief_name": name, "brief_path": "briefs/%s.md" % name, "report_path": "reports/%s.md" % name,
            "skill_dir": str(ROOT / "skills" / "turnstile"),
            "today": datetime.datetime.utcnow().strftime("%Y-%m-%d")}

def repo_vars(delivery: pathlib.Path, data: dict, vars: dict, needed: set) -> dict:
    from . import workspace
    ws = workspace.load(delivery); repos = (data.get("epic") or {}).get("repos") or {}; key = (data.get("epic") or {}).get("key") or "<KEY>"
    hint = "run: turnstile attach --epic %s (from the clone root) or pass --var repo_path=<absolute worktree>" % key
    out = {}
    if "repo_paths" in needed and "repo_paths" not in vars:
        out["repo_paths"] = ", ".join("`%s` → `%s`" % (r, p) for r, p in sorted(ws["repos"].items())) if ws and ws["repos"] else \
            "none recorded (no %s in the delivery dir — %s)" % (workspace.FILE, hint)
    if "repo_path" in needed:
        path = vars.get("repo_path")
        if path is None and vars.get("repo") is not None:
            repo = vars["repo"]
            if repo not in repos:
                raise TurnstileError("repo %r is not in epic.repos (%s)" % (repo, ", ".join(sorted(repos)) or "none"))
            if not ws or not ws["repos"].get(repo):
                raise TurnstileError("no worktree recorded for %s in %s/%s — %s" % (repo, delivery, workspace.FILE, hint))
            path = ws["repos"][repo]
        if path is not None:
            if not pathlib.Path(path).is_dir():
                raise TurnstileError("repo worktree %s does not exist — %s" % (path, hint))
            out["repo_path"] = str(pathlib.Path(path).resolve())
    return out

def parse_vars(var_list: List[str]) -> dict:
    out = {}
    for item in var_list or []:
        if "=" not in item:
            raise TurnstileError("--var needs key=value (got %r)" % item)
        k, v = item.split("=", 1)
        if not PLACEHOLDER.match("{{%s}}" % k):
            raise TurnstileError("bad placeholder name %r" % k)
        out[k] = v
    return out

def run(delivery, agent: str, name: str, var_list: List[str], force: bool = False, io=None, no_commit: bool = False, no_push: bool = False) -> int:
    from .pass_cmd import IO, _side_effects
    io = io or IO(); delivery = pathlib.Path(delivery)
    try:
        if not (AGENTS / (agent + ".md")).exists():
            raise TurnstileError("unknown agent %s (no agents/%s.md)" % (agent, agent))
        tpl = BRIEFS / (agent + ".md")
        if not tpl.exists():
            raise TurnstileError("no brief template for %s (%s)" % (agent, tpl))
        if not NAME_RX.match(name):
            raise TurnstileError("brief name must be a file stem like FIX-13223-token (got %r)" % name)
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json")
            if agent != "investigator":  # round 2 R2-11, spec §4.1: no agent starts before the lead approved the plan; a brief is the start
                plan_path = delivery / "plan.md"
                missing_plan = rules.plan_approval_missing(st.data, st_mod.digest(plan_path.read_text()) if plan_path.exists() else None)
                if missing_plan:
                    raise TurnstileError("no agent but the investigator starts before the lead approved plan.md (spec §4.1): " + missing_plan)
            eff = config.effective(st.data); vars = builtins(st.data, delivery, agent, name, eff); vars.update(parse_vars(var_list))
            tpl_text = tpl.read_text(); vars.update(repo_vars(delivery, st.data, vars, set(PLACEHOLDER.findall(tpl_text))))
            text, missing = render(tpl_text, vars)
            if missing:
                for m in missing:
                    print("MISSING placeholder %s (pass --var %s=...)" % (m, m))
                return 2
            out = delivery / "briefs" / (name + ".md")
            if out.exists() and not force:
                raise TurnstileError("briefs/%s.md exists (use --force to overwrite)" % name)
            out.parent.mkdir(parents=True, exist_ok=True); out.write_text(text)
            _side_effects(delivery, st, ["brief %s for %s" % (name, agent)], io, no_commit, no_push)
        report = delivery / "reports" / (name + ".md")
        print(models.agent_line(agent, eff["models"][agent])); print("BRIEF: %s" % out.resolve()); print("REPORT: %s" % report.resolve())
        print("PROMPT: Read and execute %s. Write your report to %s. Reply with at most 8 lines." % (out.resolve(), report.resolve()))
        print("OK brief %s for %s" % (name, agent))
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
