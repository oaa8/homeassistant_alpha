#!/bin/bash
# Extract the full traceback for the deako import failure.
HA_DIR="$HOME/ha-test-latest"

echo "== full traceback around deako config_flow import =="
awk '/Unexpected exception importing platform custom_components.deako.config_flow/,/^2026-.*(INFO|WARNING|ERROR)/' "$HA_DIR/ha.log" | head -40

echo ""
echo "== line 9 of the integration =="
sed -n '1,14p' "$HA_DIR/custom_components/deako/__init__.py"

echo ""
echo "== can the HA venv import the pinned deps? =="
"$HOME/ha-venv-latest/bin/python" -c "import atomics; print('atomics OK', atomics.__version__ if hasattr(atomics,'__version__') else '')" 2>&1 | tail -5
"$HOME/ha-venv-latest/bin/python" -c "import pydeako; print('pydeako OK')" 2>&1 | tail -5
