#!/bin/bash
# Final validation on the LATEST Home Assistant:
#   1. was the simulator auto-discovered over mDNS?
#   2. does manual setup still produce working, controllable entities?
BASE="http://127.0.0.1:8123"
SIM="http://192.168.86.65:8080"
HA_DIR="$HOME/ha-test-latest"
TOKEN=$(cat "$HA_DIR/token.txt")
AUTH="Authorization: Bearer $TOKEN"
SIM_IP="192.168.86.65"
SIM_PORT="8023"
UUID_DIMMER="550e8400-e29b-41d4-a716-446655440002"

echo "== 1. auto-discovery =="
echo "--- raw flows response ---"
curl -s "$BASE/api/config/config_entries/flow" -H "$AUTH" | head -c 300
echo ""
echo "--- deako mentions in log ---"
grep -iE "deako" "$HA_DIR/ha.log" | grep -viE "not been tested" | tail -8 || echo "  (none)"
echo "--- zeroconf step errors (missing async_step_zeroconf shows up here) ---"
grep -iE "async_step_zeroconf|UnknownStep|unknown step|discovery flow" "$HA_DIR/ha.log" | tail -8 || echo "  (none)"

echo ""
echo "== 2. manual setup =="
FLOW=$(curl -s -X POST "$BASE/api/config/config_entries/flow" -H "$AUTH" \
  -H "Content-Type: application/json" -d '{"handler":"deako","show_advanced_options":true}')
FLOW_ID=$(echo "$FLOW" | python3 -c "import sys,json; print(json.load(sys.stdin).get('flow_id',''))" 2>/dev/null)
if [ -z "$FLOW_ID" ]; then echo "FAILED to start flow: $(echo $FLOW | head -c 200)"; exit 1; fi

curl -s -X POST "$BASE/api/config/config_entries/flow/$FLOW_ID" -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "{\"ip_address\":\"$SIM_IP\",\"port\":$SIM_PORT}" | head -c 200
echo ""
sleep 20

echo ""
echo "== 3. config entry state =="
curl -s "$BASE/api/config/config_entries/entry" -H "$AUTH" \
  | python3 -c "import sys,json; [print(f\"  deako: state={e.get('state')}\") for e in json.load(sys.stdin) if e['domain']=='deako']"

echo ""
echo "== 4. entities =="
curl -s "$BASE/api/states" -H "$AUTH" | python3 -c "
import sys, json
s=[x for x in json.load(sys.stdin) if x['entity_id'].startswith('light.')]
for x in s: print(f\"  {x['entity_id']:<32} {x['state']}\")
print(f'TOTAL_LIGHTS={len(s)}')
"

echo ""
echo "== 5. control round trip =="
curl -s -X POST "$BASE/api/services/light/turn_on" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"entity_id":"light.bedroom_dimmer","brightness":200}' >/dev/null
sleep 6
echo "  after turn_on(200):"
echo "    HA : $(curl -s "$BASE/api/states/light.bedroom_dimmer" -H "$AUTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['state'], d['attributes'].get('brightness'))")"
echo "    SIM: $(curl -s "$SIM/api/devices/$UUID_DIMMER" | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")"

curl -s -X POST "$BASE/api/services/light/turn_off" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"entity_id":"light.bedroom_dimmer"}' >/dev/null
sleep 6
echo "  after turn_off:"
echo "    HA : $(curl -s "$BASE/api/states/light.bedroom_dimmer" -H "$AUTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['state'])")"
echo "    SIM: $(curl -s "$SIM/api/devices/$UUID_DIMMER" | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")"
