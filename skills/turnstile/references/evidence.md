# Evidence layout (tester)

```
delivery/evidence/<story>/<case>/
  env.png        # environment screenshot, viewport per the Figma frame, full state reached by the case
  figma.png      # Figma get_screenshot of the frame/node named in plan.md
  dom.json       # measured values: {selector: {x, y, w, h, font, size, lineHeight, color, bg, gap, padding}} + Figma expected
  diff.md        # deviations beyond tolerance (element · property · expected · observed · delta) and copy mismatches
```

One folder per case; a case with several states uses `<case>/<state>/`. Keep images under 1 MB. Paths in `ENV-<S>.md`
are relative to `delivery/`. Evidence is committed by the next `turnstile pass` of the story.
