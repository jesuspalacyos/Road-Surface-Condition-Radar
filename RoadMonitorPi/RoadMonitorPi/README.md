# Road Monitor for Raspberry Pi

Local browser dashboard for XIAO ESP32-S3 + VL53L0X + ADXL335 + NEO-6M and TI AWR6843ISK.
Includes a demo, live data, radar XY plot, GPS map/track, experimental road candidates,
CSV event export, and timestamped JSONL sensor/event logs in `logs/`.

## Connection design

Keep all three sensors wired to your existing working ESP32. Connect that ESP32
by USB to the Pi. Connect the TI board's USB data/control interface to another Pi
USB port. The Pi runs Python and displays the dashboard in Chromium on its monitor.
No BLE is required. Use adequate board power according to each board's manual.

The included ESP32 firmware is copied from your latest ThreeSensors_Windows(2)
package. If that firmware already works, do not upload it again.
Its XIAO ESP32-S3 pin mapping is:
- VL53L0X SDA = GPIO5 (D4), SCL = GPIO6 (D5).
- ADXL335 X/Y/Z = GPIO1/2/3 (D0/D1/D2).
- GPS TX -> GPIO44 (D7/RX); GPS RX <- GPIO43 (D6/TX).
- Common ground; preserve the supply wiring in your working setup.
The ADXL335 analog outputs cannot be connected directly to Pi digital GPIO inputs.

## 1. Install on Raspberry Pi OS

Download and extract RoadMonitorPi.zip into Downloads. Open Terminal:

```bash
cd ~/Downloads
unzip RoadMonitorPi.zip
cd RoadMonitorPi
sudo apt update
sudo apt install -y python3-venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py --demo
```

Open http://localhost:8000 on the Pi. Press **Calibrate on flat ground**; demo
calibration takes about 3 seconds. Simulated potholes occur around 6 seconds into
each 18-second cycle, raised objects around 12 seconds. Demo mode is always labeled.
Ctrl+C stops the server. Demo works without pyserial, but install it for hardware.

## 2. Identify real ports

```bash
source .venv/bin/activate
python app.py --list-ports
ls -l /dev/serial/by-id/
```

Unplug/reconnect one board at a time to identify it. ESP32 is often ttyACM0;
TI often exposes ttyUSB0 and ttyUSB1. These are examples, NOT guaranteed mappings.
Use the stable `/dev/serial/by-id/...` paths where possible. If permission is denied:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in before retrying. Close serial monitors; only one application
can own each serial port. Do not run the server with sudo.

## 3. Start with just the working three sensors

Replace the example port if your list differs:

```bash
python app.py --sensor-port /dev/ttyACM0
```

Check distance, accelerometer, GPS, and the latest raw packet in Diagnostics.
GPS generally needs a view of the sky. No fix means no map location; the app never
uses a made-up location in live mode. Missing ToF range is not treated as a pothole.

## 4. Add the TI radar

This parser supports mmWave SDK 3.x OUT-OF-BOX binary output: 40-byte header,
TLV 1 = float x,y,z,velocity, TLV lengths exclude the 8-byte TLV header.
It does not support compressed point-cloud, people-tracking or arbitrary custom
firmware. Firmware and config must match. No radar config is fabricated or included.
Copy YOUR WORKING full radar config into this folder as `profile.cfg`.
It must enable detected-point output and finish with sensorStart.

After confirming which interface is CLI vs DATA, replace the examples:

```bash
python app.py --sensor-port /dev/ttyACM0 --radar-cli-port /dev/ttyUSB0 --radar-data-port /dev/ttyUSB1 --radar-config profile.cfg
```

CLI default is 115200 baud; DATA default 921600; ESP32 default 115200.
Change data rate with `--radar-baud` if your firmware uses a different rate.
The app requires a Done response for each config command and reports the failing
command. If radar was already configured and is streaming, omit CLI/config:

```bash
python app.py --sensor-port /dev/ttyACM0 --radar-data-port /dev/ttyUSB1
```

