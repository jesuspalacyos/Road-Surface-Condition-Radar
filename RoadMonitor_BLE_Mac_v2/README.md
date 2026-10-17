> **Firebase update:** Start with `CLOUD_START_HERE.md`. The Firebase configuration is already included. Existing firmware is unchanged.

# RoadMonitor BLE — XIAO ESP32-S3 + Mac

A local browser dashboard for ADXL335 acceleration, VL53L0X ground distance,
and NEO-6M GPS. Sensor readings travel over **Bluetooth Low Energy only**.
The ESP32 does not start Wi-Fi or need an access point. USB is used for programming
and may supply power. The Mac hosts the HTML locally; it is not receiving sensor
data through USB. This package does not integrate the separate TI radar board.

## What this prototype can tell you

| Display | Meaning | Limitation |
|---|---|---|
| Pothole indicator | Ground farther away than the flat-ground reference | A possible dip, not a confirmed pothole; suspension movement and tilt look similar |
| Debris / raised surface | Ground closer than the reference | Cannot distinguish debris from a bump or other surface |
| Vibration | Largest acceleration-vector change from the stationary reference in the last 0.1 s | Includes tilt, braking and movement; approximate g, not calibrated laboratory acceleration |
| Ice | Cannot be measured | These sensors do not measure ice or provide an ice-free determination |
| Route / speed | GPS position and GPS ground speed | Outdoor reception needed; position may wander by meters, especially at rest |

The VL53L0X is an optical distance sensor, not radar. Its downward view only sees
the small patch beneath it, not the lane ahead. Bright sunlight, dark/wet surfaces,
mount height, and vehicle motion can invalidate readings. Never convert an invalid
reading into a pothole. A temperature/humidity sensor alone would also not prove ice;
reliable ice identification needs an appropriate sensing method and validation.
This is a bench / controlled-course research prototype, not a driver safety system.

## 1. Wiring — unplug USB before making connections

These instructions assume **sensor breakout boards** with labeled pins, not loose
surface-mount chips. Check your breakout's power rating before applying power.
All grounds must connect together. ESP32 inputs must not receive 5 V.

| Sensor signal | XIAO header label | ESP32-S3 GPIO |
|---|---|---:|
| ADXL335 X / XOUT | D0 / A0 | 1 |
| ADXL335 Y / YOUT | D1 / A1 | 2 |
| ADXL335 Z / ZOUT | D2 / A2 | 3 |
| VL53L0X SDA | D4 | 5 |
| VL53L0X SCL | D8 | 7 |
| NEO-6M TX / TXD | D7 / RX | 44 |
| NEO-6M RX / RXD | Leave disconnected | — |
| All sensor GND pins | GND | — |

Supply details:

- **ADXL335:** for a breakout supporting a 3.3 V supply, connect its supply input
  to XIAO 3V3 and GND to GND. The bare IC permits 1.8–3.6 V. Some boards have an
  onboard regulator: measure the actual sensor supply and consult the board schematic.
  Firmware assumes the sensor itself operates at 3.3 V, nominal zero = 1650 mV and
  sensitivity = 330 mV/g. Adjust ZERO_MV and MV_PER_G if your board differs.
  An external ADC is not required; this XIAO has analog inputs.
- **VL53L0X:** connect a 3.3 V-compatible breakout's VIN/VCC to 3V3; keep I²C pull-ups
  at 3.3 V. Breakouts normally include pull-ups; bare sensors need the manufacturer's
  support circuit and are not wired directly according to this table.
- **NEO-6M-0-001:** this part number identifies the receiver module, not a unique
  breakout. The module supply is 2.7–3.6 V. If your breakout accepts 3.3 V on its
  power input, use 3V3. Some regulator-equipped breakouts require a higher VIN;
  follow their schematic/rating, and verify TX is 3.3 V logic before connecting D7.
  Do not assume every board labeled NEO-6M has the same VIN requirement.
- Use a stable supply with adequate current for the board and sensors. Do not tie
  together independently powered supply outputs. Grounds must still be shared.
- Attach the XIAO's supplied external Bluetooth/Wi-Fi antenna. Firmware uses only
  BLE, but the antenna is still needed. Keep GPS's antenna facing the sky.
- This uses the standard XIAO ESP32-S3 headers. Leave the Sense camera/SD subsystem
  unused if your board is a Sense version; this sketch does not initialize it.

Mount the accelerometer rigidly to the test platform. Mount the distance sensor
facing straight down, initially about **10–60 cm** above a matte flat surface.
Do not change sensor orientation or height after calibration. Clear the optical
window and remove any shipping protection if present. A hand-held sensor or moving
mount will create misleading “surface” changes.

