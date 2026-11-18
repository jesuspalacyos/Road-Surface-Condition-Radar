# Live Water / Ice Radar Capture

This package reads LIVE serial packets only. It never generates demo readings.
Designed for the TI AWR6843ISK with compatible SDK 3.x out-of-box firmware that emits range-profile TLV type 2, as expected by the supplied original program.

## Run on Windows (Command Prompt)
Extract the ZIP. Open its Water_Ice_Live folder containing live.py.
Click File Explorer's address bar, type cmd, and press Enter.
Run each command separately:

py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe live.py --list-ports

Connect the radar by USB; close other radar apps that use its serial ports.
Find its Application/CLI UART and Auxiliary/DATA UART in the list or Device Manager.
Then run (COM3/COM4 are examples; replace with YOUR port numbers):

.venv\Scripts\python.exe live.py --cli COM3 --data COM4

No batch launcher or virtual-environment activation is needed.
CLI uses 115200 baud, DATA defaults to 921600. Override DATA using --baud if your firmware requires it.
This command sends the included road_profile.cfg and starts the sensor. It rejects configurations whose hash differs from the saved reference samples. Reusing other configurations requires new compatible training samples.

## Browser debug page (default)
live.py now shows its debug view in a web browser instead of a plot window:

    .venv\Scripts\python.exe live.py --cli COM4 --data COM3      (Windows)
    python3 live.py --cli /dev/ttyUSB0 --data /dev/ttyUSB1          (Pi / Linux)

Then open http://localhost:8050 in a browser. On a headless Pi, open http://<Pi IP address>:8050 from a laptop or phone on the same network.
The page shows status, prediction, frame rate, malformed packets, match distances, feature bins 3-6, a 60 s prediction timeline, the latest full range profile, and each radar config command's response.
"Stop & save" on the page (or Ctrl+C) sends sensorStop, closes the ports and saves the PNG, exactly like closing the old window.
Options: --port 8050 (web port), --host 0.0.0.0 (use 127.0.0.1 to allow this computer only), --window (old matplotlib window).
CSV/PNG/metadata outputs are unchanged. The original script is kept as live_original.py.

## What happens
The plot shows live match distances, four range-bin readings, and a dry/water-wet/ice/unknown prediction. Classification starts after one second of valid data and uses a trailing one-second median, updating up to five times per second. Windowing adds response delay. The display refreshes about twice per second and shows the latest minute.
Close the plot or press Ctrl+C to stop. The program sends sensorStop, closes the ports, and saves a full-session PNG line plot if any predictions were produced.

outputs/ contains timestamped files:
- *_raw.csv: all 256 range bins for every decoded frame, UTC timestamp, Unix timestamp, and radar frame ID.
- *_predictions.csv: elapsed time, frame, live_serial source, unknown ground truth, predicted label, separation margin, median counts for bins 3-6, and class distances.
- *.png: full-session line plot, saved on normal exit or handled acquisition error.
- *.metadata.json: capture configuration and port settings.
CSV files flush during capture. Force-killing the process may prevent the final PNG.
cli_live_log.txt records radar configuration responses. A 10-second absence of valid TLV 2 data stops acquisition with an error; no substitute data is used.

## Interpreting the readings
The reference data is the original surface_samples.json: one labeled session per dry, wet, ice, 15 windows each. Wet is displayed as water/wet; it is not specifically validated standing-water detection. Bins 3-6 correspond approximately to 0.73-1.46 m with the supplied configuration. Keep the same mounting geometry and target region as the labeled training captures.
Classification uses normalized distance to median class templates and rejects distant or ambiguous inputs. Separation margin is not a confidence probability. Raw processed range-profile counts are not calibrated power. These features can change with geometry and background; unknown is an expected outcome.
This is experimental surface-region matching, not validated ice detection or localization of multiple objects. Collect multiple independent labeled sessions for every surface and evaluate on separate sessions before claiming accuracy. No physical radar was available to validate serial acquisition in this environment.
