#!/bin/bash
# Onboard the throwaway HA instance and add the Deako integration pointed at the
# simulator running on the Windows host. Prints the resulting light entities.
set -e

# Generate a throwaway password per run rather than committing a literal.
# This instance is local, disposable and destroyed by the teardown script.
HA_TEST_PASSWORD="${HA_TEST_PASSWORD:-$(head -c 18 /dev/urandom | base64 | tr -d '/+=')}"
BASE="http://127.0.0.1:8123"
CLIENT_ID="$BASE/"
SIM_IP="192.168.86.65"
SIM_PORT="8023"

echo "== onboarding owner user =="
AUTH_CODE=$(curl -s -X POST "$BASE/api/onboarding/users" \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$CLIENT_ID\",\"name\":\"Sim Tester\",\"username\":\"simtester\",\"password\":\"$HA_TEST_PASSWORD\",\"language\":\"en\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['auth_code'])")

TOKEN=$(curl -s -X POST "$BASE/auth/token" \
  -d "grant_type=authorization_code" \
  -d "code=$AUTH_CODE" \
  -d "client_id=$CLIENT_ID" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "token acquired: ${TOKEN:0:12}..."
AUTH="Authorization: Bearer $TOKEN"

echo "== completing core config =="
curl -s -X POST "$BASE/api/onboarding/core_config" -H "$AUTH" >/dev/null || true
curl -s -X POST "$BASE/api/onboarding/analytics" -H "$AUTH" >/dev/null || true
curl -s -X POST "$BASE/api/onboarding/integration" -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$CLIENT_ID\",\"redirect_uri\":\"$CLIENT_ID\"}" >/dev/null || true

echo "== starting deako config flow =="
FLOW=$(curl -s -X POST "$BASE/api/config/config_entries/flow" -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"handler":"deako","show_advanced_options":true}')
echo "$FLOW" | head -c 300; echo ""

FLOW_ID=$(echo "$FLOW" | python3 -c "import sys,json; print(json.load(sys.stdin).get('flow_id',''))")
if [ -z "$FLOW_ID" ]; then
  echo "FAILED to start flow"; exit 1
fi

echo "== submitting simulator address $SIM_IP:$SIM_PORT =="
RESULT=$(curl -s -X POST "$BASE/api/config/config_entries/flow/$FLOW_ID" -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "{\"ip_address\":\"$SIM_IP\",\"port\":$SIM_PORT}")
echo "$RESULT" | head -c 600; echo ""

echo "== waiting for setup =="
sleep 20

echo "== config entries =="
curl -s "$BASE/api/config/config_entries/entry" -H "$AUTH" \
  | python3 -c "import sys,json; [print(f\"  {e['domain']}: state={e.get('state')} title={e.get('title')}\") for e in json.load(sys.stdin) if e['domain']=='deako']"

echo "== deako light entities =="
curl -s "$BASE/api/states" -H "$AUTH" \
  | python3 -c "
import sys, json
states = json.load(sys.stdin)
lights = [s for s in states if s['entity_id'].startswith('light.')]
for s in lights:
    print(f\"  {s['entity_id']:<42} state={s['state']:<10} name={s['attributes'].get('friendly_name')}\")
print(f'TOTAL_LIGHTS={len(lights)}')
"
echo "$TOKEN" > "$HOME/ha-test/token.txt"
