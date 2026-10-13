import re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from _common import read_payload, block

RULES = [
    ("merge", r"\bgh\s+pr\s+merge\b"), ("ready", r"\bgh\s+pr\s+ready\b"), ("add-reviewer", r"--add-reviewer\b"),
    ("force-push", r"\bgit\s+push\b[^\n;&|]*(\s[\"']?--force(-with-lease)?\b|\s-[a-z]*f[a-z]*\b|\s\+\S)"), ("rebase", r"\bgit\s+rebase\b"),
    ("unsigned", r"--no-gpg-sign\b"), ("trailer", r"Co-Authored-By"), ("footer", r"Generated with \[Claude Code\]"),
    ("empty-variant-tag", r"service_github_tag=(?:''|\"\"|(?=[\"']?(?:\s|&|$)))"),
]

def main():
    cmd = (read_payload().get("tool_input") or {}).get("command") or ""
    flat = cmd.replace("\\\n", " ")
    for name, rx in RULES:
        if re.search(rx, flat, re.I | re.M):
            block("blocked by rule %s. The lead performs this action, or approve it through turnstile." % name)
    if re.search(r"requested_reviewers", flat) and "copilot-pull-request-reviewer" not in flat:
        block("blocked by rule human-reviewer-request. The lead requests human reviewers.")
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block("guard crashed (%s); failing closed." % e)
