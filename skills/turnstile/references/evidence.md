# Evidence layout (tester)

```
delivery/evidence/<story>/<case>/
  env.png        # environment screenshot, viewport per the Figma frame, full state reached by the case
  figma.png      # the Figma get_screenshot result of the frame/node named in plan.md, saved with the Write tool
  dom.json       # measured values: {selector: {x, y, w, h, font, size, lineHeight, color, bg, gap, padding}} + Figma expected
  diff.md        # deviations beyond tolerance (element · property · expected · observed · delta) and copy mismatches
```

One folder per case; a case with several states uses `<case>/<state>/`. Keep images under 1 MB. Paths in `ENV-<S>.md`
are relative to `delivery/`. Evidence is committed by the next `turnstile pass` of the story.

How the files get there: the Bash guard lets any command write **strictly inside** `delivery/evidence/`, `delivery/reports/`
and `delivery/briefs/` (`mkdir -p`, `cp`, `node shot.mjs --out …`, `npx playwright screenshot … <path>`, redirects), and the
Write tool writes the same three folders (that is how `figma.png` is saved from the Figma MCP result). Both refuse
`state.json`, `ledger.md`, `plan.md`, `decisions.md`, `board.html`, `.state.lock` and the delivery root. Rules that keep a
command on the allowed side: literal absolute paths (no `$VAR`, globs or backticks in the path), no `..`, no symlinks, no
`cd` into the delivery dir, no `git` on it.
