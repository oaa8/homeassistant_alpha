#!/usr/bin/env bash
# End-to-end proof for wayfinder #16: the availability model and the converged
# light entity, in a real Home Assistant, against the simulator.
#
# What this is here to catch is the map's known trap: an integration that
# serves cached state and never marks anything unavailable, so a hub that has
# been gone for a day looks identical in history to a healthy one. That is not
# a hypothetical -- it is what the house did for nine days in August 2026.
#
# Five phases, in one Home Assistant, because most of these only mean something
# against an installation that already exists:
#
#   1. HEALTHY   -- the converged entity: color modes declared properly, state
#                   written (which is the exact thing the house cannot do
#                   today), and a physical wall press reflected with nothing
#                   polling.
#   2. DROPPED   -- the hub closes the socket. Every light must grey out in a
#                   bounded time rather than keep reporting what it last heard.
#   3. RESYNCED  -- state changes while the connection is down, and the
#                   reconnect has to correct it without anyone touching the
#                   light again (O7, the other half of O5's value).
#   4. REFUSED   -- the hub is gone entirely. Commands issued now must fail
#                   visibly instead of being swallowed.
#   5. WITHHELD  -- a device the hub promises in its count and never announces.
#                   Its entity must show unavailable rather than vanish, and a
#                   late DEVICE_FOUND must bring it back without a restart.
#
# Loopback only, and no mDNS: the real house is on this LAN with a live Home
# Assistant on it, so the simulator must not advertise itself, and nothing here
# can discover a Deako node -- every connection made below came from the
# configured address.
#
# Prerequisites: bash specs/001-deako-hub-simulator/e2e/wsl_setup_ha_latest.sh
#
# Usage (inside WSL):
#   bash specs/001-deako-hub-simulator/e2e/wsl_validate_availability_model.sh

set -uo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/../../.." && pwd)"
HA_DIR="$HOME/ha-test-latest"
VENV="$HOME/ha-venv-latest"
WORK_DIR="${AVAILABILITY_WORK_DIR:-$HOME/availability-ha}"
BASE="http://127.0.0.1:8123"
SIM_IP="127.0.0.1"
SIM_PORT="8023"
SIM_HTTP="http://127.0.0.1:8080"

DIMMER_UUID="11111111-1111-4111-8111-111111111111"
SWITCH_UUID="33333333-3333-4333-8333-333333333333"
DIMMER="light.zero_dim_test_dimmer"
SWITCH="light.zero_dim_test_switch"

# The socket dies the moment the hub sends FIN, so this is generous. The slow
# path -- a hub that goes quiet without closing -- is one ping window, measured
# at 19s against real hardware in wayfinder #19, and is not what phase 2 fires.
GREY_OUT_BUDGET_S=15
# Detection plus a fresh connection. #19 measured reconnect within ~30s of the
# fault on real firmware; a missed pong costs up to another ping window first.
RECONNECT_BUDGET_S=90
# Home Assistant's default poll interval for the light platform is 30s, so a
# quiet window has to outlast it for "nothing polled" to mean anything.
QUIET_WINDOW_S=45

PASSED=0
FAILED=0
report() { # report <ok:0|1> <name> [detail]
    if [ "$1" -eq 0 ]; then PASSED=$((PASSED + 1)); echo "PASS  $2"; else FAILED=$((FAILED + 1)); echo "FAIL  $2"; fi
    [ -n "${3:-}" ] && echo "        $3"
    return 0
}

mkdir -p "$WORK_DIR"

if [ ! -x "$VENV/bin/hass" ]; then
    echo "Home Assistant is not provisioned. Run wsl_setup_ha_latest.sh first."
    exit 1
fi

SIM_PID=""
cleanup() {
    [ -n "${SIM_PID:-}" ] && kill "$SIM_PID" 2>/dev/null
    pkill -f "hass -c $HA_DIR" 2>/dev/null
    return 0
}
trap cleanup EXIT

start_simulator() {
    if [ ! -x "$WORK_DIR/venvsim/bin/python" ]; then
        python3 -m venv "$WORK_DIR/venvsim"
    fi
    "$WORK_DIR/venvsim/bin/pip" -q install aiohttp zeroconf jsonschema
    cd "$REPO_ROOT"
    "$WORK_DIR/venvsim/bin/python" "$E2E_DIR/zero_dim_sim_runner.py" \
        --port "$SIM_PORT" --http-port 8080 > "$WORK_DIR/sim.log" 2>&1 &
    SIM_PID=$!
    for _ in $(seq 1 30); do
        grep -q "^READY" "$WORK_DIR/sim.log" 2>/dev/null && break
        sleep 1
    done
    grep -q "^READY" "$WORK_DIR/sim.log" || { echo "simulator failed to start"; tail -20 "$WORK_DIR/sim.log"; exit 1; }
}

