import datetime, pathlib, re
from typing import List, Tuple
from . import state as st_mod
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

def builtins(data: dict, delivery: pathlib.Path, agent: str, name: str) -> dict:
    epic = data.get("epic") or {}; env = epic.get("environment") or {}
    return {"epic_key": epic.get("key") or "", "github_org": epic.get("github_org") or "", "delivery": str(pathlib.Path(delivery).resolve()),
            "variant": env.get("variant") or "", "desk": env.get("desk") or "", "env_recipe": env.get("recipe") or "", "agent": agent,
            "brief_name": name, "brief_path": "briefs/%s.md" % name, "report_path": "reports/%s.md" % name,
            "today": datetime.datetime.utcnow().strftime("%Y-%m-%d")}

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

def run(delivery, agent: str, name: str, var_list: List[str], force: bool = False, io=None, no_commit: bool = False) -> int:
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
            vars = builtins(st.data, delivery, agent, name); vars.update(parse_vars(var_list))
            text, missing = render(tpl.read_text(), vars)
            if missing:
                for m in missing:
                    print("MISSING placeholder %s (pass --var %s=...)" % (m, m))
                return 2
            out = delivery / "briefs" / (name + ".md")
            if out.exists() and not force:
                raise TurnstileError("briefs/%s.md exists (use --force to overwrite)" % name)
            out.parent.mkdir(parents=True, exist_ok=True); out.write_text(text)
            _side_effects(delivery, st, ["brief %s for %s" % (name, agent)], io, no_commit)
        report = delivery / "reports" / (name + ".md")
        print("AGENT: turnstile:%s" % agent); print("BRIEF: %s" % out.resolve()); print("REPORT: %s" % report.resolve())
        print("PROMPT: Read and execute %s. Write your report to %s. Reply with at most 8 lines." % (out.resolve(), report.resolve()))
        print("OK brief %s for %s" % (name, agent))
        return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
