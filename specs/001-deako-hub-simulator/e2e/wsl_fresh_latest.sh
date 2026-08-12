#!/bin/bash
# Fresh minimal instance of the LATEST Home Assistant, with no leftover config
# entries from the earlier default_config run (which had adopted real LAN
# devices and made the API slow).
VENV="$HOME/ha-venv-latest"
HA_DIR="$HOME/ha-test-latest"
REPO="/mnt/c/Users/tolaa/Source/Repos/copilot-worktrees/homeassistant_alpha/oaa8-improved-enigma"

pkill -f "ha-venv-latest/bin/hass" 2>/dev/null
sleep 3

rm -rf "$HA_DIR"
mkdir -p "$HA_DIR/custom_components"
cp -r "$REPO/custom_components/deako" "$HA_DIR/custom_components/deako"
rm -rf "$HA_DIR/custom_components/deako/__pycache__"
find "$HA_DIR/custom_components/deako" -name '*.py' -exec sed -i 's/\r$//' {} \;

cat > "$HA_DIR/configuration.yaml" <<'YAML'
http:
config:
zeroconf:

logger:
  default: warning
  logs:
    custom_components.deako: debug
    pydeako: debug
YAML

nohup "$VENV/bin/hass" -c "$HA_DIR" --skip-pip > "$HA_DIR/ha.log" 2>&1 &
echo "HA_PID=$!"

for i in $(seq 1 72); do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8123/ 2>/dev/null || echo "000")
  [ "$code" = "200" ] || [ "$code" = "302" ] && { echo "HA UP after $((i*5))s (code $code)"; break; }
  sleep 5
done
echo "import errors: $(grep -cE 'Exception importing custom_components.deako' "$HA_DIR/ha.log")"
