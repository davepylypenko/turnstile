# PR body template

Title: `<type>(<scope>): [<KEY>] <summary>` (conventional type, Jira key). Draft, base = the story branch or the PR below.

```
<one-line intro: what the PR adds and for whom>

Scope:
- `<identifier>` — <what changed>

Tech requirements:
- <tests added / commands green>

Related: <Jira url>
```

Rules: no generated-with footer (the pass reads the body on GitHub and refuses it); no checklist boilerplate; the body
ends with the `Related:` line. Update `Scope:` when a later fix changes behaviour. Never comment on the PR.
