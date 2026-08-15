#!/usr/bin/env bash
# End-to-end proof for wayfinder #15: setup, address handling and config entry
# migration, in a real Home Assistant, against the simulator.
#
# Three phases, in one HA config directory, because the upgrade path can only be
# tested against an installation that already exists:
#
#   1. FRESH -- a new install configured through the config flow, including the
#      validation that now rejects a malformed address at the form, the refusal
#      to add the same switch twice, and an unreachable address failing loudly
#      instead of finding another node.
#   2. REWIND -- Home Assistant is stopped and the entry it just wrote is rewound
#      to the version 1 shape the house is running today: the address split
#      across `data` and `options` with the two disagreeing, plus the dead telnet
#      delay. The light entity is renamed at the same time, the way a user would
#      have renamed it years ago. Rewinding what HA itself authored is what makes
#      this faithful -- a hand-written registry would only test a guess at HA's
#      current storage schema.
#   3. UPGRADE -- Home Assistant is started again on that rewound entry, and the
#      migration runs for real.
#
# The renamed entity is the sharp instrument here: `light.house_history_probe`
# only survives if the migrated entry keeps its entry_id and the light keeps its
# unique id. Delete-and-re-add would produce `light.zero_dim_test_dimmer`
# instead, and the rename -- along with every state row recorded against it --
# would be gone.
#
# Loopback only, and no mDNS: the real house is on this LAN with a live Home
# Assistant on it, so the simulator must not advertise itself. Auto-discovery is
# not exercised because after this ticket nothing discovers -- the configured
# address is the only source of an address (outcome O8).
#
# Prerequisites: bash specs/001-deako-hub-simulator/e2e/wsl_setup_ha_latest.sh
#
# Usage (inside WSL):
#   bash specs/001-deako-hub-simulator/e2e/wsl_validate_setup_rebuild.sh

set -uo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/../../.." && pwd)"
HA_DIR="$HOME/ha-test-latest"
VENV="$HOME/ha-venv-latest"
WORK_DIR="${SETUP_REBUILD_WORK_DIR:-$HOME/setup-rebuild-ha}"
BASE="http://127.0.0.1:8123"
SIM_IP="127.0.0.1"
SIM_PORT="8023"
SIM_HTTP="http://127.0.0.1:8080"

DIMMER_UUID="11111111-1111-4111-8111-111111111111"
SWITCH_UUID="33333333-3333-4333-8333-333333333333"
# The entity id a user renamed to, three years ago, and has automations against.
RENAMED_ENTITY="light.house_history_probe"
LEGACY_DELAY_KEY="telnet_message_receive_delay"

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

