#!/usr/bin/env bash
# Run the zero-dim regression experiment for oaa8/deako-house-wayfinder#12.
#
# Everything runs inside WSL/Linux on loopback only. It never touches the LAN:
# the simulator binds 127.0.0.1 and its mDNS advertisement is suppressed (see
# zero_dim_sim_runner.py), so the real house hub and the live Home Assistant
# cannot be reached or confused by this.
#
# WHY WSL AND NOT WINDOWS: pydeako's _SocketConnection.connect_socket does
#   address, port = self.address.split(":")
#   await self.loop.sock_connect(self.sock, (address, port))
# passing the port as a *str*. getaddrinfo tolerates that on POSIX; on Windows
# it raises "'str' object cannot be interpreted as an integer" and no connection
# is ever made. This is true of both 0.3.1 and 0.6.0.
#
# Usage (from the repo root, inside WSL):
#   bash specs/001-deako-hub-simulator/e2e/wsl_run_zero_dim_experiment.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK_DIR="${ZERO_DIM_WORK_DIR:-$HOME/zerodim}"
SIM_PORT="${ZERO_DIM_SIM_PORT:-8023}"
HTTP_PORT="${ZERO_DIM_HTTP_PORT:-8080}"

mkdir -p "$WORK_DIR"

setup_venv() {
    local dir="$1"
    shift
    if [ ! -x "$dir/bin/python" ]; then
        python3 -m venv "$dir"
    fi
    "$dir/bin/pip" -q install "$@"
}

echo "== Preparing virtualenvs in $WORK_DIR"
setup_venv "$WORK_DIR/venvsim" aiohttp zeroconf jsonschema
setup_venv "$WORK_DIR/venv031" "pydeako==0.3.1"
setup_venv "$WORK_DIR/venv060" "pydeako==0.6.0"

echo "== Starting simulator (loopback only, no mDNS)"
cd "$REPO_ROOT"
"$WORK_DIR/venvsim/bin/python" \
    specs/001-deako-hub-simulator/e2e/zero_dim_sim_runner.py \
    --port "$SIM_PORT" --http-port "$HTTP_PORT" > "$WORK_DIR/sim.log" 2>&1 &
SIM_PID=$!
trap 'kill "$SIM_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
    if grep -q "^READY" "$WORK_DIR/sim.log" 2>/dev/null; then break; fi
    sleep 1
done
grep "^READY" "$WORK_DIR/sim.log" || { echo "simulator failed to start"; tail -20 "$WORK_DIR/sim.log"; exit 1; }

run_pass() {
    local venv="$1" label="$2" proxy_port="$3"
    echo "== Running experiment under pydeako $label"
    "$WORK_DIR/$venv/bin/python" \
        specs/001-deako-hub-simulator/e2e/zero_dim_experiment.py \
        --label "$label" \
        --sim-port "$SIM_PORT" \
        --http-port "$HTTP_PORT" \
        --proxy-port "$proxy_port" \
        --out "$WORK_DIR/results-${label//./}.json" > "$WORK_DIR/run-${label//./}.log" 2>&1
}

run_pass venv060 0.6.0 8123
run_pass venv031 0.3.1 8124

echo "== Results"
ls -l "$WORK_DIR"/results-*.json
echo "Copy them next to the write-up with:"
echo "  cp $WORK_DIR/results-*.json $REPO_ROOT/specs/001-deako-hub-simulator/research/data/"
