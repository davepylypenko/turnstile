# {{epic_key}} — delivery plan

Status: DRAFT — not approved. Approval: `turnstile plan-submitted` prints the `ah-id`; the lead types
`! TURNSTILE_LEAD=1 turnstile approve <ah-id>`.

## 1. Inputs read

| Document | Path / link | Notes |
|---|---|---|
| Decomposition | | |
| PRD | | |
| Design | Figma file:node | |
| Test plan | | case ids referenced below |
| Repo guides | `<repo>/CLAUDE.md` for every repo in `epic.repos` | |

## 2. Stories

One story = one business slice that is testable and releasable on its own. If the decomposition is not by story,
define the slices here and give the rationale. `human_review: per_pr` is lead-set and exempts a legacy story from the
story gates (README "The lead's word").

| Story | Title | Tickets | Repos | Story branch | After | Parallel with | Env slot |
|---|---|---|---|---|---|---|---|
| S1 | | | | | — | | variant / desk |

## 3. Merge order and stack

Per story: the ticket PRs in merge order, the story branch they stack into (`stories.<S>.branch`; a PR's base is that
branch or another PR of the same story), file overlaps with parallel stories and which merge order resolves them.

## 4. Human-review units (~400 lines of logic each, tests and markup excluded)

| Story | Unit | PRs | Logic lines (est.) |
|---|---|---|---|

## 5. Test-case map and Figma frames

| Story | Test cases | Figma frames (`file:node`) | Parity tolerance |
|---|---|---|---|
| S1 | TP-… | | 1 px, exact colour |

## 6. Inputs needed from humans

| Who | What | Needed by | Blocks |
|---|---|---|---|

## 7. Machine-readable stories (read by `turnstile plan-submitted`; keep in sync with §2–§5)

```json turnstile-stories
{
  "S1": {
    "title": "",
    "tickets": [],
    "repos": [],
    "branch": "",
    "after": [],
    "parallel_with": [],
    "test_cases": [],
    "figma": [],
    "env_slot": { "variant": null, "desk": null },
    "human_review_units": []
  }
}
```
