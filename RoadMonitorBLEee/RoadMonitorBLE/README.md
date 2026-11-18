# Road Monitor • Pi 4 + BLE browser

A working software prototype for road-condition research. Hardware integration is not yet verified on your devices. Start with the demo, then bring up sensors, radar, BLE, and cloud in that order.

## What is included

- A clean browser dashboard: pothole candidates, raised-object/debris candidates, vibration, ToF road distance, radar status, GPS speed/location and moving route trail.
- Optional street-map tiles; an offline geographic route grid works without internet.
- Start / stop recording and road-level calibration from the browser via BLE.
- Pi SQLite recording at the sensor packet rate (~10 Hz with included firmware), persistent upload queue, Firebase Firestore backup, CSV export.
- TI AWR6843ISK **SDK 3.x out-of-box Cartesian point-cloud reader**. Other radar firmware formats are not interchangeable.
- XIAO ESP32-S3 example firmware for **VL53L0X + ADXL335 + NEO-6M**, based on your previously discussed parts. Confirm models and pins before flashing.
- No Firebase private key is included in this package or browser. Your uploaded key parsed correctly, but its Google authentication has not been tested.

## What this does not establish

**Ice detection is not implemented or validated.** The ice tile always says “Not verified.” A standard TI point cloud or a low return amplitude cannot reliably distinguish ice, water, dry road, tilt or signal loss. Achieving ice detection needs labeled dry/wet/ice measurements, suitable range/reflectivity features and a tested model, often with surface-temperature information. No fake ice alerts are produced.

Pothole/debris alerts are simple experimental candidates. Downward ToF measures a road-level change after calibration; acceleration measures bumps. Raised surfaces can be debris, a speed bump, sensor motion or terrain. Radar can provide supporting height evidence **only after mounting geometry is entered**; a missing radar return is never treated as a hole. Detection performance at vehicle speed is not established. At ~10 Hz, a vehicle at 60 mph travels ~2.7 m between samples; small potholes can be missed.

## Connection layout — no Wi-Fi needed

| Connection | Transport |
|---|---|
| ToF + accelerometer + GPS → XIAO | Wired I2C, analog, UART |
| XIAO → Pi 4 | USB serial |
| TI board → Pi 4 | USB CLI and data ports |
| Pi 4 → laptop browser | **BLE using the Pi's built-in Bluetooth** |
| Pi 4 → Firebase | Ethernet or another internet connection |

The XIAO remains the three-sensor reader. BLE originates on the Pi so the browser receives **both** radar and sensor data. BLE is not a cloud internet connection. Without Pi internet, data stays queued. The laptop can display telemetry without internet. Optional street tiles need internet on the laptop, not Wi-Fi specifically.

The browser files must exist on the laptop in advance: BLE carries telemetry/control, not a website download. The Pi browser can alternatively view its own localhost page with no network connection.

## 1. Preview the clean screen first

On Windows, extract this package, open a terminal in `RoadMonitorBLE`, and run:

```powershell
py -m http.server 8000 --bind 127.0.0.1 --directory web
```

Open **http://localhost:8000** in desktop Chrome or Edge. Click **Preview demo**. This is explicitly simulated data; it cannot upload or save recordings. The marker moves and the road tiles change.

On a Mac, use `python3` instead of `py`. The local file can be opened directly for preview, but localhost is the supported BLE route. Safari/Firefox/iPhone are not supported by this dashboard's Web Bluetooth connection. A local Pi browser can use “Use this Pi's browser” without Web Bluetooth.

## 2. Prepare the Pi

Copy/extract `RoadMonitorBLE` to your Pi home directory. For installation use Ethernet internet:

```bash
cd ~/RoadMonitorBLE
sudo apt update
sudo apt install -y python3-venv python3-pip bluetooth bluez
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sudo systemctl enable --now bluetooth
sudo rfkill unblock bluetooth
sudo usermod -aG dialout "$USER"
```

Log out and back in after adding `dialout`. Installation needs internet once. Normal telemetry and recording do not.

Confirm serial ports with:

```bash
.venv/bin/python -m serial.tools.list_ports -v
ls -l /dev/serial/by-id/
```

Prefer stable `/dev/serial/by-id/...` names. `/dev/ttyACM0` and `/dev/ttyUSB0/1` below are examples; **verify the CLI/data assignments**, which can swap. Close Arduino Serial Monitor and TI Visualizer before running this app.

## 3. Confirm the XIAO packet format

The Pi expects one JSON line per reading at 115200 baud, in explicit units:

