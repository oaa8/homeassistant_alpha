#!/usr/bin/env bash
# End-to-end proof for wayfinder #37/#39: the acknowledgement drives the UI, it
# does so on the entity only, it gives up when nothing confirms it, and the
# commands the hub never took are counted separately from the switches that did
# not move.
#
# What this is here to catch is a regression the house has been living with
# since the cutover. 0.3.1 wrote the commanded value into the UI the instant the
# bytes left the machine; 0.6.0 deleted that, and every command now waits on the
# switch's own EVENT -- measured in the house at 1549-3412ms, against 9-10ms to
# the service call returning. So a light appears not to have responded, and
# someone presses again. #37 chose the hub's acknowledgement as the trigger
# instead: slower than the send, and honest, because it at least says the hub
# took the command.
#
# The instrument here is a stopwatch, not a green tick. Every phase reports the
# number it measured.
#
# Six phases, in one Home Assistant:
#   1. ENTITIES   -- the counter exists, is TOTAL_INCREASING so it survives a
#                    restart as a statistic, and starts at zero.
#   2. INSTANT    -- the headline. A commanded light reads its new state in
#                    milliseconds, and the confirming EVENT is shown arriving
#                    much later, so the gap being closed is visible rather than
#                    asserted.
#   3. REVERT     -- a switch that acknowledges and never reports gets the
#                    optimistic value taken back off it at the witness window.
#                    The flip back is the only feedback anybody gets that the
#                    light did not answer.
#   4. NOT THE CACHE -- and the value it reverts to is the witnessed one, still
#                    sitting in the device cache untouched. Proved through the
#                    probe, which reads that cache and echoes it at the mesh
#                    hourly: if optimism had reached it, the probe would
#                    physically drive the light to something nobody asked for.
#   5. DROPS      -- commands arriving at the hub too close together are
#                    silently dropped, and the counter agrees with the number
#                    the hub actually dropped. This is the measurement the map's
#                    open pacing question is waiting on.
#   6. NOT THE SWITCH -- and those drops are not counted against the device. A
#                    hub that never took a command says nothing about the
#                    switch, and blaming it there is what the integration did
#                    before this shipped.
#
# Not covered here, deliberately: a command in flight when the socket dies is
# discarded rather than counted. On loopback the ack arrives in under a
# millisecond, so there is no window to cut -- that one is proved in
# vendored_deviation_checks.py, where the ack can be withheld outright.
#
# Don't test against imagination: phases 3 and 4 use the simulator's model of a
# registered-but-unreachable device (measured in #13: it enumerates, answers
# DEVICE_POLL, acks CONTROL "ok", and never emits the EVENT), and phase 5 uses
# its ~100ms silent-drop threshold, which is measured hub behaviour from
# research/rate-limiting-systematic-test-2025-10-18.md.
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
#   bash specs/001-deako-hub-simulator/e2e/wsl_validate_ack_ui.sh

set -uo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/../../.." && pwd)"
# shellcheck source=specs/001-deako-hub-simulator/e2e/lib_port_guard.sh
. "$E2E_DIR/lib_port_guard.sh"

HA_DIR="$HOME/ha-test-latest"
VENV="$HOME/ha-venv-latest"
WORK_DIR="${ACK_WORK_DIR:-$HOME/ack-ha}"
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

DROPPED="sensor.deako_hub_unacknowledged_commands"
SWITCH_NODE="sensor.zero_dim_test_switch_node_status"
DIMMER_NODE="sensor.zero_dim_test_dimmer_node_status"
SWITCH_PROBE_VALUE="sensor.zero_dim_test_switch_last_probe_value"
PROBE_SWITCH="switch.deako_hub_reachability_probe"
CENSUS_BUTTON="button.deako_hub_run_census_now"
LAST_PASS="sensor.deako_hub_last_probe_pass"

# From custom_components/deako/pydeako/deako/_deako.py. The ordering between
# these two is the design: a command the hub never took is settled as a drop
# before the witness window would otherwise blame the device for it.
ACK_WINDOW_S=2
WITNESS_WINDOW_S=5

# The house baseline this change is measured against, from wayfinder #37:
# v0.6.0-oaa8-1 returned from the service call in 9-10ms and did not move the
# entity for 1549-3412ms. Anything near the old number here is a failure even
# if every other check passes.
INSTANT_BUDGET_MS=500

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

# Home Assistant's own view of when the entity moved, to the millisecond.
# Polling would measure this script's loop rather than the integration, and the
# whole point of this ticket is a number.
ha_last_changed() { # ha_last_changed <entity_id> -> epoch seconds as a float
    curl -s "$BASE/api/states/$1" -H "$AUTH" | python3 -c "
import sys, json
from datetime import datetime
try:
    d = json.load(sys.stdin)
    print(datetime.fromisoformat(d['last_changed']).timestamp())
except Exception:
    print('0')
"
}

