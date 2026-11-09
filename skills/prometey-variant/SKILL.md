---
name: prometey-variant
description: Use when asked to create/ensure a Prometey variant, or to deploy branch or PR builds onto one — frontend repos AND the pdffiller/pdffiller backend monolith (e.g. "збери ПР-и на варіант X", "задеплой на варіант", "залий це на дев", "створи варіант"). Also use when a change is deployed to a variant but does not show up, since the routing and static-cache traps that cause that are documented here.
---

# Prometey variants: create one and deploy branch builds to it

A Prometey variant is a personal/per-task instance of the pdffiller k8s dev stack with its own frontend builds server.

Since June 2026 frontend builds may not be deployed to the default variant — dev is kept prod-equivalent for QA — so branch testing always goes through a variant of your own. Full reference: `pdffiller-knowledge/context/resources/prometey-variants.md` (repo `pdffiller/pdffiller-knowledge`; the epic's knowledge worktree or your own checkout of it).

## Step 1 — Ensure the variant exists

Do NOT call the Prometey API directly (it is firewalled; the local machine usually has no `PROMETEY_KEY`). Use the manual workflow in `pdffiller/frontend-actions` — it authenticates via GitHub OIDC on a self-hosted runner and is **idempotent** (`action: ensure`: picks up an existing variant or creates it):

```bash
gh workflow run front-variant.yml --repo pdffiller/frontend-actions \
  -f variant_title=<variant-name> -f wait_for_ready=true
```

- `wait_for_ready=true` makes the run succeed only when the pod reaches `status=ready`.
- It creates a single `pdffiller/dev` service (current default image tag) with env vars `FRONTEND_BUILDS_SERVER=<variant-name>` and `FRONTEND_BUILDS_SERVER_URL=https://static_<variant-name>.pdffillers.com` — this is what makes the variant serve the frontend builds deployed in step 2.
- The variant is created under the CI identity (`github_oidc`), so it may NOT appear under "my variants" in the UI — search by name at https://variants.pdffillers.com/.
- The workflow never deletes variants; delete manually from the UI when done.
- **Trap (2026-09-24):** on an *existing* variant, `ensure` with an empty `service_github_tag` re-resolves the tag to the registry default and silently replaces the backend image (e.g. an epic-branch monolith build → stale `master`), even when you only meant to touch the frontend static config. Always pass the monolith tag explicitly (`-f service_github_tag=<tag the variant must keep>`), and after every run confirm an XHR still shows `x-server-name: pdffiller-web-<variant>-…` and a backend-specific endpoint answers as expected.

## Step 2 — Deploy each repo's branch to the variant

Modern devkit repos (workflow file `.github/workflows/deploy.yml`, header "managed by @pdffiller/devkit-deploy") — this is the right path for almost every frontend repo:

```bash
gh workflow run deploy.yml --repo pdffiller/<repo> --ref <branch> \
  -f environment=dev -f variant=<variant-name> -f app=all -f is-active=true \
  -f build-info="<short reason / ticket>"
```

- `environment=dev` + `variant=<name>` deploys to the DEV builds server of that variant and (with `is-active=true`) activates the version for it. This never touches RC/prod.
- `app=all` builds every app discovered in a monorepo; a single app key can be passed instead.
- The workflow definition must exist on `<branch>` (true for any branch cut from main).
- Multiple repos can be triggered in parallel; watch with `gh run view <id> --repo pdffiller/<repo>`.

Legacy repos with an old `deploy-to-dev.yml`/`.yaml` (input `target-dev`): prefer the devkit `deploy.yml` if the repo has both. Known traps in the old one:
- it sets `NODE_ENV` to `webpack-build-mode`, so `production` skips devDependencies during `npm i` and breaks `prepare: husky` — use `development` if you must run it;
- some copies predate the monorepo layout and fail on `./public/static.version` — that workflow is simply dead; use `deploy.yml`.

Skip repos that are not deployed apps (e.g. `front-project-template` — a repo template).

## Step 3 — Deploy a backend branch to the variant

Frontend builds and the monolith are separate layers. Step 2 only replaces static; the variant still runs the default `pdffiller/dev` image. When the change is in `pdffiller/pdffiller`, build an image from the branch and point the variant at it — otherwise the frontend calls an API that has none of your changes.

Build the image (this is the slow part, budget ~20 min):

```bash
gh workflow run ".1 Create build from branch" --repo pdffiller/pdffiller \
  --ref <branch> -f env=dev
```

Take the resulting ECR tag from the run log — it is `DEV_ECR_TAG`, shaped `<branch-with-underscores-truncated>-<full-sha>`:

```bash
gh run view <run-id> --repo pdffiller/pdffiller --log \
  | grep -oE "DEV_ECR_TAG = .*" | head -1
```

Then re-run the variant workflow with that tag. `ensure` updates the service on an existing variant, so this is the same command as step 1 plus one input:

```bash
gh workflow run front-variant.yml --repo pdffiller/frontend-actions \
  -f variant_title=<variant-name> -f service_github_tag=<DEV_ECR_TAG> -f wait_for_ready=true
```

Order does not matter — static lands in `static/<variant>/` whether or not the variant exists yet.

## Step 4 — Use the variant, and verify you are actually on it

Route traffic with cookie or header `Forward-Variant-pdffiller: <variant-name>`. Verified working against `www.pdffillers.com`; `www.pdffiller-rc.xyz` answered `fault filter abort`, so prefer the former unless you know otherwise.

**From a terminal you also need the `developer_access` cookie.** Without it the request is silently served by the default backend — same 200, same JSON shape, no error, no hint. Grab it from a browser request in DevTools (copy as cURL).

Two checks worth making before believing any result, because each failure mode looks exactly like "the fix does not work":

- **Right backend?** The response header `x-server-name` should read `pdffiller-web-<variant>-…`. A quick negative control also works: send a nonsense variant name — if the response is identical, routing is not happening at all and you are testing the default stack.
- **Right static?** In DevTools the app bundle must come from `static_<variant>.pdffillers.com`, not `static.pdffiller.com`. A tab opened before the variant cookie existed keeps serving the default prod bundle; only a reload switches it.

Variant state / audit: https://variants.pdffillers.com/ (Google login) or ArgoCD `applications/argocd/variants`.
