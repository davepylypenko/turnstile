import os, pathlib, posixpath, re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload, block, agent_role

# global options that may sit between the binary and its subcommand: git -C dir / -c k=v / --opt[=v]; gh -R / --repo owner/repo
GIT = r"\bgit(?:\s+(?:-[Cc]\s+(?:\"[^\"]*\"|'[^']*'|\S+)|--?[\w.-]+(?:=\S+)?))*\s+"
GH = r"\bgh(?:\s+(?:-R|--repo)(?:\s+|=)\S+)*\s+"
PR = r"pr(?:\s+(?:-R|--repo)(?:\s+|=)\S+)*\s+"
COPILOT = "copilot-pull-request-reviewer[bot]"
WRITE_FLAGS = r"(?:-X\s*(?:POST|PUT|PATCH)|--method[\s=]+(?:POST|PUT|PATCH)|\s-[fF]\s|--field|--raw-field|--input|\s-d\s)"

RULES = [
    ("merge", GH + PR + r"merge\b"),
    ("ready", GH + PR + r"ready\b"),
    ("add-reviewer", r"--add-reviewer\b"),
    ("graphql-merge-or-ready", r"\b(?:markPullRequestReadyForReview|mergePullRequest|requestReviews|ready_for_review)\b"),
    ("force-push", GIT + r"push\b[^\n;&|]*(\s[\"']?--force(-with-lease)?\b|\s-[a-z]*f[a-z]*\b|\s\+\S)"),
    ("rebase", GIT + r"rebase\b|" + GIT + r"pull\b[^\n;&|]*\s(?:--rebase\b|-r\b)|pull\.rebase\s+true\b"),
    ("unsigned", r"--no-gpg-sign\b|commit\.gpgsign\s*=\s*false"),
    ("empty-variant-tag", r"service_github_tag=(?:''|\"\"|(?=[\"']?(?:\s|&|$)))|service_github_tag\s+(?:''|\"\")"),
    ("graphql-file", r"\bgraphql\b[^\n;&|]*(?:query=@|--input\b)|(?:query=@|--input\b)[^\n;&|]*\bgraphql\b"),
]
FILE_ARG = re.compile(r"(?:^|\s)(?:-F|--file|--body-file|--input)(?:=|\s+)[\"']?([^\s\"']+)")
# a PR/commit write: the only places where a trailer or the footer can land
WRITE_CTX = re.compile(GIT + r"commit\b|" + GH + PR + r"(?:create|edit)\b|" + GH + r"api\b", re.I)
CONTENT_RULES = [("trailer", r"Co-Authored-By"), ("footer", r"Generated with \[Claude Code\]")]
# the lead's actions never pass through the model's tool calls: the lead types `! TURNSTILE_LEAD=1 turnstile approve <ah-id>`
# in the Claude Code prompt (the `!` prefix runs outside the hooks). Any model-issued command that carries the approve
# command or the lead/migration markers, in any quoting/env/export/bash -c/heredoc form, is refused on the substring.
LEAD_ONLY = [("lead-approve", "turnstile approve"), ("lead-approve", "TURNSTILE_LEAD"), ("lead-migration", "TURNSTILE_MIGRATION")]
APPROVE = [r"(?:\bturnstile|turnstile_cli)\s+(?:--delivery[=\s]\S+\s+)?approve\b", r"turnstile_cli[^\n]*\bapprove\s*\("]
LEAD_HINT = ("The lead approves by typing `! TURNSTILE_LEAD=1 turnstile approve <ah-id>` in the Claude Code prompt themself "
             "(the `!` prefix runs outside the model's tool calls). Ask the lead; never run it.")

# R2-2: the delivery dir is written only by the CLI. A command that mentions state.json or the delivery dir and is
# not read-only is refused whatever interpreter it uses (perl/node/ruby/python heredocs, git restores, redirects).
READ_ONLY = {"cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg", "jq", "ls", "find", "wc", "diff", "stat", "file", "cd",
             "pwd", "echo", "printf", "test", "[", "true", "sort", "uniq", "cut", "tr", "column", "md5", "md5sum", "shasum", "sha256sum",
             "turnstile", "sed", "python3", "python", "xargs", "which", "type"}
GIT_READ_ONLY = {"diff", "log", "show", "status", "blame", "ls-files", "rev-parse", "cat-file", "grep", "branch", "remote", "describe",
                 "push", "fetch", "shortlog", "name-rev"}
