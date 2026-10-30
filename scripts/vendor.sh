#!/bin/sh
# Vendor a tagged turnstile release into another repository: scripts/vendor.sh <tag> <dest-dir>
# Copies the plugin files of <tag> from this repo's git history (never the working tree), replaces <dest-dir>, stamps VENDORED_FROM.
set -eu
TAG="${1:?usage: vendor.sh <tag> <dest-dir>}"; DEST="${2:?usage: vendor.sh <tag> <dest-dir>}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
REPO_URL="https://github.com/davepylypenko/turnstile"
PATHS=".claude-plugin agents hooks skills templates scripts turnstile_cli tests README.md LICENSE"
if ! COMMIT="$(git -C "$HERE" rev-list -n 1 "$TAG" 2>/dev/null)"; then
  echo "vendor.sh: unknown tag $TAG in $HERE" >&2; exit 2
fi
case "$DEST" in /*) ;; *) DEST="$(pwd)/$DEST" ;; esac
# A non-empty destination without a VENDORED_FROM stamp is only replaced inside a git work tree, where the loss is recoverable.
if [ -d "$DEST" ] && [ -n "$(ls -A "$DEST")" ] && [ ! -f "$DEST/VENDORED_FROM" ] \
   && ! git -C "$DEST" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "vendor.sh: $DEST is not empty, has no VENDORED_FROM and is outside a git repo; refusing to replace it" >&2; exit 3
fi
rm -rf "$DEST"; mkdir -p "$DEST"
# shellcheck disable=SC2086
git -C "$HERE" archive --format=tar "$TAG" -- $PATHS | tar -x -C "$DEST"
{
  echo "repo: $REPO_URL"; echo "tag: $TAG"; echo "commit: $COMMIT"
  echo "date: $(date -u +%Y-%m-%dT%H:%MZ)"; echo "command: scripts/vendor.sh $TAG <dest>"
  echo "note: do not edit here; change the canonical repo, tag, re-vendor"
} > "$DEST/VENDORED_FROM"
echo "vendored $TAG ($COMMIT) into $DEST"
