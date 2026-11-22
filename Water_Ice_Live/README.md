# Water_Ice_Live — Raspberry Pi setup and operating guide

This ZIP is a **complete updated `Water_Ice_Live` folder**, combining the original TI AWR6843ISK radar water/ice browser display with live XIAO ESP32-S3 USB-serial readings from the VL53L0X ToF sensor, ADXL335 accelerometer, and NEO-6M GPS. It includes stationary **ToF/accelerometer baseline calibration** from the browser.

**Important:** The dry/wet/ice radar classifier is an experimental match to recorded examples; the **Calibrate** button does *not* recalibrate, retrain, or validate the radar classifier. Do not use the surface classification as a road-safety system.

## A. What you need

- Raspberry Pi with Raspberry Pi OS, internet access during setup, Python 3, a working power supply, and an SSH session or an attached keyboard/monitor.
- TI AWR6843ISK radar connected to the Pi over USB. Its USB interface exposes **two ports**: a **CLI/Application** port (115200 baud) and **DATA/Auxiliary** port (921600 baud in this project).
- XIAO ESP32-S3 connected over a **data-capable** USB cable. Its firmware must send line-delimited sensor **JSON over USB serial at 115200 baud**, not just Bluetooth. One compatible sketch is included under `esp32_sensors/esp32_sensors.ino`.
- Laptop/phone on the **same local network** as the Pi to view the browser dashboard (or browse directly on the Pi).
- Stop any other application, including the TI visualizer, Arduino Serial Monitor, or an existing radar service, that is using the same serial ports.

All commands in the **Pi Terminal** sections below run on the Raspberry Pi, **not** in Windows PowerShell. Replace example usernames, addresses, and serial ports with yours.

## B. Copy ZIP to the Pi

**Option 1 — Windows laptop to Pi via SSH/SCP.** Download `Water_Ice_Live_ESP32_Integrated.zip` to your Windows Downloads folder. In **Windows PowerShell**, run these commands, changing the username and IP to your Pi's:

```powershell
# RUN ON WINDOWS (PowerShell). Replace these two values.
$PiUser = "pi"
$PiIP = "192.168.1.100"

# Send ZIP from your Windows Downloads folder to the Pi's home directory.
scp "$env:USERPROFILE\Downloads\Water_Ice_Live_ESP32_Integrated.zip" "${PiUser}@${PiIP}:~/"

# Open an SSH terminal on the Pi.
ssh "${PiUser}@${PiIP}"
```

If SSH is disabled, enable it from Raspberry Pi Imager's OS customization or from Raspberry Pi Configuration; or move the ZIP using a USB drive instead. If you're already using a Pi desktop/browser, download the ZIP to `~/Downloads` and move it to `~/`:

```bash
# RUN ON THE PI, only if the ZIP is in ~/Downloads:
cp "$HOME/Downloads/Water_Ice_Live_ESP32_Integrated.zip" "$HOME/"
```

## C. Install the app on Raspberry Pi — first time only

In a **Pi terminal** or **SSH session**, copy/paste this whole block:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip unzip
cd "$HOME"
unzip -o Water_Ice_Live_ESP32_Integrated.zip
cd "$HOME/Water_Ice_Live"
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

The archive already has a `Water_Ice_Live/` top-level folder; after extraction, the program is at `~/Water_Ice_Live/live.py`. Do **not** `cd Water_Ice_Live/Water_Ice_Live`.

**Raspberry Pi OS Bookworm or newer:** the virtual environment (`.venv`) is important. Do not use `sudo pip install` or `--break-system-packages`.

To check dependencies and see available devices:

```bash
cd "$HOME/Water_Ice_Live"
./.venv/bin/python live.py --list-ports
ls -l /dev/serial/by-id/ 2>/dev/null || true
```

If you get `Permission denied` when opening a `/dev/ttyUSB*` or `/dev/ttyACM*` port, run **once**:

```bash
sudo usermod -aG dialout "$USER"
sudo reboot
```

The reboot closes your SSH connection. Reconnect with `ssh` after the Pi comes back, then re-run `--list-ports`. **Do not use `sudo python`** as a workaround.

## D. Identify the three USB serial ports

Connect the radar and ESP32, then run:

```bash
cd "$HOME/Water_Ice_Live"
./.venv/bin/python live.py --list-ports
ls -l /dev/serial/by-id/ 2>/dev/null || true
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true
```

You need three different ports. **For example only** (yours may differ, and order may change on reboot):

