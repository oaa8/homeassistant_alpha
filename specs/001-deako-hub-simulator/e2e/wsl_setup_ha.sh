#!/bin/bash
# Provision a throwaway Home Assistant instance in WSL for simulator validation.
# This is a disposable test instance -- it is NOT the user's real home setup.
set -e

HA_DIR="$HOME/ha-test"
VENV="$HOME/ha-venv"

echo "== creating venv =="
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip wheel

echo "== installing home assistant (this takes several minutes) =="
"$VENV/bin/pip" install -q homeassistant 2>&1 | tail -5

echo "== version =="
"$VENV/bin/hass" --version

mkdir -p "$HA_DIR/custom_components"
echo "HA_DIR=$HA_DIR"
echo "DONE"
