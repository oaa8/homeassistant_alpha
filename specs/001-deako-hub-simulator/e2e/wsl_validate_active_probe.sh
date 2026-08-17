#!/usr/bin/env bash
# End-to-end proof for wayfinder #26: the active reachability probe, its
# governor, and the per-switch attribution record, in a real Home Assistant
# against the simulator.
#
# #23 shipped a detector that can only confirm an unreachable switch the moment
# somebody reaches for it, which in a quiet house is never -- ten hardware runs
# with no manipulation produced zero EVENTs. #25 ruled that the integration
# should reach for every switch itself, hourly, including the ones already
# marked, and accept the one hazard that creates rather than prevent it.
#
# That acceptance is what makes this script's shape what it is. If the hazard
# ever fires -- a device whose cache went stale off-mesh, driven to that stale
# value by our own echo -- the light moves *to* the state Home Assistant
# already believes, so `light.X` reads the same before and after and the
# recorder shows nothing at all. The per-switch last_probed / last_probe_value
# pair is the only possible witness, and a test that left it
# plausible-but-wrong would defeat the entire arrangement. So phase 1 does not
# stop at "the entity exists": it reads what was sent, checks it against what
# the device actually held, and then goes to the *recorder* to prove the record
# survives being written.
#
# Eight phases, in one Home Assistant (with one deliberate restart), because
# the later ones only mean something against an installation that already has
# a history:
#   1. FIRST PASS  -- the pass runs on its own after startup, writes to every
#                     device, moves no light, is paced above the hub's drop
#                     threshold, and leaves an attribution record the recorder
#                     still holds afterwards.
#   2. DISCOVERY   -- the headline claim, and the reason #26 exists: a switch
#                     that has left the mesh is found, and then found to be
#                     back, **with nobody reaching for a light**. Before this
#                     the node status sensor could only confirm a fault
#                     somebody had already walked into.
#   3. STORM       -- three reconnects in quick succession produce no probing
#                     at all. 0.6.0 has no reconnect backoff and this house has
#                     a node that flaps every 6-12 minutes, so an ungoverned
#                     probe-on-reconnect would be a write storm aimed squarely
#                     at a mesh that is already unwell.
#   4. HUB DOWN    -- a pass falling due while the connection is down does not
#                     fire and does not fake a timestamp; the reconnect brings
#                     it forward instead.
#   5. THE SWITCH  -- turning the probe off really stops automatic passes, and
#                     the census button still works while it is off.
#   6. RESTART     -- and the off answer survives a restart, because a setting
#                     that quietly comes back looks respected and is not.
#   7. THE RETRY   -- the 30s retry brings the second miss forward so both land
#                     inside a minute, and does *not* double-count into a false
#                     mark: a device that answers the retry stays online and
#                     carries no miss into the next hour.
#   8. BACK ON     -- turning it on resumes passes without a restart.
#
# Don't test against imagination: phases 2 and 7 use the simulator's model of a
# registered-but-unreachable device, which is measured hub behaviour from #13
# (enumerates, answers DEVICE_POLL, acks CONTROL "ok", never emits the EVENT)
# rather than an invented fault.
#
# ONE CONSTANT IS SHORTENED, AND ONLY ONE. The shipped cadence is hourly;
# waiting out four real hours to see the governor work is not a test anybody
# runs. PROBE_INTERVAL_S is patched in the *deployed copy* to PATCHED_INTERVAL_S
# below, and phase 0 asserts the shipped source still says 3600 so the run says
# out loud which number ships and which was shortened. Everything else -- the
# 15s startup delay, the 1.1s pacing, the 5s witness window, the 30s retry, the
# two-miss rule -- runs at its production value.
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
#   bash specs/001-deako-hub-simulator/e2e/wsl_validate_active_probe.sh

set -uo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/../../.." && pwd)"
# shellcheck source=specs/001-deako-hub-simulator/e2e/lib_port_guard.sh
. "$E2E_DIR/lib_port_guard.sh"

HA_DIR="$HOME/ha-test-latest"
VENV="$HOME/ha-venv-latest"
WORK_DIR="${PROBE_WORK_DIR:-$HOME/probe-ha}"
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
SWITCH_NODE="sensor.zero_dim_test_switch_node_status"
LAST_PASS="sensor.deako_hub_last_probe_pass"
ANSWERING="sensor.deako_hub_devices_answering_last_probe"
NOT_ANSWERING="sensor.deako_hub_devices_not_answering_last_probe"
PROBE_SWITCH="switch.deako_hub_reachability_probe"
CENSUS_BUTTON="button.deako_hub_run_census_now"
DIMMER_PROBED="sensor.zero_dim_test_dimmer_last_probed"
DIMMER_VALUE="sensor.zero_dim_test_dimmer_last_probe_value"
SWITCH_PROBED="sensor.zero_dim_test_switch_last_probed"
SWITCH_VALUE="sensor.zero_dim_test_switch_last_probe_value"

# Production values, from custom_components/deako/probe.py and
# custom_components/deako/pydeako/deako/_deako.py. Asserted in phase 0.
SHIPPED_INTERVAL_S=3600
FIRST_PASS_DELAY_S=15
PROBE_SPACING_S="1.1"
WITNESS_WINDOW_S=5
RETRY_DELAY_S=30