GIT_RESTORE = re.compile(GIT + r"(?:checkout|switch|restore|stash|reset|clean)\b", re.I)
TREE_SUBS = {"checkout", "switch", "restore", "stash", "reset", "clean"}
# round 2 R2-12: an agent's own frontmatter hooks run this guard with TURNSTILE_ROLE set; these rules apply on top of the common ones
ROLE_RULES = {"tester": [("tester-push", GIT + r"push\b"), ("tester-commit", GIT + r"commit\b"),
                         ("tester-pr-write", GH + r"(?:pr|issue)(?:\s+(?:-R|--repo)(?:\s+|=)\S+)*\s+(?:comment|review|create|edit|close|reopen|merge|ready)\b"),
                         ("tester-api-write", r"\bgh\s+api\b[^\n;&|]*" + WRITE_FLAGS)]}
ROLE_HINT = {"tester": "the tester reports; the orchestrator records facts, and nobody pushes from a test run"}
HARMLESS_REDIRECTS = re.compile(r"\d?>\s*&\d|\d?>\s*/dev/null|&>\s*/dev/null|<<-?\s*\S+")
REDIRECT_TARGET = re.compile(r"\d?>{1,2}\s*(\S+)")
STATE_GLOB = re.compile(r"\bstate\.(?:json|\*|\?|\[)|\bstate[*?\[]")
# 2026-10-14 finding 1: the tester's evidence (PNG, JSON) and the agents' reports/briefs may be written by any command, as long as
# every delivery path the segment names is strictly inside one of these folders. The root and the CLI's files stay protected.
WRITABLE_SUBDIRS = ("evidence", "reports", "briefs")
PROTECTED = {"state.json", "ledger.md", "plan.md", "decisions.md", "board.html", ".state.lock", ".gitattributes", ".gitignore"}
UNSAFE_PATH = re.compile(r"[$`*?\[{~]")          # a computed or glob path may expand to `..`
# git writes go through `turnstile pass`; symlinks never; a shell runs code the guard does not see
NO_ALLOWANCE_HEADS = {"git", "ln", "turnstile", "turnstile_cli", "bash", "sh", "zsh", "dash", "ksh", "eval", "exec", "source", "."}
INLINE_CODE = re.compile(r"^(?:\S*/)?(?:python3?|node|deno|bun|perl|ruby|php|osascript)\b.*\s(?:-[a-zA-Z]*[ceEpr]\b|--eval\b|--print\b)"
                         r"|^(?:\S*/)?tar\b.*\s(?:-[a-zA-Z]*P|--absolute-names\b)")

def _segments(flat: str):
    return [s.strip() for s in re.split(r"\n|;|&&|\|\||\|&?", flat) if s.strip()]

HEREDOC = re.compile(r"<<-?\s*[\"']?(\w+)[\"']?")

def _segments_for_writes(flat: str, mention):
    """Segments for the delivery-write check: a heredoc body is data for its command, so its lines count only when they
    name the delivery dir themselves (a `bash`/`python3` heredoc is refused on its own head line anyway)."""
    out, terminators = [], []
    for line in flat.split("\n"):
        if terminators:
            if line.strip() == terminators[0]:
                terminators.pop(0)
            elif mention(line):
                out.extend(_segments(line))
            continue
        out.extend(_segments(line))
        terminators.extend(HEREDOC.findall(line))
    return out

def _read_only_segment(seg: str, mention, in_delivery: bool) -> bool:
    """True when the segment cannot write into the delivery dir. `mention(text)` tells whether a path names it;
    `in_delivery` is set when an earlier segment cd-ed into it, so relative redirects count as writes."""
    for target in REDIRECT_TARGET.findall(HARMLESS_REDIRECTS.sub(" ", seg)):
        if in_delivery or mention(target):
            return False
    words = seg.split()
    while words and re.match(r"^\w+=", words[0]):
        words.pop(0)
    if not words:
        return True
    head = words[0].rsplit("/", 1)[-1]
    if head == "git":
        # the subcommand is the first non-option word; -C / -c take an argument
        sub = None
        it = iter(words[1:])
        for w in it:
            if w in ("-C", "-c"):
                next(it, None); continue
            if w.startswith("-"):
                continue
            sub = w; break
        return sub in GIT_READ_ONLY
    if head in ("python", "python3"):
        return len(words) > 2 and words[1] == "-m" and words[2] == "turnstile_cli"
    if head == "sed":
        return not re.search(r"\s(?:-[a-zA-Z]*i|--in-place)\b", seg)
    if head == "find" and re.search(r"\s-(?:exec|execdir|ok|okdir|delete|fprint0?|fprintf|fls)\b", seg):
        return False
    if head == "sort" and re.search(r"\s(?:-[a-zA-Z]*o|--output)\b", seg):
        return False
    if head in ("xargs", "env"):
        return len(words) > 1 and _read_only_segment(" ".join(words[1:]), mention, in_delivery)
    return head in READ_ONLY

