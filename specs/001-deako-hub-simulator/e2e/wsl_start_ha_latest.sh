#!/bin/bash
# Deploy the Deako integration into the LATEST Home Assistant and start it.
# Auto-discovery is left to run: mirrored WSL networking means mDNS from the
# simulator should reach HA, so the integration may be discovered rather than
# configured by hand.
set -e

REPO="/mnt/c/Users/tolaa/Source/Repos/copilot-worktrees/homeassistant_alpha/oaa8-improved-enigma"
HA_DIR="$HOME/ha-test-latest"
VENV="$HOME/ha-venv-latest"

rm -rf "$HA_DIR"
mkdir -p "$HA_DIR/custom_components"
cp -r "$REPO/custom_components/deako" "$HA_DIR/custom_components/deako"
rm -rf "$HA_DIR/custom_components/deako/__pycache__"
find "$HA_DIR/custom_components/deako" -name '*.py' -exec sed -i 's/\r$//' {} \;

cat > "$HA_DIR/configuration.yaml" <<'YAML'
default_config:

logger:
  default: warning
  logs:
    custom_components.deako: debug
    pydeako: debug
YAML

echo "== starting home assistant 2026.8.1 =="
nohup "$VENV/bin/hass" -c "$HA_DIR" > "$HA_DIR/ha.log" 2>&1 &
echo "HA_PID=$!"

for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8123/ 2>/dev/null)
  if [ "$code" = "200" ]; then
    echo "HA UP after $((i*5))s"
    break
  fi
  sleep 5
done

echo ""
echo "== did the integration load cleanly? =="
grep -iE "deako" "$HA_DIR/ha.log" | grep -iE "error|exception|traceback|failed|warning" | head -20 || echo "  (no deako errors/warnings)"

echo ""
echo "== any setup failure? =="
grep -iE "Error during setup|Setup failed|Unable to prepare setup" "$HA_DIR/ha.log" | head -10 || echo "  (none)"
