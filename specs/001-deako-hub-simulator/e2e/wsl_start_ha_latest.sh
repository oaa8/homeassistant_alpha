#!/bin/bash
# Deploy the Deako integration into the LATEST Home Assistant and start it.
#
# The config is deliberately MINIMAL, not default_config. default_config pulls in
# broad LAN discovery (Sonos, cast, DLNA...) and WSL mirrored networking puts the
# real house on the other end of it: an earlier run of this script sat probing
# house devices and never finished starting. Wayfinder #15 recorded that trap and
# it was still live here. Only what the Deako test needs is enabled.
#
# Auto-discovery of the hub is NOT exercised: after this upgrade nothing calls the
# discovery module and the configured address is the only source of an address, so
# the config flow is driven by hand against the simulator's loopback address.
set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HA_DIR="$HOME/ha-test-latest"
VENV="$HOME/ha-venv-latest"

rm -rf "$HA_DIR"
mkdir -p "$HA_DIR/custom_components"
cp -r "$REPO/custom_components/deako" "$HA_DIR/custom_components/deako"
rm -rf "$HA_DIR/custom_components/deako/__pycache__"
find "$HA_DIR/custom_components/deako" -name '*.py' -exec sed -i 's/\r$//' {} \;

cat > "$HA_DIR/configuration.yaml" <<'YAML'
http:
config:

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