## 2. Install and upload with Arduino IDE on macOS

1. Install Arduino IDE 2 from https://www.arduino.cc/en/software.
2. In Settings → Additional Boards Manager URLs, add:
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
3. In Boards Manager, install **esp32 by Espressif Systems** (3.x).
4. Select **XIAO_ESP32S3** and its USB serial port under Tools.
5. Set **USB CDC On Boot → Enabled**, if shown, to view diagnostic serial output.
6. In Library Manager install:
   - **Adafruit VL53L0X** by Adafruit; accept dependencies.
   - **TinyGPSPlus** by Mikal Hart.
   BLE and Wire are included in Espressif's board package. Do not install ArduinoBLE
   or an old standalone ESP32 BLE library for this sketch.
7. Open `XIAO_RoadMonitor_BLE/XIAO_RoadMonitor_BLE.ino`, verify, and upload.
8. Open Serial Monitor at **115200 baud**, then press RESET. Expect:
   `BLE advertising: RoadMonitor-S3. Open dashboard in Chrome, then Connect.`
   The next line reports whether the distance sensor was found.

If upload cannot find the board, use a USB data cable. Hold BOOT while plugging in
USB (or hold BOOT, press/release RESET, release BOOT), select the new port and retry.
If Arduino reports the sketch is too large, choose a partition scheme with more
application space, such as **Huge APP**, if available. No OTA updates are used.

BLE starts before sensor initialization and does not wait for Serial Monitor or GPS.
A missing GPS or disconnected distance sensor should therefore not hide the BLE device.
The accelerometer's analog plausibility flag cannot reliably detect every wiring error.

## 3. Open the browser dashboard on your Mac

Keep all extracted files together. For example, if the extracted folder is in Downloads:

```bash
cd ~/Downloads/RoadMonitor_BLE_Mac_v2
python3 start_dashboard.py
```

The launcher opens Google Chrome on a Mac. If it does not open automatically, open
Chrome manually and visit:

**http://localhost:8000/dashboard.html**

Keep Terminal running. Press Control+C in Terminal when finished. If you extract the
folder elsewhere, type `cd `, drag the extracted folder into Terminal, then press Enter.
If `python3` is missing, install Python 3 from https://www.python.org/downloads/macos/.
The launcher uses only Python's standard library, binds to loopback, and does not
expose the server to other computers. No npm installation is needed.

Alternatively, from the same folder:

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

Then open the URL above in Chrome yourself. Do not run both server commands at once.
Do not open this in Safari/Firefox or inside a file preview. Use the localhost URL.

1. Turn on Mac Bluetooth.
2. Allow Google Chrome in System Settings → Privacy & Security → Bluetooth when asked.
   Older macOS releases call this System Preferences → Security & Privacy.
3. Click **Connect sensor** and select **RoadMonitor-S3**.
   Connect from the browser, not by pairing in macOS Bluetooth settings.
4. Keep the mounted sensors still over flat ground and click **Calibrate on flat ground**.
5. Wait three seconds; Calibration should become **Complete**. Partial means one sensor
   failed calibration; check its mounting/wiring/range, then retry.
6. Bring GPS outdoors. Its first fix can take several minutes, and indoor fixes may fail.
   The map uses the NEO-6M, not your Mac's location.

With cloud disabled, the default offline route plot uses GPS coordinates, a moving marker, north-up grid,
and a distance scale; it has no street names. Turn on **Online street map (optional)**
for an OpenStreetMap basemap. That requires internet on the Mac (Ethernet works too),
not Wi-Fi on the ESP32. Fully offline operation still shows the GPS route and sensor
readings. Online tiles disclose the requested map area to the tile provider.

## 4. Controlled bench test

1. Click **Try simulated data** before connecting, to see the dashboard operate without
   hardware. Every simulation session is labeled, including its CSV observations.
   Stop simulation before using real measurements. New sessions clear old observations;
   export before starting another session or refreshing the page.
2. Upload and connect the real board. With sensors fixed in place, calibrate on a flat
   surface. Confirm ground distance roughly matches a ruler. Calibration is in RAM and
   is lost on reset. Calibration rejects excessive sample variation but does not prove
   the mounting or reference is correct.
3. Hold a flat card about 5–10 cm above that ground surface beneath the fixed sensor:
   a closer surface should produce a **possible raised surface** observation.
4. Move the ground target downward without moving the sensors: a farther surface should
   produce a **possible dip** observation. Keep a target within valid optical range.
