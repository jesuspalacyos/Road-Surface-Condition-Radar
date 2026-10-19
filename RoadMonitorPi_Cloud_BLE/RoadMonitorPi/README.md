# RoadMonitorPi — filtered detections, BLE and Firebase

## What this update does

- Clear pothole, debris/raised-object, ice and storage cards, plus live sensor values,
  radar plot, GPS map and event export.
- Three-reading median range filter, two-reading persistence, accelerometer
  corroboration for potholes, three fresh radar frames for raised-object candidates.
- Raw sensor readings in JSONL; permanent candidate history and 30-second snapshots
  in SQLite. History reloads after restart; CSV exports all saved events.
- Optional authenticated Firebase Firestore uploads with an on-disk retry queue.
  Every event is uploaded; routine snapshots default to once every 30 seconds.
- Optional BLE from ESP32-S3 to Pi, automatic reconnect and fragment-loss rejection.
  USB sensor input remains available. Use only one sensor transport at a time.

These are **experimental candidates**, not a validated road classifier. No recorded
candidate does not establish a safe or clear road. Ice is **not assessed**; neither
this code nor your point-cloud configuration contains an ice model.

## Wiring / assumptions

This package uses the sensor wiring in your uploaded project:

**VL53L0X + ADXL335 + NEO-6M → XIAO ESP32-S3 → USB OR BLE → Raspberry Pi**

**TI AWR6843ISK → USB → Raspberry Pi → internet → Firebase**

The ESP32 is a BLE peripheral; the Pi is the BLE central. The browser reads the Pi's
local HTTP server. BLE does not supply an internet connection and does not carry
raw TI radar data. Power the ESP32 independently when removing its USB data cable.

| Sensor | XIAO ESP32-S3 connection |
|---|---|
| ToF SDA / SCL | GPIO5 / GPIO6 (D4 / D5) |
| ADXL335 X / Y / Z | GPIO1 / GPIO2 / GPIO3 (D0 / D1 / D2) |
| GPS TX → ESP RX | GPIO44 (D7) |
| GPS RX ← ESP TX | GPIO43 (D6) |

Keep the existing working power wiring and common ground. ESP32 GPIO inputs are
3.3 V signals. These pin assignments are for **XIAO ESP32-S3**, not all ESP32-S3
boards. Change the pin definitions if your board differs. If you wired sensors
straight to Pi GPIO, this firmware is not that driver: ADXL335 requires an external
ADC because the Pi has no analog inputs. Do not connect its outputs as digital data.

## 1. Install and try demo

Extract the downloaded ZIP in Downloads. The inner directory is `RoadMonitorPi`.
Use a fresh directory, or back up your old configuration and logs before replacing.

```bash
cd ~/Downloads/RoadMonitorPi
sudo apt update
sudo apt install -y python3-venv bluetooth bluez
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py --demo
```

Open **http://localhost:8000** on the Pi. Click **Calibrate on flat ground** right
after starting demo; keep the simulated baseline stable for 30 samples. Candidates
appear on the repeated demo cycle. Stop with Ctrl+C. Demo has separate files and
cannot be uploaded with `--cloud`.

## 2. Start your existing USB sensors first

If your current firmware emits the JSON fields in this package, keep it for USB.
For BLE you must upload the updated sketch in section 4.

```bash
source .venv/bin/activate
python app.py --list-ports
ls -l /dev/serial/by-id/
```

Identify ports by unplugging/reconnecting each board. Port numbers below are
**examples**, not detected facts. Prefer stable `/dev/serial/by-id/...` paths.

```bash
python app.py --sensor-port /dev/ttyACM0
```

Permission denied? Run `sudo usermod -aG dialout "$USER"`, then log out and back in.
Close Arduino Serial Monitor and other apps using the ports. Run Python without sudo.

## 3. Add radar

Copy your **known-working full TI configuration** into this folder as `profile.cfg`.
It is not in the uploaded ZIP, so no replacement configuration is invented here.
Use mmWave SDK 3.x out-of-box firmware with floating-point detected points (TLV 1).
The parser expects a 40-byte header and TLV payload lengths excluding TLV headers.
People-tracking/compressed-point-cloud firmware requires a different parser.

After verifying CLI and DATA port roles:

```bash
python app.py --sensor-port /dev/ttyACM0 --radar-cli-port /dev/ttyUSB0 --radar-data-port /dev/ttyUSB1 --radar-config profile.cfg
```

