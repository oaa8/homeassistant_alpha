#!/bin/bash
HA_DIR="$HOME/ha-test-latest"
echo "== log size =="
wc -l "$HA_DIR/ha.log" 2>/dev/null || echo "no log"
echo ""
echo "== last 30 lines =="
tail -30 "$HA_DIR/ha.log" 2>/dev/null || echo "no log"