5. Gently tap the mount to test vibration. Do not expect every vibration to be a pothole.
6. Outdoors, check that satellites/fix appear and the route follows your movement.
   GPS wandering while stationary is normal; do not interpret it as precise motion.
7. Remove power from the ESP32. The dashboard should mark disconnection and stop
   presenting the readings as live. A stalled notification stream becomes stale after
   two seconds; GPS telemetry becomes stale after three seconds.

## 5. Detection logic and tuning

Default exploratory thresholds (change under Setup, thresholds & connection help):

- Distance increase greater than 40 mm: possible dip.
- Distance decrease greater than 40 mm: possible raised surface.
- Vibration peak greater than 0.35 g: strong movement.

Distance observations require two consecutive 10 Hz packets, so very brief events
can be missed. Event logging has a shared two-second cooldown and retains the most
recent 1,000 observations; the screen shows 12. The route retains 5,000 points.
This is not continuous high-speed road profiling. Calibrate and tune against known
surfaces at controlled speeds before evaluating performance. No classification
accuracy is claimed. A “no flag” result means only that the available reading did
not cross the threshold, not that the road is safe.

ADXL335 is sampled about 100 Hz (actual timing depends on I²C/ADC workload); its peak
vector difference from stationary calibration is sent at 10 Hz. It is not a calibrated
RMS vibration measurement. VL53L0X runs at about 20 Hz; only status-0 readings between
30 and 1200 mm are accepted, and data older than 300 ms is invalid. This software bound
is not a promise of usable range on all surfaces. GPS UART is 9600 baud; GPS packets
are sent twice per second, which does not increase the receiver's underlying fix rate.

## 6. If the device does not appear / connect

- Check the board is **XIAO ESP32-S3**, power is stable, and its external antenna is attached.
- Reset with Serial Monitor open at 115200; look for the advertising message. If absent,
  check upload, board settings and any repeating crash messages. BLE must work before GPS fixes.
- Use desktop Chrome, localhost, Mac Bluetooth on, and Chrome's Bluetooth permission.
- Close phone BLE scanner apps and other browser tabs connected to the board. This code
  is intended for a single client. Reset the board and try again.
- Expand connection help and click **Find device without name filter** if the normal
  chooser stays empty. Choose only your board: unrelated devices lack this service.
- If the board appears but service discovery fails, upload this matching firmware,
  forget that site's Bluetooth permission in Chrome, reload and reconnect.
- Firmware automatically restarts advertising after disconnection; reconnect manually
  with the browser button. It does not silently reconnect to an old browser session.
- If connected but data is missing, check for a firmware reset or crash in Serial Monitor.
  Missing ToF: verify D4/D5, supply and GND, then reset after repairing wiring.
- No GPS serial data: GPS TX must go to **D7/GPIO44**, not D6. This is cross-wiring TX → RX.
  Check power and that the receiver outputs NMEA at 9600. If it was previously reconfigured,
  change the baud or restore its settings. “Data received” does not guarantee valid NMEA.
- GPS bytes but no fix: take it outdoors with a clear sky and wait. Check its antenna.
- If changing the board orientation, mounting height, or ADC supply, recalibrate.

## Files

- `XIAO_RoadMonitor_BLE/XIAO_RoadMonitor_BLE.ino`: firmware.
- `dashboard.html`, `style.css`, `app.js`: local dashboard (no CDN dependencies).
- `start_dashboard.py`: local server/Chrome launcher.
- `PROTOCOL.md`: packet layout, for later integration.

## Verification and limits

JavaScript syntax and automated DOM/logic checks were run for packet decoding, simulated
observations, connection/calibration controls with mocked BLE, malformed packets, and
missing/stale readings. Browser-engine rendering was not verified because its download
failed in this environment. The physical ESP32 and sensors were not available here, and
an ESP32 firmware build toolchain was not available. The sketch has not been compiled
or hardware-tested here; use Arduino Verify and the bench test above before deployment.

## Primary references

- XIAO pins / setup: https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/
- Pin multiplexing: https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/
- Chrome Web Bluetooth: https://developer.chrome.com/docs/capabilities/bluetooth
- ADXL335: https://www.analog.com/en/products/adxl335.html
- VL53L0X breakout: https://learn.adafruit.com/adafruit-vl53l0x-micro-lidar-distance-sensor-breakout
- VL53L0X API: https://github.com/adafruit/Adafruit_VL53L0X
- NEO-6 datasheet: https://content.u-blox.com/sites/default/files/products/documents/NEO-6_DataSheet_%28GPS.G6-HW-09005%29.pdf
- TinyGPSPlus: https://github.com/mikalhart/TinyGPSPlus
