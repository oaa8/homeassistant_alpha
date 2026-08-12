#!/bin/bash
# Wait for the HA HTTP API, then report onboarding state.
HA_DIR="$HOME/ha-test"

for i in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8123/ 2>/dev/null)
  if [ "$code" = "200" ]; then
    echo "HA UP (http $code) after $((i*10))s"
    break
  fi
  sleep 10
done

echo "--- onboarding status ---"
curl -s http://127.0.0.1:8123/api/onboarding | head -c 400
echo ""
echo "--- log tail ---"
tail -12 "$HA_DIR/ha.log"
