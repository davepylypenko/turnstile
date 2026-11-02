import json, os, pathlib
from typing import Optional, Tuple
from . import models
from .errors import TurnstileError

DEFAULT_REVIEW_SKILL = "/code-review"
SKILL_KEYS = ("review_skill", "story_review_skill")
KEYS_HELP = "models.<agent>, review_skill, story_review_skill, flag (epic only)"

def user_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("TURNSTILE_USER_CONFIG") or os.path.join(os.path.expanduser("~"), ".config", "turnstile", "config.json"))

def load_user() -> dict:
    p = user_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise TurnstileError("user config %s is not valid JSON (%s)" % (p, e))
    if not isinstance(data, dict):
        raise TurnstileError("user config %s must be a JSON object" % p)
    return data

def save_user(data: dict) -> pathlib.Path:
    p = user_path(); p.parent.mkdir(parents=True, exist_ok=True)
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
    return value.strip()

def _model_entry(raw, default: dict, where: str) -> dict:
    entry = dict(default); entry.update({k: v for k, v in (raw or {}).items() if k in ("model", "effort")})
    if entry["model"] not in models.MODELS or (entry["effort"] is not None and entry["effort"] not in models.EFFORTS):
        raise TurnstileError("%s holds an invalid model entry %r" % (where, raw))
    return entry

def effective(data: Optional[dict] = None, user: Optional[dict] = None) -> dict:
    user = load_user() if user is None else user
    epic = (data or {}).get("epic") or {}
    out = {"models": {}}
    for agent, default in models.DEFAULTS.items():
        u = (user.get("models") or {}).get(agent); e = (epic.get("models") or {}).get(agent)
        if u is not None:
            entry, source = _model_entry(u, default, "user config models.%s" % agent), "user"
        elif e is not None and _model_entry(e, default, "epic.models.%s" % agent) != default:
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
            out[key] = {"value": DEFAULT_REVIEW_SKILL, "source": "default"}
    out["flag"] = {"value": epic.get("flag") or None, "source": "epic" if epic.get("flag") else "default"}
    return out

def fmt_model(entry: dict) -> str:
    return entry["model"] + (":" + entry["effort"] if entry.get("effort") else "")

def lines(eff: dict) -> list:
    out = ["models.%s = %s (%s)" % (a, fmt_model(m), m["source"]) for a, m in eff["models"].items()]
    return out + ["%s = %s (%s)" % (k, eff[k]["value"], eff[k]["source"]) for k in SKILL_KEYS] + ["flag = %s (%s)" % (eff["flag"]["value"] or "none", eff["flag"]["source"])]

def one_line(eff: dict) -> str:
    overrides = ["%s models.%s" % (m["source"], a) for a, m in eff["models"].items() if m["source"] != "default"]
    overrides += ["%s %s" % (eff[k]["source"], k) for k in SKILL_KEYS if eff[k]["source"] != "default"]
    return "models %s · %s · flag=%s (%s)" % (" ".join("%s=%s" % (a, fmt_model(m)) for a, m in eff["models"].items()),
                                             " · ".join("%s=%s" % (k, eff[k]["value"]) for k in SKILL_KEYS), eff["flag"]["value"] or "none",
                                             "overrides: " + ", ".join(overrides) if overrides else "all defaults")
