# Evidence layout (tester)

```
delivery/evidence/<story>/<case>/
  env.png        # environment screenshot, viewport per the Figma frame, full state reached by the case
  figma.png      # the Figma reference of the frame/node named in plan.md, fetched from a URL with `curl -o` (see below)
  dom.json       # measured values: {selector: {x, y, w, h, font, size, lineHeight, color, bg, gap, padding}} + Figma expected
  diff.md        # deviations beyond tolerance (element · property · expected · observed · delta) and copy mismatches
```

One folder per case; a case with several states uses `<case>/<state>/`. Keep images under 1 MB. Paths in `ENV-<S>.md`
are relative to `delivery/`. Evidence is committed by the next `turnstile pass` of the story.

How the files get there: the Bash guard lets any command write **strictly inside** `delivery/evidence/`, `delivery/reports/`
and `delivery/briefs/` (`mkdir -p`, `cp`, `curl -o`, `node shot.mjs --out …`, `npx playwright screenshot … <path>`, redirects),
and the Write tool writes text files into the same three folders (`dom.json`, `diff.md`, the report). Both refuse
`state.json`, `ledger.md`, `plan.md`, `decisions.md`, `board.html`, `.state.lock` and the delivery root. Rules that keep a
command on the allowed side: literal absolute paths (no `$VAR`, globs or backticks in the path), no `..`, no symlinks, no
`cd` into the delivery dir, no `git` on it.

`figma.png` is binary, so it never goes through the Write tool: `references/tools/figma.md` § "The reference image" gives the
order — the `__download_assets` export URL, else the `__get_screenshot` URL, else the Figma REST export with `FIGMA_TOKEN`
from the tester's environment — each fetched with `curl -sSf -o /abs/delivery/evidence/<S>/<case>/figma.png "<url>"`. When
none works the affected rows are `not_testable_here: no figma reference` and parity is recorded as `not_testable_here`,
never `pass`.
