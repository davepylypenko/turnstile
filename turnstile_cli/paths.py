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
            target = marker.read_text().strip().splitlines()[0]
            p = (d / target).resolve() if not pathlib.Path(target).is_absolute() else pathlib.Path(target)
            return p
    raise TurnstileError("no %s found from %s upward; pass --delivery <dir>" % (MARKER, cur))
