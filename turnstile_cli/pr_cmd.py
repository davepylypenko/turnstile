import pathlib
from typing import Optional
from . import members, rules, state as st_mod
from .bug_cmd import PR_RX, _commit
from .errors import TurnstileError

def add(delivery, pr_id: str, story: str, ticket: str, io=None, no_commit: bool = False, no_push: bool = False, stacked_on: Optional[str] = None, owner: Optional[str] = None) -> int:
    from .pass_cmd import IO, _side_effects, _recompute_next_actions, jira_instruction, _now
    io = io or IO(); delivery = pathlib.Path(delivery)
    try:
        if not PR_RX.match(pr_id or ""):
            raise TurnstileError("pr must look like repo#123 (got %r)" % pr_id)
        with st_mod.locked(delivery):
            st = st_mod.load(delivery / "state.json"); data = st.data
            org = rules.require_org(data); st_mod.repo_cfg(st, pr_id)
            if pr_id in data.get("prs", {}):
                raise TurnstileError("%s is already recorded (state %s); use turnstile pass" % (pr_id, data["prs"][pr_id].get("state")))
            s = st_mod.story(st, story)
            if ticket not in (s.get("tickets") or []):
                raise TurnstileError("ticket %s is not in stories.%s.tickets (%s); fix plan.md and re-run plan-submitted" % (ticket, story, ", ".join(s.get("tickets") or []) or "none"))
            plan = delivery / "plan.md"
            missing_plan = rules.plan_approval_missing(data, st_mod.digest(plan.read_text()) if plan.exists() else None)
            if missing_plan:
                raise TurnstileError(missing_plan[len("MISSING "):])
            if not (delivery / "briefs" / (ticket + ".md")).exists():
                raise TurnstileError("no brief briefs/%s.md (DEV DoR: turnstile brief implementer %s …)" % (ticket, ticket))
            pr_owner = members.resolve_owner(data, delivery, owner)
            f = io.github_facts(pr_id, org)
            if f.merged:
                raise TurnstileError("%s is already merged on GitHub" % pr_id)
            blocked_by = None
            if rules.is_trunk(s):
                base = st_mod.repo_cfg(st, pr_id).get("base")
                if stacked_on:
                    below = data["prs"].get(stacked_on)
                    if not below or below.get("story") != story or below.get("state") == "MERGED":
                        raise TurnstileError("--stacked-on %s must name an open PR of %s" % (stacked_on, story))
                    if f.base != below.get("branch"):
                        raise TurnstileError("%s is based on %s, not on the branch of %s (%s)" % (pr_id, f.base, stacked_on, below.get("branch")))
                    blocked_by = stacked_on
                elif f.base != base:
                    raise TurnstileError("%s is based on %s, not on the repo base %s (trunk mode: every PR merges into the base behind the epic flag; "
                                         "a deliberate stack needs --stacked-on <pr>)" % (pr_id, f.base, base))
            elif stacked_on:
                raise TurnstileError("--stacked-on is a trunk-mode flag (story %s is in stack mode: the base rule is the story branch or another PR)" % story)
            else:
                bases = {s.get("branch")} | {p.get("branch") for p in data["prs"].values() if p.get("story") == story and p.get("state") != "MERGED"}
                if f.base not in bases:
                    raise TurnstileError("%s is based on %s, not on the story branch %s or another open PR of %s" % (pr_id, f.base, s.get("branch"), story))
            data["prs"][pr_id] = {"ticket": ticket, "story": story, "state": "DEV", "state_since": _now(), "branch": f.branch, "base": f.base, "head": f.head,
                                  "blocked_by": blocked_by, "owner": pr_owner, "evidence": {}, "jira": {"status": rules.JIRA_FOR_PR_STATE["DEV"], "synced": False}, "next_action": ""}
            _recompute_next_actions(data)
            summary = "pr %s added (%s, %s) DEV head %s" % (pr_id, story, ticket, (f.head or "")[:8])
            _side_effects(delivery, st, [summary], io, no_commit, no_push)
            print(jira_instruction(data["prs"][pr_id], data["prs"])); print("OK " + summary); return 0
    except TurnstileError as e:
        print("MISSING %s" % e); return 2
