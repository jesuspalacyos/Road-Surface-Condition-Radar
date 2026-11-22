# Start here — Road Monitor on Raspberry Pi 4

## Connections
Three sensors → XIAO ESP32-S3 → Pi by USB.
TI AWR6843ISK → Pi by USB.
Pi → laptop browser by BLE. No Wi-Fi needed.
Pi → Firebase by Ethernet or USB internet tethering; without internet, recording stays local and uploads later.

## First: see the screen without hardware
Extract the ZIP. In the RoadMonitorBLE folder:

    python3 app.py --demo --db demo.sqlite --control-code 482631

On the Pi open http://localhost:8000 and click **Use this Pi’s browser**.
Enter **482631** in the control-code box. Click **Calibrate road level**, wait for calibration, then **Start recording**. This is simulated data, not a hardware test. Stop with Ctrl+C in the terminal.

## Install for real hardware (internet needed once)
In a Pi terminal:

    cd ~/RoadMonitorBLE
    sudo apt update
    sudo apt install -y python3-venv python3-pip bluetooth bluez
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
    sudo systemctl enable --now bluetooth
    sudo rfkill unblock bluetooth
    sudo usermod -aG dialout "$USER"

Log out and back in. Find the ports:

    .venv/bin/python -m serial.tools.list_ports -v

The following ports are examples. Confirm yours; close Arduino Serial Monitor and other radar applications first.

## Start sensors and BLE

    .venv/bin/python app.py --sensor-port /dev/ttyACM0 --ble --control-code 482631

Use your own six-digit code. Firmware must emit the road-v1 JSON format shown in README.md. The bundled sketch assumes VL53L0X, ADXL335 and NEO-6M; confirm your models and wiring before uploading.

## Add radar and cloud
Copy your known-working SDK 3.x out-of-box radar configuration into this folder as profile.cfg. Keep your Firebase service-account key outside web/, for example ~/.config/roadmonitor/firebase-key.json. Neither file is supplied in this ZIP.

    .venv/bin/python app.py \
      --sensor-port /dev/ttyACM0 \
      --radar-cli-port /dev/ttyUSB0 \
      --radar-data-port /dev/ttyUSB1 \
      --radar-config profile.cfg \
      --ble \
      --cloud-key "$HOME/.config/roadmonitor/firebase-key.json" \
      --control-code 482631

Omit --cloud-key and its path until your key is on the Pi. For radar height support, measure the mounting height and tilt and enter them in config.json; defaults deliberately leave this disabled. Radar firmware compatibility must be checked on your hardware.

## Laptop screen over BLE
Copy the web folder to your Windows laptop. In the RoadMonitorBLE folder run:

    py -m http.server 8000 --bind 127.0.0.1 --directory web

Open http://localhost:8000 in Chrome or Edge. Click **Connect to Pi via BLE**, select **RoadMonitor-Pi**, and enter the control code. Keep the Pi app running. BLE sends live data; no Wi-Fi network is used.

On the Pi itself, use **Use this Pi’s browser** instead; it reads localhost without BLE or a network.

## During a stationary / low-speed test
1. Point the ToF downward at flat road. Press **Calibrate road level** and hold still.
2. Wait for a GPS fix outdoors; the location marker and trail update automatically.
3. Press **Start recording**. Local readings persist even if the laptop disconnects.
4. Watch cloud status. **Synced** with a timestamp confirms a successful upload; **Queued** means data is waiting.
5. Press **Stop recording**. On the Pi browser, load **Saved trips**, review a trip, or download its full CSV.

Cloud history: Firebase Console → Firestore Database → roadmonitors → road-pi-01 → records. Cloud receives one snapshot per second plus events/session boundaries; the Pi keeps every sensor packet while recording. BLE does not transfer full saved-trip history.

## What the results mean
- Pothole: a possible drop measured by ToF; radar geometry can add experimental support.
- Debris: a possible raised surface, which may also be a speed bump or sensor motion.
- Ice: **Not verified**. There is no trained ice classifier in this project. Labeled dry/wet/ice data and validation are required before displaying an ice classification.
- Map: offline GPS trail works without internet; optional street tiles require internet on the viewing device.

Software tested here; physical sensors, BLE radio, radar firmware and Firebase credentials were not available for end-to-end verification. See README.md for wiring, port troubleshooting, calibration assumptions and limitations.
