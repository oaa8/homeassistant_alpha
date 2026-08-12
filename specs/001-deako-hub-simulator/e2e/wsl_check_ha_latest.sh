#!/bin/bash
# Inspect the latest-HA test instance without aborting on transient curl errors.
HA_DIR="$HOME/ha-test-latest"

for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8123/ 2>/dev/null || echo "000")
  if [ "$code" = "200" ]; then
    echo "HA UP after $((i*5))s"
    break
  fi
  sleep 5
done
echo "final http code: $code"

echo ""
echo "== hass process =="
pgrep -af "ha-venv-latest/bin/hass" | head -3 || echo "  NOT RUNNING"

echo ""
echo "== deako log lines =="
grep -iE "deako" "$HA_DIR/ha.log" | tail -25 || echo "  (none)"

echo ""
echo "== errors =="
grep -iE "Error during setup|Setup failed|Traceback|ERROR" "$HA_DIR/ha.log" | tail -20 || echo "  (none)"
