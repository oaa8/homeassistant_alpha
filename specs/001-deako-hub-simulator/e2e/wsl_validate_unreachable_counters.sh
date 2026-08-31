#!/usr/bin/env bash
# End-to-end proof for wayfinder #45: the rebuilt counters, and the instrument
# that measures what clears an unreachable mark, in a real Home Assistant
# against the simulator.
#
# #43 found that the mark and the probe counters are two computations that
# never read each other, and that the probe's skip rule let them contradict
# each other in the UI. At one measured `22:47:18` pass in the house, 15 of 37
# devices were skipped and counted as answering -- and one of the 15 was a
# switch simultaneously marked `unreachable`. That is what this run has to show
# cannot happen any more, plus the three instruments #43 asked for.
#
# Four claims, which are #45's verification bar verbatim:
#
#   1. A pass writes to **every** device, and answering + not answering equals
#      the number written to. The regression is specific: a device the passive
#      detector has just heard from is exactly what the old rule skipped, so
#      this phase presses a wall button first and then counts the wire.
#   2. The new hub count agrees with the per-switch sensors at a moment when at
#      least one switch is marked. It is the same set, counted -- so agreement
#      is by construction and a disagreement would mean the count is reading
#      something else.
#   3. The per-switch outcome distinguishes a device that answered from one
#      that did not, **in the same pass**. Before this, a hub reading of "1 did
#      not answer" against 37 switches did not say which one, which #44 named
#      as part of why attributing a light that moved took a week.
#   4. The asymmetry instrument fires on a marked switch and records an outcome
#      **without altering when the mark clears**, and without feeding the
#      detector it is measuring.
#
# Phase 4 runs both readings of #43's open question, because a measurement that
# can only produce one answer is not a measurement:
#
#   * the **asymmetric** specimen -- the switch reports but cannot obey, which
#     is composed here from two primitives the simulator already has (a device
#     modelled off the mesh, plus an EVENT injected through the state endpoint).
#     It is a fixture for the instrument, and emphatically **not** a claim that
#     the house behaves this way: asymmetry has never been observed, which is
#     the entire reason #45 measures it rather than defending against it.
#   * the **intermittent** specimen -- it reports, and it also obeys.
#
# ONE CONSTANT IS SHORTENED, AND ONLY ONE, and it is not the one the last run
# shortened. PROBE_INTERVAL_S is *lengthened* in the deployed copy, so that the
# hourly tick cannot fire in the middle of a phase and re-mark a switch the
# phase just cleared; every pass below is asked for by the census button.
# Phase 0 asserts what the shipped source says. Everything else -- the 15s
# startup delay, the 1.1s pacing, the 5s witness window, the 30s retry, the
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
#   bash specs/001-deako-hub-simulator/e2e/wsl_validate_unreachable_counters.sh

set -uo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/../../.." && pwd)"
# shellcheck source=specs/001-deako-hub-simulator/e2e/lib_port_guard.sh
. "$E2E_DIR/lib_port_guard.sh"

HA_DIR="$HOME/ha-test-latest"
VENV="$HOME/ha-venv-latest"
WORK_DIR="${COUNTERS_WORK_DIR:-$HOME/counters-ha}"
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

HUB_CONNECTED="binary_sensor.deako_hub_connected"
DIMMER_NODE="sensor.zero_dim_test_dimmer_node_status"
SWITCH_NODE="sensor.zero_dim_test_switch_node_status"
LAST_PASS="sensor.deako_hub_last_probe_pass"
ANSWERING="sensor.deako_hub_devices_answering_last_probe"
NOT_ANSWERING="sensor.deako_hub_devices_not_answering_last_probe"
CENSUS_BUTTON="button.deako_hub_run_census_now"
DIMMER_PROBED="sensor.zero_dim_test_dimmer_last_probed"
SWITCH_PROBED="sensor.zero_dim_test_switch_last_probed"

# The three entities #45 adds.
MARKED="sensor.deako_hub_switches_marked_unreachable"
ASYMMETRY="sensor.deako_hub_asymmetry_probes"
DIMMER_OUTCOME="sensor.zero_dim_test_dimmer_last_probe_outcome"
SWITCH_OUTCOME="sensor.zero_dim_test_switch_last_probe_outcome"

