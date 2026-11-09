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
                     ("--figma-parity", {"choices": ["pass", "fail", "not_testable_here"]}),
                     ("--cases-not-testable", {"type": int, "help": "cases with verdict not_testable_here in the recorded run (default 0)"}),
                     ("--failed-cases", {"help": "comma-separated ids of the failed cases of the recorded run (bugs are keyed by story + case)"}),
                     ("--rerequested", {"help": "REWORK → ON_HUMAN_REVIEW: comma-separated thread authors re-requested on GitHub after the replies (verified against reviewRequests)"}),
                     ("--arm", {"choices": ["treatment", "control"], "help": "trunk mode: the arm a recorded env run tested (treatment = flag on, control = flag off)"}),
                     ("--base-heads", {"help": "trunk mode, with --build --head: repo=sha pairs when the story spans repos (default: --head for every repo)"}),
                     ("--owner", {"help": "story IN_PROGRESS: the member (GitHub login) who owns the story (default: this machine's member)"})]:
        ps.add_argument(flag, **kw)
    ps.add_argument("--not-clean", action="store_true"); ps.add_argument("--no-commit", action="store_true")
    ps.add_argument("--full", action="store_true", help="the recorded env run covered every case of the story (DONE needs a full clean run)")
    ps.add_argument("--offline", action="store_true", help="skip the GitHub head check (loud WARN; READY/ON_HUMAN_REVIEW stay refused)")

    js = sub.add_parser("jira-synced", help="record that the Jira transition was performed"); js.add_argument("ident"); js.add_argument("status")
    js.add_argument("--assignee", help="Atlassian account id of the ticket's holder: yourself (atlassianUserInfo) on take-up, or whoever already holds it; re-run to record a hand-over made by hand")
    js.add_argument("--assignee-name", help="display name for the ledger and the board (with --assignee)")
    ap = sub.add_parser("approve", help="record the lead's approval of an awaiting_human entry"); ap.add_argument("ah_id")
    sub.add_parser("render-board", help="render board.html from state.json")
    rc = sub.add_parser("reconcile", help="read-only drift check against GitHub"); rc.add_argument("--json", action="store_true")
    stp = sub.add_parser("status", help="reconcile + where we are")
    stp.add_argument("--brief", action="store_true", help="only SYNC, the PRs/stories whose state or head changed since the previous status, the awaiting list and the anomalies")
    bg = sub.add_parser("bug", help="record or update a bug found by the tester or the lead"); bsub = bg.add_subparsers(dest="bug_cmd"); p.bug_parser = bg
    ba = bsub.add_parser("add"); ba.add_argument("--story", required=True); ba.add_argument("--title", required=True)
    ba.add_argument("--source", required=True); ba.add_argument("--pr"); ba.add_argument("--figma"); ba.add_argument("--note", default="")
    ba.add_argument("--case", help="test-case id the bug covers (one bug per story + case; a persisting fail reopens it)")
    ba.add_argument("--arm", choices=["treatment", "control"], help="trunk mode: the arm the bug was found on (default treatment)")
    bs = bsub.add_parser("set"); bs.add_argument("bug_id"); bs.add_argument("--state", choices=["todo", "ai", "testing", "done"]); bs.add_argument("--pr"); bs.add_argument("--note")
    prp = sub.add_parser("pr", help="register a PR of the epic (DEV) from its GitHub facts"); psub = prp.add_subparsers(dest="pr_cmd"); p.pr_parser = prp
    pa = psub.add_parser("add"); pa.add_argument("ident"); pa.add_argument("--story", required=True); pa.add_argument("--ticket", required=True)
    pa.add_argument("--no-commit", action="store_true"); pa.add_argument("--owner", help="the member (GitHub login) who owns the PR (default: this machine's member)"); pa.add_argument("--stacked-on", help="trunk mode: the open PR of the story this PR deliberately stacks on (its base must be that PR's branch)")
    th = sub.add_parser("threads", help="classify human review threads from GitHub facts: self_resolved (reply at once) / needs_lead (the lead's word)")
    th.add_argument("pr"); th.add_argument("--self-resolved", default="", help="comma-separated thread ids (PRRT_…) or REST comment ids fixed or justified in code")
    th.add_argument("--needs-lead", default="", help="comma-separated thread ids or REST comment ids that need the lead's decision (opens one reply entry each)")
    th.add_argument("--report", help="the comments-handler report with the draft replies (relative to delivery/)"); th.add_argument("--no-commit", action="store_true")
    br = sub.add_parser("brief", help="render an agent brief from its template (the dispatch helper)"); br.add_argument("agent"); br.add_argument("name")
    br.add_argument("--var", action="append", default=[], dest="vars"); br.add_argument("--force", action="store_true"); br.add_argument("--no-commit", action="store_true")
    pl = sub.add_parser("plan-submitted", help="read stories from plan.md into state and open the lead's plan approval"); pl.add_argument("--no-commit", action="store_true")
    cf = sub.add_parser("config", help="agent models/effort, review skills and the send skill: user (~/.config/turnstile/config.json or $TURNSTILE_USER_CONFIG) > epic (state.json) > plugin defaults")
    csub = cf.add_subparsers(dest="config_cmd"); csub.add_parser("list", help="effective values with their source")
    cs = csub.add_parser("set"); cs.add_argument("assignment", metavar="key=value", help="models.<agent>=<model>[:<effort>], review_skill=/skill, story_review_skill=/skill, send_skill=/skill (the local skill that posts PRs to Slack review; default /send-pr-review); value 'default' resets")
    cu = csub.add_parser("unset"); cu.add_argument("key", help="reset the key in the chosen layer")
    ca = csub.add_parser("apply", help="apply an epic-layer change the lead approved (turnstile approve <ah-id>)"); ca.add_argument("ah_id")
    ca.add_argument("--no-commit", action="store_true"); ca.add_argument("--no-push", action="store_true")
    for c in (cs, cu):
        c.add_argument("--epic", action="store_true", help="write epic state (state.json, committed) instead of the user file"); c.add_argument("--no-commit", action="store_true")
    sub.add_parser("sync", help="fetch origin, fast-forward the epic branch and push it (never rebase or force); refuses diverged histories")
    at = sub.add_parser("attach", help="continue an existing epic from another machine: <clone root>/<key> with the knowledge worktree of origin/epic/<key>, a worktree per repo, .turnstile, workspace CLAUDE.md, status")
    for flag, kw in [("--epic", {"required": True}), ("--knowledge", {"help": "the knowledge clone (default: <clone root>/pdffiller-knowledge)"}),
                     ("--clone-root", {"help": "the folder that holds the clones (default: detected from the cwd — the knowledge clone's parent, or the cwd when it holds a named clone)"}),
                     ("--workspace", {"help": "the workspace folder to create (default: <clone root>/<epic key, lower case>)"}),
                     ("--workitem", {"help": "the workitem folder (needed when the epic branch holds several deliveries)"}),
                     ("--chat-language", {"help": "default: the epic's recorded chat_language"}),
                     ("--github", {"help": "your GitHub login (default: gh api user)"}), ("--name", {"help": "display name (default: the login)"}),
                     ("--variant", {"help": "your Prometey variant (default: <epic key>-<login>, lower case)"}), ("--desk", {"help": "your editor desk, e.g. desk05 (default: none)"}),
                     ("--board-url", {"help": "your board artifact url, when it already exists (default: a new artifact on the first publish)"})]:
        at.add_argument(flag, **kw)
    bu = sub.add_parser("board-url", help="record the url of this machine's board artifact for the current member"); bu.add_argument("url"); bu.add_argument("--no-push", action="store_true")
    for sp in (ps, js, ba, bs, pa, th, br, pl, cs, cu):
        sp.add_argument("--no-push", action="store_true", help="commit without pushing the epic branch (recorded as NOT PUSHED; READY/ON_HUMAN_REVIEW/APPROVED/MERGED/DONE then need turnstile sync)")
    ini = sub.add_parser("init", help="create the epic workspace <clone root>/<key>: the knowledge worktree, a worktree per repo and the delivery/ skeleton")
    for flag, kw in [("--epic", {"required": True}), ("--workitem", {"required": True}),
                     ("--knowledge", {"help": "the knowledge clone (default: <clone root>/pdffiller-knowledge)"}),
                     ("--clone-root", {"help": "the folder that holds the clones (default: detected from the cwd — the knowledge clone's parent, or the cwd when it holds a named clone)"}),
                     ("--lead", {"required": True}), ("--lead-github", {"required": True}), ("--github-org", {"required": True}),
                     ("--agent-github", {"help": "GitHub login the agents post thread replies as (default: --lead-github)"}),
                     ("--repo", {"action": "append", "default": [], "dest": "repos", "help": "JSON: {name, base, slack[, epic_branch, gate, gate_check, ci_ignore, copilot, branch_prefix, path]}; repeatable; path = the clone when it is not <clone root>/<name>"}),
                     ("--variant", {}), ("--desk", {}), ("--board-url", {}),
                     ("--workspace", {"help": "the workspace folder to create (default: <clone root>/<epic key, lower case>)"}),
                     ("--knowledge-base", {"default": "main"}), ("--pm", {}), ("--design", {}),
                     ("--recipe", {"default": "references/env/pdffiller-dev.md"}),
                     ("--chat-language", {"default": "English", "help": "language the orchestrator chats with the lead in (written to the workspace CLAUDE.md)"}),
                     ("--flag", {"help": "the one experiment feature flag of the epic (trunk mode; also: turnstile config set flag=<name> --epic)"}),
                     ("--story-mode", {"default": "stack", "choices": ["stack", "trunk"], "help": "default story mode for plan.md stories without `mode` (trunk recommended: PRs merge into the base behind the flag)"}),
                     ("--models", {"help": "JSON agent → {model, effort} merged over the defaults (model: haiku|sonnet|opus|fable, effort: low|medium|high|xhigh)"})]:
        ini.add_argument(flag, **kw)
    return p