now_epoch() { python3 -c "import time; print(time.time())"; }

ms_between() { # ms_between <from> <to>
    python3 -c "print(round((float('$2') - float('$1')) * 1000, 1))"
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

wait_for_change() { # wait_for_change <entity_id> <was> <budget_s> -> seconds taken, or -1
    local entity="$1" was="$2" budget="$3" i
    for i in $(seq 0 "$budget"); do
        [ "$(ha_state "$entity")" != "$was" ] && { echo "$i"; return 0; }
        sleep 1
    done
    echo "-1"
    return 1
}

command_light() { # command_light <entity_id> <on|off> [extra json]
    local extra="${3:-}"
    local body="{\"entity_id\":\"$1\"$extra}"
    curl -s -o "$WORK_DIR/cmd.json" -X POST "$BASE/api/services/light/turn_$2" -H "$AUTH" \
        -H "Content-Type: application/json" -d "$body" >/dev/null
}

press() { # press <button entity>
    curl -s -o /dev/null -X POST "$BASE/api/services/button/press" -H "$AUTH" \
        -H "Content-Type: application/json" -d "{\"entity_id\":\"$1\"}"
}

set_switch() { # set_switch <switch entity> <on|off>
    curl -s -o /dev/null -X POST "$BASE/api/services/switch/turn_$2" -H "$AUTH" \
        -H "Content-Type: application/json" -d "{\"entity_id\":\"$1\"}"
}

# What the hub received against what it answered. The simulator drops a command
# arriving inside its rate-limit window without replying at all, exactly as the
# real hub does, so the difference is the hub's own count of what it threw away
# -- an independent number to hold the integration's counter against.
#
# The two directions are matched differently on purpose: pydeako serialises with
# json.dumps' default separators, so what the hub *receives* reads
# `"type": "CONTROL"`, while the hub's own replies are compact and read
# `"type":"CONTROL"`. Grepping one pattern for both silently counts zero.
count_lines() { # count_lines <pattern> <file>
    local n
    n=$(grep -c -- "$1" "$2" 2>/dev/null)
    echo "${n:-0}"
}
sim_controls_in() { count_lines '\[RECV\].*"type": "CONTROL"' "$WORK_DIR/sim.log"; }
sim_controls_out() { count_lines '\[SEND\].*"type":"CONTROL"' "$WORK_DIR/sim.log"; }

# When the EVENT confirming a command arrived, so the gap the ack closes can be
# shown rather than asserted from memory.
#
# Read from Home Assistant's own log rather than the simulator's: the simulator
# broadcasts EVENTs without logging them, and in any case what matters is when
# the integration *heard* it, which is the thing the UI used to wait for.
ha_last_event_epoch() {
    grep '"type": "EVENT"' "$HA_DIR/ha.log" 2>/dev/null | tail -1 | python3 -c "
import sys
from datetime import datetime
parts = sys.stdin.readline().strip().split(' ')
if len(parts) < 2:
    print('0'); raise SystemExit
try:
    print(datetime.strptime(parts[0] + ' ' + parts[1],
                            '%Y-%m-%d %H:%M:%S.%f').timestamp())
except Exception:
    print('0')
"
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
             if k in ('state_class', 'brightness', 'hub_address')}
    print(f\"  {e['entity_id']:52} {str(e['state']):18} {extra if extra else ''}\")
"
    echo ""
}

# ---------------------------------------------------------------------------
# Phase 1: the counter exists and reads sanely.
# ---------------------------------------------------------------------------

echo "== starting the simulator on loopback, no mDNS =="
start_simulator

echo ""
echo "== phase 1: the counter exists =="
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

DROPPED_STATE=$(ha_state "$DROPPED")
[ "$DROPPED_STATE" = "0" ]; report $? \
    "the unacknowledged-command counter exists and starts at zero" \
    "$DROPPED=$DROPPED_STATE"

DROPPED_CLASS=$(ha_attr "$DROPPED" state_class)
[ "$DROPPED_CLASS" = "total_increasing" ]; report $? \
    "it is a statistic, not a reading that ages out of the recorder" \
    "state_class=$DROPPED_CLASS -- the recorder keeps 60 days here, long-term statistics never purge, and the pacing question needs to accumulate across a longer window than that"

# The probe would otherwise put its own commands through every measurement
# below, at an interval this script cannot see. It is turned back on in phase 4,
# where it is the instrument.
set_switch "$PROBE_SWITCH" off
sleep 2
PROBE_OFF=$(ha_state "$PROBE_SWITCH")
[ "$PROBE_OFF" = "off" ]; report $? \
    "the hourly probe is parked so it cannot confound the stopwatch" \
    "$PROBE_SWITCH=$PROBE_OFF"

dump_entities "everything the integration exposes, before any command"

# ---------------------------------------------------------------------------
# Phase 2: the headline. A light reads its new state in milliseconds.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 2: the acknowledgement drives the UI =="

# Start from a known place, and let the simulator's EVENT settle it, so the
# measurement below starts from a witnessed state rather than an optimistic one.
command_light "$DIMMER" off
sleep $((WITNESS_WINDOW_S + 2))
BEFORE=$(ha_state "$DIMMER")

EVENTS_BEFORE=$(ha_last_event_epoch)
T0=$(now_epoch)
command_light "$DIMMER" on ",\"brightness\":128"
CHANGED_S=$(wait_for_state "$DIMMER" "on" 15)
T_MOVED=$(ha_last_changed "$DIMMER")
INSTANT_MS=$(ms_between "$T0" "$T_MOVED")

python3 -c "
import sys
sys.exit(0 if 0 <= float('$INSTANT_MS') <= $INSTANT_BUDGET_MS else 1)
"
report $? "the light reads its commanded state within ${INSTANT_BUDGET_MS}ms of the service call" \
    "measured ${INSTANT_MS}ms, from ${BEFORE} to on -- the house measured 1549-3412ms to this same transition on v0.6.0-oaa8-1, with 9-10ms to the service call returning"

BRIGHTNESS=$(ha_attr "$DIMMER" brightness)

# The EVENT still arrives, and still does its job; it is simply no longer what
# the UI waits for. Printing the gap is what makes phase 2 legible.
sleep 4
EVENT_AT=$(ha_last_event_epoch)
EVENT_MS=$(ms_between "$T0" "$EVENT_AT")
python3 -c "
import sys
event_at, before = float('$EVENT_AT'), float('$EVENTS_BEFORE')
sys.exit(0 if event_at > before and float('$EVENT_MS') > float('$INSTANT_MS') else 1)
"
report $? "the switch's own EVENT arrived later, which is the gap being closed" \
    "ack-driven update at ${INSTANT_MS}ms, the confirming EVENT at ${EVENT_MS}ms -- the EVENT keeps every job it had, it is simply no longer what the UI waits for"

# What matters is not that the optimistic brightness matches the number Home
# Assistant was handed -- the percent-to-255 round trip through the protocol
# loses a step either way -- but that it matches what the *witnessed* value
# resolves to. A disagreement would show as a visible twitch when the EVENT
# lands, and would mean the two paths compute brightness differently.
SETTLED_BRIGHTNESS=$(ha_attr "$DIMMER" brightness)
[ "$BRIGHTNESS" = "$SETTLED_BRIGHTNESS" ]
report $? "the optimistic brightness is the same value the EVENT settles on" \
    "optimistic=$BRIGHTNESS, after the EVENT=$SETTLED_BRIGHTNESS, commanded=128 (the protocol carries dim as a percent, so 128 goes out as 50% and comes back as 127)"

python3 -c "
import sys
sys.exit(0 if abs(int('$BRIGHTNESS') - 128) <= 2 else 1)
"
report $? "and it is the brightness that was asked for, to within the protocol's resolution" \
    "brightness=$BRIGHTNESS for a commanded 128"

STILL_ON=$(ha_state "$DIMMER")
[ "$STILL_ON" = "on" ]; report $? \
    "a witnessed command is never reverted" \
    "$DIMMER=$STILL_ON after the witness window closed -- a revert here would flip a light that worked"

# ---------------------------------------------------------------------------
# Phase 3: the revert, on a switch that acknowledges and never reports.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 3: nothing confirms it, so it is taken back =="
curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d "{\"uuids\":[\"$SWITCH_UUID\"]}" > "$WORK_DIR/unreachable.json"
grep -q "$SWITCH_UUID" "$WORK_DIR/unreachable.json"; report $? \
    "the simulator will acknowledge the switch and never report it" \
    "$(head -c 160 "$WORK_DIR/unreachable.json")"

SWITCH_BEFORE=$(ha_state "$SWITCH")
R0=$(now_epoch)
command_light "$SWITCH" on
OPT_S=$(wait_for_state "$SWITCH" "on" 5)
T_OPT=$(ha_last_changed "$SWITCH")
OPT_MS=$(ms_between "$R0" "$T_OPT")
[ "$OPT_S" != "-1" ]; report $? \
    "an unreachable switch is still shown as commanded -- the hub took it" \
    "showed on after ${OPT_MS}ms; the ack proves the hub accepted the command, never that the switch moved (#13)"

REVERT_S=$(wait_for_state "$SWITCH" "$SWITCH_BEFORE" $((WITNESS_WINDOW_S + 6)))
T_REVERT=$(ha_last_changed "$SWITCH")
REVERT_MS=$(ms_between "$R0" "$T_REVERT")
[ "$REVERT_S" != "-1" ]; report $? \
    "the witness window closing takes the optimistic value back off it" \
    "back to $SWITCH_BEFORE after ${REVERT_MS}ms, against a ${WITNESS_WINDOW_S}s window -- the flip back is the only feedback anyone gets that the light did not answer"

# ---------------------------------------------------------------------------
# Phase 4: what it reverted to, and why the cache must stay clean.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 4: optimism never reached the device cache =="

# The probe reads the device cache with get_state() and echoes it back at the
# mesh. If the ack had written the commanded value there, this pass would drive
# the switch to a state nobody asked for -- and on a dimmable, to a brightness
# nobody asked for. The probe's own attribution record is what makes that
# readable.
set_switch "$PROBE_SWITCH" on
sleep 2
PASS_BEFORE=$(ha_state "$LAST_PASS")
press "$CENSUS_BUTTON"
PASS_S=$(wait_for_change "$LAST_PASS" "$PASS_BEFORE" 60)
[ "$PASS_S" != "-1" ]; report $? \
    "a census pass ran, so the probe has read the cache and said what it sent" \
    "after ${PASS_S}s"

PROBED_VALUE=$(ha_state "$SWITCH_PROBE_VALUE")
[ "$PROBED_VALUE" = "$SWITCH_BEFORE" ]; report $? \
    "the probe echoed the witnessed value, not the one we optimistically showed" \
    "probe sent '$PROBED_VALUE', witnessed state was '$SWITCH_BEFORE', we had optimistically shown 'on' -- optimism in the cache would be re-commanded on every pass forever"

set_switch "$PROBE_SWITCH" off
sleep 2

# ---------------------------------------------------------------------------
# Phase 5: commands the hub never took.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 5: the hub drops commands, and we now count them =="
curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d '{"uuids":[]}' > /dev/null
sleep 2

DROPS_BEFORE=$(ha_state "$DROPPED")
SIM_IN_BEFORE=$(sim_controls_in)
SIM_OUT_BEFORE=$(sim_controls_out)

# Fired together on purpose. The hub silently drops a second command to the same
# device inside ~100ms, which is exactly what a scene does now that 0.6.0 has no
# send queue -- 0.3.1 spaced them 500ms apart and could not produce this.
#
# Waited on by pid, never a bare `wait`: this shell also owns the simulator and
# Home Assistant as background jobs, and a bare wait would sit on those forever.
BURST_PIDS=""
for level in 40 80 120 160 200 240; do
    command_light "$DIMMER" on ",\"brightness\":$level" &
    BURST_PIDS="$BURST_PIDS $!"
done
# shellcheck disable=SC2086
wait $BURST_PIDS
sleep $((ACK_WINDOW_S + WITNESS_WINDOW_S + 4))

SIM_IN=$(( $(sim_controls_in) - SIM_IN_BEFORE ))
SIM_OUT=$(( $(sim_controls_out) - SIM_OUT_BEFORE ))
SIM_DROPPED=$((SIM_IN - SIM_OUT))
DROPS_AFTER=$(ha_state "$DROPPED")
COUNTED=$((DROPS_AFTER - DROPS_BEFORE))

[ "$SIM_DROPPED" -gt 0 ]; report $? \
    "the hub really did drop commands sent this close together" \
    "it received $SIM_IN and answered $SIM_OUT, so it threw away $SIM_DROPPED -- measured behaviour, ~100ms apart is the threshold"

[ "$COUNTED" -eq "$SIM_DROPPED" ]; report $? \
    "the counter agrees with what the hub actually threw away" \
    "counted $COUNTED, hub dropped $SIM_DROPPED -- this is the number the map's open pacing question is waiting on, so it has to be the hub's number and not our own"

# ---------------------------------------------------------------------------
# Phase 6: and a drop is not the switch's fault.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 6: a dropped command is not counted against the switch =="
DIMMER_STATUS=$(ha_state "$DIMMER_NODE")
[ "$DIMMER_STATUS" = "online" ]; report $? \
    "the device the hub dropped commands for still reads online" \
    "$DIMMER_NODE=$DIMMER_STATUS -- no ack means the *hub* never took it; before this shipped the witness window opened anyway and the switch wore the miss, and #26's retry then spent a real physical command confirming a fault that was never there"

RETRIES=$(count_lines "Re-sending the unwitnessed command to $DIMMER_UUID" "$HA_DIR/ha.log")
[ "$RETRIES" -eq 0 ]; report $? \
    "and no retry was spent confirming a fault that was never there" \
    "retries for this device=$RETRIES (the unreachable switch from phase 3 has its own, which is #26 working as intended)"

dump_entities "everything the integration exposes, at the end"

echo ""
echo "===================================================================="
echo "$PASSED passed, $FAILED failed"
echo "===================================================================="
[ "$FAILED" -eq 0 ]
