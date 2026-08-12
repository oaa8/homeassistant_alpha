#!/bin/bash
# Repair the cffi/_cffi_backend version skew that breaks `atomics`, then restart
# HA so we can judge the integration on its own merits rather than on a
# packaging artifact of this test venv.
VENV="$HOME/ha-venv-latest"
HA_DIR="$HOME/ha-test-latest"
export PATH="$HOME/.local/bin:$PATH"

echo "== before =="
"$VENV/bin/python" -c "import cffi, _cffi_backend; print('cffi', cffi.__version__, '| backend', _cffi_backend.__version__)" 2>&1 | tail -3

echo "== reinstalling cffi to match its compiled backend =="
VIRTUAL_ENV="$VENV" uv pip install --quiet --force-reinstall --no-cache cffi 2>&1 | tail -3

echo "== after =="
"$VENV/bin/python" -c "import cffi, _cffi_backend; print('cffi', cffi.__version__, '| backend', _cffi_backend.__version__)" 2>&1 | tail -3
"$VENV/bin/python" -c "import atomics; print('atomics imports OK')" 2>&1 | tail -3

echo ""
echo "== restarting home assistant =="
pkill -f "ha-venv-latest/bin/hass" 2>/dev/null
sleep 3
rm -f "$HA_DIR/ha.log"
nohup "$VENV/bin/hass" -c "$HA_DIR" > "$HA_DIR/ha.log" 2>&1 &
echo "HA_PID=$!"

for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8123/ 2>/dev/null || echo "000")
  [ "$code" = "200" ] && { echo "HA UP after $((i*5))s"; break; }
  sleep 5
done

echo ""
echo "== deako errors this run =="
grep -iE "deako" "$HA_DIR/ha.log" | grep -iE "error|importerror" | head -10 || echo "  NONE - integration imported cleanly"