def main(argv=None):
    parser = build_parser()
    a = parser.parse_args(argv)
    if a.cmd is None:
        parser.print_help(); return 0
    if a.cmd == "bug" and a.bug_cmd is None:
        parser.bug_parser.print_help(sys.stderr); return 2
    if a.cmd == "pr" and a.pr_cmd is None:
        parser.pr_parser.print_help(sys.stderr); return 2
    try:
        if a.cmd == "init":
            from .init_cmd import run as init_run, InitOptions
            return init_run(InitOptions(**{k: v for k, v in vars(a).items() if k not in ("cmd", "delivery")}))
        if a.cmd == "attach":
            from .attach_cmd import run as attach_run, AttachOptions
            return attach_run(AttachOptions(**{k: v for k, v in vars(a).items() if k not in ("cmd", "delivery")}))
        if a.cmd == "config":
            from . import config_cmd
            try:
                delivery = paths.find_delivery(pathlib.Path.cwd(), a.delivery)
            except TurnstileError:
                if a.delivery or getattr(a, "epic", False) or a.config_cmd == "apply":
                    raise
                delivery = None
            if a.config_cmd == "set":
                return config_cmd.set_(delivery, a.assignment, epic=a.epic, no_commit=a.no_commit, no_push=a.no_push)
            if a.config_cmd == "unset":
                return config_cmd.unset(delivery, a.key, epic=a.epic, no_commit=a.no_commit, no_push=a.no_push)
            if a.config_cmd == "apply":
                return config_cmd.apply(delivery, a.ah_id, no_commit=a.no_commit, no_push=a.no_push)
            return config_cmd.list_(delivery)
        delivery = paths.find_delivery(pathlib.Path.cwd(), a.delivery)
        if a.cmd == "sync":
            from .sync import run as sync_run
            return sync_run(delivery)
        if a.cmd == "board-url":
            from . import members
            return members.board_url(delivery, a.url, no_push=a.no_push)
        if a.cmd == "pass":
            from .pass_cmd import run, Options
            o = Options(**{k.replace("-", "_"): v for k, v in vars(a).items()
                           if k not in ("cmd", "delivery", "kind", "ident", "target")})
            return run(delivery, a.kind, a.ident, a.target, o)
        if a.cmd == "brief":
            from .brief_cmd import run as brief_run
            return brief_run(delivery, a.agent, a.name, a.vars, force=a.force, no_commit=a.no_commit, no_push=a.no_push)
        if a.cmd == "bug":
            from . import bug_cmd
            if a.bug_cmd == "add":
                return bug_cmd.add(delivery, a.story, a.title, a.source, pr=a.pr, figma=a.figma, note=a.note, case=a.case, no_push=a.no_push, arm=a.arm)
            if a.bug_cmd == "set":
                return bug_cmd.set_(delivery, a.bug_id, state=a.state, pr=a.pr, note=a.note, no_push=a.no_push)
            return 2
        if a.cmd == "pr":
            from .pr_cmd import add as pr_add
            return pr_add(delivery, a.ident, a.story, a.ticket, no_commit=a.no_commit, no_push=a.no_push, stacked_on=a.stacked_on, owner=a.owner)
        if a.cmd == "threads":
            from .threads import run as threads_run
            return threads_run(delivery, a.pr, a.self_resolved, a.needs_lead, report=a.report, no_commit=a.no_commit, no_push=a.no_push)
        if a.cmd == "plan-submitted":
            from .plan_cmd import run as plan_run
            return plan_run(delivery, no_commit=a.no_commit, no_push=a.no_push)
        if a.cmd == "jira-synced":
            from .pass_cmd import jira_synced
            return jira_synced(delivery, a.ident, a.status, no_push=a.no_push, assignee=a.assignee, assignee_name=a.assignee_name)
        if a.cmd == "approve":
            from .pass_cmd import approve
            return approve(delivery, a.ah_id)
        if a.cmd == "render-board":
            from . import board, state
            files = board.render_files(state.load(delivery / "state.json").data)
            board.write_files(delivery, files)
            print("OK rendered %s" % ", ".join(str(delivery / rel) for rel in files)); return 0
        if a.cmd in ("reconcile", "status"):
            from .reconcile import cli
            return cli(delivery, as_json=getattr(a, "json", False), status=(a.cmd == "status"), brief=getattr(a, "brief", False))
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
