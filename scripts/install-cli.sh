#!/bin/sh
# Put a `turnstile` shim on PATH: scripts/install-cli.sh [bin-dir]   (default ~/.local/bin)
# The shim resolves the installed plugin at every run (installed_plugins.json, else the newest plugin cache entry,
# TURNSTILE_HOME overrides both), so a `claude plugin update` needs no reinstall.
set -eu
BIN="${1:-$HOME/.local/bin}"
mkdir -p "$BIN"
cat > "$BIN/turnstile" <<'SHIM'
#!/bin/sh
set -eu
CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
ROOT="${TURNSTILE_HOME:-}"
if [ -z "$ROOT" ] && [ -f "$CFG/plugins/installed_plugins.json" ]; then
  ROOT="$(python3 - "$CFG/plugins/installed_plugins.json" <<'PY'
import json, pathlib, sys
try:
    plugins = json.loads(pathlib.Path(sys.argv[1]).read_text()).get("plugins", {})
except Exception:
    plugins = {}
for key, entries in plugins.items():
    if key.split("@", 1)[0] != "turnstile":
        continue
    for e in entries:
        root = e.get("installPath") or ""
        if pathlib.Path(root, "scripts", "turnstile").is_file():
            print(root); sys.exit(0)
PY
)"
fi
if [ -z "$ROOT" ]; then
  ROOT="$(ls -td "$CFG"/plugins/cache/*/turnstile/*/ 2>/dev/null | head -n 1)"
fi
if [ -z "$ROOT" ] || [ ! -f "$ROOT/scripts/turnstile" ]; then
  echo "turnstile: no installed plugin under $CFG/plugins (run: claude plugin install turnstile@turnstile) and TURNSTILE_HOME is unset" >&2
  exit 127
fi
exec bash "$ROOT/scripts/turnstile" "$@"
SHIM
chmod +x "$BIN/turnstile"
echo "installed $BIN/turnstile"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "note: $BIN is not on PATH; add it to your shell profile, e.g. export PATH=\"$BIN:\$PATH\"" ;; esac