# Production values, from custom_components/deako/probe.py and
# custom_components/deako/pydeako/deako/_deako.py. Asserted in phase 0.
SHIPPED_INTERVAL_S=3600
FIRST_PASS_DELAY_S=15
WITNESS_WINDOW_S=5
RETRY_DELAY_S=30

# The one changed constant, and it is changed the safe way -- longer, so that
# nothing fires unasked.
PATCHED_INTERVAL_S=1800

PASS_BUDGET_S=40
# The mark's whole arc off one census: write, miss at 5s, retry at 35s, second
# miss at 40s.
MARK_ARC_S=70
# Long enough to cover a witness window and a retry, which is how long it would
# take the measurement to re-mark a switch if it were feeding the detector.
NO_REMARK_WATCH_S=45

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
# Phase 0: say out loud what ships, and that the convicted rule is gone.
# ---------------------------------------------------------------------------

echo "== phase 0: the constants that ship, and the rule that does not =="
PROBE_SRC="$REPO_ROOT/custom_components/deako/probe.py"
DEAKO_SRC="$REPO_ROOT/custom_components/deako/pydeako/deako/_deako.py"

# The repo is checked out with CRLF line endings on the Windows side, so an
# anchored `grep "...$"` against the source silently never matches and every
# constant below reports FAIL while shipping exactly the right number. A check
# that cannot pass is worse than no check, so the CR is stripped first --
# deploy_integration already does the same to the deployed copy.
#
# Process substitution rather than a pipe, and that is not a style choice: this
# script runs under `set -o pipefail`, and `grep -q` closes its input the
# instant it matches, so `tr | grep -q` kills tr with SIGPIPE and the pipeline
# reports 141 *because* the pattern was found. Every check here would then fail
# on success, which is the exact failure mode the comment above is about.
src_grep() { # src_grep <file> <pattern>
    grep -q "$2" <(tr -d '\r' < "$1")
}

src_grep "$PROBE_SRC" "^PROBE_INTERVAL_S = $SHIPPED_INTERVAL_S\$"
report $? "the shipped cadence is still hourly" \
    "PROBE_INTERVAL_S=$SHIPPED_INTERVAL_S in probe.py; this run lengthens the deployed copy to ${PATCHED_INTERVAL_S}s so no pass fires unasked, and changes nothing else"

! src_grep "$PROBE_SRC" "_cycle_end"
report $? "the skip rule's clock is gone from the source" \
    "no _cycle_end in probe.py -- #43 convicted the rule it served, and it existed only to serve it"

sed -n '/async def _attempt_pass/,/async def _probe_device/p' "$PROBE_SRC" \
    > "$WORK_DIR/attempt_pass.py"
! grep -q "get_last_witness" "$WORK_DIR/attempt_pass.py"
report $? "the pass asks no question before writing" \
    "_attempt_pass() no longer consults get_last_witness; every device is written to, every pass"

src_grep "$PROBE_SRC" "self._witnessed = len(answered)\$"
report $? "the pair counts the writes it made, and nothing else" \
    "witnessed = len(answered), not len(skipped) + len(answered) -- which is what put a switch marked unreachable inside '35 answering'"

src_grep "$DEAKO_SRC" "^RETRY_DELAY_S = $RETRY_DELAY_S\$"
report $? "the second miss is still brought forward by a single retry" \
    "RETRY_DELAY_S=${RETRY_DELAY_S}s"

src_grep "$DEAKO_SRC" "^MISSES_TO_UNREACHABLE = 2\$"
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
    local n
    n=$(grep -c "^READY" "$WORK_DIR/sim.log" 2>/dev/null)
    echo "${n:-0}"
}

