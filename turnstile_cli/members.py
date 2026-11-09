import datetime, pathlib, re
from typing import Optional, Tuple
from .errors import TurnstileError

BOARD_URL_RX = re.compile(r"^https://claude\.ai/(code/)?artifact/\S+$")
CAPABILITIES = ["db", "user"]

def _now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def new_entry(name: str, variant: Optional[str], desk: Optional[str], board_url: Optional[str]) -> dict:
    return {"name": name, "variant": variant, "desk": desk, "board": {"artifact_url": board_url, "capabilities": list(CAPABILITIES)}, "added_at": _now()}

def default_variant(epic_key: str, login: str) -> str:
    return "%s-%s" % (epic_key.lower(), login.lower())

def migrate(data: dict) -> bool:
    epic = data.get("epic") if isinstance(data, dict) else None
    if not isinstance(epic, dict) or "members" in epic:
        return False
    roles = epic.get("roles") or {}; lead = roles.get("lead_github")
    if not lead:
        return False
    env, board = epic.get("environment") or {}, epic.get("board") or {}
    entry = new_entry(roles.get("lead") or lead, env.get("variant"), env.get("desk"), board.get("artifact_url"))
    entry["board"]["capabilities"] = list(board.get("capabilities") or CAPABILITIES)
    epic["members"] = {lead: entry}
    return True

def check_board_url(url: str) -> str:
    if not BOARD_URL_RX.match(url or ""):
        raise TurnstileError("board url must look like https://claude.ai/artifact/<id> or https://claude.ai/code/artifact/<id> (got %r)" % url)
    return url

def attach_line(epic_key: str, login: str) -> str:
    return "turnstile attach --epic %s --github %s" % (epic_key, login)

def current(data: dict, delivery) -> Tuple[str, dict]:
    from . import workspace
    epic = data.get("epic") or {}
    login = (workspace.load(delivery) or {}).get("member") or (epic.get("roles") or {}).get("lead_github")
    members = epic.get("members") or {}
    if not login or login not in members:
        raise TurnstileError("this machine's member %s is not in epic.members (%s); run: %s" %
                             (login or "(none recorded)", ", ".join(sorted(members)) or "none", attach_line(epic.get("key") or "<KEY>", login or "<login>")))
    return login, members[login]

def current_or_none(data: dict, delivery) -> Optional[Tuple[str, dict]]:
    try:
        return current(data, delivery)
    except TurnstileError:
        return None

def variant_desk(data: dict, delivery) -> Tuple[Optional[str], Optional[str]]:
    env = (data.get("epic") or {}).get("environment") or {}
    cur = current_or_none(data, delivery)
    if not cur:
        return env.get("variant"), env.get("desk")
    return cur[1].get("variant") or env.get("variant"), cur[1].get("desk") or env.get("desk")

def board_url_of(data: dict, delivery) -> Optional[str]:
    cur = current_or_none(data, delivery)
    if cur:
        return (cur[1].get("board") or {}).get("artifact_url")
    return ((data.get("epic") or {}).get("board") or {}).get("artifact_url")

def board_line(data: dict, delivery) -> str:
    url = board_url_of(data, delivery)
    return "BOARD: publish %s → %s" % (pathlib.Path(delivery) / "board.html", url or "new artifact (capabilities: db, user) — then: turnstile board-url <url>")

def member_line(data: dict, delivery) -> str:
    cur = current_or_none(data, delivery)
    if not cur:
        try:
            current(data, delivery)
        except TurnstileError as e:
            return "MEMBER: unknown — %s" % e
        return "MEMBER: unknown"
    login, e = cur
    return "MEMBER: %s · variant %s · desk %s · board %s" % (login, e.get("variant") or "none", e.get("desk") or "none", (e.get("board") or {}).get("artifact_url") or "none")

def unknown_proposal(data: dict, delivery):
    from . import workspace
    from .reconcile import Proposal
    try:
        current(data, delivery)
    except TurnstileError as e:
        login = (workspace.load(delivery) or {}).get("member") or "<login>"
        return Proposal("epic", "member_unknown", str(e), attach_line((data.get("epic") or {}).get("key") or "<KEY>", login))
    return None

def board_url(delivery, url: str, io=None, no_push: bool = False) -> int:
    from . import state as st_mod
    from .pass_cmd import IO, _side_effects
    io = io or IO(); delivery = pathlib.Path(delivery)
    try:
        check_board_url(url)
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json"); epic = st.data["epic"]
            login, entry = current(st.data, delivery)
            entry.setdefault("board", {"capabilities": list(CAPABILITIES)})["artifact_url"] = url
            if login == (epic.get("roles") or {}).get("lead_github"):
                epic.setdefault("board", {"capabilities": list(CAPABILITIES)})["artifact_url"] = url
            _side_effects(delivery, st, ["board-url %s: %s" % (login, url)], io, False, no_push)
        print("OK board-url %s → %s" % (login, url)); return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
