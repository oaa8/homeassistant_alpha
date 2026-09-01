#!/usr/bin/env bash
# Bring a probe rig up and LEAVE IT RUNNING, so a person can drive it by hand.
#
# **This is not a test, and that is the point.** This map's bar is that nobody
# claims a change works until they have driven it end to end and watched the
# effects -- and every other script in this directory tears its rig down on
# exit, which makes that impossible. So sessions ran suites instead and called
# it hand-driving. Wayfinder #45 did exactly that, and an hour of actually
# poking a live rig then found four things its 30 green assertions had no
# assertion for, including two false claims in the code's own docstrings.
#
# So: this starts the simulator and a real Home Assistant on the working tree,
# wires the config entry, leaves a token where curl can find it, and then holds
# still until you stop it.
#
# The probe interval is *lengthened* rather than shortened, unlike the suites:
# nothing should fire unasked while somebody is looking at it. Every pass you
# see is one you asked for, with the census button.
#
# Loopback only and no mDNS, for the usual reason: the real house is on this
# LAN with a live Home Assistant on it.
#
# Prerequisites: bash specs/001-deako-hub-simulator/e2e/wsl_setup_ha_latest.sh
#
# Usage (inside WSL):
#   bash specs/001-deako-hub-simulator/e2e/wsl_rig_up.sh
#
# Then, from another shell:
#   python3 specs/001-deako-hub-simulator/e2e/rig_poke.py dump
#   python3 specs/001-deako-hub-simulator/e2e/rig_poke.py call button press \
#       button.deako_hub_run_census_now
#
# Stop it with Ctrl-C; the trap tears the rig down.

set -uo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/../../.." && pwd)"
# shellcheck source=specs/001-deako-hub-simulator/e2e/lib_port_guard.sh
. "$E2E_DIR/lib_port_guard.sh"

HA_DIR="$HOME/ha-test-latest"
VENV="$HOME/ha-venv-latest"
WORK_DIR="${RIG_WORK_DIR:-$HOME/rig}"
SIM_IP="127.0.0.1"
HA_PORT="8123"
BASE="http://127.0.0.1:$HA_PORT"

# Two hours. Long enough that the hourly tick cannot surprise you mid-thought.
PATCHED_INTERVAL_S="${RIG_PROBE_INTERVAL_S:-7200}"

mkdir -p "$WORK_DIR"

if [ ! -x "$VENV/bin/hass" ]; then
    echo "Home Assistant is not provisioned. Run wsl_setup_ha_latest.sh first."
    exit 1
fi

echo "== checking the ports this rig depends on =="
SIM_PORT=$(first_silent_port "$SIM_IP" "simulator telnet port" 8023 8024 8025 8026) || exit 1
SIM_HTTP_PORT=$(first_silent_port "$SIM_IP" "simulator control port" 8080 8081 8082 8083) || exit 1
SIM_HTTP="http://$SIM_IP:$SIM_HTTP_PORT"

# Anything already on 8123 is somebody else's Home Assistant. Driving a rig
# that is not the one you deployed to is how wayfinder #15 lost a whole run.
if port_answers "127.0.0.1" "$HA_PORT"; then
    echo "  something already answers on 127.0.0.1:$HA_PORT; refusing to use it"
    echo "  it is $(describe_port "127.0.0.1" "$HA_PORT")"
    exit 1
fi
echo "  simulator $SIM_IP:$SIM_PORT, control $SIM_HTTP, Home Assistant $BASE"

SIM_PID=""
cleanup() {
    echo ""
    echo "tearing the rig down"
    [ -n "${SIM_PID:-}" ] && kill "$SIM_PID" 2>/dev/null
    pkill -f "hass -c $HA_DIR" 2>/dev/null
    return 0
}
trap cleanup EXIT

echo ""
echo "== starting the simulator on loopback, no mDNS =="
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
    grep -q "^READY" "$WORK_DIR/sim.log" 2>/dev/null && break
    sleep 1
done
grep -q "^READY" "$WORK_DIR/sim.log" || {
    echo "the simulator did not start"; tail -20 "$WORK_DIR/sim.log"; exit 1; }
echo "  up, pid $SIM_PID"

echo ""
echo "== deploying the working tree's integration =="
rm -rf "$HA_DIR"
mkdir -p "$HA_DIR/custom_components"
cp -r "$REPO_ROOT/custom_components/deako" "$HA_DIR/custom_components/deako"
rm -rf "$HA_DIR/custom_components/deako/__pycache__"
# The repo is checked out CRLF on the Windows side.
find "$HA_DIR/custom_components/deako" -name '*.py' -exec sed -i 's/\r$//' {} \;
sed -i "s/^PROBE_INTERVAL_S = .*/PROBE_INTERVAL_S = $PATCHED_INTERVAL_S/" \
    "$HA_DIR/custom_components/deako/probe.py"