def _delivery_matcher(cwd: str):
    """Returns mention(text) -> str: the delivery reference found in `text` ('' when none). `mention.paths(seg)` lists the
    paths relative to the delivery dir that the segment's words name ('' for the dir itself); `mention.abs_path` is the
    resolved delivery dir when it could be found."""
    name, abs_path = "delivery", None
    try:
        from _common import delivery_dir
        d = delivery_dir(cwd); name, abs_path = d.name, str(d)
    except Exception:
        pass
    token = re.compile(r"(?<![\w.-])%s(?=/|\s|$)" % re.escape(name), re.M)
    def mention(text: str) -> str:
        if STATE_GLOB.search(text):
            return "state.json"
        if abs_path and abs_path in text:
            return abs_path
        if token.search(text):
            return name + "/"
        return ""
    def paths(seg: str):
        out = []
        for w in seg.split():
            rel = None
            if abs_path and abs_path in w:
                rel = w[w.index(abs_path) + len(abs_path):]
            else:
                m = token.search(w)
                if m:
                    rel = w[m.end():]
            if rel is not None:
                out.append(rel.lstrip("/"))
        return out
    mention.paths = paths; mention.abs_path = abs_path
    return mention

def _writable_segment(seg: str, mention) -> bool:
    """True when every delivery path the segment names is strictly inside evidence/, reports/ or briefs/ (after `..`
    normalisation and, when the dir exists, symlink resolution), none is computed, and the command is not git/ln."""
    if STATE_GLOB.search(seg):
        return False
    words = seg.split()
    while words and re.match(r"^\w+=", words[0]):
        words.pop(0)
    if words and words[0] == "env":
        words = [w for w in words[1:] if not re.match(r"^\w+=", w)]
    if not words or words[0].rsplit("/", 1)[-1] in NO_ALLOWANCE_HEADS:
        return False
    if INLINE_CODE.search(" ".join(words)):  # round 2: inline code or tar -P writes wherever it likes, whatever evidence path it also names
        return False
    rels = mention.paths(seg)
    if not rels:
        return False
    for rel in rels:
        if not rel or UNSAFE_PATH.search(rel):
            return False
        norm = posixpath.normpath(rel)
        parts = norm.split("/")
        if len(parts) < 2 or parts[0] not in WRITABLE_SUBDIRS or any(p in PROTECTED for p in parts):
            return False
        if mention.abs_path:  # a symlink under evidence/ must not lead back to the root or the CLI's files
            root = os.path.realpath(mention.abs_path)
            real = os.path.relpath(os.path.realpath(os.path.join(root, norm)), root).split(os.sep)
            if len(real) < 2 or real[0] not in WRITABLE_SUBDIRS or any(p in PROTECTED for p in real):
                return False
    return True

def _worktree_root(path: str):
    """The git worktree that contains `path` (the nearest ancestor with a .git dir or file), or None."""
    d = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent

def _git_call(seg: str):
    """(subcommand, the words after it, the -C dir) of a git segment; None when the segment is not a git call."""
    words = seg.split()
    while words and re.match(r"^\w+=", words[0]):
        words.pop(0)
    if words and words[0] == "env":
        words = [w for w in words[1:] if not re.match(r"^\w+=", w)]
    if not words or words[0].rsplit("/", 1)[-1] != "git":
        return None
    cdir, sub, i = None, None, 1
    while i < len(words):
        w = words[i]
        if w in ("-C", "-c"):
            if w == "-C" and i + 1 < len(words):
                cdir = words[i + 1]
            i += 2; continue
        if w.startswith("-"):
            i += 1; continue
        sub = w; break
    return sub, (words[i + 1:] if sub else []), cdir

