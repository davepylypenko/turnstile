import pathlib
from typing import Optional
from .errors import TurnstileError

MARKER = ".turnstile"

def find_delivery(start: pathlib.Path, override: Optional[str]) -> pathlib.Path:
    if override:
        p = pathlib.Path(override).expanduser().resolve()
        if not (p / "state.json").exists():
            raise TurnstileError("no state.json in %s" % p)
        return p
    cur = start.resolve()
    for d in [cur] + list(cur.parents):
        marker = d / MARKER
        if marker.exists():
            lines = [ln.strip() for ln in marker.read_text().splitlines() if ln.strip()]
            if not lines:
                raise TurnstileError("%s is empty; it must hold the delivery dir path" % marker)
            target = lines[0]
            return (d / target).resolve() if not pathlib.Path(target).is_absolute() else pathlib.Path(target)
    raise TurnstileError("no %s found from %s upward; pass --delivery <dir>" % (MARKER, cur))
