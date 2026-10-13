import re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload, block

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
    ("rebase", GIT + r"rebase\b|" + GIT + r"pull\b[^\n;&|]*\s(?:--rebase\b|-r\b)"),
    ("unsigned", r"--no-gpg-sign\b|commit\.gpgsign\s*=\s*false"),
    ("empty-variant-tag", r"service_github_tag=(?:''|\"\"|(?=[\"']?(?:\s|&|$)))"),
]
# a PR/commit write: the only places where a trailer or the footer can land
WRITE_CTX = re.compile(GIT + r"commit\b|" + GH + PR + r"(?:create|edit)\b|" + GH + r"api\b", re.I)
CONTENT_RULES = [("trailer", r"Co-Authored-By"), ("footer", r"Generated with \[Claude Code\]")]
STATE_WRITE = [r">{1,2}\s*[\"']?[^\s\"'|;&]*state\.json", r"\bsed\s+(?:-[a-zA-Z]*i|--in-place)\b", r"\btee\b", r"\bpython3?\s+-c\b",
               r"\b(?:cp|mv|rm|install|truncate|dd)\b"]
APPROVE = [r"(?:\bturnstile|turnstile_cli)\s+(?:--delivery[=\s]\S+\s+)?approve\b", r"turnstile_cli[^\n]*\bapprove\s*\("]

def check(cmd: str) -> None:
    for flat in (cmd.replace("\\\n", " "), re.sub(r"[\"'\\]", "", cmd.replace("\\\n", " "))):  # also unquoted: gh "pr" merge
        _check(flat)

def _check(flat: str) -> None:
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
    if re.search(r"state\.json\b", flat) and "TURNSTILE_MIGRATION=1" not in flat:
        for rx in STATE_WRITE:
            if re.search(rx, flat, re.I):
                block("blocked by rule state-json-write. state.json is written only by 'turnstile pass' (TURNSTILE_MIGRATION=1 for a migration).")
    for rx in APPROVE:
        if re.search(rx, flat) and not re.search(r"(?:^|[\s;&|])TURNSTILE_LEAD=1\s+[^;&|\n]*approve", flat, re.M):
            block("blocked by rule lead-approve. 'turnstile approve' is the lead's action: the lead types "
                  "`TURNSTILE_LEAD=1 turnstile approve <ah-id>` themself; agents only report what awaits the lead.")

def main():
    p = read_payload()
    ti = p.get("tool_input")
    if not isinstance(ti, dict) or not isinstance(ti.get("command"), str):
        block("malformed hook payload (no tool_input.command); failing closed.")
    check(ti["command"])
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block("guard crashed (%s); failing closed." % e)
