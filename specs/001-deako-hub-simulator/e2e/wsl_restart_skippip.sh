#!/bin/bash
# HA reinstalls manifest requirements on every start, which re-downgrades cffi
# and reintroduces the version skew with the compiled _cffi_backend. Pin the
# deps once, then start with --skip-pip so HA leaves them alone.
VENV="$HOME/ha-venv-latest"
HA_DIR="$HOME/ha-test-latest"
export PATH="$HOME/.local/bin:$PATH"

pkill -f "ha-venv-latest/bin/hass" 2>/dev/null
sleep 3

echo "== pinning integration deps + matching cffi =="
VIRTUAL_ENV="$VENV" uv pip install --quiet --no-cache pydeako==0.3.1 atomics==1.0.2 2>&1 | tail -3
VIRTUAL_ENV="$VENV" uv pip install --quiet --force-reinstall --no-cache cffi 2>&1 | tail -3

"$VENV/bin/python" -c "import cffi, _cffi_backend; print('cffi', cffi.__version__, '| backend', _cffi_backend.__version__)"
"$VENV/bin/python" -c "import atomics, pydeako; print('atomics + pydeako import OK')"

echo ""
echo "== starting HA with --skip-pip =="
rm -f "$HA_DIR/ha.log"
nohup "$VENV/bin/hass" -c "$HA_DIR" --skip-pip > "$HA_DIR/ha.log" 2>&1 &
echo "HA_PID=$!"

for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8123/ 2>/dev/null || echo "000")
  [ "$code" = "200" ] && { echo "HA UP after $((i*5))s"; break; }
  sleep 5
done

echo ""
echo "== deako import errors =="
grep -iE "deako.*(error|importerror)" "$HA_DIR/ha.log" | head -6 || echo "  NONE - integration imported cleanly"

echo ""
echo "== deako discovery activity =="
grep -iE "deako" "$HA_DIR/ha.log" | grep -viE "not been tested" | tail -12 || echo "  (no deako log lines)"