```json
{"schema":"road-v1","tof_mm":580,"ax":0.01,"ay":0.02,"az":1.0,"gps_fix":true,"lat":32.985,"lon":-96.750,"speed_kmh":5.2,"satellites":8}
```

Acceleration is **g**, not ADC counts or m/s². A missing value must be `null`; no GPS fix must be `false`. Old firmware with different keys will show a format error; it is not silently guessed. Either adapt `normalize()` in `core.py` or upload the included sketch.

Optional firmware: open `firmware/ThreeSensors/ThreeSensors.ino` in Arduino IDE. Select **XIAO_ESP32S3**, enable **USB CDC On Boot**, and install **Adafruit VL53L0X** and **TinyGPSPlus** through Library Manager. Check existing wiring before changing it:

| Device signal | XIAO pin | GPIO |
|---|---|---|
| ADXL335 X / Y / Z | D0 / D1 / D2 | 1 / 2 / 3 |
| VL53L0X SDA / SCL | D4 / D5 | 5 / 6 |
| GPS TX → XIAO RX | D7 | 44 |
| GPS RX ← XIAO TX (optional) | D6 | 43 |

Share ground. Use 3.3 V-safe logic and each breakout's correct supply. The sketch assumes ADXL335 330 mV/g and approximate 1.65 V zero-g level; calibrate actual offsets/sensitivity. Your `accel_mv_per_g` setting is retained for reference, but conversion occurs in firmware (`MV_PER_G`), not in the Pi. `vertical_axis` defaults to `az`; change it to the installed vertical axis.

Start the sensor-only app first:

```bash
.venv/bin/python app.py --sensor-port /dev/ttyACM0 --control-code 482631
```

Choose your own six-digit code. On the Pi open **http://localhost:8000**, click **Use this Pi's browser**, enter the code. Confirm distance/acceleration. GPS needs a valid satellite fix, often outdoors. Calibrate while stationary over flat road, then start recording. The ToF must point down at the road; pointing it forward does not measure pothole depth.

## 4. Add the TI board

Use a **known-working `.cfg` exported for your exact installed SDK 3.x out-of-box firmware and AWR6843ISK antenna variant**. This package deliberately does not guess a radar profile or flash firmware. Tracking, people-counting and compressed point-cloud formats need a different parser.

Point-cloud output must be enabled in that profile (`guiMonitor` detectedObjects). Range profile output is optional; when present its mean is logged as a research feature, not an ice score. Firmware with no point TLV but a nonzero object count is rejected. Radar-only alerts are not generated.

Place the working profile at `~/RoadMonitorBLE/profile.cfg`, then:

```bash
.venv/bin/python app.py \
  --sensor-port /dev/ttyACM0 \
  --radar-cli-port /dev/ttyUSB0 \
  --radar-data-port /dev/ttyUSB1 \
  --radar-config profile.cfg \
  --control-code 482631
```

CLI is 115200; data defaults to 921600 (`--radar-baud` overrides). If the board is already configured and streaming, omit `--radar-config` and `--radar-cli-port`. Commands are acknowledged; configuration errors stop startup.

“TI radar: N returns” means valid received points inside the configured region, not N potholes.

For experimental radar support of a ToF event, edit `config.json` only after measuring mounting:

- `radar_mount_height_m`: radar height above a flat road (e.g. 0.5 only if measured).
- `radar_pitch_down_deg`: angle tilted down from a horizontal forward boresight.
- Coordinates assumed x lateral, y forward, z upward, zero roll. Incorrect orientation invalidates height estimates.
- Height = z·cos(pitch) − y·sin(pitch) + mount height. Median of at least 3 ROI points is compared with the same depth/raised thresholds.
- Region bounds are in **sensor coordinates**, before height transform. Tune them to select the road, not cars/sidewalks.

ToF and radar may view different road patches. Support is approximate, using radar frames less than two seconds old; time/position alignment, pitch/roll compensation and speed validation are still needed for moving-vehicle research. No mounting values are fabricated in the supplied config.

## 5. Turn on BLE to the laptop

Add `--ble` to the working command. On Pi OS, if BlueZ reports access denied, retry the same command using `sudo .venv/bin/python app.py ...` with the same explicit arguments. Do not run plain system Python outside the venv. Use an absolute key path if adding cloud. Root-created recordings may need ownership restored with `sudo chown "$USER":"$USER" recordings.sqlite*` after stopping the app.

On the laptop run the step 1 localhost server, open Chrome/Edge, click **Connect to Pi via BLE**, select **RoadMonitor-Pi**, enter the same six-digit code. Start/stop/calibration commands require it. Telemetry uses 20-byte chunks and typically refreshes near 1 Hz; local acquisition remains ~10 Hz. This research BLE service has no application-level telemetry encryption; the control code prevents accidental commands, not a determined nearby attacker. Use it in a controlled test setting.

