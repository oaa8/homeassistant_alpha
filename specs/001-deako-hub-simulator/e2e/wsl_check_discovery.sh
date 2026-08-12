#!/bin/bash
# Check HA state and whether the simulator was auto-discovered via mDNS.
HA_DIR="$HOME/ha-test-latest"
BASE="http://127.0.0.1:8123"

code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/" 2>/dev/null || echo "000")
echo "HA http: $code"
pgrep -af "ha-venv-latest/bin/hass" | head -2 || echo "  hass NOT RUNNING"

echo ""
echo "== deako log lines =="
grep -iE "deako" "$HA_DIR/ha.log" | grep -viE "not been tested" | tail -15 || echo "  (none)"

echo ""
echo "== zeroconf discovery of _deako._tcp =="
grep -iE "zeroconf|discover" "$HA_DIR/ha.log" | grep -iE "deako" | tail -10 || echo "  (no deako zeroconf lines)"

echo ""
echo "== any import errors at all =="
grep -cE "Exception importing custom_components.deako" "$HA_DIR/ha.log" || true

echo ""
echo "== onboarding status =="
curl -s "$BASE/api/onboarding" | head -c 300
echo ""