CLI uses 115200 baud and DATA defaults to 921600. Config commands must return Done.
If radar is already configured and streaming, omit `--radar-cli-port` and
`--radar-config`. The UI reports unsupported TLVs, stale frames and CLI errors.

## 4. Use ESP32-S3 BLE

In Arduino IDE:

1. Install Espressif **esp32** board support; choose Seeed XIAO ESP32S3 for that board.
2. Enable **USB CDC On Boot**. Install **Adafruit VL53L0X**, its dependencies and
   **TinyGPSPlus** using Library Manager.
3. Open `esp32_sensors/esp32_sensors.ino`, check the pins, then upload.
   The sketch uses the BLE library bundled with Arduino-ESP32, not NimBLE.
4. Stop any browser/phone app connected to this ESP32. It advertises `RoadMonitor-S3`.

On the Pi:

```bash
sudo systemctl enable --now bluetooth
rfkill unblock bluetooth
bluetoothctl power on
source .venv/bin/activate
python app.py --ble-address auto
```

If several boards have the same name, use `bluetoothctl scan on` to find yours;
stop scanning with `scan off`, exit with `quit`, and use its address instead of auto:

```bash
python app.py --ble-address AA:BB:CC:DD:EE:FF --radar-cli-port /dev/ttyUSB0 --radar-data-port /dev/ttyUSB1 --radar-config profile.cfg
```

This replaces the `--sensor-port` option. Keep radar USB connected. BLE JSON is
split into 20-byte notifications with sequence/index headers. A missing fragment
discards the whole sample. Default sample interval is 100 ms, but ToF reads and BLE
transmission can make the actual rate slower. If BLE is unreliable, keep USB for
measurements and test BLE on the bench. Firmware BLE is unencrypted and intended
for local prototype testing; add pairing/bonding before sensitive deployments.

## 5. Calibration and clean interpretation

Secure the sensors to the same rigid assembly. Point ToF down toward flat ground;
orient radar so +Y faces forward, and choose the physically vertical accelerometer
axis in `config.json`. Calibration must be repeated after a restart or mount change.

1. Keep assembly still on flat ground and click **Calibrate on flat ground**.
2. Wait for 30 valid samples. Excessive movement rejects calibration.
3. Start with slow controlled passes over a known depression and raised target.
4. Compare events to manually labeled observations; tune config and restart.

| Output | Required evidence / interpretation |
|---|---|
| Possible pothole | Median clearance increase over 50 mm, sustained for two filtered readings, and >0.45 g approximate vertical transient within 0.8 s |
| Possible raised object / debris | Median clearance decrease over 50 mm with persistence, plus at least three consecutive radar frames in configured region, latest <1 s old |
| Possible bump | Sustained clearance decrease plus transient without persistent radar evidence |
| Ice | Always not assessed; no validated model |

Median filtering rejects brief noise but **also removes real narrow events**.
At 60 mph, 10 Hz is one sample per 2.7 m; this package is not adequate for reliable
highway-speed pothole detection. BLE may reduce rate further. Thresholds are
starting guesses; suspension travel, mounting tilt, outdoor ToF failures, road
returns and passing objects can cause false positives or misses. A clearance change
is not a measured pothole depth. ADC sensitivity defaults to 330 mV/g; calibrate it.

`radar_z_min_m` / `radar_z_max_m` add a configurable height window in **radar
coordinates**. Default ±2 m is broad; set it from your mount tests. This is not
ground-plane removal. The radar sees ahead while ToF sees below; the 0.8-second
coincidence window does not prove they saw the same object. Speed-aware geometric
alignment and a validated classifier are needed for stronger debris identification.
GPS labels locate the vehicle at detection, not the exact defect. Missing fixes
leave events unlocated. The app does not invent GPS coordinates in live mode.

## 6. Firebase cloud storage

This implements upload support; **your Firebase account is not configured by this
ZIP**. The Pi needs internet via Wi-Fi, Ethernet or a hotspot. You do not need ESP32
Wi-Fi or a browser firebaseConfig. Upload happens from Python on the Pi.

1. Open https://console.firebase.google.com/ and choose/create your project.
2. Create a **Cloud Firestore** database in Native mode (default database), using
   production/locked rules. Do not enable public test-mode access.
3. Project settings → Service accounts → Generate new private key. Download the
   JSON securely to the Pi. Do not send it in chat or put it inside `static/`.
4. Move it outside the project and restrict permissions (change the source filename):

