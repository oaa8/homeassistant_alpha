#!/bin/bash
# Deploy the Deako custom integration into the throwaway HA instance and start it.
#
# REPO is derived from this script's own location, never hardcoded: this file
# used to name a specific worktree, so running it from any other worktree
# deployed a DIFFERENT session's integration and validated that instead, while
# reporting success. Sibling worktrees are live, so the path resolved and
# nothing looked wrong.
#
# The config is minimal rather than default_config, which pulls in broad LAN
# discovery; WSL mirrored networking puts the real house on the other end of it.
set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HA_DIR="$HOME/ha-test"
VENV="$HOME/ha-venv"

mkdir -p "$HA_DIR/custom_components"
rm -rf "$HA_DIR/custom_components/deako"
cp -r "$REPO/custom_components/deako" "$HA_DIR/custom_components/deako"
# Strip CRLF that the Windows checkout introduces; Python tolerates it but
# manifest parsing and logging are cleaner without.
find "$HA_DIR/custom_components/deako" -name '*.py' -exec sed -i 's/\r$//' {} \;
echo "== integration deployed from $REPO =="
ls "$HA_DIR/custom_components/deako"

cat > "$HA_DIR/configuration.yaml" <<'YAML'
http:
config:

logger:
  default: warning
  logs:
    custom_components.deako: debug
    pydeako: debug
YAML

echo "== starting home assistant =="
nohup "$VENV/bin/hass" -c "$HA_DIR" > "$HA_DIR/ha.log" 2>&1 &
echo "HA_PID=$!"
sleep 5
echo "started; log tail:"
tail -5 "$HA_DIR/ha.log" || true
