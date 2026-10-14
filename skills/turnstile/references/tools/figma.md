# Figma MCP tools — resolved per environment

Turnstile never hard-codes a connector prefix: the same team member may have the claude.ai Figma connector
(`mcp__claude_ai_Figma__…`), the Figma plugin MCP (`mcp__plugin_figma_figma__…`) or a local server (`mcp__figma__…`), and the
tester must work with whichever is registered. Agents use the logical names; the suffix is what a tool name ends with.

| Logical name | Tool-name suffix | Used for |
|---|---|---|
| `figma.download` | `__download_assets` | the reference frame image: returns an `export` URL of the node (pass `defaultFormat: png`, `defaultScale: 2`), fetched into `evidence/<S>/<case>/figma.png` with `curl -o` |
| `figma.screenshot` | `__get_screenshot` | the same reference when `__download_assets` is absent: returns a short-lived URL plus curl instructions, fetched the same way (never `enableBase64Response`: the image would go to the model, not to a file) |
| `figma.design_context` | `__get_design_context` | layout, sizes, fonts, colours, copy of the node |
| `figma.variables` | `__get_variable_defs` | design tokens the DOM check compares against |
| `figma.metadata` | `__get_metadata` | node tree and ids under a frame |

## Resolution (tester, step 0 of every run)

1. List the tools available to you: the MCP tool names in your context, plus `ToolSearch` with the query `figma get_screenshot`
   when tools are deferred.
2. For each logical name pick the tool whose name ends with the suffix and whose prefix contains `figma` (case-insensitive).
   Several candidates: the `claude_ai` connector wins over a plugin, a plugin over a local server.
3. Write the resolved names into the report header (`Figma tools:`), so the evidence says which connector produced the
   reference.
4. None resolved for `__get_design_context` or `__get_variable_defs` → stop before the first case and reply
   `BLOCKED: no Figma MCP tools in this environment (need *__get_design_context, *__get_variable_defs and one of
   *__download_assets / *__get_screenshot); connect the Figma MCP for this user and relaunch` — never fall back to a parity
   check without the design context.

## The reference image (`figma.png`), in this order

The Figma tools return the image to the model or as a URL; none of them writes a file, and the Write tool cannot write PNG
bytes. So the reference is always fetched from a URL with `curl -o` into the evidence folder (the Bash guard allows a
literal absolute path strictly inside `evidence/`):

1. `figma.download` (`__download_assets`, `fileKey` + `nodeId` from the brief's `file:node`, `defaultFormat: png`,
   `defaultScale: 2`) → take the `export` URL →
   `curl -sSf -o /abs/delivery/evidence/<S>/<case>/figma.png "<url>"`. A connector variant whose download tool takes an
   output path instead gets the same evidence path. URLs are temporary: download at once.
2. Else `figma.screenshot` (`__get_screenshot`, `maxDimension` ≥ the frame's longer edge ×2) → its URL → the same `curl -o`.
3. Else, when `FIGMA_TOKEN` is set in your environment (the lead exports it in the shell that launched the session; it is
   never in the brief, the report or any file), the REST export:
   `curl -s -H "X-Figma-Token: $FIGMA_TOKEN" "https://api.figma.com/v1/images/<fileKey>?ids=<node>&format=png&scale=2"`
   → JSON `images["<node>"]` → `curl -sSf -o …/figma.png "<url>"` (`<node>` with `:`; the id in `?ids=` may use `-`).
4. None of the three produced a non-empty `figma.png` (check `file` says PNG and the size is > 0) → every parity row of that
   screen/state and every case whose expected result is the design get the verdict `not_testable_here: no figma reference`
   (the reason verbatim, so the orchestrator counts them under `--cases-not-testable`), the run's parity is recorded as
   `--figma-parity not_testable_here`, and the report header names which of the three paths failed and why. Never mark
   parity `pass` without `figma.png`.
