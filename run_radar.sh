#!/usr/bin/env bash
# Configure the radar and start a view/logger (Linux / WSL / Raspberry Pi).
#   ./run_radar.sh            live X/Y view
#   ./run_radar.sh log        headless logger
cd "$(dirname "$0")"
VENV="${RADAR_VENV:-$HOME/sd-venv}"
source "$VENV/bin/activate"
exec python run_radar.py "$@"
