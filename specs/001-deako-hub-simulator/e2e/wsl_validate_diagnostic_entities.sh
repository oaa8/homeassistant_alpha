#!/usr/bin/env bash
# End-to-end proof for wayfinder #23: the five diagnostic entities, and the
# command-witness detector behind the per-node one, in a real Home Assistant
# against the simulator.
#
# What this is here to catch is the thing the house cannot currently tell you.
# A switch drops off the mesh every few weeks -- powered, physically working,
# and not remotely controllable -- and today the only symptom is that somebody
# reaches for a light and nothing happens. The integration reports the light as
# healthy throughout, because the hub acknowledges every command for it in
# ~110ms whether or not the switch still exists. Wayfinder #13 measured that
# against a switch pulled out of the wall months ago, then found six more live
# in the house, one of them in daily use.
#
# Five phases, in one Home Assistant, because the later ones only mean
# something against an installation that already exists:
#   1. HEALTHY      -- all five entity types exist and read sanely: the hub is
#                      connected and names the address it is bound to, both
#                      nodes are online, the sweep is fully accounted for, and
#                      the hub's last word is recent.
#   2. UNREACHABLE  -- a switch that acks and never reports. Two commanded
#                      changes go unwitnessed and its node status says so --
#                      while the *other* node stays online, the hub stays
#                      connected, and the light stays available, which is the
#                      part that decides whether the mark can ever clear.
#   3. RECOVERY     -- the switch is back on the mesh. The next command is
#                      witnessed and the node reads online again, with no
#                      restart and nothing reloaded.
#   4. HUB DOWN     -- the connection dies. Every node reads hub_disconnected
#                      rather than making a claim about a switch it cannot
#                      reach, and the reconnect is counted when it comes back.
#   5. HUB QUIET    -- the hub stops answering without closing the socket. The
#                      age of its last word climbs, which is the only thing
#                      that sees this before the ping watchdog does.
#
# Loopback only, and no mDNS: the real house is on this LAN with a live Home
# Assistant on it, so the simulator must not advertise itself, and nothing here
# can discover a Deako node -- every connection made below came from the
# configured address.
#
# Every port this script depends on is measured before it is used, per
# lib_port_guard.sh (wayfinder #24).
#
# Prerequisites: bash specs/001-deako-hub-simulator/e2e/wsl_setup_ha_latest.sh
#
# Usage (inside WSL):
#   bash specs/001-deako-hub-simulator/e2e/wsl_validate_diagnostic_entities.sh

set -uo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/../../.." && pwd)"
# shellcheck source=specs/001-deako-hub-simulator/e2e/lib_port_guard.sh
. "$E2E_DIR/lib_port_guard.sh"

HA_DIR="$HOME/ha-test-latest"
VENV="$HOME/ha-venv-latest"
WORK_DIR="${DIAGNOSTICS_WORK_DIR:-$HOME/diagnostics-ha}"
SIM_IP="127.0.0.1"
HA_PORT="8123"
BASE="http://127.0.0.1:$HA_PORT"

SIM_PORT=""
SIM_HTTP_PORT=""
SIM_HTTP=""

DIMMER_UUID="11111111-1111-4111-8111-111111111111"
SWITCH_UUID="33333333-3333-4333-8333-333333333333"
DIMMER="light.zero_dim_test_dimmer"
SWITCH="light.zero_dim_test_switch"

# The entities under test. Hard-coded rather than discovered, because the ids
# are part of what ships: automations and dashboards will name them.
HUB_CONNECTED="binary_sensor.deako_hub_connected"
RECONNECTS="sensor.deako_hub_reconnects_since_restart"
LAST_MESSAGE="sensor.deako_hub_time_since_last_hub_message"
DEVICES_REPORTING="sensor.deako_hub_devices_reporting"
DIMMER_NODE="sensor.zero_dim_test_dimmer_node_status"
SWITCH_NODE="sensor.zero_dim_test_switch_node_status"

# The detector's window, from custom_components/deako/pydeako/deako/_deako.py.
# Two commands have to be spaced further apart than this, or the second one
# replaces the first's window instead of following it.
WITNESS_WINDOW_S=5
COMMAND_GAP_S=8
# Detection plus a fresh connection. #19 measured reconnect within ~30s of the
# fault on real firmware; a missed pong costs up to another ping window first.
RECONNECT_BUDGET_S=90
GREY_OUT_BUDGET_S=15

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

