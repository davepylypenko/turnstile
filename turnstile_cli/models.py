import json
from typing import Optional
from .errors import TurnstileError

MODELS = ("haiku", "sonnet", "opus", "fable")
EFFORTS = ("low", "medium", "high", "xhigh")
DEFAULTS = {"implementer": {"model": "sonnet", "effort": None}, "deployer": {"model": "sonnet", "effort": None},
            "tester": {"model": "sonnet", "effort": None}, "stack-step": {"model": "haiku", "effort": None}, "gate-runner": {"model": "sonnet", "effort": None},
            "comments-handler": {"model": "haiku", "effort": None}, "investigator": {"model": "haiku", "effort": None},
            "reviewer": {"model": "opus", "effort": "xhigh"}, "story-reviewer": {"model": "opus", "effort": "xhigh"}}
PREVIOUS_DEFAULTS = {"reviewer": [{"model": "opus", "effort": "medium"}], "story-reviewer": [{"model": "opus", "effort": "high"}]}

def defaults() -> dict:
    return {k: dict(v) for k, v in DEFAULTS.items()}

def parse(spec: Optional[str]) -> dict:
    out = defaults()
    if not spec:
        return out
    try:
        raw = json.loads(spec)
    except json.JSONDecodeError as e:
        raise TurnstileError("--models must be a JSON object agent → {model, effort} (%s): %r" % (e, spec))
    if not isinstance(raw, dict):
        raise TurnstileError("--models must be a JSON object agent → {model, effort}")
    for agent, cfg in raw.items():
        if agent not in out:
            raise TurnstileError("--models names unknown agent %r (known: %s)" % (agent, ", ".join(sorted(out))))
        if not isinstance(cfg, dict) or set(cfg) - {"model", "effort"} or not cfg:
            raise TurnstileError("--models.%s must be an object with model and/or effort" % agent)
        if "model" in cfg and cfg["model"] not in MODELS:
            raise TurnstileError("--models.%s.model %r not in %s" % (agent, cfg["model"], ", ".join(MODELS)))
        if "effort" in cfg and cfg["effort"] is not None and cfg["effort"] not in EFFORTS:
            raise TurnstileError("--models.%s.effort %r not in %s" % (agent, cfg["effort"], ", ".join(EFFORTS)))
        out[agent].update(cfg)
    return out

def overrides(spec: Optional[str]) -> dict:
    full = parse(spec)
    return {agent: full[agent] for agent in (json.loads(spec) if spec else {})}

def resolved_effort(agent: str, cfg: dict) -> Optional[str]:
    return cfg.get("effort") or DEFAULTS.get(agent, {}).get("effort")

def agent_line(agent: str, cfg: dict) -> str:
    line = "AGENT: turnstile:%s model=%s" % (agent, cfg["model"])
    effort = resolved_effort(agent, cfg)
    return line + (" effort=%s" % effort if effort else "")