def _tree_wide_reset(seg: str, cwd: str, delivery_abs):
    """Round 2 R2-8: `git checkout|switch|restore|stash|reset|clean` run inside the knowledge worktree that holds the delivery
    dir, with no pathspec (a branch switch, `reset --hard`, `stash`, `clean -fd`) or with one that covers the delivery dir
    (`.`, `..`, `:/`, an ancestor), rolls state.json and ledger.md back without naming them. Returns the refusal text."""
    call = _git_call(seg)
    if not call or call[0] not in TREE_SUBS:
        return None
    sub, rest, cdir = call
    eff = os.path.realpath(os.path.join(cwd or ".", cdir) if cdir else (cwd or "."))
    if not delivery_abs:
        try:
            from _common import delivery_dir
            delivery_abs = str(delivery_dir(eff))
        except Exception:
            return None
    root = _worktree_root(delivery_abs)
    if root is None or not (eff == root or eff.startswith(root + os.sep)):
        return None
    if sub == "stash" and rest and rest[0] in ("list", "show", "drop", "clear"):
        return None
    if sub == "clean" and any(w in ("-n", "--dry-run") or (w.startswith("-") and not w.startswith("--") and "n" in w) for w in rest):
        return None
    why = "blocked by rule knowledge-worktree-reset. git %s inside the knowledge worktree %s %s: the delivery dir changes only through 'turnstile pass'; name a path outside it."
    if "--" in rest:
        paths = rest[rest.index("--") + 1:]
        if not paths:
            return why % (sub, root, "with no pathspec resets the whole tree")
    else:
        paths = [w for w in rest if not w.startswith("-")]
        if sub in ("checkout", "switch", "reset", "stash") and (not paths or any(not os.path.exists(os.path.join(eff, w)) for w in paths)):
            return why % (sub, root, "with a ref or no pathspec resets the whole tree")
        if not paths:
            return why % (sub, root, "with no pathspec resets the whole tree")
    dl = os.path.realpath(delivery_abs)
    for pth in paths:
        if pth.startswith(":") or UNSAFE_PATH.search(pth):
            return why % (sub, root, "with the pathspec %r (magic, glob or computed) may cover the delivery dir" % pth)
        ap = os.path.realpath(os.path.join(eff, pth))
        if ap == dl or dl.startswith(ap + os.sep) or ap.startswith(dl + os.sep):
            return why % (sub, root, "with the pathspec %r covers the delivery dir" % pth)
    return None

def _file_contents(flat: str, cwd: str):
    """Text of every file a write command points at with -F/--file/--body-file/--input (R2-11); missing files are skipped."""
    for name in FILE_ARG.findall(flat):
        p = pathlib.Path(name) if pathlib.Path(name).is_absolute() else pathlib.Path(cwd or ".") / name
        try:
            if p.is_file() and p.stat().st_size < 1_000_000:
                yield name, p.read_text(errors="replace")
        except OSError:
            continue

def check(cmd: str, cwd: str = ".", role: str = "") -> None:
    joined = cmd.replace("\\\n", " ")
    stripped = re.sub(r"[\"'\\]", "", joined)  # also unquoted: gh "pr" merge, T\URNSTILE_LEAD
    for flat in (joined, stripped, re.sub(r"\s+", " ", stripped)):
        _check(flat, role)
    if WRITE_CTX.search(stripped):
        for name, text in _file_contents(stripped, cwd):
            for rule, rx in CONTENT_RULES:
                if re.search(rx, text, re.I):
                    block("blocked by rule %s. %s carries it: commits carry no trailer and PR bodies no generated-with footer." % (rule, name))
    flat = re.sub(r"[ \t]+", " ", stripped)
    mention_fn = _delivery_matcher(cwd)
    mention = mention_fn(flat)
    for seg in _segments(flat):  # round 2 R2-8: tree-wide resets in the knowledge worktree name no delivery path
        why = _tree_wide_reset(seg, cwd, mention_fn.abs_path)
        if why:
            block(why)
    # round 2: the Bash cwd persists across calls, so `cd delivery/evidence` then `cp x ../ledger.md` names no delivery path
    cwd_inside = bool(mention_fn.abs_path) and (os.path.realpath(cwd or ".") + os.sep).startswith(os.path.realpath(mention_fn.abs_path) + os.sep)
    mention = mention or ("cwd " + cwd if cwd_inside else "")
    if mention:
        if GIT_RESTORE.search(flat):
            block("blocked by rule delivery-git-restore. git checkout/restore/stash/reset must not touch %s: the delivery dir changes only "
                  "through 'turnstile pass'." % mention)
        bad, in_delivery = [], cwd_inside
        for seg in _segments_for_writes(flat, mention_fn):
            if not _read_only_segment(seg, mention_fn, in_delivery) and (in_delivery or not _writable_segment(seg, mention_fn)):
                bad.append(seg)
            if re.match(r"cd\s", seg) and mention_fn(seg):
                in_delivery = True
        if bad:
            block("blocked by rule delivery-write. The command mentions %s and '%s' is not read-only (allowed: cat, less, head, tail, grep, jq, "
                  "git diff/log/show/status, turnstile …) and does not write only inside evidence/, reports/ or briefs/ (literal paths, no "
                  "`..`, no symlinks, no cd into the delivery dir). The rest of the delivery dir is written only by 'turnstile pass' and, for "
                  "plan.md/decisions.md, the Write tool." % (mention, bad[0][:60]))

