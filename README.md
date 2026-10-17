# Road Surface Condition Radar (Senior Design)

TI AWR6843ISK mmWave radar + XIAO ESP32-S3 sensor hub (VL53L0X distance, ADXL335
accelerometer, NEO-6M GPS) on a Raspberry Pi 4. Research prototype - not a safety system.

## Which app do I run?

| Folder / file | Use it for | Runs on |
|---|---|---|
| **`RoadMonitorPi/RoadMonitorPi/`** | **Main app.** ESP32 sensors + radar, browser dashboard, events, logs | Pi |
| `*.py` at repo root (`run_radar.py`, `start_radar.py`, viewers, `log_radar.py`) | Radar-only bench tools: configure, plot, log points to CSV | Windows / WSL / Pi |
| `road_radar_pi.py` | Radar-only road analysis (its rules are now merged into RoadMonitorPi) | Pi |
| `Road_Radar_Heatmap_Clean/` | Range-angle heatmap + "calibrate clean road" change detection (bench) | Windows / Pi |
| `IceRadar_AWR6843ISK/` | Dry / wet / ice sample-matching experiment (stationary bench only) | Windows |
| `ThreeSensors_Windows (2)/` | ESP32 firmware + logger for the 3 sensors alone | Windows |
| `RoadMonitor_BLE_Mac_v2/` | Same sensors over Bluetooth to a Mac + Firebase (no radar) | Mac |

## Quick start (Pi)

```bash
cd RoadMonitorPi/RoadMonitorPi
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py --demo     # try it without hardware, open http://localhost:8000
python app.py --auto     # real hardware: finds ESP32 + radar, sends profile.cfg
```
Set `radar_height_m` and `radar_pitch_deg` in `config.json` to your measured mount first.

## Radar configs (all for TI SDK 3.6 out-of-box firmware)

| Config | TX/RX | Notes |
|---|---|---|
| `profile.cfg` (root, and copy in RoadMonitorPi) | 3 TX / 4 RX | Height (Z) on, heatmap off, 10 fps, max ~0.67 m/s. **Bench only.** |
| `Road_Radar_Heatmap_Clean/.../heatmap_profile.cfg` | 1 TX / 4 RX | Range-azimuth heatmap (~30 deg resolution) |
| `IceRadar_AWR6843ISK/IceRadar/road_profile.cfg` | 1 TX / 2 RX | Range profile only, 0.24 m bins |

**Never enable the range-Doppler heatmap (`guiMonitor` 5th value = 1) at a 100 ms frame:**
it overruns the 921600-baud UART and the firmware freezes after one frame.

**None of these work while driving yet** (max velocity is ~1 m/s). A driving config
(>= ~22 m/s max velocity, 20-30 fps) is the next radar task.

## Ports

| | Windows | Linux / Pi |
|---|---|---|
| Radar CLI (115200) | COM4 | `/dev/serial/by-id/...CP2105...-if00` (ttyUSB0) |
| Radar DATA (921600) | COM3 | `/dev/serial/by-id/...CP2105...-if01` (ttyUSB1) |
| ESP32 (115200) | varies | `/dev/serial/by-id/...Espressif...` (ttyACM0) |

Only one program can open a port at a time. On Linux read the DATA port at least every
~50 ms (tty buffer is ~4 KB). User must be in the `dialout` group.

## Git workflow
`git pull` before you start, `git add . && git commit -m "..." && git push` when done.
Don't upload `__pycache__`, venvs, logs or zips of folders that are already in the repo.
