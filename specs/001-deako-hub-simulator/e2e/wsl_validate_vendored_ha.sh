#!/usr/bin/env bash
# End-to-end validation of the integration running on the vendored pydeako,
# inside a real Home Assistant, against the simulator.
#
# Loopback only, and no mDNS. The real house is on this LAN with a live Home
# Assistant on it, so the simulator must not advertise itself and must not be
# reachable from the LAN. zero_dim_sim_runner.py already binds 127.0.0.1 and
# suppresses the advertisement, so it is reused here as the safe runner -- its
# name records where it came from, not what it is limited to.
#
# Auto-discovery is deliberately NOT exercised: after this upgrade nothing
# calls the discovery module, the configured address is the only source of an
# address, and proving that requires a manual setup, not a discovered one.
#
# Prerequisites: bash specs/001-deako-hub-simulator/e2e/wsl_setup_ha_latest.sh
#
# Usage (inside WSL):
#   bash specs/001-deako-hub-simulator/e2e/wsl_validate_vendored_ha.sh

set -uo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/../../.." && pwd)"
HA_DIR="$HOME/ha-test-latest"
WORK_DIR="${VENDORED_HA_WORK_DIR:-$HOME/vendored-ha}"
BASE="http://127.0.0.1:8123"
SIM_HTTP="http://127.0.0.1:8080"
SIM_IP="127.0.0.1"
SIM_PORT="8023"
DIMMER_UUID="11111111-1111-4111-8111-111111111111"
DIMMER_ENTITY="light.zero_dim_test_dimmer"

PASSED=0
FAILED=0
report() { # report <ok:0|1> <name> [detail]
    if [ "$1" -eq 0 ]; then PASSED=$((PASSED + 1)); echo "PASS  $2"; else FAILED=$((FAILED + 1)); echo "FAIL  $2"; fi
    [ -n "${3:-}" ] && echo "        $3"
    return 0
}

mkdir -p "$WORK_DIR"

if [ ! -x "$HOME/ha-venv-latest/bin/hass" ]; then
    echo "Home Assistant is not provisioned. Run wsl_setup_ha_latest.sh first."
    exit 1
fi

if [ ! -x "$WORK_DIR/venvsim/bin/python" ]; then
    python3 -m venv "$WORK_DIR/venvsim"
fi
"$WORK_DIR/venvsim/bin/pip" -q install aiohttp zeroconf jsonschema

cleanup() {
    [ -n "${SIM_PID:-}" ] && kill "$SIM_PID" 2>/dev/null
    pkill -f "hass -c $HA_DIR" 2>/dev/null
    return 0
}
trap cleanup EXIT

echo "== starting the simulator on loopback, no mDNS =="
cd "$REPO_ROOT"
"$WORK_DIR/venvsim/bin/python" "$E2E_DIR/zero_dim_sim_runner.py" \
    --port "$SIM_PORT" --http-port 8080 > "$WORK_DIR/sim.log" 2>&1 &
SIM_PID=$!
for _ in $(seq 1 30); do
    grep -q "^READY" "$WORK_DIR/sim.log" 2>/dev/null && break
    sleep 1
done
grep -q "^READY" "$WORK_DIR/sim.log" || { echo "simulator failed to start"; tail -20 "$WORK_DIR/sim.log"; exit 1; }

echo ""
echo "== deploying this worktree's integration and starting Home Assistant =="
bash "$E2E_DIR/wsl_start_ha_latest.sh"

echo ""
echo "== onboarding =="
HA_TEST_PASSWORD="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
CLIENT_ID="$BASE/"
AUTH_CODE=$(curl -s -X POST "$BASE/api/onboarding/users" -H "Content-Type: application/json" \
    -d "{\"client_id\":\"$CLIENT_ID\",\"name\":\"Sim Tester\",\"username\":\"simtester\",\"password\":\"$HA_TEST_PASSWORD\",\"language\":\"en\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('auth_code',''))")
if [ -z "$AUTH_CODE" ]; then
    TOKEN=$(cat "$HA_DIR/token.txt" 2>/dev/null)
