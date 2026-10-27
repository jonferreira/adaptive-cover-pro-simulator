#!/usr/bin/env bash
# Adaptive Cover Pro Simulator — launcher (macOS / Linux)
#
# Creates a local virtualenv (".venv") on first run, installs the
# dependencies from requirements.txt, then starts the web UI at
# http://127.0.0.1:8765
#
# Usage:  ./run.sh

set -euo pipefail

SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_NAME="$(basename "$SIM_DIR")"
ACP_ROOT="$(dirname "$SIM_DIR")"

VENV_PY="$SIM_DIR/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  echo "Creating virtual environment in .venv ..."
  python3 -m venv "$SIM_DIR/.venv"
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PY" -m pip install -r "$SIM_DIR/requirements.txt"
fi

echo "Starting Adaptive Cover Pro Simulator at http://127.0.0.1:8765"
cd "$ACP_ROOT"
exec "$VENV_PY" -m uvicorn "$SIM_NAME.server:app" --host 127.0.0.1 --port 8765
