#!/bin/bash
# Dig into the two anomalies seen on HA 2026.8.1:
#   - only 2 of 3 lights registered
#   - HA entity state not tracking the simulator after a successful command
BASE="http://127.0.0.1:8123"
SIM="http://192.168.86.65:8080"
HA_DIR="$HOME/ha-test-latest"
TOKEN=$(cat "$HA_DIR/token.txt")
AUTH="Authorization: Bearer $TOKEN"
UUID_DIMMER="550e8400-e29b-41d4-a716-446655440002"

echo "== simulator's own device list =="
curl -s "$SIM/api/devices" | python3 -c "
import sys, json
d = json.load(sys.stdin)
devs = d['devices'] if isinstance(d, dict) else d
for x in devs: print(f\"  {x['uuid'][-4:]}  {x['name']:<20} {x['state']}\")
print('SIM_TOTAL=', len(devs))
"

echo ""
echo "== all HA light entities =="
curl -s "$BASE/api/states" -H "$AUTH" | python3 -c "
import sys, json
s=[x for x in json.load(sys.stdin) if x['entity_id'].startswith('light.')]
for x in s: print(f\"  {x['entity_id']:<34} state={x['state']:<6} bri={x['attributes'].get('brightness')}\")
print('HA_TOTAL=', len(s))
"

echo ""
echo "== turn_on then poll HA state repeatedly =="
curl -s -X POST "$BASE/api/services/light/turn_on" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"entity_id":"light.bedroom_dimmer","brightness":200}' >/dev/null
for t in 2 5 10 20 30; do
  sleep $((t == 2 ? 2 : 3))
  ha=$(curl -s "$BASE/api/states/light.bedroom_dimmer" -H "$AUTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['state'], d['attributes'].get('brightness'))")
  sim=$(curl -s "$SIM/api/devices/$UUID_DIMMER" | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")
  echo "  t~${t}s  HA=[$ha]  SIM=$sim"
done

echo ""
echo "== deako / light errors in log =="
grep -iE "deako|light" "$HA_DIR/ha.log" | grep -iE "error|warn|traceback|exception" | grep -viE "not been tested" | tail -15 || echo "  (none)"

echo ""
echo "== last deako debug lines =="
grep -iE "custom_components.deako|pydeako" "$HA_DIR/ha.log" | tail -15 || echo "  (none)"
