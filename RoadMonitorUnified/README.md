# RoadSense unified dashboard

Combines RoadMonitorBLE telemetry, BLE controls, GPS route, SQLite recordings and optional Firebase backup with Water_Ice_Live experimental range-profile matching. Original source folders remain intact.

## Quick preview

From this folder: `python app.py --demo --db demo.sqlite --control-code 482631`
Open http://localhost:8000 and click **Preview demo** for simulated sensor and surface charts, or **Use this Pi's browser** for server telemetry and recording. Browser preview never records files. Server demo records simulated sensor samples only; surface matching requires a real range profile. Choose your own control code for hardware use.

## Hardware

Install `python -m pip install -r requirements.txt`. Sensor-only, BLE and cloud commands remain as documented in ORIGINAL_ROADMONITOR_README.md. Add surface matching:

```powershell
python app.py --sensor-port COM5 --radar-cli-port COM3 --radar-data-port COM4 --radar-config road_profile.cfg --surface --control-code 482631
```

Verify your actual ports and firmware first. Sensor input is optional for radar-only use. One serial reader feeds both point-cloud and range-profile decoders. Surface mode requires the exact bundled training config SHA-256; it does not claim that firmware or physical mounting is compatible. Never run the original live.py against the same serial ports at the same time.

Surface results use one-second median windows and the original model's unknown rejection. They are experimental sample matches, not validated ice detection or probabilities. Stale matches disappear after two seconds. Surface records join the existing SQLite/cloud queue while recording. `python export.py --out recordings.csv` exports full recorded history; the dashboard exports up to 60 visible surface samples.

The interface supports narrow phones through wide desktops, keyboard focus, touch targets and reduced-motion preferences. Web Bluetooth support depends on browser/platform; unsupported phones can use browser preview. The server binds localhost for local hardware control.

## Checks

`python -m unittest discover -s tests -v`


## OpenStreetMap, Firebase and complete CSV downloads

OpenStreetMap street tiles are enabled by default and need no API key or billing setup. The map follows Pi GPS with a recent route and pothole/raised-object candidate markers. Street tiles need internet; an offline route grid remains available. OpenStreetMap attribution stays visible. No location is presented as a live fix without GPS.

On the Pi, keep your Firebase service-account JSON outside this project and web directory. Add `--cloud-key /home/YOUR_USER/.config/roadmonitor/firebase-key.json` to your hardware command. Create/enable Firestore in the intended project. The service-account project selects the destination; records use `roadmonitors/road-pi-01/records`. Recording uploads periodic sensor snapshots, surface records, events and trip boundaries. The persistent queue retries after outages. The cloud tile reports confirmed sync or errors; demo mode refuses cloud upload. Local sensor records are preserved at input rate; cloud snapshot frequency is configured in config.json.

Click Start recording after calibration. Download recorded CSV exports the current trip or all local history from the server, with UTC times, separate unit-labeled columns, GPS, pothole/debris candidates, experimental surface results, evidence and cloud status. Empty cells mean unavailable; Yes/No are explicit booleans. UTF-8 BOM and standard CSV quoting support Excel. CSV itself cannot carry colors or column widths. Download live-view CSV includes the last 10,000 received browser snapshots and works over BLE, including clearly marked simulated preview readings.

Full Pi database downloads require the Pi HTTP API. For a laptop, use `ssh -L 8001:127.0.0.1:8000 YOUR_USER@PI_ADDRESS`, then open http://localhost:8001 and choose Connect to local server. The default server remains bound to localhost. A BLE-only session cannot retrieve the complete database; use the live-view CSV or `python export.py --out trip.csv` on the Pi.

The current sensor reader expects the bundled XIAO/ESP32 `road-v1` JSON over USB. Direct Pi GPIO sensors need a driver matched to the exact modules, wiring and ADC; ADXL335 analog outputs require an ADC. Do not select example serial devices without verifying them.

Live runs also accept ROADMONITOR_FIREBASE_KEY as the credential-file path; explicit --cloud-key overrides it. Demo runs ignore this environment setting. On the Pi, set it to the path of the credential file actually stored on that Pi. Credentials are never embedded in the website.
