#!/bin/bash
# Drive lights from Home Assistant and confirm the simulator's own state agrees.
# This proves the full round trip: HA service call -> integration -> pydeako ->
# telnet -> simulator state -> back out through the HTTP control API.
BASE="http://127.0.0.1:8123"
SIM="http://192.168.86.65:8080"
TOKEN=$(cat "$HOME/ha-test/token.txt")
AUTH="Authorization: Bearer $TOKEN"
UUID_DIMMER="550e8400-e29b-41d4-a716-446655440002"

sim_state () {
  curl -s "$SIM/api/devices/$UUID_DIMMER" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['state'])"
}
ha_state () {
  curl -s "$BASE/api/states/light.bedroom_dimmer" -H "$AUTH" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"state={d['state']} brightness={d['attributes'].get('brightness')}\")"
}

echo "== initial =="
echo "  HA : $(ha_state)"
echo "  SIM: $(sim_state)"

echo ""
echo "== HA service call: light.turn_on (brightness 128) =="
curl -s -X POST "$BASE/api/services/light/turn_on" -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"entity_id":"light.bedroom_dimmer","brightness":128}' >/dev/null
sleep 6
echo "  HA : $(ha_state)"
echo "  SIM: $(sim_state)"
SIM_ON=$(sim_state)

echo ""
echo "== HA service call: light.turn_off =="
curl -s -X POST "$BASE/api/services/light/turn_off" -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"entity_id":"light.bedroom_dimmer"}' >/dev/null
sleep 6
echo "  HA : $(ha_state)"
echo "  SIM: $(sim_state)"
SIM_OFF=$(sim_state)

echo ""
echo "== external change: simulator physical button press =="
curl -s -X POST "$SIM/api/devices/$UUID_DIMMER/button" >/dev/null
sleep 8
echo "  SIM: $(sim_state)"
echo "  HA : $(ha_state)"

echo ""
echo "=================== SUMMARY ==================="
echo "$SIM_ON"  | grep -q "'power': True"  && echo "PASS  HA turn_on reached simulator"  || echo "FAIL  HA turn_on did not reach simulator"
echo "$SIM_OFF" | grep -q "'power': False" && echo "PASS  HA turn_off reached simulator" || echo "FAIL  HA turn_off did not reach simulator"
echo "==============================================="
