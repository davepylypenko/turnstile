# Figma MCP tools — resolved per environment

Turnstile never hard-codes a connector prefix: the same team member may have the claude.ai Figma connector
(`mcp__claude_ai_Figma__…`), the Figma plugin MCP (`mcp__plugin_figma_figma__…`) or a local server (`mcp__figma__…`), and the
tester must work with whichever is registered. Agents use the logical names; the suffix is what a tool name ends with.

| Logical name | Tool-name suffix | Used for |
|---|---|---|
| `figma.screenshot` | `__get_screenshot` | the reference frame image → `evidence/<S>/<case>/figma.png` (saved with the Write tool) |
| `figma.design_context` | `__get_design_context` | layout, sizes, fonts, colours, copy of the node |
| `figma.variables` | `__get_variable_defs` | design tokens the DOM check compares against |
| `figma.metadata` | `__get_metadata` | node tree and ids under a frame |

## Resolution (tester, step 0 of every run)

1. List the tools available to you: the MCP tool names in your context, plus `ToolSearch` with the query `figma get_screenshot`
   when tools are deferred.
2. For each logical name pick the tool whose name ends with the suffix and whose prefix contains `figma` (case-insensitive).
   Several candidates: the `claude_ai` connector wins over a plugin, a plugin over a local server.
3. Write the four resolved names into the report header (`Figma tools:`), so the evidence says which connector produced the
   reference.
4. None resolved for `__get_screenshot`, `__get_design_context` or `__get_variable_defs` → stop before the first case and
   reply `BLOCKED: no Figma MCP tools in this environment (need *__get_screenshot, *__get_design_context,
   *__get_variable_defs); connect the Figma MCP for this user and relaunch` — never fall back to a parity check without
   the reference, and never mark parity `pass` without `figma.png`.