echo "  probe interval held at ${PATCHED_INTERVAL_S}s so nothing fires unasked"

# Deliberately not default_config: with WSL mirrored networking it discovers
# the real house and times the rig out (wayfinder #15). recorder and history
# are loaded because half of what is worth checking is what got written down.
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

echo ""
echo "== starting Home Assistant =="
nohup "$VENV/bin/hass" -c "$HA_DIR" --skip-pip > "$HA_DIR/ha.log" 2>&1 &
HA_PID=$!
for i in $(seq 1 72); do
    if ! kill -0 "$HA_PID" 2>/dev/null; then
        echo "  it exited during startup"; tail -30 "$HA_DIR/ha.log"; exit 1
    fi
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE/api/" 2>/dev/null)
    [ "${code:-000}" != "000" ] && { echo "  up after $((i * 5))s (pid $HA_PID)"; break; }
    sleep 5
done

echo ""
echo "== onboarding =="
PW="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
CLIENT_ID="$BASE/"
AUTH_CODE=$(curl -s -X POST "$BASE/api/onboarding/users" -H "Content-Type: application/json" \
    -d "{\"client_id\":\"$CLIENT_ID\",\"name\":\"Rig\",\"username\":\"rig\",\"password\":\"$PW\",\"language\":\"en\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('auth_code',''))")
curl -s -X POST "$BASE/auth/token" -d "grant_type=authorization_code" \
    -d "code=$AUTH_CODE" -d "client_id=$CLIENT_ID" > "$WORK_DIR/auth.json"
TOKEN=$(python3 -c "import json; print(json.load(open('$WORK_DIR/auth.json'))['access_token'])")
# The refresh token, because an access token expires in 30 minutes and a
# session spent driving a rig by hand is longer than that. Ask for a fresh one
# with `$WORK_DIR/refresh` rather than rebuilding the rig.
python3 -c "import json; print(json.load(open('$WORK_DIR/auth.json'))['refresh_token'])" \
    > "$WORK_DIR/refresh.txt"
echo "$TOKEN" > "$WORK_DIR/token.txt"

cat > "$WORK_DIR/refresh" <<REFRESH
#!/bin/bash
curl -s -X POST "$BASE/auth/token" -d "grant_type=refresh_token" \\
    -d "refresh_token=\$(cat $WORK_DIR/refresh.txt)" \\
    -d "client_id=$CLIENT_ID" \\
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" \\
    > $WORK_DIR/token.txt
cat $WORK_DIR/token.txt
REFRESH
chmod +x "$WORK_DIR/refresh"

AUTH="Authorization: Bearer $TOKEN"
curl -s -X POST "$BASE/api/onboarding/core_config" -H "$AUTH" >/dev/null 2>&1
curl -s -X POST "$BASE/api/onboarding/integration" -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"client_id\":\"$CLIENT_ID\",\"redirect_uri\":\"$CLIENT_ID\"}" >/dev/null 2>&1

echo ""
echo "== wiring the config entry to the simulator =="
FLOW_ID=$(curl -s -X POST "$BASE/api/config/config_entries/flow" -H "$AUTH" \
    -H "Content-Type: application/json" -d '{"handler":"deako","show_advanced_options":true}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('flow_id',''))")
curl -s -X POST "$BASE/api/config/config_entries/flow/$FLOW_ID" -H "$AUTH" \
    -H "Content-Type: application/json" \
    -d "{\"ip_address\":\"$SIM_IP\",\"port\":$SIM_PORT}" > "$WORK_DIR/flow.json"

cat <<INFO

================================================================
RIG UP. It stays up until you stop this script.

  Home Assistant  $BASE
  simulator       $SIM_IP:$SIM_PORT   control $SIM_HTTP
  token           $WORK_DIR/token.txt   (renew: $WORK_DIR/refresh)
  logs            $WORK_DIR/sim.log   $HA_DIR/ha.log

Drive it from another shell:

  python3 $E2E_DIR/rig_poke.py dump
  python3 $E2E_DIR/rig_poke.py get sensor.deako_hub_asymmetry_probes
  python3 $E2E_DIR/rig_poke.py call button press button.deako_hub_run_census_now
  python3 $E2E_DIR/rig_poke.py deaf     # a switch leaves the mesh
  python3 $E2E_DIR/rig_poke.py hear     # and comes back
  python3 $E2E_DIR/rig_poke.py event true

Then report what you saw, not what passed.
================================================================

INFO

sleep infinity
