#!/usr/bin/env bash
# End-to-end proof for wayfinder #41: a socket that says nothing is not a hub,
# reconnection is event-driven with a deliberate backoff, and the reconnect
# counter now tells you what the attempts actually did.
#
# The thing this exists to catch is not slowness. `is_connected()` was satisfied
# by a TCP handshake and never required the hub to have said anything -- and
# Deako's telnet server is exclusive, so a node still holding a previous session
# accepts our socket at the network layer and serves nothing across it. Home
# Assistant then shows 37 available lights serving cached state, and commands
# into that socket vanish with no error. Wayfinder #32 caught the house node
# doing exactly this for 13 seconds and it was read as a node symptom.
#
# So the headline check below is not a stopwatch, it is a negative: with the hub
# accepting connections and answering nothing, the integration must refuse to
# call that a connection, for as long as it goes on.
#
# Five phases, in one Home Assistant:
#   1. ENTITIES     -- the reconnect counter carries the failed-attempt record
#                      as *attributes*, not as new entities. #10 ruled that
#                      diagnostics stay small, and #32 closed with no instrument
#                      at all; this is the instrument, for the price of two
#                      attributes.
#   2. STUCK SLOT   -- the headline. The hub accepts the socket and serves
#                      nothing. Connected must stay off, the lights must stay
#                      unavailable, and the reconnect count must not move --
#                      while the unanswered-attempt attribute climbs, which is
#                      the proof that attempts really were made and rejected.
#   3. NOT SILENT   -- and a command issued into that stuck slot reaches
#                      nothing and moves nothing. #16 shipped "a command to a
#                      dead hub no longer succeeds silently"; #38 found a
#                      technically-alive socket defeats it, because the lights
#                      stayed available and the send stayed "successful". With
#                      the gate in place they are unavailable, so Home Assistant
#                      will not route the call at all -- that is the hole
#                      closed, by availability rather than by an error.
#   4. RECOVERY     -- unaided, once the hub starts answering. Retry is forever;
#                      that is the property #19 proved and the house depends on,
#                      and it must survive going event-driven.
#   5. HONEST COUNT -- exactly one reconnect is recorded for one real recovery,
#                      no matter how many stuck attempts preceded it. Before
#                      #41 each knock on a door that had not finished closing
#                      was logged as an arrival, which is why #32's ten
#                      reconnects were not ten node failures.
#
# The backoff ladder itself is measured separately and directly by
# tools/deako_connect_cost.py, which reports the gaps rather than asserting
# them: 1, 2, 4, 8 then capped at 10s, against the flat 10.02s it measured
# before this change.
#
# Don't test against imagination: the muted-hub mode used in phases 2-4 is
# modelled hub behaviour, not invented fault injection. #32 observed the house
# node accept a connection, serve nothing for 13s and then close it itself, and
# the map owner confirmed the mechanism first-hand.
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
#   bash specs/001-deako-hub-simulator/e2e/wsl_validate_event_driven_reconnect.sh

set -uo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/../../.." && pwd)"
# shellcheck source=specs/001-deako-hub-simulator/e2e/lib_port_guard.sh
. "$E2E_DIR/lib_port_guard.sh"

HA_DIR="$HOME/ha-test-latest"
VENV="$HOME/ha-venv-latest"
WORK_DIR="${RECONNECT_WORK_DIR:-$HOME/reconnect-ha}"
SIM_IP="127.0.0.1"
HA_PORT="8123"
BASE="http://127.0.0.1:$HA_PORT"

SIM_PORT=""
SIM_HTTP_PORT=""
SIM_HTTP=""

DIMMER="light.zero_dim_test_dimmer"
SWITCH="light.zero_dim_test_switch"

CONNECTED="binary_sensor.deako_hub_connected"
RECONNECTS="sensor.deako_hub_reconnects_since_restart"
PROBE_SWITCH="switch.deako_hub_reachability_probe"

