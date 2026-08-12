#!/bin/bash
# Print the complete traceback block for the deako import failure.
HA_DIR="$HOME/ha-test-latest"

"$HOME/ha-venv-latest/bin/python" - <<'PY'
import re, pathlib
log = pathlib.Path.home() / "ha-test-latest" / "ha.log"
lines = log.read_text(errors="replace").splitlines()

start = None
for i, l in enumerate(lines):
    if "importing platform custom_components.deako.config_flow" in l:
        start = i
        break

if start is None:
    print("no deako import failure found")
else:
    # Traceback continuation lines are those not starting a new timestamped record.
    out = [lines[start]]
    for l in lines[start+1:start+60]:
        if re.match(r"^\d{4}-\d{2}-\d{2} ", l):
            break
        out.append(l)
    print("\n".join(out))
PY

echo ""
echo "== direct import attempt in HA context =="
cd "$HOME/ha-test-latest"
"$HOME/ha-venv-latest/bin/python" -c "
import sys; sys.path.insert(0, '.')
try:
    import custom_components.deako.config_flow as m
    print('config_flow imported OK')
except Exception as e:
    import traceback; traceback.print_exc()
" 2>&1 | tail -25
