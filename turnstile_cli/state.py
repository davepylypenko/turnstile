import contextlib, fcntl, hashlib, json, os, pathlib, tempfile
from dataclasses import dataclass
from .errors import TurnstileError, StaleStateError


@dataclass
class State:
    data: dict
    path: pathlib.Path
    loaded_digest: str

def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def load(path: pathlib.Path) -> State:
    path = pathlib.Path(path)
    if not path.exists():
        raise TurnstileError("state file not found: %s" % path)
    text = path.read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise TurnstileError("state file is not valid JSON: %s (%s)" % (path, e))
    return State(data=data, path=path, loaded_digest=digest(text))

def dumps(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

def write_atomic(path: pathlib.Path, text: str) -> None:
    """Write through a temp file in the same dir + os.replace: readers never see a partial file."""
    path = pathlib.Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".%s." % path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

def save(st: State) -> None:
    current = st.path.read_text() if st.path.exists() else ""
    if digest(current) != st.loaded_digest:
        raise StaleStateError("%s changed on disk since it was loaded; re-run the command" % st.path)
    text = dumps(st.data)
    write_atomic(st.path, text)
    st.loaded_digest = digest(text)

@contextlib.contextmanager
def locked(delivery: pathlib.Path, wait: bool = True):
    """Exclusive flock on state.json for the whole load → write → commit sequence (one machine; two clones
    are protected by git, with ledger.md merge=union). The lock is taken before load, so a waiter re-reads."""
    path = pathlib.Path(delivery) / "state.json"
    if not path.exists():
        raise TurnstileError("state file not found: %s" % path)
    with open(str(path), "r") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except OSError:
            raise TurnstileError("another turnstile process holds %s; retry" % path)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def pr(st: State, pr_id: str) -> dict:
    try:
        return st.data["prs"][pr_id]
    except KeyError:
        raise TurnstileError("unknown PR %s" % pr_id)

def story(st: State, sid: str) -> dict:
    try:
        return st.data["stories"][sid]
    except KeyError:
        raise TurnstileError("unknown story %s" % sid)

def repo_cfg(st: State, pr_id: str) -> dict:
    repo = pr_id.split("#", 1)[0]
    try:
        return st.data["epic"]["repos"][repo]
    except KeyError:
        raise TurnstileError("repo %s is not configured in epic.repos" % repo)