else
    TOKEN=$(curl -s -X POST "$BASE/auth/token" -d "grant_type=authorization_code" \
        -d "code=$AUTH_CODE" -d "client_id=$CLIENT_ID" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
    echo "$TOKEN" > "$HA_DIR/token.txt"
fi
AUTH="Authorization: Bearer $TOKEN"
[ -n "$TOKEN" ] || { echo "could not obtain a token"; exit 1; }
curl -s -X POST "$BASE/api/onboarding/core_config" -H "$AUTH" >/dev/null 2>&1
curl -s -X POST "$BASE/api/onboarding/integration" -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"client_id\":\"$CLIENT_ID\",\"redirect_uri\":\"$CLIENT_ID\"}" >/dev/null 2>&1

echo ""
echo "== configuring deako by hand at $SIM_IP:$SIM_PORT =="
FLOW_ID=$(curl -s -X POST "$BASE/api/config/config_entries/flow" -H "$AUTH" \
    -H "Content-Type: application/json" -d '{"handler":"deako","show_advanced_options":true}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('flow_id',''))")
[ -n "$FLOW_ID" ] || { echo "could not start the config flow"; exit 1; }
curl -s -X POST "$BASE/api/config/config_entries/flow/$FLOW_ID" -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d "{\"ip_address\":\"$SIM_IP\",\"port\":$SIM_PORT}" > "$WORK_DIR/flow.json"
sleep 25

echo ""
echo "== results =="

STATE=$(curl -s "$BASE/api/config/config_entries/entry" -H "$AUTH" \
    | python3 -c "import sys,json; print(next((e.get('state') for e in json.load(sys.stdin) if e['domain']=='deako'), 'missing'))")
[ "$STATE" = "loaded" ]; report $? "config entry loaded on the vendored library" "state=$STATE"

LIGHTS=$(curl -s "$BASE/api/states" -H "$AUTH" \
    | python3 -c "import sys,json; print(len([x for x in json.load(sys.stdin) if x['entity_id'].startswith('light.')]))")
[ "$LIGHTS" -eq 2 ]; report $? "both simulator devices became light entities" "count=$LIGHTS"

ha_attr() { # ha_attr <entity> <state|attribute name>
    curl -s "$BASE/api/states/$1" -H "$AUTH" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print('unreadable'); raise SystemExit
if 'state' not in d:
    print('missing'); raise SystemExit
print(d['state'] if '$2' == 'state' else d.get('attributes', {}).get('$2'))
"
}

curl -s -X POST "$BASE/api/services/light/turn_on" -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"entity_id\":\"$DIMMER_ENTITY\",\"brightness\":200}" >/dev/null
sleep 8
HA_STATE=$(ha_attr "$DIMMER_ENTITY" state)
SIM_STATE=$(curl -s "$SIM_HTTP/api/devices/$DIMMER_UUID" | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")
[ "$HA_STATE" = "on" ]; report $? "turn_on reaches the hub and is reflected in Home Assistant" "HA=$HA_STATE SIM=$SIM_STATE"

# O9 through the whole stack: brightness 1 rounds to dim 0.0, which is the case
# 0.6.0 stock discards, leaving Home Assistant reporting 204.
curl -s -X POST "$BASE/api/services/light/turn_on" -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"entity_id\":\"$DIMMER_ENTITY\",\"brightness\":1}" >/dev/null
sleep 8
BRIGHTNESS=$(ha_attr "$DIMMER_ENTITY" brightness)
SIM_STATE=$(curl -s "$SIM_HTTP/api/devices/$DIMMER_UUID" | python3 -c "import sys,json; print(json.load(sys.stdin)['state'])")
[ "$BRIGHTNESS" = "0" ]; report $? "O9 zero brightness survives the whole stack" "HA brightness=$BRIGHTNESS SIM=$SIM_STATE (stock reports 204)"

# O6: an out-of-band change, the way a wall press arrives.
curl -s -X POST "$SIM_HTTP/api/devices/$DIMMER_UUID/state" -H "Content-Type: application/json" \
    -d '{"power": false}' >/dev/null
sleep 8
HA_STATE=$(ha_attr "$DIMMER_ENTITY" state)
[ "$HA_STATE" = "off" ]; report $? "O6 a hub-originated change is pushed to Home Assistant" "state=$HA_STATE, with nothing polling"

BAD=$(grep -iE "custom_components\.deako|pydeako" "$HA_DIR/ha.log" \
    | grep -iE "Traceback|ERROR|Exception" | grep -viE "No socket to send data to" | head -5)
[ -z "$BAD" ]; report $? "no errors or tracebacks from the integration" "${BAD:-clean}"

BLOCKING=$(grep -iE "Detected blocking call|blocks the event loop" "$HA_DIR/ha.log" \
    | grep -iE "deako" | head -3)
[ -z "$BLOCKING" ]; report $? "no blocking-call warnings from the integration" "${BLOCKING:-clean}"

echo ""
echo "===================================================================="
echo "$PASSED/$((PASSED + FAILED)) passed"
[ "$FAILED" -eq 0 ] || echo "see $HA_DIR/ha.log and $WORK_DIR/sim.log"
echo "===================================================================="
exit $([ "$FAILED" -eq 0 ] && echo 0 || echo 1)