```bash
mkdir -p ~/.config/roadmonitor
mv ~/Downloads/YOUR-DOWNLOADED-KEY.json ~/.config/roadmonitor/firebase-key.json
chmod 600 ~/.config/roadmonitor/firebase-key.json
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/roadmonitor/firebase-key.json"
```

Set that environment variable again in each new terminal. The key's service account
must have permission to write Firestore (for example Cloud Datastore User).
Admin/server credentials use IAM, not the client Security Rules. Keep client rules
locked if only this Python app writes:

```text
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} { allow read, write: if false; }
  }
}
```

Then enable upload, adding your actual radar options if needed:

```bash
python app.py --sensor-port /dev/ttyACM0 --cloud
# OR BLE plus radar:
python app.py --ble-address auto --radar-cli-port /dev/ttyUSB0 --radar-data-port /dev/ttyUSB1 --radar-config profile.cfg --cloud
```

Review data in the Firebase console → Firestore → Data:

- `roadmonitors / road-pi-01 / events / <record ID>`
- `roadmonitors / road-pi-01 / samples / <record ID>`

The parent device document may appear as a missing/italic document because the
records live in its subcollections. Use the subcollections to inspect them.
Change `cloud_device_id` for each Pi, and keep that ID/project consistent while a
queue is pending. Historical unsent records upload when cloud is enabled.

The dashboard displays Local only, Uploading, Synced or Retrying, plus queue count.
On outage, readings continue locally; queued records retry with capped exponential
backoff. Stable record IDs make retries overwrite the same cloud document rather
than duplicate it. Errors are visible in Diagnostics. Missing credentials or an
uncreated database do not make local acquisition stop.

Default snapshots: 2 writes/minute (2,880/day if running continuously), plus events.
All original raw sensor packets stay on the Pi; they are not all uploaded.
Cloud radar snapshots retain at most 256 points plus the full point count.
Check your project's quotas/pricing and change `cloud_snapshot_s` as needed.
No remote web dashboard/login is deployed here: review cloud data in Firebase
console; review local history and map at the Pi dashboard.

## 7. Files, history and network access

- `logs/live.sqlite3`: all live events, sampled snapshots and upload queue.
- `logs/live_*.jsonl`: raw sensor packets and events for each run.
- Demo uses `demo.sqlite3` and `demo_*.jsonl` separately.
- History card counts/map use the most recent 500 events. CSV exports ALL SQLite
  events. Existing old JSONL files are not automatically imported into SQLite.
- Logs and SQLite are retained indefinitely. Monitor free disk space; stop the app
  before backing up/moving the SQLite file (or use SQLite's backup API). Do not delete
  the database if you need its unsent queue. Disk-full errors require intervention.

The dashboard is local by default. For another device on a trusted LAN, add
`--host 0.0.0.0` and open `http://PI_IP:8000`. There is no HTTP authentication or TLS;
keep it on a trusted network and do not port-forward it to the public internet.
Map assets and street tiles require internet and use Leaflet/OpenStreetMap.
Sensor acquisition, logs and numeric coordinates work without map access.

## 8. What is needed for ice detection

The existing point-cloud rules cannot distinguish dry, wet and icy pavement.
A surface-temperature sensor can add freezing-risk context but cannot confirm ice.
For an actual radar ice classifier, collect labeled dry/wet/ice measurements with
fixed mounting and a suitable road-looking radar configuration, retain surface
features such as range profiles, train a model, then evaluate on unseen surfaces,
temperatures, speeds and days. This package does not yet collect those training
features or include such a model. Never substitute "weak return = ice".

## Verification and sources

Run `python -m unittest discover -v`. Software tests cover noisy range rejection,
sustained candidates, invalid/stale readings, radar fragmentation, BLE loss, and
persistent upload retry. Demo HTTP/CSV and JavaScript syntax are checked separately.
Physical GPIO, Arduino compilation, live radar firmware compatibility, BLE RF
performance and authenticated Firebase writes must still be verified on your setup.

Official docs:
- https://firebase.google.com/docs/admin/setup
- https://firebase.google.com/docs/firestore/quickstart-server
- https://bleak.readthedocs.io/en/latest/backends/linux.html
- https://docs.espressif.com/projects/arduino-esp32/en/latest/api/ble.html
- https://www.ti.com/technologies/edge-ai/use-cases/surface-classification-mobile-robotics.html

TI's linked surface-classification example is for IWRL6432; it is background for
model development, not a drop-in AWR6843ISK ice detector.