echo "== checking the ports this run depends on =="
SIM_PORT=$(first_silent_port "$SIM_IP" "simulator telnet port" 8023 8024 8025 8026) || exit 1
SIM_HTTP_PORT=$(first_silent_port "$SIM_IP" "simulator control port" 8080 8081 8082 8083) || exit 1
SIM_HTTP="http://$SIM_IP:$SIM_HTTP_PORT"
echo "  simulator $SIM_IP:$SIM_PORT, control $SIM_HTTP"

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
        --port "$SIM_PORT" --http-port "$SIM_HTTP_PORT" > "$WORK_DIR/sim.log" 2>&1 &
    SIM_PID=$!
    for _ in $(seq 1 30); do
        grep -q "^READY" "$WORK_DIR/sim.log" 2>/dev/null && break
        sleep 1
    done
    grep -q "^READY" "$WORK_DIR/sim.log" || { echo "simulator failed to start"; tail -20 "$WORK_DIR/sim.log"; exit 1; }
}

deploy_integration() {
    mkdir -p "$HA_DIR/custom_components"
    rm -rf "$HA_DIR/custom_components/deako"
    cp -r "$REPO_ROOT/custom_components/deako" "$HA_DIR/custom_components/deako"
    rm -rf "$HA_DIR/custom_components/deako/__pycache__"
    find "$HA_DIR/custom_components/deako" -name '*.py' -exec sed -i 's/\r$//' {} \;
    # Deliberately not default_config: with WSL mirrored networking it pulls in
    # broad LAN discovery against the real house, which is slow enough to time
    # this script out and intrusive besides.
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
    # Anything answering on 8123 is someone else's Home Assistant -- a leftover
    # from an aborted run, or another rig. Every check below would run against
    # it and pass or fail for unrelated reasons. This exact mistake silently
    # invalidated a whole run in wayfinder #15.
    if port_answers "127.0.0.1" "$HA_PORT"; then
        echo "  something already answers on 127.0.0.1:$HA_PORT; refusing to test against it"
        echo "  it is $(describe_port "127.0.0.1" "$HA_PORT")"
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

wait_for_state() { # wait_for_state <entity_id> <wanted> <budget_s> -> seconds taken, or -1
    local entity="$1" wanted="$2" budget="$3" i
    for i in $(seq 0 "$budget"); do
        [ "$(ha_state "$entity")" = "$wanted" ] && { echo "$i"; return 0; }
        sleep 1
    done
    echo "-1"
    return 1
}

# Everything this integration exposes, as a human would read it off a
# dashboard. Printed rather than asserted: the assertions below pin the
# specific facts, and this is here so a run can be *looked at* rather than only
# counted, which is the bar this map sets for claiming a change works.
dump_entities() { # dump_entities <heading>
    echo ""
    echo "  --- $1 ---"
    curl -s "$BASE/api/states" -H "$AUTH" | python3 -c "
import sys, json
interesting = ('deako', 'zero_dim')
rows = [e for e in json.load(sys.stdin)
        if any(k in e['entity_id'] for k in interesting)]
for e in sorted(rows, key=lambda r: r['entity_id']):
    attrs = e['attributes']
    extra = {k: v for k, v in attrs.items()
             if k in ('hub_address', 'expected_devices', 'missing_uuids',
                      'device_class', 'state_class', 'brightness')}
    print(f\"  {e['entity_id']:52} {str(e['state']):18} {extra if extra else ''}\")
"
    echo ""
}

command_light() { # command_light <entity_id> <on|off> -> HTTP body written to $WORK_DIR/cmd.json
    curl -s -o "$WORK_DIR/cmd.json" -X POST "$BASE/api/services/light/turn_$2" -H "$AUTH" \
        -H "Content-Type: application/json" -d "{\"entity_id\":\"$1\"}" >/dev/null
}

# Every inbound request the simulator has logged, by name. The integration's
# only reason to send DEVICE_LIST is setup and reconnect, and DEVICE_POLL it
# must never send at all -- #13 ruled it out of the vendored copy, because it
# is a cache echo and having it there would imply a device can be interrogated.
sim_request_count() { # sim_request_count <NAME>
    local n
    n=$(grep -c "\[RECV\].*\"type\": \"$1\"" "$WORK_DIR/sim.log" 2>/dev/null)
    echo "${n:-0}"
}

# ---------------------------------------------------------------------------
# Phase 1: the entities exist and read sanely.
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

MISSING=""
for entity in "$HUB_CONNECTED" "$RECONNECTS" "$LAST_MESSAGE" "$DEVICES_REPORTING" \
              "$DIMMER_NODE" "$SWITCH_NODE"; do
    state=$(ha_state "$entity")
    [ "$state" = "missing" ] && MISSING="$MISSING $entity"
done
if [ -z "$MISSING" ]; then
    ENTITY_DETAIL="6 entities: 1 connectivity, 3 hub-level, 2 per-node"
    ENTITIES_OK=0
else
    ENTITY_DETAIL="absent:$MISSING; what was actually created: $(
        curl -s "$BASE/api/states" -H "$AUTH" | python3 -c "
import sys, json
print(', '.join(sorted(e['entity_id'] for e in json.load(sys.stdin)
                       if 'deako' in e['entity_id'] or 'zero_dim' in e['entity_id'])))
")"
    ENTITIES_OK=1
fi
report "$ENTITIES_OK" "all five diagnostic entity types were created" "$ENTITY_DETAIL"

CONNECTED=$(ha_state "$HUB_CONNECTED")
[ "$CONNECTED" = "on" ]; report $? "the hub reports connected" "state=$CONNECTED"

# Manual address selection is this map's safety control, and the options flow
# was dead in the house for nine days -- so the bound address has to be
# readable from something other than the options screen.
BOUND=$(ha_attr "$HUB_CONNECTED" hub_address)
[ "$BOUND" = "$SIM_IP:$SIM_PORT" ]; report $? \
    "the bound hub address is readable as an attribute" "hub_address=$BOUND"

REPORTING=$(ha_state "$DEVICES_REPORTING")
EXPECTED=$(ha_attr "$DEVICES_REPORTING" expected_devices)
MISSING_UUIDS=$(ha_attr "$DEVICES_REPORTING" missing_uuids)
[ "$REPORTING" = "2" ] && [ "$EXPECTED" = "2" ] && [ "$MISSING_UUIDS" = "[]" ]
report $? "the sweep is fully accounted for" \
    "reporting=$REPORTING expected=$EXPECTED missing=$MISSING_UUIDS"

AGE=$(ha_state "$LAST_MESSAGE")
python3 -c "
import sys
try:
    sys.exit(0 if 0 <= float('$AGE') < 60 else 1)
except ValueError:
    sys.exit(1)
"
report $? "the hub's last message is timed, and it is recent" \
    "age=${AGE}s -- stamped before pong filtering, so an idle hub still counts as talking"

RECONNECT_COUNT=$(ha_state "$RECONNECTS")
[ "$RECONNECT_COUNT" = "0" ]; report $? \
    "nothing has reconnected yet" "reconnects=$RECONNECT_COUNT"

DIMMER_STATUS=$(ha_state "$DIMMER_NODE")
SWITCH_STATUS=$(ha_state "$SWITCH_NODE")
[ "$DIMMER_STATUS" = "online" ] && [ "$SWITCH_STATUS" = "online" ]
report $? "both nodes read online" "$DIMMER_NODE=$DIMMER_STATUS $SWITCH_NODE=$SWITCH_STATUS"

# The node status sensor has to sit on the same device as its light, or "which
# switch, and why" needs a cross-reference at read time. #10 chose this shape
# precisely because `unavailable` alone is not a diagnosis.
SAME_DEVICE=$(curl -s -X POST "$BASE/api/template" -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d "{\"template\": \"{{ device_id('$SWITCH_NODE') == device_id('$SWITCH') }}\"}")
[ "$SAME_DEVICE" = "True" ]; report $? \
    "the node status sensor sits on the same device as its light" \
    "device_id('$SWITCH_NODE') == device_id('$SWITCH') -> $SAME_DEVICE"

OPTIONS=$(ha_attr "$SWITCH_NODE" options)
echo "$OPTIONS" | grep -q "unreachable" && echo "$OPTIONS" | grep -q "hub_disconnected"
report $? "the node status sensor declares its three readings" "options=$OPTIONS"

dump_entities "everything the integration exposes, healthy"

# ---------------------------------------------------------------------------
# Phase 2: a switch that acknowledges and never reports.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 2: a registered-but-unreachable switch =="
curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d "{\"uuids\":[\"$SWITCH_UUID\"]}" > "$WORK_DIR/unreachable.json"
grep -q "$SWITCH_UUID" "$WORK_DIR/unreachable.json"; report $? \
    "the simulator will acknowledge the switch and never report it" \
    "$(head -c 160 "$WORK_DIR/unreachable.json")"

BEFORE_LIGHT=$(ha_state "$SWITCH")

# One miss is a lost mesh frame and must mark nothing.
command_light "$SWITCH" on
sleep $((WITNESS_WINDOW_S + 2))
AFTER_ONE=$(ha_state "$SWITCH_NODE")
[ "$AFTER_ONE" = "online" ]; report $? \
    "one unwitnessed command does not condemn a switch" "$SWITCH_NODE=$AFTER_ONE"

# Two consecutive is the pattern somebody is already complaining about.
sleep "$COMMAND_GAP_S"
command_light "$SWITCH" off
MARK_S=$(wait_for_state "$SWITCH_NODE" "unreachable" $((WITNESS_WINDOW_S + 10)))
[ "$MARK_S" != "-1" ]; report $? \
    "a second unwitnessed command marks the node unreachable" "after ${MARK_S}s"

# The failure has to be attributed to the switch, not to the hub or the house.
OTHER_NODE=$(ha_state "$DIMMER_NODE")
STILL_CONNECTED=$(ha_state "$HUB_CONNECTED")
[ "$OTHER_NODE" = "online" ] && [ "$STILL_CONNECTED" = "on" ]
report $? "the blame lands on the switch, not the hub" \
    "$DIMMER_NODE=$OTHER_NODE $HUB_CONNECTED=$STILL_CONNECTED"

# The house's actual symptom: the command was accepted, in ~110ms, and nothing
# moved. Before this ticket that was the whole story and it was silent.
AFTER_LIGHT=$(ha_state "$SWITCH")
[ "$AFTER_LIGHT" = "$BEFORE_LIGHT" ]; report $? \
    "the light never moved, because no EVENT ever confirmed it" \
    "state=$AFTER_LIGHT (unchanged from $BEFORE_LIGHT, despite two acknowledged commands)"

# The decision this ticket made, and the one the recovery path depends on.
# Home Assistant drops unavailable entities from service calls
# (helpers/service.py), so a light greyed out on `unreachable` could never be
# commanded again -- and the next command is the cheapest thing that can clear
# the mark. #10 said otherwise, but it said so while `unreachable` was still
# believed to be observed on every sweep, and therefore self-clearing.
LIGHT_AVAILABLE=$([ "$AFTER_LIGHT" != "unavailable" ] && echo yes || echo no)
[ "$LIGHT_AVAILABLE" = "yes" ]; report $? \
    "the light stays available so it can still be commanded" \
    "state=$AFTER_LIGHT -- unavailable would latch the mark on for good"

# The recovery path, measured at the wire rather than inferred. Home Assistant's
# service API answers with the states that *changed*, and for a light nothing
# ever confirms that is always none -- so a call that did reach the integration
# is indistinguishable there from one that was dropped. What has to be true is
# that the command left the building, because that command is the only thing
# that can clear the mark.
CONTROLS_BEFORE=$(grep -c "\[RECV\].*\"type\": \"CONTROL\".*$SWITCH_UUID" "$WORK_DIR/sim.log" 2>/dev/null)
command_light "$SWITCH" on
sleep 3
CONTROLS_AFTER=$(grep -c "\[RECV\].*\"type\": \"CONTROL\".*$SWITCH_UUID" "$WORK_DIR/sim.log" 2>/dev/null)
[ "${CONTROLS_AFTER:-0}" -gt "${CONTROLS_BEFORE:-0}" ]; report $? \
    "a command aimed at an unreachable light still reaches the hub" \
    "CONTROLs for this switch ${CONTROLS_BEFORE}->${CONTROLS_AFTER}; had the entity been marked unavailable, Home Assistant would have dropped the call before the integration ever saw it"

dump_entities "one switch unreachable -- what the owner would actually see"

# ---------------------------------------------------------------------------
# Phase 3: the switch comes back, with nobody restarting anything.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 3: the switch rejoins the mesh =="
curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d '{"uuids":[]}' >/dev/null
# The hub silently drops a second command to the same device inside 100ms
# (first-in-wins), so give the previous phase's command room to be the one that
# was dropped rather than this one.
sleep 2

command_light "$SWITCH" on
CLEAR_S=$(wait_for_state "$SWITCH_NODE" "online" 20)
[ "$CLEAR_S" != "-1" ]; report $? \
    "a witnessed command clears the mark, with no restart and no reload" "after ${CLEAR_S}s"

RECOVERED_LIGHT=$(wait_for_state "$SWITCH" "on" 10)
[ "$RECOVERED_LIGHT" != "-1" ]; report $? \
    "and the light moves again" "reached on after ${RECOVERED_LIGHT}s"

# ---------------------------------------------------------------------------
# Phase 4: the hub goes away, and every node says so rather than guessing.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 4: the connection dies =="
curl -s -X POST "$SIM_HTTP/api/control/disconnect" >/dev/null

DOWN_S=$(wait_for_state "$HUB_CONNECTED" "off" "$GREY_OUT_BUDGET_S")
[ "$DOWN_S" != "-1" ]; report $? \
    "the connectivity sensor reports the outage rather than vanishing with it" "after ${DOWN_S}s"

DIMMER_DOWN=$(ha_state "$DIMMER_NODE")
SWITCH_DOWN=$(ha_state "$SWITCH_NODE")
[ "$DIMMER_DOWN" = "hub_disconnected" ] && [ "$SWITCH_DOWN" = "hub_disconnected" ]
report $? "every node blames the hub instead of claiming to know about a switch" \
    "$DIMMER_NODE=$DIMMER_DOWN $SWITCH_NODE=$SWITCH_DOWN"

BACK_S=$(wait_for_state "$HUB_CONNECTED" "on" "$RECONNECT_BUDGET_S")
[ "$BACK_S" != "-1" ]; report $? \
    "the connection comes back with no human action" "after ${BACK_S}s"

sleep 5
RECONNECT_COUNT=$(ha_state "$RECONNECTS")
[ "$RECONNECT_COUNT" = "1" ]; report $? \
    "the rebuilt connection was counted" \
    "reconnects=$RECONNECT_COUNT after exactly one outage"

REPORTING=$(ha_state "$DEVICES_REPORTING")
EXPECTED=$(ha_attr "$DEVICES_REPORTING" expected_devices)
[ "$REPORTING" = "2" ] && [ "$EXPECTED" = "2" ]; report $? \
    "the reconnect's resync refreshed the sweep numbers" \
    "reporting=$REPORTING expected=$EXPECTED"

BACK_ONLINE=$(wait_for_state "$SWITCH_NODE" "online" 20)
[ "$BACK_ONLINE" != "-1" ]; report $? \
    "the nodes stop blaming the hub once it is back" "after ${BACK_ONLINE}s"

# #13 ruled DEVICE_POLL out of the vendored copy: it echoes the node's own
# cache, so having it there would imply the integration can interrogate a
# device. Nothing in this run may have sent one.
POLLS=$(sim_request_count DEVICE_POLL)
[ "$POLLS" -eq 0 ]; report $? \
    "the integration never polls a device" \
    "DEVICE_POLL requests received=$POLLS (it is a cache echo, not a question)"

# ---------------------------------------------------------------------------
# Phase 5: the hub goes quiet, and the age sensor is what notices.
# ---------------------------------------------------------------------------
#
# Worth its own phase because of something this run made visible. On a healthy
# connection the age reads a near-constant small number -- 3.3s twice in a row
# in the dumps above -- and that is aliasing, not a stuck entity: Home
# Assistant samples every 30s and the watchdog pings every 10s, so every sample
# lands on the same phase of the ping cycle. A flat healthy baseline is good
# for reading a graph, but it means "the number is moving" can never be the
# evidence that this entity works. So make the hub actually go quiet and
# require the age to climb past a ping window.

echo ""
echo "== phase 5: the hub goes quiet =="
AGE_BEFORE=$(ha_state "$LAST_MESSAGE")
kill "$SIM_PID" 2>/dev/null
SIM_PID=""
for _ in $(seq 1 15); do
    port_answers "$SIM_IP" "$SIM_PORT" || break
    sleep 1
done

# Two poll intervals plus slack: one to leave the healthy phase behind, one to
# be sure the reading that follows was taken after the hub stopped talking.
sleep 75
AGE_AFTER=$(ha_state "$LAST_MESSAGE")
python3 -c "
import sys
try:
    before, after = float('$AGE_BEFORE'), float('$AGE_AFTER')
except ValueError:
    sys.exit(1)
sys.exit(0 if after > before and after > 30 else 1)
"
report $? "silence is what makes the age climb, and it does" \
    "age ${AGE_BEFORE}s -> ${AGE_AFTER}s after the hub stopped answering \
(healthy it sits inside one 10s ping window; this is the silent-degradation \
signal the ping watchdog takes 19s to reach on its own)"

STILL_THERE=$(ha_state "$LAST_MESSAGE")
[ "$STILL_THERE" != "unavailable" ] && [ "$STILL_THERE" != "missing" ]
report $? "the diagnostics outlive the outage they are describing" \
    "$LAST_MESSAGE=$STILL_THERE, $HUB_CONNECTED=$(ha_state "$HUB_CONNECTED")"

echo ""
echo "======================================================================"
echo "  passed: $PASSED    failed: $FAILED"
echo "  simulator log: $WORK_DIR/sim.log"
echo "  home assistant log: $HA_DIR/ha.log"
echo "======================================================================"
[ "$FAILED" -eq 0 ]