No frames: check board power, port roles, configured data baud, correct firmware,
and whether sensorStart succeeded. Unsupported TLVs: use the appropriate firmware
parser before relying on radar data. Check the TLV types shown in Diagnostics.

## 5. Calibrate and evaluate

Mount ToF pointing down at a smooth flat surface within its valid range. Secure
all sensors; aim radar forward (+Y). Keep stationary and press Calibrate. Thirty
valid samples establish ground clearance and the vertical accelerometer baseline.
Motion during calibration is rejected. Calibration is intentionally required after
restarting. ADXL335 defaults to Z as the vertical axis; edit `vertical_axis` if needed.

`config.json` contains starting guesses, NOT validated detection thresholds:
- `depth_mm`: 50 mm clearance increase, plus vertical transient within 0.8 seconds,
  produces Possible pothole.
- `raised_mm`: 50 mm clearance decrease, plus a transient, produces Possible bump.
- Reduced clearance plus at least 3 consecutive radar frames containing a point
  in the forward region produces Possible raised object / debris.
- `shock_g`: 0.45 g approximate difference from stationary vertical baseline.
- `accel_mv_per_g`: 330 mV/g nominal starting value; calibrate YOUR sensor. Raw
  axis voltages remain available. This is not a calibrated vibration instrument.
- `event_cooldown_s`: 4 seconds per label; distinct nearby events may merge.
- Radar region defaults: X ±0.8 m, Y 0.2–4 m, in SENSOR coordinates.

Restart after editing settings. Thresholds must be tuned with labeled measurements
on your mounting setup. A 0.8-second evidence window is a prototype assumption,
not exact synchronization. Separate sensor positions and vehicle speed create
spatial offsets. Radar obstacles can include road returns, walls, vehicles and
people; no ground-plane compensation or debris identification model is provided.

Your existing firmware samples about 10 Hz. At 60 mph this is roughly one sample
every 2.7 m; narrow potholes can be missed. Start with stationary bench tests and
slow controlled measurements. Higher-rate acquisition, timestamp alignment,
mounting calibration and labeled validation are needed for vehicle-speed detection.
Outdoor ToF performance and vibration/tilt can also cause missing ranges or false
candidates. The system does not infer pothole depth from a single raw range.

ICE is always NOT ASSESSED: the current four devices and simple rules do not
reliably distinguish ice, wet road and dry pavement. A surface-temperature sensor
would provide useful extra evidence, but temperature alone still cannot confirm
ice; a validated surface sensing/classification method is required.

## Maps and saved data

Leaflet and OpenStreetMap tiles need internet on first load. Without internet,
readings/logs and numeric coordinates still work; the map explains missing assets.
There is no bundled offline street map. Map assets use unpkg.com and tiles use
OpenStreetMap; tile requests disclose the displayed map area to the tile provider.

Live location needs a current GPS fix and current serial packets. Old track is
retained with the position marker dimmed when fix is lost. Event markers show
vehicle GPS position at detection, not surveyed hazard coordinates. GPS accuracy
and sensor offsets limit location accuracy. Export contains the current session's
last 500 events. Full sample and event JSONL files persist in logs; demo and live
files have different prefixes. Radar raw bytes/point clouds are not logged.
Review/move logs periodically to avoid filling the Pi SD card. Session history
is not automatically reloaded after restart. The displayed trace is 160 samples.

Default access is only the Pi itself. For a laptop on the same trusted LAN, add
`--host 0.0.0.0` and open http://PI_IP_ADDRESS:8000. This service has no login or
TLS; do not expose it through router port forwarding or on an untrusted network.

## Verification and limits

The package was checked with synthetic fragmented radar frames, incompatible
TLVs, calibration, event rules, stale GPS, and HTTP demo/API checks. It has not
been connected to your physical hardware or validated for road classification.
Browser visual QA and physical integration remain to be done on your Pi.

Reference: TI SDK 3.x point structures:
https://git.ti.com/cgit/mmwave_radar/mmwave_ti_ros/tree/ros2_driver/src/ti_mmwave_rospkg/include/mmWave.h
Pi GPIO documentation:
https://www.raspberrypi.com/documentation/computers/raspberry-pi.html
