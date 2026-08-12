#!/bin/bash
# Onboard the latest-HA instance, then report whether the Deako simulator was
# auto-discovered over mDNS (now possible under WSL mirrored networking).
BASE="http://127.0.0.1:8123"
CLIENT_ID="$BASE/"
HA_DIR="$HOME/ha-test-latest"

AUTH_CODE=$(curl -s -X POST "$BASE/api/onboarding/users" \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$CLIENT_ID\",\"name\":\"Sim Tester\",\"username\":\"simtester\",\"password\":\"$HA_TEST_PASSWORD\",\"language\":\"en\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('auth_code',''))")

if [ -z "$AUTH_CODE" ]; then
  echo "already onboarded or failed; trying stored token"
  TOKEN=$(cat "$HA_DIR/token.txt" 2>/dev/null)
else
  TOKEN=$(curl -s -X POST "$BASE/auth/token" \
    -d "grant_type=authorization_code" -d "code=$AUTH_CODE" -d "client_id=$CLIENT_ID" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
  echo "$TOKEN" > "$HA_DIR/token.txt"
fi
AUTH="Authorization: Bearer $TOKEN"
echo "token: ${TOKEN:0:10}..."

curl -s -X POST "$BASE/api/onboarding/core_config" -H "$AUTH" >/dev/null 2>&1
curl -s -X POST "$BASE/api/onboarding/analytics" -H "$AUTH" >/dev/null 2>&1
curl -s -X POST "$BASE/api/onboarding/integration" -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$CLIENT_ID\",\"redirect_uri\":\"$CLIENT_ID\"}" >/dev/null 2>&1

echo ""
echo "== waiting 25s for zeroconf discovery =="
sleep 25

echo "== discovery flows currently offered by HA =="
curl -s "$BASE/api/config/config_entries/flow" -H "$AUTH" \
  | python3 -c "
import sys, json
try:
    flows = json.load(sys.stdin)
except Exception as e:
    print('  could not read flows:', e); raise SystemExit
if not flows:
    print('  (none)')
for f in flows:
    print(f\"  handler={f.get('handler')} step={f.get('step_id')} context={f.get('context',{}).get('source')}\")
deako = [f for f in flows if f.get('handler') == 'deako']
print()
print('DEAKO_DISCOVERY_FLOW:', 'YES' if deako else 'NO')
"

echo ""
echo "== zeroconf/deako log evidence =="
grep -iE "deako" "$HA_DIR/ha.log" | grep -viE "not been tested" | tail -12 || echo "  (no deako lines)"