| Hardware connection | Typical Linux port | Baud |
| --- | --- | --- |
| Radar CLI / Application UART | `/dev/ttyUSB0` | 115200 |
| Radar DATA / Auxiliary UART | `/dev/ttyUSB1` | 921600 |
| XIAO ESP32-S3 sensor USB | `/dev/ttyACM0` | 115200 |

If unsure which port is the ESP32, unplug **only** the ESP32 USB cable, run `--list-ports`, reconnect it and repeat; the new entry is the ESP32. To distinguish the two radar ports, check the device descriptions and `/dev/serial/by-id` interface names. If radar configuration fails, ensure the CLI and DATA ports have not been swapped. `/dev/serial/by-id/...` paths can be used instead of `/dev/ttyUSB0` to make assignment more stable, when available.

## E. Launch the dashboard — choose ONE method

### Method 1: guided Pi launcher (easiest)

Copy/paste on the Pi:

```bash
cd "$HOME/Water_Ice_Live"
bash START_PI.sh
```

It lists the ports and prompts for **radar CLI**, **radar DATA**, and **ESP32** device paths, then starts the browser app. The launcher uses the `.venv` you installed in Section C.

### Method 2: direct command (explicit and repeatable)

**Replace all three example paths with your actual serial device paths** discovered in Section D:

```bash
cd "$HOME/Water_Ice_Live"
./.venv/bin/python live.py \
  --cli /dev/ttyUSB0 \
  --data /dev/ttyUSB1 \
  --sensor-port /dev/ttyACM0 \
  --host 0.0.0.0 \
  --port 8050
```

The program runs **in the foreground** and prints status or errors in this terminal. Leave the terminal open while using it. To run **radar only** for debugging, replace `--sensor-port /dev/ttyACM0` with `--sensor-port none`.

Optional: If your connected ESP32's accelerometer **vertical** axis is not Z, add `--cal-axis ax` or `--cal-axis ay`; the default is `az`. If the radar DATA firmware expects a different baud rate, set `--baud`, but **921600 is the default for the provided config**.

## F. Open the browser from your laptop

From another Pi terminal (or a second SSH session), find its local IP:

```bash
hostname -I
```

If it prints `192.168.1.100`, open **http://192.168.1.100:8050** in your laptop browser. Use your *actual* IP. On the Pi itself use **http://localhost:8050**.

To check that the server is responding locally from a second Pi terminal:

```bash
curl -s http://127.0.0.1:8050/api/state | python3 -m json.tool | head -n 50
```

If the page doesn't load: check both devices are on the same network, the application terminal is still running, the right IP/port is used, and that no firewall or network client-isolation rule is blocking port 8050. The dashboard is intended for a **trusted LAN**, not exposed directly to the internet.

## G. Verify each sensor and calibrate

1. **Radar:** the page should display a growing frame count, a range profile, and eventually the predicted class. The first radar prediction requires about one second of valid frames.
2. **ESP32:** the sensor status should say connected/online and sensor packet count should increase (about 10 messages/second with the included firmware). Look at the **Latest ESP32 serial line** and any error message if it doesn't.
3. **VL53L0X:** a nonblank, valid distance is required for calibration. If it reads invalid or `—`, verify I²C wiring and the distance to a suitable surface.
4. **ADXL335:** accelerometer values should be present. The calibration assumes the selected axis corresponds to the physically vertical axis; use `--cal-axis` if needed.
5. **NEO-6M GPS:** a valid outdoor GPS fix may take time. GPS is **not necessary** for calibration.
6. With the sensor assembly **fully stationary over a stable, flat surface**, press **Calibrate on flat ground**. The app collects **30 valid ToF + accelerometer readings**, usually around 3 seconds with 10 Hz reporting. It rejects samples if distance varies by more than **30 mm** or the chosen accelerometer axis varies by more than **35 mV**; it times out after 15 seconds if enough valid data is not received.
7. Once calibrated, the browser shows relative clearance changes (mm) and approximate acceleration changes (g) from that baseline. **Calibration is held in RAM and resets whenever the program restarts.**

**Important: calibration does not change the radar water/ice model.** The model depends on the supplied training samples and radar `road_profile.cfg`, which this ZIP preserves.

## H. Safely stop, save, and restart

Use the browser's **Stop & save** button to stop radar acquisition, close the serial devices, and save the original radar CSV files and session PNG (if predictions were recorded) under `~/Water_Ice_Live/outputs/`. `Ctrl+C` in the running terminal also stops the app. Do not just kill the Pi's power if you need the saved session output.

Next time you start the Pi, you **do not** need to repeat installation. Run:

```bash
cd "$HOME/Water_Ice_Live"
bash START_PI.sh
```

Or repeat the explicit `./.venv/bin/python live.py ...` command from Section E.

### Optional: keep running when you disconnect from SSH

Start a persistent terminal session on the Pi:

```bash
sudo apt install -y tmux
tmux new -s waterice
```

Inside tmux run `cd "$HOME/Water_Ice_Live"` and then `bash START_PI.sh` (or the explicit start command). To detach without stopping the app, press **Ctrl+B**, release, then press **D**. Reattach later with:

```bash
tmux attach -t waterice
```

Use the dashboard's **Stop & save** button to shut down cleanly when finished.

## I. Troubleshooting commands

**Radar works, ESP32 sensors don't:** confirm an extra USB port exists and check the sensor's JSON stream. From the Pi, **stop the main app first**, then use the sample ESP32 port:

```bash
cd "$HOME/Water_Ice_Live"
./.venv/bin/python -m serial.tools.miniterm /dev/ttyACM0 115200
```

Replace `/dev/ttyACM0` with the correct ESP32 port. You should see one JSON object per line with `distance_mm` and `ax_mv`/`ay_mv`/`az_mv`, or `tof_mm` and `ax`/`ay`/`az`. Exit miniterm with **Ctrl+]**; then restart the dashboard. **Never have miniterm and the dashboard reading the same serial port at once.** A BLE-only firmware does not supply the required USB JSON.

**No VL53L0X distance:** look at your sensor wiring. The included ESP32 sketch defaults to **SDA GPIO5 (D4)**, **SCL GPIO7 (D8)**. Some other sketches in the GitHub repository use **SCL GPIO6 (D5)**. If your ToF SCL wire goes to GPIO6, change the sketch's `PIN_SCL` from 7 to 6 before flashing. GPIO1/2/3 serve ADXL335 X/Y/Z. GPS TX connects to ESP32 GPIO44 (D7). All sensor signals must be at appropriate 3.3 V logic levels.

**Radar won't configure / no frames:** confirm CLI and DATA ports, check `cli_live_log.txt` for errors, and close other radar applications. If your Pi previously ran `radar.service`, inspect it and stop it **only if it is already using your radar ports**:

```bash
sudo systemctl status radar.service --no-pager
# Only if this service is active and owns your radar:
sudo systemctl stop radar.service
```

**USB disconnects or random resets:** use a stable Pi power supply, data-capable USB cables, and consider a powered USB hub for several peripherals.

**Python package installation fails:** check Python version (`python3 --version`) and Pi OS architecture (`uname -m`). On older/32-bit systems the NumPy/Matplotlib wheel may not be available, requiring extra system libraries or a newer 64-bit Raspberry Pi OS. Do not force-install system-wide packages over the OS-managed Python environment.

**Calibration fails:** hold the entire sensor assembly still, ensure valid ToF readings, and that the selected accelerometer axis produces finite readings. If the ESP32 goes offline, inspect the browser's sensor error/last raw packet and the terminal output.

## J. Optional self-test (no hardware required)

```bash
cd "$HOME/Water_Ice_Live"
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m py_compile live.py sensor_input.py radar_decoder.py radar_model.py
```

## K. Windows, if you run on a PC instead

Extract ZIP, open the `Water_Ice_Live` folder, and double-click `START_WINDOWS.bat`. For a manual **Windows Command Prompt** setup:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe live.py --list-ports
.venv\Scripts\python.exe live.py --cli COM4 --data COM3 --sensor-port COM5
```

COM4, COM3, COM5 are **examples only**; use actual device ports.

## Files and compatibility

- `live.py`: radar acquisition, browser web server, ESP32 reader thread and `/api/calibrate` endpoint.
- `sensor_input.py`: sensor normalization, USB serial connection, stationary baseline calibration and diagnostics.
- `debug.html`: combined dashboard and calibration controls.
- `radar_decoder.py`, `radar_model.py`, `road_profile.cfg`, `data/surface_samples.json`: existing radar decoder and sample-based model; reference data/config are preserved.
- `esp32_sensors/esp32_sensors.ino`: optional ESP32 USB JSON firmware (Seeed XIAO ESP32-S3; Arduino USB CDC On Boot enabled).
- `START_PI.sh`: guided Pi startup after initial setup; `START_WINDOWS.bat`: guided PC startup.
- `tests/test_integrated.py`: offline Python tests.

**No code was pushed to your GitHub repository.** Back up working files before replacing an existing installation.
