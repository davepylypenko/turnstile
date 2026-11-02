# Environment recipe — pdffiller dev (variants + editor desks)

Domain: `https://www.pdffillers.com`. All cookies are set on `.pdffillers.com`.

## Users
Pattern `<mailbox>+tester<N>@<company domain>` with the shared dev password (`## Credentials`; never in git). Parallel sessions on one user log each other out: register `+tester1`, `+tester2`, … for each parallel agent.
Login answers "we can't recognize you" → set the user agent to `pdffiller-autotests` for the login request only, then
restore the default.

## Credentials
The shared dev password is never in git, in a brief or in a prompt. The tester reads it at login from, in order:
1. `TURNSTILE_TEST_PASSWORD` — the lead exports it in the shell that starts Claude Code (`export TURNSTILE_TEST_PASSWORD=…; claude …`); subagents inherit the environment.
2. The macOS keychain: the lead stores it once with `security add-generic-password -s turnstile-test-password -a "<test user address>" -w` (prompts for the secret; `-U` updates), and the tester reads it with `security find-generic-password -s turnstile-test-password -a "<test user address>" -w`.
Neither present → the tester replies `BLOCKED` before the first login.

## Routing
- Editor build on a desk: cookie `jsfillerEnv=deskNN` (`path=/`). Desk builds reset every morning — redeliver first.
- Backend on a Prometey variant: cookies `Forward-Variant-pdffiller=<variant>` **and** `developer_access=md5(<UTC date
  'Y-m-d'>)` (expires daily; without it requests silently hit the default backend). Set both as cookies on
  `.pdffillers.com`; **never as a request header** from a browser (`Forward-Variant-pdffiller` as a header breaks CORS
  preflights).
- Proof before the first case: an XHR response carries `x-server-name: pdffiller-web-<variant>-…` and the app bundle
  is served from `static_<variant>.pdffillers.com`. A tab opened before the cookies existed keeps the default bundle;
  reload. Negative control when in doubt: a nonsense variant name must change the response.

## Browser
Use an isolated headless browser (Playwright) with its own profile / user-data dir under the scratchpad. Never the user's
visible Chrome, never a shared devtools MCP session. Viewport per the Figma frame; device scale factor 1 unless the
frame is retina.

## Feature flag

Trunk-mode epics ship behind one experiment flag (`epic.flag`). The lead records here how to toggle it on this environment (e.g. the AB
Tower / feature-flag admin URL, a cookie or query parameter, or an account allowlist) and how to prove the state (an XHR field, a DOM
marker). The tester toggles it only that way: `treatment` = flag on, `control` = flag off. No method recorded here → the tester
replies `BLOCKED: no flag toggle for <flag> on <environment>` before the first case; it never guesses.

## Builds
Front: `static.version` of each app on the variant (deployer records it). Monolith: variant image tag (`DEV_ECR_TAG`).
Record both in the `ENV-<S>.md` header.
