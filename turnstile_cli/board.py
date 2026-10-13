import datetime, json, pathlib

TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "templates" / "board.html"
TOKEN = "/*__TURNSTILE_STATE__*/null"

def render(data: dict, delivery: pathlib.Path) -> pathlib.Path:
    html = TEMPLATE.read_text()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace(TOKEN, payload)
    html = html.replace("__TURNSTILE_UPDATED__", datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    out = pathlib.Path(delivery) / "board.html"
    out.write_text(html)
    return out