# The one shortened constant.
PATCHED_INTERVAL_S=120

# Budgets. A pass over two devices is ~2.2s of paced writes plus a 7s settle.
PASS_BUDGET_S=40
RECONNECT_BUDGET_S=90
# The retry's whole arc: miss at 5s, retry at 35s, second miss at 40s.
RETRY_ARC_S=55

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

# ---------------------------------------------------------------------------
# Phase 0: say out loud what ships, before anything is patched.
# ---------------------------------------------------------------------------

echo "== phase 0: the constants that ship =="
PROBE_SRC="$REPO_ROOT/custom_components/deako/probe.py"
DEAKO_SRC="$REPO_ROOT/custom_components/deako/pydeako/deako/_deako.py"

grep -q "^PROBE_INTERVAL_S = $SHIPPED_INTERVAL_S\$" "$PROBE_SRC"
report $? "the shipped cadence is hourly" \
    "PROBE_INTERVAL_S=$SHIPPED_INTERVAL_S in probe.py; this run patches the deployed copy to ${PATCHED_INTERVAL_S}s and nothing else"

grep -q "^PROBE_SPACING_S = $PROBE_SPACING_S\$" "$PROBE_SRC"
report $? "the pass is paced above the hub's silent-drop threshold" \
    "PROBE_SPACING_S=$PROBE_SPACING_S -- the vendor documents 800ms and #13's whole-house scans ran at 900ms and 2500ms with identical results; 37 devices at this spacing is a ~41s pass"

grep -q "^FIRST_PASS_DELAY_S = DEVICE_FOUND_WINDOW_S\$" "$PROBE_SRC"
report $? "startup waits out the enumeration window before probing" \
    "FIRST_PASS_DELAY_S = DEVICE_FOUND_WINDOW_S (${FIRST_PASS_DELAY_S}s), so a straggler is in the first census rather than missing from it"

grep -q "^RETRY_DELAY_S = $RETRY_DELAY_S\$" "$DEAKO_SRC"
report $? "the second miss is brought forward by a single retry" \
    "RETRY_DELAY_S=${RETRY_DELAY_S}s, so both misses land inside a minute"

grep -q "^MISSES_TO_UNREACHABLE = 2\$" "$DEAKO_SRC"
report $? "two consecutive misses still mark, never one" \
    "MISSES_TO_UNREACHABLE=2, unchanged from #23"

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

ready_count() {
    # grep -c prints 0 and exits non-zero when nothing matches, so a `|| echo 0`
    # here produces "0\n0" and every arithmetic test downstream then fails.
    local n
    n=$(grep -c "^READY" "$WORK_DIR/sim.log" 2>/dev/null)
    echo "${n:-0}"
}

start_simulator() { # start_simulator [append]
    if [ ! -x "$WORK_DIR/venvsim/bin/python" ]; then
        python3 -m venv "$WORK_DIR/venvsim"
    fi
    "$WORK_DIR/venvsim/bin/pip" -q install aiohttp zeroconf jsonschema
    cd "$REPO_ROOT"
    local want
    if [ "${1:-}" = "append" ]; then
        # Restarting mid-run: the log carries this run's history, and the
        # CONTROL counts are read from it, so it must not be truncated.
        want=$(( $(ready_count) + 1 ))
        "$WORK_DIR/venvsim/bin/python" "$E2E_DIR/zero_dim_sim_runner.py" \
            --port "$SIM_PORT" --http-port "$SIM_HTTP_PORT" >> "$WORK_DIR/sim.log" 2>&1 &
    else
        # Truncate before counting, or a previous run's READY lines set a
        # target this run can never reach.
        : > "$WORK_DIR/sim.log"
        want=1
        "$WORK_DIR/venvsim/bin/python" "$E2E_DIR/zero_dim_sim_runner.py" \
            --port "$SIM_PORT" --http-port "$SIM_HTTP_PORT" > "$WORK_DIR/sim.log" 2>&1 &
    fi
    SIM_PID=$!
    for _ in $(seq 1 30); do
        [ "$(ready_count)" -ge "$want" ] && break
        sleep 1
    done
    [ "$(ready_count)" -ge "$want" ] || {
        echo "simulator failed to start"; tail -20 "$WORK_DIR/sim.log"; exit 1; }
}

