#!/bin/bash
# Provision the LATEST Home Assistant, which needs a newer Python than the
# distro ships. uv is used to fetch that Python without touching system
# packages.
set -e
cd ~

if ! command -v uv >/dev/null 2>&1; then
  echo "== installing uv =="
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

echo "== installing python 3.14 =="
uv python install 3.14

echo "== creating venv =="
rm -rf "$HOME/ha-venv-latest"
uv venv --python 3.14 "$HOME/ha-venv-latest" >/dev/null

echo "== installing latest home assistant (several minutes) =="
VIRTUAL_ENV="$HOME/ha-venv-latest" uv pip install --quiet homeassistant 2>&1 | tail -5

echo "== version =="
"$HOME/ha-venv-latest/bin/hass" --version
"$HOME/ha-venv-latest/bin/python" --version
echo "DONE"