deploy_integration() {
    mkdir -p "$HA_DIR/custom_components"
    rm -rf "$HA_DIR/custom_components/deako"
    cp -r "$REPO_ROOT/custom_components/deako" "$HA_DIR/custom_components/deako"
    rm -rf "$HA_DIR/custom_components/deako/__pycache__"
    find "$HA_DIR/custom_components/deako" -name '*.py' -exec sed -i 's/\r$//' {} \;
    # Deliberately not default_config: with WSL mirrored networking it pulls in
    # broad LAN discovery (Sonos, cast, DLNA) against the real house, which is
    # slow enough to time this script out and intrusive besides. Only what these
    # checks need is enabled. zeroconf is left out entirely, which also proves
    # the point of outcome O8 -- nothing here can discover a Deako node, so
    # every connection made below came from the configured address.
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

# The API answers 401 before onboarding and 200 after, so "not 000" is the
# honest test for "HTTP is serving". Waiting on / would instead wait on the
# frontend, which this minimal configuration does not load.
ha_http_code() {
    local code
    # curl already writes 000 for a connection it could not make, so the exit
    # status is discarded rather than used to echo a second value.
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE/api/" 2>/dev/null)
    echo "${code:-000}"
}

start_ha() {
    # Anything already serving 8123 means another Home Assistant -- a leftover
    # from an aborted run, or another rig entirely -- owns it. Every check below
    # would then run against someone else's instance and pass or fail for
    # reasons unrelated to this integration, so refuse rather than produce a
    # confident wrong answer.
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

stop_ha() {
    pkill -f "hass -c $HA_DIR" 2>/dev/null
    for _ in $(seq 1 30); do
        pgrep -f "hass -c $HA_DIR" >/dev/null || break
        sleep 1
    done
    # The port outlives the process briefly, and starting the next phase while
    # it is still held is what makes a run silently test the wrong instance.
    for _ in $(seq 1 30); do
        [ "$(ha_http_code)" = "000" ] && break
        sleep 1
    done
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

deako_entry() { # deako_entry <json path expression applied to the deako entry>
    curl -s "$BASE/api/config/config_entries/entry" -H "$AUTH" | python3 -c "
import sys, json
entries = json.load(sys.stdin)
entry = next((e for e in entries if e['domain'] == 'deako'), None)
print('missing' if entry is None else entry.get('$1', 'absent'))
"
}

# The REST API exposes neither the entry's schema version nor its data, so both
# are read from the store on disk.
stored_entry() { # stored_entry <field> [entry_id]
    python3 - "$HA_DIR/.storage/core.config_entries" "$1" "${2:-}" <<'PY'
import json
import sys

path, field, entry_id = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    entries = json.load(open(path, encoding="utf-8"))["data"]["entries"]
except (OSError, ValueError, KeyError):
    print("unreadable")
    raise SystemExit

candidates = [e for e in entries if e["domain"] == "deako"]
if entry_id:
    candidates = [e for e in candidates if e["entry_id"] == entry_id]
if not candidates:
    print("missing")
    raise SystemExit

value = candidates[0].get(field, "absent")
print(json.dumps(value) if isinstance(value, (dict, list)) else value)
PY
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


# ---------------------------------------------------------------------------
# Phase 1: the fresh install, and the address validation in front of it.
# ---------------------------------------------------------------------------

echo "== starting the simulator on loopback, no mDNS =="
start_simulator

echo ""
echo "== fresh install =="
rm -rf "$HA_DIR"
mkdir -p "$HA_DIR"
deploy_integration
start_ha || exit 1
onboard

FLOW_ID=$(curl -s -X POST "$BASE/api/config/config_entries/flow" -H "$AUTH" \
    -H "Content-Type: application/json" -d '{"handler":"deako","show_advanced_options":true}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('flow_id',''))")
[ -n "$FLOW_ID" ]; report $? "the config flow starts" "flow_id=${FLOW_ID:-none}"

BAD=$(curl -s -X POST "$BASE/api/config/config_entries/flow/$FLOW_ID" -H "$AUTH" \
    -H "Content-Type: application/json" -d '{"ip_address":"192.168.86.46:23","port":23}')
echo "$BAD" | grep -q "invalid_host"; report $? \
    "an address with a port pasted into it is rejected at the form" "$(echo "$BAD" | head -c 200)"

BAD_PORT=$(curl -s -X POST "$BASE/api/config/config_entries/flow/$FLOW_ID" -H "$AUTH" \
    -H "Content-Type: application/json" -d '{"ip_address":"127.0.0.1","port":99999}')
echo "$BAD_PORT" | grep -qE "invalid_port|not a valid"; report $? \
    "a port outside the usable range is rejected at the form" "$(echo "$BAD_PORT" | head -c 200)"

curl -s -X POST "$BASE/api/config/config_entries/flow/$FLOW_ID" -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d "{\"ip_address\":\"$SIM_IP\",\"port\":$SIM_PORT}" > "$WORK_DIR/flow.json"
sleep 25

FRESH_STATE=$(deako_entry state)
[ "$FRESH_STATE" = "loaded" ]; report $? "a fresh install connects to the configured address" "state=$FRESH_STATE"

FRESH_VERSION=$(stored_entry version)
[ "$FRESH_VERSION" = "2" ]; report $? "a fresh entry is created at the current version" "version=$FRESH_VERSION"

LIGHTS=$(curl -s "$BASE/api/states" -H "$AUTH" \
    | python3 -c "import sys,json; print(len([x for x in json.load(sys.stdin) if x['entity_id'].startswith('light.')]))")
[ "$LIGHTS" -eq 2 ]; report $? "both simulator devices became light entities" "count=$LIGHTS"

# O8: a second entry pointing at the same switch would block itself, because
# Deako's telnet server is exclusive.
DUP_FLOW=$(curl -s -X POST "$BASE/api/config/config_entries/flow" -H "$AUTH" \
    -H "Content-Type: application/json" -d '{"handler":"deako","show_advanced_options":true}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('flow_id',''))")
DUP=$(curl -s -X POST "$BASE/api/config/config_entries/flow/$DUP_FLOW" -H "$AUTH" \
    -H "Content-Type: application/json" -d "{\"ip_address\":\"$SIM_IP\",\"port\":$SIM_PORT}")
echo "$DUP" | grep -q "already_configured"; report $? \
    "a second entry for the same switch is refused" "$(echo "$DUP" | head -c 200)"

# O8 again, the failure that matters: an address nobody can reach must say so,
# not go looking for another node.
UNREACHABLE_FLOW=$(curl -s -X POST "$BASE/api/config/config_entries/flow" -H "$AUTH" \
    -H "Content-Type: application/json" -d '{"handler":"deako","show_advanced_options":true}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('flow_id',''))")
curl -s -X POST "$BASE/api/config/config_entries/flow/$UNREACHABLE_FLOW" -H "$AUTH" \
    -H "Content-Type: application/json" -d '{"ip_address":"127.0.0.1","port":8099}' > "$WORK_DIR/unreachable.json"
sleep 25
UNREACHABLE_STATE=$(curl -s "$BASE/api/config/config_entries/entry" -H "$AUTH" | python3 -c "
import sys, json
entries = [e for e in json.load(sys.stdin) if e['domain'] == 'deako']
other = [e for e in entries if e.get('state') != 'loaded']
print(other[0]['state'] if other else 'none')
")
[ "$UNREACHABLE_STATE" = "setup_retry" ]; report $? \
    "an unreachable address retries with a clear error instead of finding another node" \
    "state=$UNREACHABLE_STATE"

CANNOT_REACH=$(grep -c "Cannot reach the Deako switch at 127.0.0.1:8099" "$HA_DIR/ha.log")
[ "$CANNOT_REACH" -gt 0 ]; report $? "the failure names the address the user configured" "occurrences=$CANNOT_REACH"

WRONG_NODE=$(grep -iE "discover|zeroconf|mdns" "$HA_DIR/ha.log" | grep -i "custom_components.deako" | head -3)
[ -z "$WRONG_NODE" ]; report $? "the integration never went looking for a node" "${WRONG_NODE:-clean}"

# Remove the deliberately unreachable entry so the rewind below has exactly one.
UNREACHABLE_ID=$(curl -s "$BASE/api/config/config_entries/entry" -H "$AUTH" | python3 -c "
import sys, json
entries = [e for e in json.load(sys.stdin) if e['domain'] == 'deako']
other = [e for e in entries if e.get('state') != 'loaded']
print(other[0]['entry_id'] if other else '')
")
[ -n "$UNREACHABLE_ID" ] && curl -s -X DELETE "$BASE/api/config/config_entries/entry/$UNREACHABLE_ID" -H "$AUTH" >/dev/null

stop_ha

# ---------------------------------------------------------------------------
# Phase 2: rewind what Home Assistant just wrote to the shape the house holds.
# ---------------------------------------------------------------------------

echo ""
echo "== rewinding the installation to the version 1 shape =="
REWIND=$(python3 - "$HA_DIR/.storage" "$SIM_IP" "$SIM_PORT" "$DIMMER_UUID" \
        "$RENAMED_ENTITY" "$LEGACY_DELAY_KEY" <<'PY'
import json
import sys

storage, ip, port, dimmer, renamed, delay_key = sys.argv[1:7]

entries_path = f"{storage}/core.config_entries"
registry_path = f"{storage}/core.entity_registry"

with open(entries_path, encoding="utf-8") as handle:
    entries_store = json.load(handle)

entry = next(
    e for e in entries_store["data"]["entries"] if e["domain"] == "deako"
)

# The version 1 shape, taken from the entry the house is actually running --
# read off disk and recorded in wayfinder #3, not imagined here:
#
#   "version": 1, "source": "zeroconf", "unique_id": null,
#   "data":    {"ip_address": "...", "port": 23},
#   "options": {"ip_address": "...", "port": 23,
#               "telnet_message_receive_delay": 0.0001},
#   "discovery_keys": {"zeroconf": ["231M...._deako._tcp.local."]}
#
# Two details of that shape matter and would be easy to miss. The house entry
# was created by the **discovery flow**, so it carries a `source` of zeroconf
# and a `discovery_keys` record -- a migration that dropped either would rewrite
# provenance Home Assistant owns. And the stored delay is `0.0001`, chosen to
# sit just above the deployed code's 1e-5 floor, so it is a live setting rather
# than an inert default.
#
# The addresses are made to disagree deliberately: only `options` reaches the
# simulator, so the migration is wrong unless the most recent edit wins.
entry["version"] = 1
entry["source"] = "zeroconf"
entry["unique_id"] = None
entry["data"] = {"ip_address": "192.168.86.99", "port": 23, delay_key: 0.1}
entry["options"] = {"ip_address": ip, "port": int(port), delay_key: 0.0001}
entry["discovery_keys"] = {
    "zeroconf": [{"domain": "zeroconf", "key": "231M000000000000._deako._tcp.local.", "version": 1}]
}

with open(entries_path, "w", encoding="utf-8") as handle:
    json.dump(entries_store, handle, indent=2)

# Rename the light the way a user would have, years ago. Only the entity_id is
# touched: everything else is Home Assistant's own record, at whatever schema
# this version writes, which is the point of rewinding rather than seeding.
with open(registry_path, encoding="utf-8") as handle:
    registry = json.load(handle)

light = next(
    e
    for e in registry["data"]["entities"]
    if e["platform"] == "deako" and e["unique_id"] == dimmer
)
was = light["entity_id"]
light["entity_id"] = renamed

with open(registry_path, "w", encoding="utf-8") as handle:
    json.dump(registry, handle, indent=2)

print(json.dumps({"entry_id": entry["entry_id"], "renamed_from": was}))
PY
)
[ -n "$REWIND" ] || { echo "could not rewind the installation"; exit 1; }
ENTRY_ID=$(echo "$REWIND" | python3 -c "import sys,json; print(json.load(sys.stdin)['entry_id'])")
RENAMED_FROM=$(echo "$REWIND" | python3 -c "import sys,json; print(json.load(sys.stdin)['renamed_from'])")
echo "  entry $ENTRY_ID rewound to version 1; $RENAMED_FROM renamed to $RENAMED_ENTITY"

# ---------------------------------------------------------------------------
# Phase 3: the upgrade. Start again and let the migration run for real.
# ---------------------------------------------------------------------------

echo ""
echo "== starting Home Assistant on the rewound installation =="
start_ha || exit 1
sleep 25

echo ""
echo "== upgrade results =="

VERSION=$(stored_entry version "$ENTRY_ID")
[ "$VERSION" = "2" ]; report $? "the version 1 entry migrated to version 2" "version=$VERSION"

STATE=$(deako_entry state)
[ "$STATE" = "loaded" ]; report $? "the migrated entry connects and loads" "state=$STATE"

SAME_ID=$(deako_entry entry_id)
[ "$SAME_ID" = "$ENTRY_ID" ]; report $? "the entry was migrated in place, not replaced" "entry_id=$SAME_ID"

# Read the migrated entry off disk: the REST API does not expose data/options.
MIGRATED=$(python3 - "$HA_DIR/.storage/core.config_entries" "$ENTRY_ID" <<'PY'
import json
import sys

entries = json.load(open(sys.argv[1], encoding="utf-8"))["data"]["entries"]
entry = next(e for e in entries if e["entry_id"] == sys.argv[2])
print(json.dumps({"data": entry["data"], "options": entry["options"]}))
PY
)
echo "$MIGRATED" | grep -q "\"ip_address\": \"$SIM_IP\""; report $? \
    "the address the user last edited (options) won over the stale one in data" "$MIGRATED"

if echo "$MIGRATED" | grep -q "$LEGACY_DELAY_KEY"; then FOUND_DELAY=1; else FOUND_DELAY=0; fi
[ "$FOUND_DELAY" -eq 0 ]; report $? \
    "the dead telnet delay was dropped from both data and options" "$MIGRATED"

echo "$MIGRATED" | python3 -c "import sys,json; sys.exit(0 if json.load(sys.stdin)['options'] == {} else 1)"
report $? "options is empty, so there is one place an address can live" "$MIGRATED"

RENAMED_STATE=$(ha_state "$RENAMED_ENTITY")
[ "$RENAMED_STATE" != "missing" ] && [ "$RENAMED_STATE" != "unavailable" ] && [ "$RENAMED_STATE" != "unreadable" ]
report $? "the renamed entity kept its entity id, so its history survives" \
    "$RENAMED_ENTITY=$RENAMED_STATE (delete-and-re-add would have produced $RENAMED_FROM)"

# The house's entry was created by the discovery flow, so it carries provenance
# Home Assistant owns: a `source` of zeroconf and a `discovery_keys` record. The
# migration has no business rewriting either -- and since it does not pass them
# to async_update_entry, "unchanged" is the assertion that proves it.
SOURCE=$(stored_entry source "$ENTRY_ID")
[ "$SOURCE" = "zeroconf" ]; report $? \
    "the entry's discovery provenance was not rewritten" "source=$SOURCE"

DISCOVERY_KEYS=$(stored_entry discovery_keys "$ENTRY_ID")
echo "$DISCOVERY_KEYS" | grep -q "_deako._tcp.local."; report $? \
    "discovery_keys survived the migration untouched" "$DISCOVERY_KEYS"

DUPLICATE=$(curl -s "$BASE/api/states" -H "$AUTH" \
    | python3 -c "import sys,json; print(len([x for x in json.load(sys.stdin) if x['entity_id'] == '$RENAMED_FROM']))")
[ "$DUPLICATE" = "0" ]; report $? "no duplicate entity was created alongside the renamed one" "duplicates=$DUPLICATE"

MIGRATION_ERRORS=$(grep -iE "Error (setting up|during setup)|Migration handler failed" "$HA_DIR/ha.log" | grep -i deako | head -3)
[ -z "$MIGRATION_ERRORS" ]; report $? "no migration or setup errors" "${MIGRATION_ERRORS:-clean}"

# The options screen is the thing HA 2025.12 broke: assigning to the read-only
# config_entry property raises the moment the screen is opened.
OPTIONS_FLOW=$(curl -s -X POST "$BASE/api/config/config_entries/options/flow" -H "$AUTH" \
    -H "Content-Type: application/json" -d "{\"handler\":\"$ENTRY_ID\"}")
echo "$OPTIONS_FLOW" | grep -q '"step_id": *"init"'; report $? \
    "the options screen opens on current Home Assistant" "$(echo "$OPTIONS_FLOW" | head -c 200)"

OPTIONS_FLOW_ID=$(echo "$OPTIONS_FLOW" | python3 -c "import sys,json; print(json.load(sys.stdin).get('flow_id',''))")
if [ -n "$OPTIONS_FLOW_ID" ]; then
    BAD_EDIT=$(curl -s -X POST "$BASE/api/config/config_entries/options/flow/$OPTIONS_FLOW_ID" -H "$AUTH" \
        -H "Content-Type: application/json" -d '{"ip_address":"not a switch","port":23}')
    echo "$BAD_EDIT" | grep -q "invalid_host"; report $? \
        "a malformed address is rejected in the options screen" "$(echo "$BAD_EDIT" | head -c 200)"
    curl -s -X DELETE "$BASE/api/config/config_entries/options/flow/$OPTIONS_FLOW_ID" -H "$AUTH" >/dev/null
else
    report 1 "a malformed address is rejected in the options screen" "no options flow to submit to"
fi

# Editing the address has to actually rebind, because that is the safety
# control: pointing the integration at a different node is how a user gets off
# the node SmartThings is using. Proven by moving it to a port nothing serves
# and watching it stop working, then moving it back.
edit_address() { # edit_address <ip> <port>
    local flow_id
    flow_id=$(curl -s -X POST "$BASE/api/config/config_entries/options/flow" -H "$AUTH" \
        -H "Content-Type: application/json" -d "{\"handler\":\"$ENTRY_ID\"}" \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('flow_id',''))")
    [ -n "$flow_id" ] || return 1
    curl -s -X POST "$BASE/api/config/config_entries/options/flow/$flow_id" -H "$AUTH" \
        -H "Content-Type: application/json" -d "{\"ip_address\":\"$1\",\"port\":$2}" >/dev/null
}

edit_address "127.0.0.1" 8099
sleep 30
MOVED_STATE=$(deako_entry state)
[ "$MOVED_STATE" = "setup_retry" ]; report $? \
    "editing the address rebinds the connection to the node the user named" \
    "state=$MOVED_STATE after moving to a port nothing serves"

MOVED_DATA=$(stored_entry data "$ENTRY_ID")
echo "$MOVED_DATA" | grep -q '"port": 8099'; report $? \
    "the edited address is stored in data, not options" "$MOVED_DATA"

edit_address "$SIM_IP" "$SIM_PORT"
sleep 30
RESTORED_STATE=$(deako_entry state)
[ "$RESTORED_STATE" = "loaded" ]; report $? \
    "editing it back reconnects, so the change is not one-way" "state=$RESTORED_STATE"

# Two of the checks above deliberately point the integration at a port nothing
# serves, and the vendored manager logs a connection timeout at ERROR when that
# happens. Those lines are the expected result of this script's own probes, so
# they are excluded by their exact text rather than by broadening the filter.
BAD_LOG=$(grep -iE "custom_components\.deako" "$HA_DIR/ha.log" \
    | grep -iE "Traceback|ERROR|Exception" \
    | grep -viE "No socket to send data to|Cannot reach the Deako switch|Timeout attempting to connect|Full exception" \
    | head -5)
[ -z "$BAD_LOG" ]; report $? "no unexpected errors or tracebacks from the integration" "${BAD_LOG:-clean}"

# The flip side of the exclusion above: the retries must be bounded by Home
# Assistant's own backoff rather than a reconnect loop the integration left
# running. A leaked loop would retry every second or two, not every ~15s.
TIMEOUTS=$(grep -c "Timeout attempting to connect" "$HA_DIR/ha.log")
[ "$TIMEOUTS" -lt 30 ]; report $? \
    "the unreachable address did not leave a reconnect loop running" \
    "connect timeouts logged=$TIMEOUTS across the whole run"

echo ""
echo "===================================================================="
echo "$PASSED/$((PASSED + FAILED)) passed"
[ "$FAILED" -eq 0 ] || echo "see $HA_DIR/ha.log and $WORK_DIR/sim.log"
echo "===================================================================="
exit $([ "$FAILED" -eq 0 ] && echo 0 || echo 1)