If the chooser is empty: check Bluetooth power, distance, terminal errors, and ensure no other central is connected. If BLE disconnects, click Connect again; Pi recording continues. Reconnect does not retrieve a full historical route—only live GPS plus the recent event summary. Full history is in SQLite/Firestore.

## 6. Enable Firebase backup over Ethernet

Use your existing project **roadmonitor-16c51**. In Firebase Console, open **Build → Firestore Database** and create a database if none exists. This code uses **Cloud Firestore**, not Realtime Database. The server SDK uses service-account IAM permissions; making client security rules public does not fix a service-account problem.

Keep your service-account JSON on the Pi, **outside `web/`**:

```bash
mkdir -p ~/.config/roadmonitor
cp "$HOME/Downloads/firebase-key(1).json" ~/.config/roadmonitor/firebase-key.json
chmod 600 ~/.config/roadmonitor/firebase-key.json
```

Adjust the source location to wherever you copied the uploaded JSON. Add the cloud key to the working command:

```bash
.venv/bin/python app.py \
  --sensor-port /dev/ttyACM0 \
  --radar-cli-port /dev/ttyUSB0 \
  --radar-data-port /dev/ttyUSB1 \
  --radar-config profile.cfg \
  --ble \
  --cloud-key "$HOME/.config/roadmonitor/firebase-key.json" \
  --control-code 482631
```

The key is loaded explicitly; an old `GOOGLE_APPLICATION_CREDENTIALS` variable cannot override it. Click **Start recording**. Cloud “Synced” plus a last-sync time indicates a completed upload, not just an enabled setting.

Firestore records appear under:

`roadmonitors / road-pi-01 / records / <unique record ID>`

Each document includes session ID, timestamp, kind and data. All samples are recorded locally at the input rate. This package changes your uploaded `cloud_snapshot_s` from 30 to **1 second** for approximately live cloud snapshots, plus all generated events and session start/stop records. To reduce write volume, set it back to **30**, then restart. The queue survives app restarts and uses stable document IDs to avoid duplicate retry writes. No auto-deletion is performed; monitor SD-card capacity and cloud usage.

If the existing “Invalid JWT Signature” error returns, the dashboard will say the key was rejected. Generate a fresh key in **Project settings → Service accounts → Generate new private key**, replace the Pi key file, and restart. A syntactically valid key can still be revoked or mismatched. Keep the Pi time synchronized. Never put this key in browser JavaScript or send it to the ESP32.

## 7. Review recorded trips

Start/stop controls delimit sessions. To export all local history:

```bash
cd ~/RoadMonitorBLE
.venv/bin/python export.py --out recordings.csv
```

Use `--session <session ID>` for one trip; the dashboard's Connection details shows the current ID. CSV contains timestamps, session IDs, record kinds, sensor/radar JSON and upload status. This is the full recording; the live browser shows only recent events and its current connected route. Stop the app before copying the SQLite database (or use SQLite backup), because WAL files may contain recent writes.

## Test modes and limits

No hardware/dependencies needed for local demo:

```bash
python3 app.py --demo --db demo.sqlite --control-code 482631
```

Then use the Pi-local browser option. Unlike the browser-only preview, this demo can save simulated rows to its separate database. `--demo --cloud-key` is intentionally rejected.

Software checks: `python3 -m unittest discover -s tests -v`. Tests cover invalid values, GPS fix handling, calibration, candidate persistence, local recording, restart-persistent cloud queue, stale sensor status, radar geometry gating and fragmented/malformed UART frames. Tests do not prove physical BLE throughput, board firmware compatibility, cloud authorization, road accuracy or ice detection. Arduino sketch needs compilation/upload in your board environment.

## Sources

- TI AWR6843: https://www.ti.com/product/AWR6843
- TI mmWave SDK 3.5 guide: https://dr-download-cdn.ti.com/software-development/software-development-kit-sdk/MD-PIrUeCYr3X/03.05.00.04/mmwave_sdk_user_guide.pdf
- Web Bluetooth / secure-context requirements: https://developer.chrome.com/docs/capabilities/bluetooth
- Bless server API: https://github.com/kevincar/bless/blob/master/examples/server.py
- Firebase Admin setup: https://firebase.google.com/docs/admin/setup
- XIAO pins: https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/
- Example ice-classification research (not implemented here): https://www.mdpi.com/2072-4292/14/20/5252
