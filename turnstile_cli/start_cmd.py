import pathlib, re
from dataclasses import dataclass
from typing import List, Optional
from . import config, members, paths, workspace
from .attach_cmd import AttachOptions, run as attach_run
from .init_cmd import InitIO, InitOptions, _same_epic, epic_branch_name, run as init_run
from .errors import TurnstileError

WORKITEMS = "context/workitems"
KICKOFF_NEXT = ("NEXT: kickoff — read the workitem docs per references/kickoff.md, add each repo with turnstile repo add, "
                "write delivery/plan.md, then turnstile plan-submitted")
STATUS_NEXT = "NEXT: turnstile status"
ORIGIN_RX = re.compile(r"^(?:git@[^:]+:|https?://[^/]+/|ssh://[^/]+/)([^/]+)/[^/]+?(?:\.git)?/?$")

@dataclass
class StartOptions:
    epic: str
    clone_root: Optional[str] = None
    knowledge: Optional[str] = None
    workitem: Optional[str] = None
    github: Optional[str] = None
    name: Optional[str] = None
    variant: Optional[str] = None
    desk: Optional[str] = None
    board_url: Optional[str] = None
    chat_language: Optional[str] = None
    jira_base_url: Optional[str] = None
    story_mode: Optional[str] = None
    flag: Optional[str] = None
    knowledge_base: str = "main"
    no_push: bool = False

def github_org(origin: str) -> str:
    m = ORIGIN_RX.match(origin.strip())
    if not m:
        raise TurnstileError("cannot read the GitHub owner from the knowledge clone's origin %r (expected git@github.com:<org>/<repo>.git or https://github.com/<org>/<repo>)" % origin)
    return m.group(1)

def _login(o: StartOptions, io: InitIO) -> str:
    login = (o.github or "").strip() or (io.github_login() or "").strip()
    if not login:
        raise TurnstileError("no GitHub login: `gh api user --jq .login` returned nothing on this machine (run gh auth login, or pass --github <login>)")
    return login

def _remote_branch_exists(io: InitIO, knowledge: pathlib.Path, branch: str) -> bool:
    try:
        return bool(io.git(["ls-remote", "--heads", "origin", branch], knowledge).strip())
    except TurnstileError as e:
        raise TurnstileError("cannot reach origin of %s to look for %s (%s)" % (knowledge, branch, e))

def _ref(io: InitIO, knowledge: pathlib.Path, base: str) -> str:
    try:
        io.git(["fetch", "origin", base], knowledge); return "origin/" + base
    except TurnstileError as e:
        print("WARN %s; reading context/workitems from the local %s, which may be stale" % (e, base)); return base

def _ls(io: InitIO, knowledge: pathlib.Path, ref: str, path: str) -> List[str]:
    try:
        return [ln.strip() for ln in io.git(["ls-tree", "--name-only", "%s:%s" % (ref, path)], knowledge).splitlines() if ln.strip()]
    except TurnstileError:
        return []

def find_workitem(io: InitIO, knowledge: pathlib.Path, key: str, base: str) -> str:
    ref = _ref(io, knowledge, base)
    word = re.compile(r"(?<![\w-])%s(?!\w)" % re.escape(key), re.I)
    hits = []
    for folder in _ls(io, knowledge, ref, WORKITEMS):
        if key.lower() in folder.lower():
            hits.append(folder); continue
        for name in _ls(io, knowledge, ref, "%s/%s" % (WORKITEMS, folder)):
            if not name.endswith(".md"):
                continue
            try:
                text = io.git(["show", "%s:%s/%s/%s" % (ref, WORKITEMS, folder, name)], knowledge)
            except TurnstileError:
                continue
            if word.search(text):
                hits.append(folder); break
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise TurnstileError("several workitems mention %s: %s — pass --workitem <name>" % (key, ", ".join(hits)))
    raise TurnstileError("no workitem folder under %s mentions %s; create one (%s/%s/<slug>/) or pass --workitem <name>" % (WORKITEMS, key, knowledge, WORKITEMS))

def run(o: StartOptions, io: Optional[InitIO] = None, writer=None) -> int:
    io = io or InitIO()
    key = o.epic.strip().upper()
    try:
        cwd = pathlib.Path.cwd()
        root = workspace.detect_root(cwd, o.clone_root, o.knowledge, [], io)
        knowledge = workspace.resolve_knowledge(root, o.knowledge)
        ws = workspace.default_workspace(root, key)
        branch = epic_branch_name(key)
        existing = _same_epic(ws, key) or _remote_branch_exists(io, knowledge, branch)
        if existing:
            rc = attach_run(AttachOptions(epic=key, knowledge=str(knowledge), clone_root=str(root), workspace=str(ws), workitem=o.workitem,
                                          chat_language=o.chat_language, github=o.github, name=(o.name or "").strip() or (io.github_name() or "").strip() or None,
                                          variant=o.variant, desk=o.desk, board_url=o.board_url, no_push=o.no_push), io, writer)
            if rc == 2:
                return rc
        else:
            login = _login(o, io)
            workitem = o.workitem or find_workitem(io, knowledge, key, o.knowledge_base)
            org = github_org(workspace._origin(io, knowledge))
            opts = InitOptions(epic=key, workitem=workitem, lead=(o.name or "").strip() or (io.github_name() or "").strip() or login, lead_github=login,
                               github_org=org, knowledge=str(knowledge), clone_root=str(root), repos=[], variant=o.variant or members.default_variant(key, login),
                               desk=o.desk, board_url=o.board_url, knowledge_base=o.knowledge_base, chat_language=o.chat_language or config.chat_language(),
                               agent_github=login, flag=o.flag, story_mode=o.story_mode or "stack", jira_base_url=o.jira_base_url, no_push=o.no_push)
            rc = init_run(opts, io, nexts=False)
            if rc != 0:
                return rc
        try:
            paths.set_active(root, key)
        except OSError as e:
            print("WARN: active epic not recorded in %s: %s" % (paths.registry_path(), e))
        print("OK start %s" % key)
        print(STATUS_NEXT if existing else KICKOFF_NEXT)
        return rc
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
