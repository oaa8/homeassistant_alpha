#!/bin/bash
# Deploy the Deako custom integration into the throwaway HA instance and start it.
set -e

REPO="/mnt/c/Users/tolaa/Source/Repos/copilot-worktrees/homeassistant_alpha/oaa8-improved-enigma"
HA_DIR="$HOME/ha-test"
VENV="$HOME/ha-venv"

mkdir -p "$HA_DIR/custom_components"
rm -rf "$HA_DIR/custom_components/deako"
cp -r "$REPO/custom_components/deako" "$HA_DIR/custom_components/deako"
# Strip CRLF that the Windows checkout introduces; Python tolerates it but
# manifest parsing and logging are cleaner without.
find "$HA_DIR/custom_components/deako" -name '*.py' -exec sed -i 's/\r$//' {} \;
echo "== integration deployed =="
ls "$HA_DIR/custom_components/deako"

cat > "$HA_DIR/configuration.yaml" <<'YAML'
default_config:

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
