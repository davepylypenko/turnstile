import argparse, pathlib, sys
from . import __version__, paths
from .errors import TurnstileError

def build_parser():
    p = argparse.ArgumentParser(prog="turnstile", description="Evidence-gated delivery. No ticket, no entry.")
    p.add_argument("--version", action="version", version="turnstile " + __version__)
    p.add_argument("--delivery", help="path to the delivery dir (default: resolved from .turnstile)")
    sub = p.add_subparsers(dest="cmd")

    ps = sub.add_parser("pass", help="move a PR or story to the next state with evidence")
    ps.add_argument("kind", choices=["pr", "story"]); ps.add_argument("ident"); ps.add_argument("target")
    for flag, kw in [("--head", {}), ("--ci", {"choices": ["success", "failure"]}), ("--deep-review", {}),
                     ("--rounds", {"type": int}), ("--gate", {}), ("--copilot", {"type": int}), ("--slack", {}),
                     ("--reviewers", {}), ("--approved", {}), ("--approvals", {}), ("--open-threads", {"type": int}),
                     ("--reason", {}), ("--merged-sha", {}), ("--report", {}), ("--build", {}),
                     ("--cases-pass", {"type": int}), ("--cases-fail", {"type": int}),
                     ("--figma-parity", {"choices": ["pass", "fail"]}),
                     ("--companions", {"help": "paired PRs the same Slack message may mention (e.g. locales#5)"})]:
        ps.add_argument(flag, **kw)
    ps.add_argument("--not-clean", action="store_true"); ps.add_argument("--no-commit", action="store_true")
    ps.add_argument("--offline", action="store_true", help="skip the GitHub head check (loud WARN; READY/ON_HUMAN_REVIEW stay refused)")

    js = sub.add_parser("jira-synced", help="record that the Jira transition was performed"); js.add_argument("ident"); js.add_argument("status")
    ap = sub.add_parser("approve", help="record the lead's approval of an awaiting_human entry"); ap.add_argument("ah_id")
    sub.add_parser("render-board", help="render board.html from state.json")
    rc = sub.add_parser("reconcile", help="read-only drift check against GitHub"); rc.add_argument("--json", action="store_true")
    sub.add_parser("status", help="reconcile + where we are")
    ini = sub.add_parser("init", help="create the knowledge worktree and the delivery/ skeleton for an epic")
    for flag, kw in [("--epic", {"required": True}), ("--workitem", {"required": True}), ("--knowledge", {"required": True}),
                     ("--lead", {"required": True}), ("--lead-github", {"required": True}), ("--github-org", {"required": True}),
                     ("--repo", {"action": "append", "default": [], "dest": "repos", "help": "JSON: {name, base, epic_branch, slack[, gate, gate_check, ci_ignore, copilot, branch_prefix]}; repeatable"}),
                     ("--variant", {}), ("--desk", {}), ("--board-url", {}), ("--workspace", {"default": "."}),
                     ("--knowledge-base", {"default": "main"}), ("--pm", {}), ("--design", {}),
                     ("--recipe", {"default": "references/env/pdffiller-dev.md"})]:
        ini.add_argument(flag, **kw)
    return p

def main(argv=None):
    parser = build_parser()
    a = parser.parse_args(argv)
    if a.cmd is None:
        parser.print_help(); return 0
    try:
        if a.cmd == "init":
            from .init_cmd import run as init_run, InitOptions
            return init_run(InitOptions(**{k: v for k, v in vars(a).items() if k not in ("cmd", "delivery")}))
        delivery = paths.find_delivery(pathlib.Path.cwd(), a.delivery)
        if a.cmd == "pass":
            from .pass_cmd import run, Options
            o = Options(**{k.replace("-", "_"): v for k, v in vars(a).items()
                           if k not in ("cmd", "delivery", "kind", "ident", "target")})
            return run(delivery, a.kind, a.ident, a.target, o)
        if a.cmd == "jira-synced":
            from .pass_cmd import jira_synced
            return jira_synced(delivery, a.ident, a.status)
        if a.cmd == "approve":
            from .pass_cmd import approve
            return approve(delivery, a.ah_id)
        if a.cmd == "render-board":
            from . import board, state
            board.render(state.load(delivery / "state.json").data, delivery)
            print("OK rendered %s" % (delivery / "board.html")); return 0
        if a.cmd in ("reconcile", "status"):
            from .reconcile import cli
            return cli(delivery, as_json=getattr(a, "json", False), status=(a.cmd == "status"))
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