stop_simulator() {
    [ -z "${SIM_PID:-}" ] && return 0
    kill "$SIM_PID" 2>/dev/null
    for _ in $(seq 1 20); do
        kill -0 "$SIM_PID" 2>/dev/null || break
        sleep 1
    done
    SIM_PID=""
}

deploy_integration() {
    mkdir -p "$HA_DIR/custom_components"
    rm -rf "$HA_DIR/custom_components/deako"
    cp -r "$REPO_ROOT/custom_components/deako" "$HA_DIR/custom_components/deako"
    rm -rf "$HA_DIR/custom_components/deako/__pycache__"
    find "$HA_DIR/custom_components/deako" -name '*.py' -exec sed -i 's/\r$//' {} \;
    # Deliberately not default_config: with WSL mirrored networking it pulls in
    # broad LAN discovery against the real house, which is slow enough to time
    # this script out and intrusive besides. Leaving zeroconf out entirely also
    # proves outcome O8 -- nothing here can find a Deako node.
    cat > "$HA_DIR/configuration.yaml" <<'YAML'
http:
api:
config:
onboarding:

logger:
  default: warning
  logs:
    custom_components.deako: debug
YAML
}

ha_http_code() {
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE/api/" 2>/dev/null)
    echo "${code:-000}"
}

start_ha() {
    # Anything already serving 8123 is someone else's Home Assistant -- a
    # leftover from an aborted run, or another rig. Every check below would run
    # against it and pass or fail for unrelated reasons. This exact mistake
    # silently invalidated a whole run in wayfinder #15.
    if [ "$(ha_http_code)" != "000" ]; then
        echo "  something is already serving $BASE; refusing to test against it"
        command -v ss >/dev/null && ss -ltnp 2>/dev/null | grep 8123
        return 1
    fi

    nohup "$VENV/bin/hass" -c "$HA_DIR" --skip-pip > "$HA_DIR/ha.log" 2>&1 &
    HA_PID=$!
    for i in $(seq 1 72); do
        if ! kill -0 "$HA_PID" 2>/dev/null; then
            echo "  HA exited during startup"; tail -30 "$HA_DIR/ha.log"; return 1
        fi
        [ "$(ha_http_code)" != "000" ] && { echo "  HA up after $((i * 5))s (pid $HA_PID)"; return 0; }
        sleep 5
    done
    echo "  HA never came up"; tail -30 "$HA_DIR/ha.log"; return 1
}

onboard() { # sets TOKEN and AUTH
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
}

ha_state() { # ha_state <entity_id>
    curl -s "$BASE/api/states/$1" -H "$AUTH" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print('unreadable'); raise SystemExit
print(d.get('state', 'missing'))
"
}

ha_attr() { # ha_attr <entity_id> <attribute>
    curl -s "$BASE/api/states/$1" -H "$AUTH" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print('unreadable'); raise SystemExit
value = d.get('attributes', {}).get('$2', 'absent')
print(json.dumps(value) if isinstance(value, (dict, list)) else value)
"
}

wait_for_state() { # wait_for_state <entity_id> <wanted> <budget_s> -> echoes seconds taken, or -1
    local entity="$1" wanted="$2" budget="$3" i
    for i in $(seq 0 "$budget"); do
        [ "$(ha_state "$entity")" = "$wanted" ] && { echo "$i"; return 0; }
        sleep 1
    done
    echo "-1"
    return 1
}

wait_for_not_state() { # wait_for_not_state <entity_id> <unwanted> <budget_s>
    local entity="$1" unwanted="$2" budget="$3" i
    for i in $(seq 0 "$budget"); do
        [ "$(ha_state "$entity")" != "$unwanted" ] && { echo "$i"; return 0; }
        sleep 1
    done
    echo "-1"
    return 1
}

# Every inbound request the simulator has logged, by name. This is the
# instrument for "nothing is polling": the integration's only reason to send
# DEVICE_LIST is setup and reconnect, and DEVICE_POLL it should never send at
# all.
sim_request_count() { # sim_request_count <NAME>
    local n
    n=$(grep -c "\[RECV\].*\"name\": \"$1\"" "$WORK_DIR/sim.log" 2>/dev/null)
    echo "${n:-0}"
}

