import json, os, pathlib, re
from typing import Iterable, List, Optional, Tuple
from . import models, workspace
from .errors import TurnstileError
from .rules import DEFAULT_SEND_SKILL

DEFAULT_REVIEW_SKILL = "/code-review"
SKILL_KEYS = ("review_skill", "story_review_skill", "send_skill")
SKILL_DEFAULTS = {"review_skill": DEFAULT_REVIEW_SKILL, "story_review_skill": DEFAULT_REVIEW_SKILL, "send_skill": DEFAULT_SEND_SKILL}
SKILL_RX = re.compile(r"^/(?:[\w][\w.-]*:)?[\w][\w.-]*$")
KEYS_HELP = "models.<agent>, review_skill, story_review_skill, send_skill, flag (epic only)"
SEND_SKILL_INSTALL = "ln -s <pdffiller-knowledge clone>/playground/zolotukhin-ivan/skills/send-pr-review ~/.claude/skills/send-pr-review"

def default_user_dir() -> pathlib.Path:
    return pathlib.Path(os.path.expanduser("~")) / ".config" / "turnstile"

def _inside_checkout(p: pathlib.Path) -> bool:
    for d in [p] + list(p.parents):
        if (d / ".git").exists() or (d / ".turnstile").exists() or (d / ".state.lock").exists():
            return True
    return False

def user_path() -> pathlib.Path:
    override = os.environ.get("TURNSTILE_USER_CONFIG")
    if not override:
        return default_user_dir() / "config.json"
    p = pathlib.Path(override).expanduser().resolve()
    if p.suffix != ".json" or _inside_checkout(p.parent):
        raise TurnstileError("TURNSTILE_USER_CONFIG must be a .json file outside any git checkout, delivery dir or workspace (got %s)" % p)
    return p

def _check_user_shape(data, p: pathlib.Path) -> dict:
    if not isinstance(data, dict):
        raise TurnstileError("user config %s must be a JSON object" % p)
    m = data.get("models")
    if m is not None and (not isinstance(m, dict) or any(not isinstance(v, dict) for v in m.values())):
        raise TurnstileError("user config %s: models must map agent → {model, effort}" % p)
    for k in SKILL_KEYS:
        if data.get(k) is not None and not (isinstance(data[k], str) and SKILL_RX.match(data[k])):
            raise TurnstileError("user config %s: %s must be a slash command like /my-review (is %r)" % (p, k, data[k]))
    return data

def load_user() -> dict:
    p = user_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise TurnstileError("user config %s is not valid JSON (%s)" % (p, e))
    return _check_user_shape(data, p)

