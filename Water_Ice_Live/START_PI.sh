#!/usr/bin/env bash
# Guided Raspberry Pi launcher; first install dependencies using README section C.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

PY="./.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "ERROR: Python virtual environment not found."
  echo "Run these commands first:"
  echo "  sudo apt update && sudo apt install -y python3 python3-venv python3-pip unzip"
  echo "  python3 -m venv .venv"
  echo "  ./.venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi

echo "======================================================"
echo " Water_Ice_Live  |  TI radar + XIAO ESP32 USB sensors"
echo "======================================================"
echo "Detected serial ports:"
"$PY" live.py --list-ports
if [[ -d /dev/serial/by-id ]]; then
  echo
  echo "Stable serial aliases:"
  ls -l /dev/serial/by-id/ || true
fi
echo

echo "Enter THREE DIFFERENT port paths from the list above."
read -r -p "Radar CLI/Application port (e.g. /dev/ttyUSB0): " CLI_PORT
read -r -p "Radar DATA/Auxiliary port (e.g. /dev/ttyUSB1): " DATA_PORT
read -r -p "ESP32 USB sensor port (e.g. /dev/ttyACM0, 'auto', or 'none'): " SENSOR_PORT

: "${SENSOR_PORT:=auto}"
if [[ -z "$CLI_PORT" || -z "$DATA_PORT" ]]; then
  echo "ERROR: Both radar ports are required." >&2
  exit 2
fi
if [[ "$CLI_PORT" == "$DATA_PORT" ]]; then
  echo "ERROR: Radar CLI and DATA must use different serial ports." >&2
  exit 2
fi

echo
echo "Starting radar + sensor server. Open http://<PI-IP>:8050 on your laptop."
echo "To identify PI-IP, run 'hostname -I' in a second terminal."
echo "Use the browser's Stop & save button to close cleanly."
echo
exec "$PY" live.py \
  --cli "$CLI_PORT" \
  --data "$DATA_PORT" \
  --sensor-port "$SENSOR_PORT" \
  --host 0.0.0.0 \
  --port 8050