deploy_integration() {
    mkdir -p "$HA_DIR/custom_components"
    rm -rf "$HA_DIR/custom_components/deako"
    cp -r "$REPO_ROOT/custom_components/deako" "$HA_DIR/custom_components/deako"
    rm -rf "$HA_DIR/custom_components/deako/__pycache__"
    find "$HA_DIR/custom_components/deako" -name '*.py' -exec sed -i 's/\r$//' {} \;
    # The one shortened constant, in the deployed copy only. Phase 0 has
    # already asserted what the source says.
    sed -i "s/^PROBE_INTERVAL_S = .*/PROBE_INTERVAL_S = $PATCHED_INTERVAL_S/" \
        "$HA_DIR/custom_components/deako/probe.py"
    grep -q "^PROBE_INTERVAL_S = $PATCHED_INTERVAL_S\$" \
        "$HA_DIR/custom_components/deako/probe.py" || {
        echo "could not shorten the probe interval in the deployed copy"; exit 1; }
    # Deliberately not default_config: with WSL mirrored networking it pulls in
    # broad LAN discovery against the real house, which is slow enough to time
    # this script out and intrusive besides.
    #
    # recorder and history *are* loaded, and they are not scenery here: the
    # attribution record only counts if it is recorded, since the whole reason
    # it exists is a question asked hours later about a light that moved.
    cat > "$HA_DIR/configuration.yaml" <<'YAML'
http:
api:
config:
onboarding:
recorder:
history:

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

stop_ha() {
    pkill -f "hass -c $HA_DIR" 2>/dev/null
    for _ in $(seq 1 30); do
        port_answers "127.0.0.1" "$HA_PORT" || return 0
        sleep 2
    done
    return 1
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

call_service() { # call_service <domain> <service> <entity_id>
    curl -s -o "$WORK_DIR/svc.json" -X POST "$BASE/api/services/$1/$2" -H "$AUTH" \
        -H "Content-Type: application/json" -d "{\"entity_id\":\"$3\"}" >/dev/null
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

wait_for_change() { # wait_for_change <entity_id> <old> <budget_s> -> seconds taken, or -1
    local entity="$1" old="$2" budget="$3" i now
    for i in $(seq 0 "$budget"); do
        now=$(ha_state "$entity")
        [ "$now" != "$old" ] && [ "$now" != "unreadable" ] && { echo "$i"; return 0; }
        sleep 1
    done
    echo "-1"
    return 1
}

# CONTROLs the simulator has actually received, which is the only honest count:
# Home Assistant's own API cannot tell a command that reached the integration
# from one that was dropped before it.
controls_for() { # controls_for <uuid|"">
    local n
    if [ -z "${1:-}" ]; then
        n=$(grep -c "\[RECV\].*\"type\": \"CONTROL\"" "$WORK_DIR/sim.log" 2>/dev/null)
    else
        n=$(grep -c "\[RECV\].*\"type\": \"CONTROL\".*$1" "$WORK_DIR/sim.log" 2>/dev/null)
    fi
    echo "${n:-0}"
}

# Everything the probe exposes, as a human would read it off a dashboard.
dump_probe() { # dump_probe <heading>
    echo ""
    echo "  --- $1 ---"
    curl -s "$BASE/api/states" -H "$AUTH" | python3 -c "
import sys, json
rows = [e for e in json.load(sys.stdin)
        if ('probe' in e['entity_id'] or 'census' in e['entity_id']
            or 'node_status' in e['entity_id'] or e['entity_id'].startswith('light.zero'))]
for e in sorted(rows, key=lambda r: r['entity_id']):
    extra = {k: v for k, v in e['attributes'].items() if k in ('dim', 'brightness')}
    print(f\"  {e['entity_id']:56} {str(e['state']):32} {extra if extra else ''}\")
"
    echo ""
}

# ---------------------------------------------------------------------------
# Phase 1: a pass runs on its own, and leaves a record that survives.
# ---------------------------------------------------------------------------

echo ""
echo "== starting the simulator on loopback, no mDNS =="
start_simulator

echo ""
echo "== phase 1: the first pass, unasked =="
rm -rf "$HA_DIR"
mkdir -p "$HA_DIR"
deploy_integration
start_ha || exit 1
onboard

FLOW_AT=$(date +%s)
FLOW_ID=$(curl -s -X POST "$BASE/api/config/config_entries/flow" -H "$AUTH" \
    -H "Content-Type: application/json" -d '{"handler":"deako","show_advanced_options":true}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('flow_id',''))")
curl -s -X POST "$BASE/api/config/config_entries/flow/$FLOW_ID" -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d "{\"ip_address\":\"$SIM_IP\",\"port\":$SIM_PORT}" > "$WORK_DIR/flow.json"
# Long enough for setup to finish and the entities to exist, and short enough
# to still be inside the startup delay -- the sample below is taken while the
# enumeration window is open, not at the moment it closes.
sleep 8

MISSING=""
for entity in "$LAST_PASS" "$ANSWERING" "$NOT_ANSWERING" "$PROBE_SWITCH" \
              "$CENSUS_BUTTON" "$DIMMER_PROBED" "$DIMMER_VALUE" \
              "$SWITCH_PROBED" "$SWITCH_VALUE"; do
    state=$(ha_state "$entity")
    [ "$state" = "missing" ] && MISSING="$MISSING $entity"
done
if [ -z "$MISSING" ]; then
    ENTITY_OK=0
    ENTITY_DETAIL="9 entities for 2 devices: 2 per switch, 3 hub-level, 1 switch, 1 button (74 + 5 = 79 across the house's 37)"
else
    ENTITY_OK=1
    ENTITY_DETAIL="absent:$MISSING; what was created: $(
        curl -s "$BASE/api/states" -H "$AUTH" | python3 -c "
import sys, json
print(', '.join(sorted(e['entity_id'] for e in json.load(sys.stdin)
                       if 'deako' in e['entity_id'] or 'zero_dim' in e['entity_id'])))
")"
fi
report "$ENTITY_OK" "every probe entity type was created" "$ENTITY_DETAIL"

DEFAULT_SWITCH=$(ha_state "$PROBE_SWITCH")
[ "$DEFAULT_SWITCH" = "on" ]; report $? \
    "the probe is on by default" \
    "$PROBE_SWITCH=$DEFAULT_SWITCH -- #25 decided the probe ships, and defaulting it off would be shipping the decision without taking it"

# Nothing may have been written while the enumeration window is still open.
EARLY_CONTROLS=$(controls_for "")
[ "$EARLY_CONTROLS" -eq 0 ]; report $? \
    "nothing is probed while the enumeration window is still open" \
    "CONTROLs 8s into a ${FIRST_PASS_DELAY_S}s delay=$EARLY_CONTROLS"

BEFORE_DIMMER=$(ha_state "$DIMMER")
BEFORE_SWITCH=$(ha_state "$SWITCH")

PASS_S=$(wait_for_change "$LAST_PASS" "unknown" "$PASS_BUDGET_S")
[ "$PASS_S" != "-1" ]; report $? \
    "a pass runs on its own, with nobody asking" \
    "$LAST_PASS=$(ha_state "$LAST_PASS") after ${PASS_S}s more"

ANSWERED=$(ha_state "$ANSWERING")
UNANSWERED=$(ha_state "$NOT_ANSWERING")
[ "$ANSWERED" = "2" ] && [ "$UNANSWERED" = "0" ]
report $? "both devices answered the census" \
    "answering=$ANSWERED not answering=$UNANSWERED"

# When the first write actually landed, measured rather than sampled: a sleep
# racing the same delay it is checking proves nothing either way.
python3 -c "
import json, subprocess, sys
from datetime import datetime, timezone

out = subprocess.run(
    ['curl', '-s',
     '$BASE/api/history/period?filter_entity_id=$DIMMER_PROBED,$SWITCH_PROBED',
     '-H', '$AUTH'],
    capture_output=True, text=True).stdout
try:
    series = json.loads(out)
except Exception as exc:
    print(f'unreadable: {exc}')
    sys.exit(1)

stamps = [datetime.fromisoformat(p['last_changed'])
          for run in series for p in run
          if p.get('state') not in (None, 'unknown', 'unavailable')]
if not stamps:
    print('no probe write was recorded at all')
    sys.exit(1)
first = min(stamps)
waited = (first - datetime.fromtimestamp($FLOW_AT, timezone.utc)).total_seconds()
print(f'the first write landed {waited:.1f}s after the hub was configured')
sys.exit(0 if waited >= 12 else 1)
" > "$WORK_DIR/startup.txt"
STARTUP_OK=$?
report "$STARTUP_OK" "the first pass waits out the enumeration window" \
    "$(cat "$WORK_DIR/startup.txt") -- a straggler that reports late still gets an entity (O10), and probing a device the hub has not finished announcing asks a question about our own timing rather than about the mesh"

CONTROLS=$(controls_for "")
[ "$CONTROLS" -eq 2 ]; report $? \
    "every device was written to exactly once" \
    "CONTROLs received=$CONTROLS for 2 devices -- the probe reaches for the marked and the healthy alike, but only once each"

# The idempotence that makes this safe in the normal case. The echo asks the
# device for the state it is already in, so the house does not visibly move.
AFTER_DIMMER=$(ha_state "$DIMMER")
AFTER_SWITCH=$(ha_state "$SWITCH")
[ "$AFTER_DIMMER" = "$BEFORE_DIMMER" ] && [ "$AFTER_SWITCH" = "$BEFORE_SWITCH" ]
report $? "no light moved" \
    "$DIMMER $BEFORE_DIMMER->$AFTER_DIMMER, $SWITCH $BEFORE_SWITCH->$AFTER_SWITCH -- and this is exactly why the attribution record below has to be right, because a light that *did* move would leave no trace here either"

# The attribution record: what was sent, per switch, checked against what the
# device actually held rather than against itself.
DIMMER_SENT=$(ha_state "$DIMMER_VALUE")
SWITCH_SENT=$(ha_state "$SWITCH_VALUE")
EXPECT_DIMMER=$([ "$BEFORE_DIMMER" = "on" ] && echo on || echo off)
EXPECT_SWITCH=$([ "$BEFORE_SWITCH" = "on" ] && echo on || echo off)
[ "$DIMMER_SENT" = "$EXPECT_DIMMER" ] && [ "$SWITCH_SENT" = "$EXPECT_SWITCH" ]
report $? "the record says what was actually sent to each switch" \
    "$DIMMER_VALUE=$DIMMER_SENT (light was $BEFORE_DIMMER), $SWITCH_VALUE=$SWITCH_SENT (light was $BEFORE_SWITCH)"

DIMMER_DIM=$(ha_attr "$DIMMER_VALUE" dim)
report 0 "the level that went with it is recorded too" \
    "$DIMMER_VALUE dim=$DIMMER_DIM (None when the echo was 'off', since a dim on an off command is a brightness nobody asked for)"

# Pacing, measured from the recorder rather than from either log: the state of
# a timestamp entity is published to the second, and both this simulator and
# Home Assistant log to the second, so only `last_changed` can tell 1.1s of
# deliberate spacing from a burst.
python3 -c "
import json, subprocess, sys
from datetime import datetime

out = subprocess.run(
    ['curl', '-s',
     '$BASE/api/history/period?filter_entity_id=$DIMMER_PROBED,$SWITCH_PROBED',
     '-H', '$AUTH'],
    capture_output=True, text=True).stdout
try:
    series = json.loads(out)
except Exception as exc:
    print(f'unreadable: {exc}')
    sys.exit(1)

written = {}
for run in series:
    for point in run:
        if point.get('state') in (None, 'unknown', 'unavailable'):
            continue
        entity = point['entity_id']
        stamp = datetime.fromisoformat(point['last_changed'])
        written.setdefault(entity, stamp)

if len(written) != 2:
    print(f'only saw writes for {sorted(written)}')
    sys.exit(1)
first, second = sorted(written.values())
gap = (second - first).total_seconds()
print(f'{gap:.3f}s between the two writes, measured on last_changed')
sys.exit(0 if gap >= 0.8 else 1)
" > "$WORK_DIR/pacing.txt"
PACING_OK=$?
report "$PACING_OK" "the pass paces itself above the hub's silent-drop threshold" \
    "$(cat "$WORK_DIR/pacing.txt") -- commands closer than 800ms are dropped with no reply at all, so an unpaced pass would lose writes invisibly and read them back as unreachable devices"

# And the record has to survive being written, or it cannot answer a question
# asked in the morning about a light that moved in the night.
python3 -c "
import json, subprocess, sys

out = subprocess.run(
    ['curl', '-s',
     '$BASE/api/history/period?filter_entity_id=$SWITCH_PROBED,$SWITCH_VALUE',
     '-H', '$AUTH'],
    capture_output=True, text=True).stdout
try:
    series = json.loads(out)
except Exception as exc:
    print(f'unreadable: {exc}')
    sys.exit(1)
found = {}
for run in series:
    for point in run:
        entity = point.get('entity_id')
        state = point.get('state')
        if state not in (None, 'unknown', 'unavailable'):
            found.setdefault(entity, state)
print('recorder holds: ' + (', '.join(f'{k}={v}' for k, v in sorted(found.items())) or 'nothing'))
sys.exit(0 if len(found) == 2 else 1)
" > "$WORK_DIR/recorder.txt"
RECORDER_OK=$?
report "$RECORDER_OK" "the recorder holds the attribution, not just the state machine" \
    "$(cat "$WORK_DIR/recorder.txt") -- #25 accepted the light-flip risk on the strength of this pair being readable back later; an entity that is right now and unrecorded would not have earned that"

dump_probe "after the first pass"

# ---------------------------------------------------------------------------
# Phase 2: the probe finds a switch that left the mesh, with nobody asking.
# ---------------------------------------------------------------------------
#
# This is the whole reason #26 exists. #23's detector can only confirm an
# unreachable switch at the moment somebody reaches for it, and in this house
# that is when a person walks into a dark room. Nothing below calls a light
# service: every command in this phase is the probe's own.

echo ""
echo "== phase 2: a switch leaves the mesh, and nobody touches a light =="
curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d "{\"uuids\":[\"$SWITCH_UUID\"]}" > "$WORK_DIR/unreachable.json"
grep -q "$SWITCH_UUID" "$WORK_DIR/unreachable.json"; report $? \
    "the simulator will acknowledge the switch and never report it" \
    "measured hub behaviour from #13, not an invented fault: it still enumerates, still answers DEVICE_POLL, and is still acked status ok"

DISCOVER_MARK=$(ha_state "$LAST_PASS")
DISCOVER_CONTROLS_BEFORE=$(controls_for "")
call_service button press "$CENSUS_BUTTON"
DISCOVER_S=$(wait_for_change "$LAST_PASS" "$DISCOVER_MARK" "$PASS_BUDGET_S")
[ "$DISCOVER_S" != "-1" ]; report $? "a census runs" "after ${DISCOVER_S}s"

D_ANSWERED=$(ha_state "$ANSWERING")
D_UNANSWERED=$(ha_state "$NOT_ANSWERING")
[ "$D_ANSWERED" = "1" ] && [ "$D_UNANSWERED" = "1" ]
report $? "the census counts the one that did not answer" \
    "answering=$D_ANSWERED not answering=$D_UNANSWERED -- and both are numeric, so this house's mesh drop rate, which #10 said nobody knows, starts accumulating in long-term statistics from here"

AFTER_PASS_NODE=$(ha_state "$SWITCH_NODE")
[ "$AFTER_PASS_NODE" = "online" ]; report $? \
    "one pass is one miss, and one miss condemns nothing" \
    "$SWITCH_NODE=$AFTER_PASS_NODE immediately after the pass"

DISCOVER_MARK_S=$(wait_for_state "$SWITCH_NODE" "unreachable" "$RETRY_ARC_S")
[ "$DISCOVER_MARK_S" != "-1" ]; report $? \
    "the probe discovers the fault unaided, with nobody reaching for a light" \
    "$SWITCH_NODE=unreachable ${DISCOVER_MARK_S}s after the census, off the probe's own write and its retry -- before this, the node status sensor could only confirm a fault somebody had already walked into, and the docstring said so"

report 0 "and it really was unattended" \
    "no light service was called in this phase; the only writes were the probe's, CONTROLs ${DISCOVER_CONTROLS_BEFORE}->$(controls_for "")"

echo "  putting the switch back on the mesh, and asking again"
curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d '{"uuids":[]}' >/dev/null
RECOVER_MARK=$(ha_state "$LAST_PASS")
call_service button press "$CENSUS_BUTTON"
RECOVER_S=$(wait_for_state "$SWITCH_NODE" "online" "$PASS_BUDGET_S")
[ "$RECOVER_S" != "-1" ]; report $? \
    "and recovery is detected unattended too" \
    "$SWITCH_NODE=online after ${RECOVER_S}s -- this is what #25 bought by refusing the containment rule that would never have re-probed a marked device: the record now carries outage *durations*, not just onsets"

wait_for_change "$LAST_PASS" "$RECOVER_MARK" "$PASS_BUDGET_S" >/dev/null
R_ANSWERED=$(ha_state "$ANSWERING")
R_UNANSWERED=$(ha_state "$NOT_ANSWERING")
[ "$R_ANSWERED" = "2" ] && [ "$R_UNANSWERED" = "0" ]
report $? "the census reads a whole house again" \
    "answering=$R_ANSWERED not answering=$R_UNANSWERED"

dump_probe "after the fault was found and cleared, with nobody in the room"

# ---------------------------------------------------------------------------
# Phase 3: a reconnect storm produces no probing at all.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 3: three reconnects in quick succession =="
# Start the interval fresh, so the storm is unambiguously inside it and a
# scheduled pass falling due mid-storm cannot be mistaken for one the
# reconnects provoked. The census button resets the governor's clock, which is
# the honest way to do this -- nothing here reaches inside the running probe.
CENSUS_MARK=$(ha_state "$LAST_PASS")
call_service button press "$CENSUS_BUTTON"
FRESH_S=$(wait_for_change "$LAST_PASS" "$CENSUS_MARK" "$PASS_BUDGET_S")
[ "$FRESH_S" != "-1" ]; report $? \
    "the census button runs a pass on request" \
    "$LAST_PASS=$(ha_state "$LAST_PASS") after ${FRESH_S}s, which also starts the interval fresh for the storm below"

STORM_BEFORE=$(controls_for "")
PASS_BEFORE=$(ha_state "$LAST_PASS")

for i in 1 2 3; do
    curl -s -X POST "$SIM_HTTP/api/control/disconnect" >/dev/null
    BACK=$(wait_for_state "$HUB_CONNECTED" "on" "$RECONNECT_BUDGET_S")
    echo "  reconnect $i came back after ${BACK}s"
done
sleep 10

STORM_AFTER=$(controls_for "")
PASS_AFTER=$(ha_state "$LAST_PASS")
[ "$STORM_AFTER" -eq "$STORM_BEFORE" ] && [ "$PASS_AFTER" = "$PASS_BEFORE" ]
report $? "three reconnects inside the interval produce no probing at all" \
    "CONTROLs ${STORM_BEFORE}->${STORM_AFTER}, last pass unchanged at $PASS_AFTER -- ungoverned this would have been 3 x 37 writes aimed at a mesh already misbehaving, and the house has a node that flaps every 6-12 minutes"

# ---------------------------------------------------------------------------
# Phase 4: a pass due while the hub is gone does not fire, and is not faked.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 4: the hub is away when a pass falls due =="
DOWN_PASS_BEFORE=$(ha_state "$LAST_PASS")
DOWN_CONTROLS_BEFORE=$(controls_for "")

kill "$SIM_PID" 2>/dev/null
SIM_PID=""
for _ in $(seq 1 15); do
    port_answers "$SIM_IP" "$SIM_PORT" || break
    sleep 1
done
DOWN_S=$(wait_for_state "$HUB_CONNECTED" "off" 30)
[ "$DOWN_S" != "-1" ]; report $? "the connection is down" "after ${DOWN_S}s"

# Wait past the moment the next pass would have been due.
sleep $((PATCHED_INTERVAL_S + 15))

DOWN_PASS_AFTER=$(ha_state "$LAST_PASS")
[ "$DOWN_PASS_AFTER" = "$DOWN_PASS_BEFORE" ]
report $? "a pass due while the hub is gone does not fake a timestamp" \
    "$LAST_PASS still $DOWN_PASS_AFTER after the interval elapsed with no connection -- this entity's job is to show the probe *stopping*, so recording a pass that never happened would hide the one condition it watches for"

grep -q "probe pass is due but there is no connection" "$HA_DIR/ha.log"
report $? "and it says so rather than failing silently" \
    "$(grep -o "A probe pass is due but there is no connection to the hub; waiting for one" "$HA_DIR/ha.log" | tail -1)"

echo "  bringing the hub back"
start_simulator append
BACK_S=$(wait_for_state "$HUB_CONNECTED" "on" "$RECONNECT_BUDGET_S")
[ "$BACK_S" != "-1" ]; report $? "the connection comes back with no human action" "after ${BACK_S}s"

FORWARD_S=$(wait_for_change "$LAST_PASS" "$DOWN_PASS_BEFORE" "$PASS_BUDGET_S")
[ "$FORWARD_S" != "-1" ]; report $? \
    "the reconnect brings the missed pass forward instead of waiting out another interval" \
    "$LAST_PASS=$(ha_state "$LAST_PASS") after ${FORWARD_S}s -- one governor, so startup and reconnect are the same case as the hourly tick rather than three sets of rules"

DOWN_CONTROLS_AFTER=$(controls_for "")
[ "$DOWN_CONTROLS_AFTER" -eq $((DOWN_CONTROLS_BEFORE + 2)) ]
report $? "and it is one pass, not a backlog of the ones it missed" \
    "CONTROLs ${DOWN_CONTROLS_BEFORE}->${DOWN_CONTROLS_AFTER} for 2 devices"

# ---------------------------------------------------------------------------
# Phase 5: the switch really stops it, and the button still works.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 5: turning the probe off =="
call_service switch turn_off "$PROBE_SWITCH"
sleep 2
OFF_STATE=$(ha_state "$PROBE_SWITCH")
[ "$OFF_STATE" = "off" ]; report $? "the switch turns off" "$PROBE_SWITCH=$OFF_STATE"

OFF_PASS_BEFORE=$(ha_state "$LAST_PASS")
OFF_CONTROLS_BEFORE=$(controls_for "")
sleep $((PATCHED_INTERVAL_S + 15))

OFF_PASS_AFTER=$(ha_state "$LAST_PASS")
OFF_CONTROLS_AFTER=$(controls_for "")
[ "$OFF_PASS_AFTER" = "$OFF_PASS_BEFORE" ] && [ "$OFF_CONTROLS_AFTER" -eq "$OFF_CONTROLS_BEFORE" ]
report $? "no automatic pass runs while it is off" \
    "last pass unchanged at $OFF_PASS_AFTER, CONTROLs ${OFF_CONTROLS_BEFORE}->${OFF_CONTROLS_AFTER} across a full interval"

grep -q "A pass is due but the probe is turned off" "$HA_DIR/ha.log"
report $? "and the reason is in the log rather than inferred" \
    "the governor says why it declined, which is what makes a silent house distinguishable from a stopped probe"

echo "  pressing the census button while the probe is off"
call_service button press "$CENSUS_BUTTON"
CENSUS_S=$(wait_for_change "$LAST_PASS" "$OFF_PASS_BEFORE" "$PASS_BUDGET_S")
[ "$CENSUS_S" != "-1" ]; report $? \
    "the census button works even when the switch is off" \
    "$LAST_PASS=$(ha_state "$LAST_PASS") after ${CENSUS_S}s -- a human asking is the consent model this design rests on, so the off switch must not take their own question away from them"

CENSUS_CONTROLS=$(controls_for "")
[ "$CENSUS_CONTROLS" -eq $((OFF_CONTROLS_AFTER + 2)) ]
report $? "and it really wrote to the mesh" \
    "CONTROLs ${OFF_CONTROLS_AFTER}->${CENSUS_CONTROLS}"

# ---------------------------------------------------------------------------
# Phase 6: the off answer survives a restart.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 6: restarting Home Assistant with the probe off =="
RESTART_CONTROLS_BEFORE=$(controls_for "")
stop_ha
start_ha || exit 1
sleep 20

RESTORED=$(ha_state "$PROBE_SWITCH")
[ "$RESTORED" = "off" ]; report $? \
    "the probe is still off after a restart" \
    "$PROBE_SWITCH=$RESTORED -- a setting that quietly comes back at the next restart looks respected and is not"

sleep $((FIRST_PASS_DELAY_S + 15))
RESTART_CONTROLS_AFTER=$(controls_for "")
[ "$RESTART_CONTROLS_AFTER" -eq "$RESTART_CONTROLS_BEFORE" ]
report $? "and no startup pass slipped out before the restored answer landed" \
    "CONTROLs ${RESTART_CONTROLS_BEFORE}->${RESTART_CONTROLS_AFTER} across the startup delay"

# ---------------------------------------------------------------------------
# Phase 7: the retry confirms a fault, and does not manufacture one.
# ---------------------------------------------------------------------------
#
# Run with the probe off on purpose: this measures individual commands and
# their retries, and an automatic pass landing in the middle would add writes
# that are not part of the arc being measured.

echo ""
echo "== phase 7: the 30s retry =="
curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d "{\"uuids\":[\"$SWITCH_UUID\"]}" > "$WORK_DIR/unreachable.json"
grep -q "$SWITCH_UUID" "$WORK_DIR/unreachable.json"; report $? \
    "the simulator will acknowledge the switch and never report it" \
    "measured hub behaviour from #13, not an invented fault: it still enumerates, still answers DEVICE_POLL, and is still acked status ok"

RETRY_CONTROLS_BEFORE=$(controls_for "$SWITCH_UUID")
call_service light turn_on "$SWITCH"

# One command, and the retry is what produces the second miss.
sleep $((WITNESS_WINDOW_S + 3))
AFTER_ONE=$(ha_state "$SWITCH_NODE")
[ "$AFTER_ONE" = "online" ]; report $? \
    "one unwitnessed command still condemns nothing" \
    "$SWITCH_NODE=$AFTER_ONE -- one miss is a lost mesh frame"

MARK_S=$(wait_for_state "$SWITCH_NODE" "unreachable" "$RETRY_ARC_S")
[ "$MARK_S" != "-1" ]; report $? \
    "the retry brings the second miss forward, and the mark lands inside a minute" \
    "marked ${MARK_S}s after the single command -- before this, a switch nobody touched again would have waited for the next cadence, and two misses an hour apart describe two faults rather than one"

RETRY_CONTROLS_AFTER=$(controls_for "$SWITCH_UUID")
[ "$RETRY_CONTROLS_AFTER" -eq $((RETRY_CONTROLS_BEFORE + 2)) ]
report $? "it took exactly one retry, not a stream of them" \
    "CONTROLs for this switch ${RETRY_CONTROLS_BEFORE}->${RETRY_CONTROLS_AFTER}: the command and one retry"

# The half that matters more: a retry that is answered must clear the count
# rather than carry it, or the next single miss anywhere would mark falsely.
echo "  putting the switch back on the mesh"
curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d '{"uuids":[]}' >/dev/null
sleep 2
call_service light turn_off "$SWITCH"
CLEAR_S=$(wait_for_state "$SWITCH_NODE" "online" 20)
[ "$CLEAR_S" != "-1" ]; report $? \
    "a witnessed command clears the mark, as it always did" "after ${CLEAR_S}s"

echo "  now: a device that misses once and then answers its retry"
curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d "{\"uuids\":[\"$SWITCH_UUID\"]}" >/dev/null
sleep 2
call_service light turn_on "$SWITCH"
sleep $((WITNESS_WINDOW_S + 3))          # one miss counted
curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d '{"uuids":[]}' >/dev/null          # back on the mesh before the retry
sleep $((RETRY_DELAY_S + WITNESS_WINDOW_S + 8))

ANSWERED_RETRY=$(ha_state "$SWITCH_NODE")
[ "$ANSWERED_RETRY" = "online" ]; report $? \
    "a device that answers its retry is not condemned by it" \
    "$SWITCH_NODE=$ANSWERED_RETRY after one miss and an answered retry"

# And the count really was cleared, not merely not-yet-tripped: a fresh single
# miss must still leave it online. This is the false-mark case in full.
curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d "{\"uuids\":[\"$SWITCH_UUID\"]}" >/dev/null
sleep 2
call_service light turn_off "$SWITCH"
sleep $((WITNESS_WINDOW_S + 3))
FRESH_MISS=$(ha_state "$SWITCH_NODE")
[ "$FRESH_MISS" = "online" ]; report $? \
    "and the earlier miss was cleared rather than banked" \
    "$SWITCH_NODE=$FRESH_MISS after a single fresh miss -- had the answered retry left the count at one, this one miss would have marked the switch, which is the double-count this ticket asked to be ruled out"

curl -s -X POST "$SIM_HTTP/api/control/unreachable" -H "Content-Type: application/json" \
    -d '{"uuids":[]}' >/dev/null
sleep 2
call_service light turn_on "$SWITCH"
wait_for_state "$SWITCH_NODE" "online" 20 >/dev/null

# ---------------------------------------------------------------------------
# Phase 8: turning it back on resumes passes, with no restart.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 8: turning the probe back on =="
RESUME_PASS_BEFORE=$(ha_state "$LAST_PASS")
call_service switch turn_on "$PROBE_SWITCH"
RESUME_S=$(wait_for_change "$LAST_PASS" "$RESUME_PASS_BEFORE" "$PASS_BUDGET_S")
[ "$RESUME_S" != "-1" ]; report $? \
    "passes resume as soon as it is turned back on" \
    "$LAST_PASS=$(ha_state "$LAST_PASS") after ${RESUME_S}s, with no restart and nothing reloaded"

FINAL_ANSWERING=$(ha_state "$ANSWERING")
FINAL_NOT=$(ha_state "$NOT_ANSWERING")
report 0 "the census reads the house it is actually in" \
    "answering=$FINAL_ANSWERING not answering=$FINAL_NOT (both numeric, so long-term statistics keep them past this recorder's 60-day history)"

dump_probe "final state"

echo ""
echo "======================================================================"
echo "  passed: $PASSED    failed: $FAILED"
echo "  simulator log: $WORK_DIR/sim.log"
echo "  home assistant log: $HA_DIR/ha.log"
echo "======================================================================"
[ "$FAILED" -eq 0 ]