# From custom_components/deako/pydeako/deako/_manager.py. The watchdog is what
# notices a hub that has gone quiet, and it is deliberately NOT changed here --
# how fast that should be is its own ticket (#42). It bounds how long phase 2
# has to wait before any reconnect attempt is even made.
PING_WORKER_WAIT_S=10
HANDSHAKE_PONG_TIMEOUT_S=3

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
HA_PID=""
cleanup() {
    # Leave the hub answering again whatever happened, so an aborted run does
    # not hand the next one a muted simulator.
    curl -s -o /dev/null -X POST "$SIM_HTTP/api/control/mute" \
        -H "Content-Type: application/json" -d '{"mute":false}' 2>/dev/null
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

entity_exists() { # entity_exists <entity_id>
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/states/$1" -H "$AUTH")
    [ "$code" = "200" ]
}

mute_hub() { # mute_hub <true|false> [close_after]
    curl -s -o /dev/null -X POST "$SIM_HTTP/api/control/mute" \
        -H "Content-Type: application/json" \
        -d "{\"mute\":$1,\"close_after\":${2:-0}}"
}

drop_connection() {
    curl -s -o /dev/null -X POST "$SIM_HTTP/api/control/disconnect" \
        -H "Content-Type: application/json" -d '{}'
}

set_switch() { # set_switch <switch entity> <on|off>
    curl -s -o /dev/null -X POST "$BASE/api/services/switch/turn_$2" -H "$AUTH" \
        -H "Content-Type: application/json" -d "{\"entity_id\":\"$1\"}"
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
             if k in ('failed_attempts', 'unanswered_attempts')}
    print(f\"  {e['entity_id']:52} {str(e['state']):18} {extra if extra else ''}\")
"
    echo ""
}

# ---------------------------------------------------------------------------
# Phase 1: the instrument exists, and it is an attribute rather than an entity.
# ---------------------------------------------------------------------------

echo "== starting the simulator on loopback, no mDNS =="
start_simulator
mute_hub false

echo ""
echo "== phase 1: the failed-attempt record ships as attributes =="
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

CONNECTED_STATE=$(ha_state "$CONNECTED")
[ "$CONNECTED_STATE" = "on" ]; report $? \
    "setup reached a hub that answers, so the connection is reported up" \
    "$CONNECTED=$CONNECTED_STATE -- and it took a correlated pong to say so, not just a socket"

RECONNECTS_STATE=$(ha_state "$RECONNECTS")
[ "$RECONNECTS_STATE" = "0" ]; report $? \
    "the reconnect counter exists and starts at zero" \
    "$RECONNECTS=$RECONNECTS_STATE"

FAILED_ATTR=$(ha_attr "$RECONNECTS" failed_attempts)
UNANSWERED_ATTR=$(ha_attr "$RECONNECTS" unanswered_attempts)
[ "$FAILED_ATTR" = "0" ] && [ "$UNANSWERED_ATTR" = "0" ]; report $? \
    "it carries the failed-attempt record as attributes" \
    "failed_attempts=$FAILED_ATTR unanswered_attempts=$UNANSWERED_ATTR -- #32 closed with no instrument that would explain the next burst, and #10 ruled diagnostics stay small, so this costs no new entity"

! entity_exists "sensor.deako_hub_failed_attempts"; report $? \
    "and no new entity was added for it" \
    "#38 chose an attribute deliberately; a new entity here would be a diagnostic nobody asked for"

# The hourly probe would otherwise be issuing its own commands into a hub this
# script is about to mute, which muddies phase 3's error.
set_switch "$PROBE_SWITCH" off
sleep 2
PROBE_OFF=$(ha_state "$PROBE_SWITCH")
[ "$PROBE_OFF" = "off" ]; report $? \
    "the hourly probe is parked so it cannot confound the stuck-slot phases" \
    "$PROBE_SWITCH=$PROBE_OFF"

dump_entities "everything the integration exposes, against a healthy hub"

# ---------------------------------------------------------------------------
# Phase 2: the headline. A socket the hub never answers is not a connection.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 2: the hub accepts the socket and serves nothing =="

RECONNECTS_BEFORE=$(ha_state "$RECONNECTS")

mute_hub true
drop_connection

DOWN_S=$(wait_for_state "$CONNECTED" "off" 30)
[ "$DOWN_S" != "-1" ]; report $? \
    "losing the socket is noticed" \
    "connected went off in ${DOWN_S}s"

# Nothing retries until the watchdog returns a verdict, which is up to two ping
# windows away -- that is #42's question, not this ticket's. After that, each
# attempt opens a socket, waits out the ping budget and climbs the backoff
# ladder. Watch until two stuck attempts have been recorded rather than for a
# fixed time, so this phase cannot pass by never having attempted anything.
WATCH_BUDGET=$((2 * PING_WORKER_WAIT_S + 40))
FALSELY_UP="no"
STUCK=0
for _ in $(seq 1 "$WATCH_BUDGET"); do
    sleep 1
    [ "$(ha_state "$CONNECTED")" = "on" ] && { FALSELY_UP="yes"; break; }
    STUCK=$(ha_attr "$RECONNECTS" unanswered_attempts)
    [ "$STUCK" != "absent" ] && [ "$STUCK" -ge 2 ] 2>/dev/null && break
done

[ "$FALSELY_UP" = "no" ] && [ "$STUCK" -ge 2 ] 2>/dev/null; report $? \
    "a socket the hub never answers is not reported connected" \
    "$STUCK attempt(s) opened a socket to a hub serving nothing, connected stayed off throughout (falsely_up=$FALSELY_UP). Before #41 the first of those read as a live hub: 37 lights available, serving cached state, taking commands into a socket going nowhere"

LIGHT_STATE=$(ha_state "$DIMMER")
[ "$LIGHT_STATE" = "unavailable" ]; report $? \
    "and the lights are unavailable rather than serving cached state" \
    "$DIMMER=$LIGHT_STATE -- this is #16's availability model, which a technically-alive socket used to defeat"

RECONNECTS_DURING=$(ha_state "$RECONNECTS")
[ "$RECONNECTS_DURING" = "$RECONNECTS_BEFORE" ]; report $? \
    "a stuck slot does not inflate the reconnect count" \
    "reconnects=$RECONNECTS_DURING, was $RECONNECTS_BEFORE, with $STUCK stuck attempt(s) recorded as attributes instead. #32's ten reconnects were not ten node failures for exactly this reason"

FAILED_DURING=$(ha_attr "$RECONNECTS" failed_attempts)
[ "$FAILED_DURING" -ge "$STUCK" ] 2>/dev/null; report $? \
    "every stuck attempt is also a failed attempt" \
    "failed_attempts=$FAILED_DURING unanswered_attempts=$STUCK -- unanswered is the subset worth reading first, because it is us knocking on a door that has not finished closing"

dump_entities "while the hub is accepting sockets and serving nothing"

# ---------------------------------------------------------------------------
# Phase 3: a command into that stuck slot cannot vanish.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 3: commands cannot vanish into a stuck slot =="

# What the hub actually received. The muted connection is never served, so
# nothing sent into it is parsed or logged -- which makes this count exactly
# "commands that reached a hub willing to read them".
sim_controls_in() {
    local n
    n=$(grep -c -- '\[RECV\].*"type": "CONTROL"' "$WORK_DIR/sim.log" 2>/dev/null)
    echo "${n:-0}"
}

CONTROLS_BEFORE=$(sim_controls_in)
DROPPED_BEFORE=$(ha_state "sensor.deako_hub_unacknowledged_commands")

CMD_CODE=$(curl -s -o "$WORK_DIR/cmd.json" -w "%{http_code}" \
    -X POST "$BASE/api/services/light/turn_on" -H "$AUTH" \
    -H "Content-Type: application/json" -d "{\"entity_id\":\"$DIMMER\"}")
sleep 5

CONTROLS_AFTER=$(sim_controls_in)
STUCK_LIGHT=$(ha_state "$DIMMER")

[ "$CONTROLS_AFTER" = "$CONTROLS_BEFORE" ] && [ "$STUCK_LIGHT" = "unavailable" ]; report $? \
    "a command issued while the hub is stuck reaches nothing and moves nothing" \
    "hub received $CONTROLS_AFTER CONTROLs (was $CONTROLS_BEFORE), $DIMMER=$STUCK_LIGHT. HTTP $CMD_CODE is Home Assistant declining to route a service call to an unavailable entity (#23), not the integration taking it -- and being unavailable is precisely what #41 buys, because a stuck slot used to leave these lights available"

DROPPED_AFTER=$(ha_state "sensor.deako_hub_unacknowledged_commands")
[ "$DROPPED_AFTER" = "$DROPPED_BEFORE" ]; report $? \
    "and it is not counted against the hub as a dropped command" \
    "unacknowledged=$DROPPED_AFTER (was $DROPPED_BEFORE) -- nothing was sent, so there is nothing for the hub to have failed to answer. #39's counter measures a hub refusing a command, and blaming it here would corrupt the number the pacing question is waiting on"

# The optimistic UI update #39 ships fires on the *acknowledgement*, so this is
# also the check that it cannot fire on a socket the hub never answered.
[ "$STUCK_LIGHT" != "on" ]; report $? \
    "the ack-driven UI update did not fire on a hub that said nothing" \
    "$DIMMER=$STUCK_LIGHT -- #39 moves the entity when the hub acknowledges, and a stuck slot acknowledges nothing"

# ---------------------------------------------------------------------------
# Phase 4: recovery, unaided.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 4: the hub starts answering again =="

mute_hub false

# Worst case is one backoff cap plus the ping budget, plus the resync.
UP_S=$(wait_for_state "$CONNECTED" "on" 45)
[ "$UP_S" != "-1" ]; report $? \
    "the connection recovers unaided once the hub answers" \
    "connected went on ${UP_S}s after the hub started answering. Retry is forever and the backoff caps at 10s, which is the cadence #19 measured as survivable against a dead node -- so steady state is no more aggressive than the code already in the house"

LIGHT_BACK_S=$(wait_for_state "$DIMMER" "on" 30)
[ "$LIGHT_BACK_S" != "-1" ] || [ "$(ha_state "$DIMMER")" != "unavailable" ]; report $? \
    "and the lights come back with it" \
    "$DIMMER=$(ha_state "$DIMMER") after ${LIGHT_BACK_S}s"

# ---------------------------------------------------------------------------
# Phase 5: one recovery, one reconnect.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 5: the count is honest =="

RECONNECTS_AFTER=$(ha_state "$RECONNECTS")
FAILED_AFTER=$(ha_attr "$RECONNECTS" failed_attempts)
UNANSWERED_AFTER=$(ha_attr "$RECONNECTS" unanswered_attempts)

[ "$RECONNECTS_AFTER" = "$((RECONNECTS_BEFORE + 1))" ]; report $? \
    "exactly one reconnect is recorded for one real recovery" \
    "reconnects=$RECONNECTS_AFTER (was $RECONNECTS_BEFORE) after $UNANSWERED_AFTER stuck attempts and one proven connection"

[ "$UNANSWERED_AFTER" -ge 2 ] 2>/dev/null; report $? \
    "and what the reconnect actually did is still readable afterwards" \
    "failed_attempts=$FAILED_AFTER unanswered_attempts=$UNANSWERED_AFTER -- the record survives the recovery, which is the whole point of putting it on a sensor rather than in a log line"

dump_entities "after recovery"

echo ""
echo "===================================================================="
echo "$PASSED passed, $FAILED failed"
echo ""
echo "NOTE: the reconnect counter's meaning changes at this release. It now"
echo "counts connections the hub has answered on, not sockets that opened, so"
echo "recorder history is not comparable across the deploy that ships #41."
echo "===================================================================="

[ "$FAILED" -eq 0 ]
