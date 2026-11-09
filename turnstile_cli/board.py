import copy, datetime, json, pathlib
from typing import Dict, Optional

TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "templates" / "board.html"
TOKEN = "/*__TURNSTILE_STATE__*/null"
BOARDS_DIR = "boards"

def member_rel(login: str) -> str:
    return "%s/%s.html" % (BOARDS_DIR, login)

def render_html(data: dict) -> str:
    html = TEMPLATE.read_text()
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    html = html.replace(TOKEN, payload)
    return html.replace("__TURNSTILE_UPDATED__", datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))

def story_owner(data: dict, sid: Optional[str]) -> Optional[str]:
    return ((data.get("stories") or {}).get(sid) or {}).get("owner")

def pr_owner(data: dict, pr_id: str) -> Optional[str]:
    p = (data.get("prs") or {}).get(pr_id) or {}
    return p.get("owner") or story_owner(data, p.get("story"))

def member_view(data: dict, login: str) -> dict:
    out = copy.deepcopy(data)
    out["stories"] = {sid: s for sid, s in (data.get("stories") or {}).items() if s.get("owner") == login}
    out["prs"] = {pid: p for pid, p in (data.get("prs") or {}).items() if pr_owner(data, pid) == login}
    out["bugs"] = [b for b in (data.get("bugs") or []) if (b.get("owner") or story_owner(data, b.get("story"))) == login]
    out["awaiting_human"] = [a for a in (data.get("awaiting_human") or [])
                             if (a.get("pr") and a["pr"] in out["prs"]) or (a.get("story") and a["story"] in out["stories"]) or not (a.get("pr") or a.get("story"))]
    m = ((data.get("epic") or {}).get("members") or {}).get(login) or {}
    out["view"] = {"login": login, "name": m.get("name") or login, "variant": m.get("variant"), "desk": m.get("desk"), "full": "board.html"}
    return out

def render_member_files(data: dict) -> Dict[str, str]:
    members = ((data.get("epic") or {}).get("members") or {})
    return {member_rel(login): render_html(member_view(data, login)) for login in members}

def render_files(data: dict) -> Dict[str, str]:
    files = {"board.html": render_html(data)}
    files.update(render_member_files(data))
    return files

def write_files(delivery: pathlib.Path, files: Dict[str, str]) -> None:
    for rel, html in files.items():
        out = pathlib.Path(delivery) / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)

def render(data: dict, delivery: pathlib.Path) -> pathlib.Path:
    write_files(delivery, render_files(data))
    return pathlib.Path(delivery) / "board.html"
