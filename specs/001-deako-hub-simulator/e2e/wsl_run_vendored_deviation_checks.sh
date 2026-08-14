#!/usr/bin/env bash
# Run the vendored-pydeako deviation checks against the simulator.
#
# Everything runs inside WSL/Linux on loopback only. It never touches the LAN:
# the simulator binds 127.0.0.1 and its mDNS advertisement is suppressed, so the
# real house hub and the live Home Assistant cannot be reached or confused by it.
#
# WHY WSL AND NOT WINDOWS: pydeako's _SocketConnection.connect_socket does
#   address, port = self.address.split(":")
#   await self.loop.sock_connect(self.sock, (address, port))
# passing the port as a *str*. getaddrinfo tolerates that on POSIX; on Windows it
# raises "'str' object cannot be interpreted as an integer" and no connection is
# ever made. True of stock 0.3.1, stock 0.6.0, and the vendored copy alike.
#
# The checks import the vendored library from custom_components/deako/pydeako and
# refuse to run against an installed pydeako, so this venv deliberately does NOT
# install one -- only the simulator's own dependencies.
#
# Usage (from anywhere, inside WSL):
#   bash specs/001-deako-hub-simulator/e2e/wsl_run_vendored_deviation_checks.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK_DIR="${DEVIATION_WORK_DIR:-$HOME/deviation-checks}"
SIM_PORT="${DEVIATION_SIM_PORT:-8023}"
HTTP_PORT="${DEVIATION_HTTP_PORT:-8080}"

mkdir -p "$WORK_DIR"

if [ ! -x "$WORK_DIR/venv/bin/python" ]; then
    echo "== Creating virtualenv in $WORK_DIR/venv"
    python3 -m venv "$WORK_DIR/venv"
fi
"$WORK_DIR/venv/bin/pip" -q install aiohttp zeroconf jsonschema

cd "$REPO_ROOT"
exec "$WORK_DIR/venv/bin/python" \
    specs/001-deako-hub-simulator/e2e/vendored_deviation_checks.py \
    --port "$SIM_PORT" --http-port "$HTTP_PORT" "$@"