def save_user(data: dict) -> pathlib.Path:
    p = user_path()
    if not p.parent.exists():
        if default_user_dir() not in [p.parent] + list(p.parent.parents):
            raise TurnstileError("%s does not exist; turnstile creates directories only under %s" % (p.parent, default_user_dir()))
        p.parent.mkdir(parents=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n"); return p

def parse_key(key: str) -> Tuple[str, Optional[str]]:
    if key.startswith("models."):
        agent = key[len("models."):]
        if agent not in models.DEFAULTS:
            raise TurnstileError("unknown agent %r in %s (known: %s)" % (agent, key, ", ".join(sorted(models.DEFAULTS))))
        return "models", agent
    if key in SKILL_KEYS or key == "flag":
        return key, None
    raise TurnstileError("unknown config key %r (allowed: %s)" % (key, KEYS_HELP))

def parse_value(key: str, value: str):
    section, _ = parse_key(key)
    if section == "models":
        model, _, effort = value.strip().partition(":")
        if model not in models.MODELS:
            raise TurnstileError("%s: model %r not in %s (value is model or model:effort)" % (key, model, ", ".join(models.MODELS)))
        if effort and effort not in models.EFFORTS:
            raise TurnstileError("%s: effort %r not in %s" % (key, effort, ", ".join(models.EFFORTS)))
        return {"model": model, "effort": effort or None}
    if not value or not value.strip():
        raise TurnstileError("%s needs a non-empty %s" % (key, "flag name" if key == "flag" else "skill name (e.g. /pdf-review:run)"))
    if key != "flag" and not SKILL_RX.match(value.strip()):
        raise TurnstileError("%s must be a slash command like /pdf-review:run or /my-review (got %r)" % (key, value))
    return value.strip()

def _model_entry(raw, default: dict, where: str) -> dict:
    entry = dict(default); entry.update({k: v for k, v in (raw or {}).items() if k in ("model", "effort")})
    if entry["model"] not in models.MODELS or (entry["effort"] is not None and entry["effort"] not in models.EFFORTS):
        raise TurnstileError("%s holds an invalid model entry %r" % (where, raw))
    return entry

def _is_default(agent: str, entry: dict) -> bool:
    return entry in [models.DEFAULTS[agent]] + models.PREVIOUS_DEFAULTS.get(agent, [])

def is_frozen_set(epic_models) -> bool:
    """Before 0.4.1 `init` wrote every agent's then default into epic.models; only that full-set shape reads default-valued
    entries as defaults, a partial set holds deliberate overrides."""
    return isinstance(epic_models, dict) and set(models.DEFAULTS) <= set(epic_models)

def drop_frozen_defaults(epic: dict) -> None:
    m = epic.get("models")
    if not is_frozen_set(m):
        return
    for agent in list(m):
        if agent in models.DEFAULTS and _is_default(agent, _model_entry(m[agent], models.DEFAULTS[agent], "epic.models.%s" % agent)):
            del m[agent]

def effective(data: Optional[dict] = None, user: Optional[dict] = None) -> dict:
    user = load_user() if user is None else user
    epic = (data or {}).get("epic") or {}
    frozen = is_frozen_set(epic.get("models"))
    out = {"models": {}}
    for agent, default in models.DEFAULTS.items():
        u = (user.get("models") or {}).get(agent); e = (epic.get("models") or {}).get(agent)
        if u is not None:
            entry, source = _model_entry(u, default, "user config models.%s" % agent), "user"
        elif e is not None and not (frozen and _is_default(agent, _model_entry(e, default, "epic.models.%s" % agent))):
            entry, source = _model_entry(e, default, "epic.models.%s" % agent), "epic"
        else:
            entry, source = dict(default), "default"
        entry["source"] = source; out["models"][agent] = entry
    for key in SKILL_KEYS:
        if user.get(key):
            out[key] = {"value": str(user[key]), "source": "user"}
        elif epic.get(key):
            out[key] = {"value": str(epic[key]), "source": "epic"}
        else:
            out[key] = {"value": SKILL_DEFAULTS[key], "source": "default"}
    out["flag"] = {"value": epic.get("flag") or None, "source": "epic" if epic.get("flag") else "default"}
    return out

def fmt_model(entry: dict) -> str:
    return entry["model"] + (":" + entry["effort"] if entry.get("effort") else "")

def fmt_resolved(agent: str, entry: dict) -> str:
    return fmt_model(dict(entry, effort=models.resolved_effort(agent, entry)))

def _source_note(agent: str, entry: dict) -> str:
    inherited = not entry.get("effort") and models.resolved_effort(agent, entry)
    return entry["source"] + ("; effort = agent default" if inherited else "")

def lines(eff: dict) -> list:
    out = ["models.%s = %s (%s)" % (a, fmt_resolved(a, m), _source_note(a, m)) for a, m in eff["models"].items()]
    return out + ["%s = %s (%s)" % (k, eff[k]["value"], eff[k]["source"]) for k in SKILL_KEYS] + ["flag = %s (%s)" % (eff["flag"]["value"] or "none", eff["flag"]["source"])]

def one_line(eff: dict) -> str:
    overrides = ["%s models.%s" % (m["source"], a) for a, m in eff["models"].items() if m["source"] != "default"]
    overrides += ["%s %s" % (eff[k]["source"], k) for k in SKILL_KEYS if eff[k]["source"] != "default"]
    return "models %s · %s · flag=%s (%s)" % (" ".join("%s=%s" % (a, fmt_resolved(a, m)) for a, m in eff["models"].items()),
                                             " · ".join("%s=%s" % (k, eff[k]["value"]) for k in SKILL_KEYS), eff["flag"]["value"] or "none",
                                             "overrides: " + ", ".join(overrides) if overrides else "all defaults")

def claude_dir() -> pathlib.Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return pathlib.Path(override).expanduser() if override else pathlib.Path(os.path.expanduser("~")) / ".claude"

def _glob(base: pathlib.Path, pattern: str) -> List[pathlib.Path]:
    try:
        return sorted(base.glob(pattern))
    except OSError:
        return []

PLUGIN_SKILL_DEPTHS = ("*/%s/*/%s/SKILL.md", "*/%s/*/*/%s/SKILL.md", "*/%s/*/*/*/%s/SKILL.md", "*/%s/*/*/*/*/%s/SKILL.md")

def skill_path(name: str, roots: Iterable[pathlib.Path] = ()) -> Optional[pathlib.Path]:
    home = claude_dir()
    cache = home / "plugins" / "cache"
    plugin, _, skill = name.lstrip("/").rpartition(":")
    if plugin:
        candidates = [c for pattern in PLUGIN_SKILL_DEPTHS for c in _glob(cache, pattern % (plugin, skill))]
        candidates += _glob(cache, "*/%s/*/commands/%s.md" % (plugin, skill))
    else:
        dirs = [home] + [pathlib.Path(r) / ".claude" for r in roots if r]
        candidates = [d / "skills" / skill / "SKILL.md" for d in dirs] + [d / "commands" / (skill + ".md") for d in dirs]
        candidates += _glob(cache, "*/*/*/skills/%s/SKILL.md" % skill) + _glob(cache, "*/*/*/commands/%s.md" % skill)
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None

def skill_roots(delivery: Optional[pathlib.Path] = None) -> List[pathlib.Path]:
    roots = []
    try:
        roots.append(pathlib.Path.cwd())
    except OSError:
        pass
    rec = workspace.load(delivery) if delivery else None
    for key in ("workspace", "clone_root"):
        if rec and rec.get(key):
            roots.append(pathlib.Path(rec[key]))
    return roots

def send_skill(data: Optional[dict], delivery: Optional[pathlib.Path] = None, user: Optional[dict] = None) -> Tuple[str, Optional[pathlib.Path]]:
    name = effective(data, user)["send_skill"]["value"]
    return name, skill_path(name, skill_roots(delivery))

def send_skill_line(name: str, found: Optional[pathlib.Path]) -> str:
    if found:
        return "SEND_SKILL: %s (found: %s)" % (name, found)
    install = "install the default: " + SEND_SKILL_INSTALL if name == DEFAULT_SEND_SKILL else "install it"
    return ("SEND_SKILL: %s not found on this machine — NEXT: ask the lead which skill sends PRs to review (then turnstile config set "
            "send_skill=/<name>) or %s" % (name, install))

def send_skill_warning(name: str, found: Optional[pathlib.Path]) -> Optional[str]:
    return None if found else "WARN: send skill %s not found on this machine (config set send_skill=… or install it)" % name