# ---------------------------------------------------------------------------
# Phase 1: the converged entity, healthy.
# ---------------------------------------------------------------------------

echo "== starting the simulator on loopback, no mDNS =="
start_simulator

echo ""
echo "== phase 1: healthy =="
rm -rf "$HA_DIR"
mkdir -p "$HA_DIR"
deploy_integration
start_ha || exit 1
onboard

FLOW_ID=$(curl -s -X POST "$BASE/api/config/config_entries/flow" -H "$AUTH" \
    -H "Content-Type: application/json" -d '{"handler":"deako","show_advanced_options":true}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('flow_id',''))")
curl -s -X POST "$BASE/api/config/config_entries/flow/$FLOW_ID" -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d "{\"ip_address\":\"$SIM_IP\",\"port\":$SIM_PORT}" > "$WORK_DIR/flow.json"
sleep 20

ENTRY_ID=$(curl -s "$BASE/api/config/config_entries/entry" -H "$AUTH" | python3 -c "
import sys, json
entries = [e for e in json.load(sys.stdin) if e['domain'] == 'deako']
print(entries[0]['entry_id'] if entries else '')
")
[ -n "$ENTRY_ID" ]; report $? "the integration set up against the configured address" "entry_id=${ENTRY_ID:-none}"

DIMMER_STATE=$(ha_state "$DIMMER")
[ "$DIMMER_STATE" = "on" ]; report $? "the dimmer reports the state the hub gave it" "state=$DIMMER_STATE"

# The house's live fault, in one assertion. Without a declared color mode
# current Home Assistant rejects every state write, and 37 lights sat frozen
# for nine days while the integration reported itself healthy (wayfinder #3).
DIMMER_MODE=$(ha_attr "$DIMMER" color_mode)
[ "$DIMMER_MODE" = "brightness" ]; report $? "the dimmer declares an active color mode" "color_mode=$DIMMER_MODE"

DIMMER_MODES=$(ha_attr "$DIMMER" supported_color_modes)
echo "$DIMMER_MODES" | grep -q "brightness"; report $? \
    "the dimmer supports brightness" "supported_color_modes=$DIMMER_MODES"

# O6: dimmability comes from the device's declared capabilities, not from
# whether a `dim` value happened to be in the reported state. The simulator's
# switch reports no dim at all, so both readings agree here -- what this pins
# is that the on/off device is not accidentally advertised as a dimmer.
SWITCH_MODES=$(ha_attr "$SWITCH" supported_color_modes)
[ "$SWITCH_MODES" = '["onoff"]' ]; report $? \
    "the non-dimmable switch is onoff only" "supported_color_modes=$SWITCH_MODES"

# The entity ids have to be the ones the house already has. Adopting core's
# has_entity_name shape must not rename anything.
SWITCH_STATE=$(ha_state "$SWITCH")
[ "$SWITCH_STATE" != "missing" ] && [ "$SWITCH_STATE" != "unreadable" ]; report $? \
    "both simulator devices became the expected entities" "$DIMMER=$DIMMER_STATE $SWITCH=$SWITCH_STATE"

# O6: a physical wall press, reflected with nothing polling.
curl -s -X POST "$SIM_HTTP/api/devices/$SWITCH_UUID/button" >/dev/null
PRESS_S=$(wait_for_state "$SWITCH" "on" 10)
[ "$PRESS_S" != "-1" ] && [ "$PRESS_S" -le 5 ]; report $? \
    "a physical wall press reaches Home Assistant promptly" "after ${PRESS_S}s"

# A command still has to work, and its result has to be visible.
curl -s -X POST "$BASE/api/services/light/turn_on" -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d "{\"entity_id\":\"$DIMMER\",\"brightness\":128}" >/dev/null
sleep 5
DIMMER_BRIGHTNESS=$(ha_attr "$DIMMER" brightness)
[ "$DIMMER_BRIGHTNESS" != "absent" ] && [ "$DIMMER_BRIGHTNESS" -ge 120 ] && [ "$DIMMER_BRIGHTNESS" -le 135 ]
report $? "a brightness command round-trips through the hub" "brightness=$DIMMER_BRIGHTNESS"

echo "  holding still for ${QUIET_WINDOW_S}s to see whether anything polls..."
LIST_BEFORE=$(sim_request_count DEVICE_LIST)
POLL_BEFORE=$(sim_request_count DEVICE_POLL)
sleep "$QUIET_WINDOW_S"
LIST_AFTER=$(sim_request_count DEVICE_LIST)
POLL_AFTER=$(sim_request_count DEVICE_POLL)
[ "$LIST_AFTER" -eq "$LIST_BEFORE" ] && [ "$POLL_AFTER" -eq "$POLL_BEFORE" ]; report $? \
    "nothing polls the hub while the connection is healthy" \
    "DEVICE_LIST ${LIST_BEFORE}->${LIST_AFTER}, DEVICE_POLL ${POLL_BEFORE}->${POLL_AFTER} over ${QUIET_WINDOW_S}s"

# ---------------------------------------------------------------------------
# Phase 2: the hub drops the connection. This is the known trap.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 2: the connection is dropped =="
curl -s -X POST "$SIM_HTTP/api/control/disconnect" >/dev/null

GREY_S=$(wait_for_state "$DIMMER" "unavailable" "$GREY_OUT_BUDGET_S")
[ "$GREY_S" != "-1" ]; report $? \
    "the dimmer goes unavailable when the connection dies" "after ${GREY_S}s"

SWITCH_GREY=$(ha_state "$SWITCH")
[ "$SWITCH_GREY" = "unavailable" ]; report $? \
    "every light goes unavailable, not just the one that was touched" "$SWITCH=$SWITCH_GREY"

# ---------------------------------------------------------------------------
# Phase 3: state moves while we are blind, and the reconnect corrects it.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 3: state changes while disconnected, then reconnect =="
# The hub is fine; only the socket died. Turn the dimmer off at the wall while
# nothing is listening -- the EVENT goes nowhere.
curl -s -X POST "$SIM_HTTP/api/devices/$DIMMER_UUID/state" \
    -H "Content-Type: application/json" -d '{"power": false}' >/dev/null

BACK_S=$(wait_for_not_state "$DIMMER" "unavailable" "$RECONNECT_BUDGET_S")
[ "$BACK_S" != "-1" ]; report $? \
    "the connection comes back with no human action" "after ${BACK_S}s"

RESYNC_STATE=$(ha_state "$DIMMER")
[ "$RESYNC_STATE" = "off" ]; report $? \
    "the reconnect corrects state that changed while we were blind" "state=$RESYNC_STATE (changed to off during the outage)"

# ---------------------------------------------------------------------------
# Phase 4: the hub is gone entirely, and a command must fail visibly.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 4: the hub is gone; commands must fail loudly =="
stop_simulator

DOWN_S=$(wait_for_state "$DIMMER" "unavailable" 40)
[ "$DOWN_S" != "-1" ]; report $? "a hub that vanished marks the lights unavailable" "after ${DOWN_S}s"

# O5's last clause, at the Home Assistant level. Current Home Assistant drops
# unavailable entities from an entity service call before it reaches the
# integration (helpers/service.py), so the command never gets as far as the
# hub -- and the light stays visibly unavailable rather than flipping to `on`
# as though something had happened. That entity-level refusal is only possible
# because the entity now reports itself unavailable at all; before this ticket
# it read `off` and accepted the command.
#
# The integration's own refusal -- raising rather than swallowing a send that
# failed -- is a library-level contract and is proved in
# vendored_deviation_checks.py, where the failure can be produced without
# racing Home Assistant's own filter.
curl -s -o "$WORK_DIR/failed_command.json" -w "%{http_code}" \
    -X POST "$BASE/api/services/light/turn_on" -H "$AUTH" \
    -H "Content-Type: application/json" -d "{\"entity_id\":\"$DIMMER\"}" > "$WORK_DIR/cmd_code.txt"
sleep 5
AFTER_CMD=$(ha_state "$DIMMER")
[ "$AFTER_CMD" = "unavailable" ]; report $? \
    "a command aimed at a dead hub does not fake success" \
    "state=$AFTER_CMD, HTTP $(cat "$WORK_DIR/cmd_code.txt") $(head -c 80 "$WORK_DIR/failed_command.json")"

ROUTED=$(python3 -c "
import json, sys
try:
    print(len(json.load(open('$WORK_DIR/failed_command.json'))))
except Exception:
    print('unreadable')
")
[ "$ROUTED" = "0" ]; report $? \
    "the command reached no entity at all, so nothing was silently swallowed" \
    "entities changed=$ROUTED"

# ---------------------------------------------------------------------------
# Phase 5: a device the hub counts and never announces (O10).
# ---------------------------------------------------------------------------

echo ""
echo "== phase 5: an enumeration shortfall, then a late arrival =="
start_simulator
curl -s -X POST "$SIM_HTTP/api/control/withhold" -H "Content-Type: application/json" \
    -d "{\"uuids\":[\"$SWITCH_UUID\"]}" > "$WORK_DIR/withhold.json"
grep -q "$SWITCH_UUID" "$WORK_DIR/withhold.json"; report $? \
    "the simulator will hold the switch back from the DEVICE_FOUND stream" \
    "$(head -c 160 "$WORK_DIR/withhold.json")"

# Let the running integration find the new simulator process first. Reloading
# on top of a half-built connection would have the reload's own connection
# arrive while the previous one is still the simulator's active client, and be
# accepted as a passive zombie that never receives anything.
wait_for_not_state "$DIMMER" "unavailable" "$RECONNECT_BUDGET_S" >/dev/null
sleep 5

# Reload rather than restart: this is the shape a Home Assistant that is
# already running takes when a switch stops answering, and it exercises the
# registry path -- the entity is not re-added, and must not be deleted either.
#
# Setup waits out the enumeration window for the device that never comes, so
# the lights are gone for that long before the ones that did report appear.
curl -s -X POST "$BASE/api/config/config_entries/entry/$ENTRY_ID/reload" -H "$AUTH" >/dev/null

RELOAD_S=$(wait_for_not_state "$DIMMER" "unavailable" 120)
[ "$RELOAD_S" != "-1" ]; report $? \
    "the device that did report is working despite the shortfall" \
    "$DIMMER=$(ha_state "$DIMMER") after ${RELOAD_S}s"

SWITCH_AFTER=$(ha_state "$SWITCH")
[ "$SWITCH_AFTER" = "unavailable" ]; report $? \
    "the withheld device is unavailable, not missing" "$SWITCH=$SWITCH_AFTER"

# And say so out loud, rather than continuing quietly the way the old
# DEVICE_FOUND_POLLING_INTERVAL_S = 60 trick did -- that did not slow a poll,
# it made the shortfall check unreachable.
grep -q "Enumeration fell short" "$HA_DIR/ha.log"; report $? \
    "the shortfall is logged rather than passed over in silence" \
    "$(grep -m1 -o 'Enumeration fell short.*' "$HA_DIR/ha.log" | head -c 160)"

# Home Assistant only shows it that way because the registry entry survived.
# If it had been deleted, its history, its dashboards and every automation
# naming it would have gone with it.
IN_REGISTRY=$(python3 - "$HA_DIR/.storage/core.entity_registry" "$SWITCH_UUID" <<'PY'
import json
import sys

path, uuid = sys.argv[1], sys.argv[2]
try:
    entities = json.load(open(path, encoding="utf-8"))["data"]["entities"]
except (OSError, ValueError, KeyError):
    print("unreadable")
    raise SystemExit
match = [e for e in entities if e["platform"] == "deako" and e["unique_id"] == uuid]
print(match[0]["entity_id"] if match else "deleted")
PY
)
[ "$IN_REGISTRY" = "$SWITCH" ]; report $? \
    "the withheld device keeps its registry entry, and so its history" "registry=$IN_REGISTRY"

# The late DEVICE_FOUND. Nothing asked for it, and nothing is going to restart.
curl -s -X POST "$SIM_HTTP/api/control/deliver/$SWITCH_UUID" > "$WORK_DIR/deliver.json"
LATE_S=$(wait_for_not_state "$SWITCH" "unavailable" 20)
[ "$LATE_S" != "-1" ]; report $? \
    "a late DEVICE_FOUND brings the device back without a restart" \
    "after ${LATE_S}s, $(head -c 120 "$WORK_DIR/deliver.json")"

LATE_STATE=$(ha_state "$SWITCH")
LATE_MODES=$(ha_attr "$SWITCH" supported_color_modes)
[ "$LATE_MODES" = '["onoff"]' ]; report $? \
    "the recovered entity is a fully formed light, not a stub" \
    "state=$LATE_STATE supported_color_modes=$LATE_MODES"

# It has to be controllable too -- a device that came back and cannot be
# commanded is the same failure wearing a different state.
curl -s -X POST "$BASE/api/services/light/turn_off" -H "$AUTH" \
    -H "Content-Type: application/json" -d "{\"entity_id\":\"$SWITCH\"}" >/dev/null
OFF_S=$(wait_for_state "$SWITCH" "off" 15)
[ "$OFF_S" != "-1" ]; report $? "the recovered device accepts commands" "off after ${OFF_S}s"

echo ""
echo "== $PASSED passed, $FAILED failed =="
echo "   HA log:        $HA_DIR/ha.log"
echo "   simulator log: $WORK_DIR/sim.log"
[ "$FAILED" -eq 0 ]