TURNSTILE_SUBS = {"pass", "reconcile", "status", "render-board", "jira-synced", "init", "plan-submitted", "bug", "brief", "-h", "--help", "--version"}

def _turnstile_sub_ok(flat: str) -> bool:
    """R3-1: a turnstile invocation names its subcommand literally; `turnstile $(echo approve)` / `$X` spellings are refused."""
    for seg in _segments(flat):
        words = seg.split()
        while words and re.match(r"^\w+=", words[0]):
            words.pop(0)
        if words and words[0] == "env":
            words = [w for w in words[1:] if not re.match(r"^\w+=", w)]
        for i, w in enumerate(words[:-1]):  # anywhere in the segment: a computed word after turnstile is a computed subcommand
            if w.rsplit("/", 1)[-1] in ("turnstile", "turnstile_cli") and re.search(r"[$`]", words[i + 1]):
                return False
        if words and words[0].rsplit("/", 1)[-1] in ("python", "python3") and words[1:3] == ["-m", "turnstile_cli"]:
            words = words[2:]
        if not words or words[0].rsplit("/", 1)[-1] not in ("turnstile", "turnstile_cli"):
            continue
        rest = words[1:]
        while rest and rest[0].startswith("--delivery"):
            rest = rest[1:] if "=" in rest[0] else rest[2:]
        if rest and rest[0] not in TURNSTILE_SUBS:
            return False
    return True

def _check(flat: str, role: str = "") -> None:
    for name, rx in ROLE_RULES.get(role, []):
        if re.search(rx, flat, re.I | re.M):
            block("blocked by rule %s. The %s role cannot run this: %s." % (name, role, ROLE_HINT.get(role, "report it instead")))
    if not _turnstile_sub_ok(flat):
        block("blocked by rule lead-approve. turnstile subcommands are named literally (%s); 'approve' is the lead's. %s"
              % (", ".join(sorted(TURNSTILE_SUBS)), LEAD_HINT))
    for name, needle in LEAD_ONLY:
        if needle in flat:
            block("blocked by rule %s. `%s` is the lead's marker. %s" % (name, needle, LEAD_HINT))
    for rx in APPROVE:
        if re.search(rx, flat):
            block("blocked by rule lead-approve. 'turnstile approve' is the lead's action. " + LEAD_HINT)
    for name, rx in RULES:
        if re.search(rx, flat, re.I | re.M):
            block("blocked by rule %s. The lead performs this action, or approve it through turnstile." % name)
    if re.search(r"pulls/\d+/merge\b", flat) and re.search(WRITE_FLAGS, flat):
        block("blocked by rule rest-merge. The lead merges.")
    if WRITE_CTX.search(flat):
        for name, rx in CONTENT_RULES:
            if re.search(rx, flat, re.I):
                block("blocked by rule %s. Commits carry no trailer and PR bodies no generated-with footer." % name)
    if "requested_reviewers" in flat:
        values = re.findall(r"reviewers\[\]=[\"']?([^\"'\s&]+)", flat)
        writing = bool(values) or re.search(WRITE_FLAGS, flat) is not None
        if writing and ("--input" in flat or not values or any(v != COPILOT for v in values)):
            block("blocked by rule human-reviewer-request. The lead requests human reviewers (only %s may be requested here)." % COPILOT)

def main():
    p = read_payload()
    ti = p.get("tool_input")
    if not isinstance(ti, dict) or not isinstance(ti.get("command"), str):
        block("malformed hook payload (no tool_input.command); failing closed.")
    check(ti["command"], p.get("cwd") or ".", agent_role(p))
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block("guard crashed (%s); failing closed." % e)
