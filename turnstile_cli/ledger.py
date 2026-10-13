import datetime, pathlib
from typing import Optional

def append(delivery: pathlib.Path, line: str, when: Optional[datetime.datetime] = None) -> None:
    path = pathlib.Path(delivery) / "ledger.md"
    when = when or datetime.datetime.utcnow()
    if not path.exists():
        path.write_text("# Ledger\n\n")
    with path.open("a") as f:
        f.write("- %s UTC %s\n" % (when.strftime("%Y-%m-%d %H:%M"), line))