start_simulator() {
    if [ ! -x "$WORK_DIR/venvsim/bin/python" ]; then
        python3 -m venv "$WORK_DIR/venvsim"
    fi
    "$WORK_DIR/venvsim/bin/pip" -q install aiohttp zeroconf jsonschema
    cd "$REPO_ROOT"
    : > "$WORK_DIR/sim.log"
    "$WORK_DIR/venvsim/bin/python" "$E2E_DIR/zero_dim_sim_runner.py" \
        --port "$SIM_PORT" --http-port "$SIM_HTTP_PORT" > "$WORK_DIR/sim.log" 2>&1 &
    SIM_PID=$!
    for _ in $(seq 1 30); do
        [ "$(ready_count)" -ge 1 ] && break
        sleep 1
    done
    [ "$(ready_count)" -ge 1 ] || {
        echo "simulator failed to start"; tail -20 "$WORK_DIR/sim.log"; exit 1; }
}

deploy_integration() {
    mkdir -p "$HA_DIR/custom_components"
    rm -rf "$HA_DIR/custom_components/deako"
    cp -r "$REPO_ROOT/custom_components/deako" "$HA_DIR/custom_components/deako"
    rm -rf "$HA_DIR/custom_components/deako/__pycache__"
    find "$HA_DIR/custom_components/deako" -name '*.py' -exec sed -i 's/\r$//' {} \;
    sed -i "s/^PROBE_INTERVAL_S = .*/PROBE_INTERVAL_S = $PATCHED_INTERVAL_S/" \
        "$HA_DIR/custom_components/deako/probe.py"
    grep -q "^PROBE_INTERVAL_S = $PATCHED_INTERVAL_S\$" \
        "$HA_DIR/custom_components/deako/probe.py" || {
        echo "could not lengthen the probe interval in the deployed copy"; exit 1; }
    # Deliberately not default_config: with WSL mirrored networking it pulls in
    # broad LAN discovery against the real house (#15).
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
    # Anything answering on 8123 is someone else's Home Assistant. Testing
    # against it silently invalidated a whole run in wayfinder #15.
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

# How many node status sensors read `unreachable` right now. The hub count is
# supposed to equal this by construction -- it is the same set, counted -- so
# this is read from Home Assistant's own states rather than from the client.
marked_nodes() {
    curl -s "$BASE/api/states" -H "$AUTH" | python3 -c "
import sys, json
rows = [e for e in json.load(sys.stdin)
        if e['entity_id'].endswith('_node_status') and e['state'] == 'unreachable']
print(len(rows))
"
}

call_service() { # call_service <domain> <service> <entity_id>
    curl -s -o "$WORK_DIR/svc.json" -X POST "$BASE/api/services/$1/$2" -H "$AUTH" \
        -H "Content-Type: application/json" -d "{\"entity_id\":\"$3\"}" >/dev/null
}

wait_for_state() { # wait_for_state <entity_id> <wanted> <budget_s> -> seconds, or -1
    local entity="$1" wanted="$2" budget="$3" i
    for i in $(seq 0 "$budget"); do
        [ "$(ha_state "$entity")" = "$wanted" ] && { echo "$i"; return 0; }
        sleep 1
    done
    echo "-1"
    return 1
}

wait_for_change() { # wait_for_change <entity_id> <old> <budget_s> -> seconds, or -1
    local entity="$1" old="$2" budget="$3" i now
    for i in $(seq 0 "$budget"); do
        now=$(ha_state "$entity")
        [ "$now" != "$old" ] && [ "$now" != "unreadable" ] && { echo "$i"; return 0; }
        sleep 1
    done
    echo "-1"
    return 1
}

# CONTROLs the simulator has actually received, which is the only honest count.
controls_for() { # controls_for <uuid|"">
    local n
    if [ -z "${1:-}" ]; then
        n=$(grep -c "\[RECV\].*\"type\": \"CONTROL\"" "$WORK_DIR/sim.log" 2>/dev/null)
    else
        n=$(grep -c "\[RECV\].*\"type\": \"CONTROL\".*$1" "$WORK_DIR/sim.log" 2>/dev/null)
    fi
    echo "${n:-0}"
}

run_census() { # run_census -> 0 if a pass concluded
    local before after
    before=$(ha_state "$LAST_PASS")
    call_service button press "$CENSUS_BUTTON"
    after=$(wait_for_change "$LAST_PASS" "$before" "$PASS_BUDGET_S")
    [ "$after" != "-1" ]
}

# Set which devices the simulator models as registered but off the mesh.
set_unreachable() { # set_unreachable <uuid|"">
    if [ -z "${1:-}" ]; then
        curl -s -X POST "$SIM_HTTP/api/control/unreachable" \
            -H "Content-Type: application/json" -d '{"uuids":[]}' >/dev/null
    else
        curl -s -X POST "$SIM_HTTP/api/control/unreachable" \
            -H "Content-Type: application/json" -d "{\"uuids\":[\"$1\"]}" >/dev/null
    fi
}

dump_counters() { # dump_counters <heading>
    echo ""
    echo "  --- $1 ---"
    curl -s "$BASE/api/states" -H "$AUTH" | python3 -c "
import sys, json
rows = [e for e in json.load(sys.stdin)
        if ('probe' in e['entity_id'] or 'asymmetry' in e['entity_id']
            or 'unreachable' in e['entity_id'] or 'node_status' in e['entity_id']
            or e['entity_id'].startswith('light.zero'))]
for e in sorted(rows, key=lambda r: r['entity_id']):
    extra = {k: v for k, v in e['attributes'].items()
             if k in ('dim', 'witnessed', 'unwitnessed', 'unreachable_uuids')}
    print(f\"  {e['entity_id']:58} {str(e['state']):26} {extra if extra else ''}\")
"
    echo ""
}

# ---------------------------------------------------------------------------
# Phase 1: every device is written to, every pass.
# ---------------------------------------------------------------------------

echo ""
echo "== starting the simulator on loopback, no mDNS =="
start_simulator

echo ""
echo "== phase 1: a pass writes to every device =="
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
sleep 8

MISSING=""
for entity in "$MARKED" "$ASYMMETRY" "$DIMMER_OUTCOME" "$SWITCH_OUTCOME"; do
    state=$(ha_state "$entity")
    [ "$state" = "missing" ] && MISSING="$MISSING $entity"
done
[ -z "$MISSING" ]; report $? "the three new entity types were created" \
    "${MISSING:-$MARKED, $ASYMMETRY, and one outcome sensor per switch}"

START_MARKED=$(ha_state "$MARKED")
[ "$START_MARKED" = "0" ]; report $? \
    "nothing is marked at startup, and it says 0 rather than unknown" \
    "$MARKED=$START_MARKED -- the mark lives in memory and is genuinely gone after a restart, so restoring a count of marks that no longer exist would be an invention"

FIRST_PASS_S=$(wait_for_change "$LAST_PASS" "unknown" "$PASS_BUDGET_S")
[ "$FIRST_PASS_S" != "-1" ]; report $? \
    "the first pass runs on its own after the enumeration window" \
    "$LAST_PASS=$(ha_state "$LAST_PASS") after ${FIRST_PASS_S}s past the ${FIRST_PASS_DELAY_S}s delay"

# The regression, and it is specific. A device the passive detector has just
# heard from is exactly what the old rule skipped -- and then counted as
# answering. So: press the dimmer's wall button, wait for the EVENT to be
# witnessed, and then count what actually goes on the wire.
echo "  pressing the dimmer's wall button, so the passive detector has just heard from it"
curl -s -X POST "$SIM_HTTP/api/devices/$DIMMER_UUID/button" >/dev/null
sleep 3

SKIP_BEFORE_DIMMER=$(controls_for "$DIMMER_UUID")
SKIP_BEFORE_SWITCH=$(controls_for "$SWITCH_UUID")
run_census
report $? "a census runs" "$LAST_PASS=$(ha_state "$LAST_PASS")"

SKIP_AFTER_DIMMER=$(controls_for "$DIMMER_UUID")
SKIP_AFTER_SWITCH=$(controls_for "$SWITCH_UUID")
DIMMER_WRITES=$((SKIP_AFTER_DIMMER - SKIP_BEFORE_DIMMER))
SWITCH_WRITES=$((SKIP_AFTER_SWITCH - SKIP_BEFORE_SWITCH))
[ "$DIMMER_WRITES" -eq 1 ] && [ "$SWITCH_WRITES" -eq 1 ]
report $? "the just-witnessed device is written to anyway" \
    "CONTROLs this pass: dimmer=$DIMMER_WRITES switch=$SWITCH_WRITES -- the old rule would have written 0 to the dimmer and still counted it as answering, which is exactly what put 15 of 37 devices inside '35 answering' at the house's 22:47:18 pass"

P1_ANSWERING=$(ha_state "$ANSWERING")
P1_NOT=$(ha_state "$NOT_ANSWERING")
P1_TOTAL=$((P1_ANSWERING + P1_NOT))
P1_WRITTEN=$((DIMMER_WRITES + SWITCH_WRITES))
[ "$P1_TOTAL" -eq "$P1_WRITTEN" ] && [ "$P1_ANSWERING" = "2" ] && [ "$P1_NOT" = "0" ]
report $? "the pair equals the number of devices written to" \
    "answering=$P1_ANSWERING + not answering=$P1_NOT = $P1_TOTAL, against $P1_WRITTEN written to -- the entity names now mean what they say"

dump_counters "after a pass over a house where nothing is wrong"

# ---------------------------------------------------------------------------
# Phase 2: the marked count, against the per-switch sensors.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 2: a switch leaves the mesh =="
set_unreachable "$SWITCH_UUID"
echo "  the simulator will now acknowledge the switch and never report it (#13's measured hub behaviour)"

run_census
report $? "a census runs against a house with one switch off the mesh" \
    "$LAST_PASS=$(ha_state "$LAST_PASS")"

P2_ANSWERING=$(ha_state "$ANSWERING")
P2_NOT=$(ha_state "$NOT_ANSWERING")
[ "$P2_ANSWERING" = "1" ] && [ "$P2_NOT" = "1" ]
report $? "the pair counts the one that did not answer" \
    "answering=$P2_ANSWERING not answering=$P2_NOT"

# Claim 3, and it has to be read in the same pass as the pair above.
P2_DIMMER_OUTCOME=$(ha_state "$DIMMER_OUTCOME")
P2_SWITCH_OUTCOME=$(ha_state "$SWITCH_OUTCOME")
[ "$P2_DIMMER_OUTCOME" = "answered" ] && [ "$P2_SWITCH_OUTCOME" = "no_answer" ]
report $? "the per-switch outcome names which one did not answer" \
    "$DIMMER_OUTCOME=$P2_DIMMER_OUTCOME, $SWITCH_OUTCOME=$P2_SWITCH_OUTCOME -- the hub pair says '1 did not answer'; against 37 switches that never said which, and #44 named the gap"

# The mark itself needs the retry's second miss, which lands 30s after the
# pass's own miss -- so it arrives after the numbers above were published.
MARK_S=$(wait_for_state "$SWITCH_NODE" "unreachable" "$MARK_ARC_S")
[ "$MARK_S" != "-1" ]; report $? \
    "and the mark follows, unaided" \
    "$SWITCH_NODE=unreachable ${MARK_S}s after the census -- a miss at ${WITNESS_WINDOW_S}s and the confirming retry's miss at about $((RETRY_DELAY_S + WITNESS_WINDOW_S))s"

sleep 2
P2_MARKED=$(ha_state "$MARKED")
P2_NODES=$(marked_nodes)
[ "$P2_MARKED" = "$P2_NODES" ] && [ "$P2_MARKED" = "1" ]
report $? "the new hub count agrees with the per-switch sensors" \
    "$MARKED=$P2_MARKED against $P2_NODES node status sensors reading unreachable -- the same set, counted, so agreement is by construction rather than by luck"

P2_UUIDS=$(ha_attr "$MARKED" unreachable_uuids)
echo "$P2_UUIDS" | grep -q "$SWITCH_UUID"
report $? "and it names which switch, so the number is followable" \
    "unreachable_uuids=$P2_UUIDS"

report 0 "the marked count and the probe pair are different readings, as expected" \
    "marked=$P2_MARKED, answering=$(ha_state "$ANSWERING"), not answering=$(ha_state "$NOT_ANSWERING") -- a snapshot against a verdict: the mark needed two misses and the confirming retry landed after this pass had already published its numbers"

dump_counters "with one switch marked"

# ---------------------------------------------------------------------------
# Phase 3: the asymmetric specimen -- it reports, and it cannot obey.
# ---------------------------------------------------------------------------
#
# The fixture composes two things the simulator already has: the device is
# modelled off the mesh (deaf to CONTROL, #13's measured behaviour), and an
# EVENT is injected through the state endpoint. That combination has never been
# observed in the house. It is here because #45's instrument has to be shown
# recording *both* answers, and this is the one it cannot get any other way.

echo ""
echo "== phase 3: an EVENT arrives from a marked switch that cannot obey =="
P3_ASYM_BEFORE=$(ha_state "$ASYMMETRY")
P3_CONTROLS_BEFORE=$(controls_for "$SWITCH_UUID")

curl -s -X POST "$SIM_HTTP/api/devices/$SWITCH_UUID/state" \
    -H "Content-Type: application/json" -d '{"power": true}' > "$WORK_DIR/event.json"
grep -q "$SWITCH_UUID" "$WORK_DIR/event.json"
report $? "the simulator broadcast an EVENT for the marked switch" \
    "$(cat "$WORK_DIR/event.json")"

CLEAR_S=$(wait_for_state "$SWITCH_NODE" "online" 15)
[ "$CLEAR_S" != "-1" ]; report $? \
    "the mark clears on the EVENT, exactly as it did before" \
    "$SWITCH_NODE=online after ${CLEAR_S}s -- the measurement does not gate the clear, which is the first thing #45 forbids it from doing"

sleep $((WITNESS_WINDOW_S + 3))
P3_ASYM_AFTER=$(ha_state "$ASYMMETRY")
P3_CONTROLS_AFTER=$(controls_for "$SWITCH_UUID")
P3_SENT=$((P3_CONTROLS_AFTER - P3_CONTROLS_BEFORE))
[ "$P3_SENT" -eq 1 ] && [ "$P3_ASYM_AFTER" = "$((P3_ASYM_BEFORE + 1))" ]
report $? "exactly one CONTROL was sent, and the measurement counted it" \
    "CONTROLs to this switch=$P3_SENT, $ASYMMETRY ${P3_ASYM_BEFORE}->${P3_ASYM_AFTER} -- one per clear, marked devices only"

P3_WITNESSED=$(ha_attr "$ASYMMETRY" witnessed)
P3_UNWITNESSED=$(ha_attr "$ASYMMETRY" unwitnessed)
[ "$P3_UNWITNESSED" = "1" ] && [ "$P3_WITNESSED" = "0" ]
report $? "an unanswered measurement is recorded as unwitnessed" \
    "witnessed=$P3_WITNESSED unwitnessed=$P3_UNWITNESSED -- this fixture reports but cannot obey, which is #43's asymmetric reading"

grep -q "Asymmetry measurement on $SWITCH_UUID" "$HA_DIR/ha.log"
report $? "and it says so in the log too" \
    "$(grep -o "Asymmetry measurement on .*" "$HA_DIR/ha.log" | tail -1)"

# The second thing #45 forbids it from doing. An unwitnessed CONTROL through
# the ordinary path would count a miss, schedule the 30s retry, and re-mark the
# switch on the retry's own miss. This one must do none of that.
echo "  watching for ${NO_REMARK_WATCH_S}s to see whether the measurement feeds the detector"
sleep "$NO_REMARK_WATCH_S"
P3_STILL=$(ha_state "$SWITCH_NODE")
P3_MARKED_NOW=$(ha_state "$MARKED")
[ "$P3_STILL" = "online" ] && [ "$P3_MARKED_NOW" = "0" ]
report $? "the measurement counted no miss and re-marked nothing" \
    "$SWITCH_NODE=$P3_STILL and $MARKED=$P3_MARKED_NOW, ${NO_REMARK_WATCH_S}s after an unwitnessed measurement -- longer than a witness window plus the ${RETRY_DELAY_S}s retry, which is how long a re-mark would have taken had this gone through the ordinary command path"

P3_CONTROLS_END=$(controls_for "$SWITCH_UUID")
[ "$P3_CONTROLS_END" -eq "$P3_CONTROLS_AFTER" ]
report $? "and it scheduled no retry" \
    "CONTROLs to this switch unchanged at $P3_CONTROLS_END across the whole watch"

dump_counters "after the asymmetric measurement"

# ---------------------------------------------------------------------------
# Phase 4: the intermittent specimen -- it reports, and it also obeys.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 4: the other reading of #43's open question =="
echo "  marking the switch again, off the probe's own writes"
run_census >/dev/null
REMARK_S=$(wait_for_state "$SWITCH_NODE" "unreachable" "$MARK_ARC_S")
[ "$REMARK_S" != "-1" ]; report $? "the switch is marked again" \
    "$SWITCH_NODE=unreachable after ${REMARK_S}s"

echo "  putting it back on the mesh, so that this time it can obey"
set_unreachable ""
sleep 1

P4_ASYM_BEFORE=$(ha_state "$ASYMMETRY")
curl -s -X POST "$SIM_HTTP/api/devices/$SWITCH_UUID/state" \
    -H "Content-Type: application/json" -d '{"power": false}' >/dev/null

CLEAR2_S=$(wait_for_state "$SWITCH_NODE" "online" 15)
[ "$CLEAR2_S" != "-1" ]; report $? "the mark clears on the EVENT again" \
    "$SWITCH_NODE=online after ${CLEAR2_S}s"

sleep $((WITNESS_WINDOW_S + 3))
P4_ASYM_AFTER=$(ha_state "$ASYMMETRY")
P4_WITNESSED=$(ha_attr "$ASYMMETRY" witnessed)
[ "$P4_ASYM_AFTER" = "$((P4_ASYM_BEFORE + 1))" ] && [ "$P4_WITNESSED" = "1" ]
report $? "a measurement the switch answers is recorded as witnessed" \
    "$ASYMMETRY ${P4_ASYM_BEFORE}->${P4_ASYM_AFTER}, witnessed=$P4_WITNESSED -- the instrument can produce both answers, which is what makes it a measurement rather than a foregone conclusion"

# ---------------------------------------------------------------------------
# Phase 5: the per-switch outcome is in the recorder, not just in memory.
# ---------------------------------------------------------------------------

echo ""
echo "== phase 5: the outcome survives being written =="
python3 -c "
import json, subprocess, sys

out = subprocess.run(
    ['curl', '-s',
     '$BASE/api/history/period?filter_entity_id=$DIMMER_OUTCOME,$SWITCH_OUTCOME',
     '-H', '$AUTH'],
    capture_output=True, text=True).stdout
try:
    series = json.loads(out)
except Exception as exc:
    print(f'unreadable: {exc}')
    sys.exit(1)

seen = {}
for run in series:
    for point in run:
        state = point.get('state')
        if state in (None, 'unknown', 'unavailable'):
            continue
        seen.setdefault(point['entity_id'], set()).add(state)

print('; '.join(f'{k} recorded {sorted(v)}' for k, v in sorted(seen.items())) or 'nothing recorded')
ok = (
    'answered' in seen.get('$DIMMER_OUTCOME', set())
    and 'no_answer' in seen.get('$SWITCH_OUTCOME', set())
)
sys.exit(0 if ok else 1)
" > "$WORK_DIR/outcome_history.txt"
OUTCOME_OK=$?
report "$OUTCOME_OK" "the recorder holds the per-switch outcome" \
    "$(cat "$WORK_DIR/outcome_history.txt") -- an attribution record that is only right in memory would not answer a question asked hours later, which is the question it exists for"

dump_counters "at the end of the run"

echo ""
echo "===================================================================="
echo "$PASSED passed, $FAILED failed"
echo "===================================================================="
[ "$FAILED" -eq 0 ] || exit 1
