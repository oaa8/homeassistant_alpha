#!/bin/bash
# Restart the latest-HA test instance with a minimal config.
#
# default_config pulls in broad LAN discovery (Sonos, cast, DLNA...). With WSL
# mirrored networking the instance can now see the real home network, so that is
# both slow and needlessly intrusive. Only what the Deako test requires is
# enabled: HTTP API, config entries, and zeroconf for mDNS discovery.
VENV="$HOME/ha-venv-latest"
HA_DIR="$HOME/ha-test-latest"

pkill -f "ha-venv-latest/bin/hass" 2>/dev/null
sleep 3

cat > "$HA_DIR/configuration.yaml" <<'YAML'
http:
config:
zeroconf:

logger:
  default: warning
  logs:
    custom_components.deako: debug
    pydeako: debug
    homeassistant.components.zeroconf: info
YAML

rm -f "$HA_DIR/ha.log"
nohup "$VENV/bin/hass" -c "$HA_DIR" --skip-pip > "$HA_DIR/ha.log" 2>&1 &
echo "HA_PID=$!"

for i in $(seq 1 72); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8123/ 2>/dev/null || echo "000")
  [ "$code" = "200" ] && { echo "HA UP after $((i*5))s"; break; }
  sleep 5
done
echo "final code: $code"

echo ""
echo "== deako import errors =="
grep -cE "Exception importing custom_components.deako" "$HA_DIR/ha.log"

echo ""
echo "== discovery flows offered =="
curl -s "http://127.0.0.1:8123/api/onboarding" | head -c 200
echo ""
tail -6 "$HA_DIR/ha.log"
