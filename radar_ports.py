"""
Pick the AWR6843ISK serial ports on Windows or Linux / WSL.

The standalone ISK uses a Silicon Labs CP2105 dual USB-UART bridge:
    Enhanced COM port  (interface 0) -> CLI  (115200)
    Standard COM port  (interface 1) -> DATA (921600)

Windows:  CLI = COM4, DATA = COM3
Linux:    looks under /dev/serial/by-id/ for the CP2105 (or an XDS110,
          for boards on the mmWaveICBoost carrier), then falls back to
          /dev/ttyUSB0 / ttyUSB1 or /dev/ttyACM0 / ttyACM1.

Override either one with environment variables, e.g.
    RADAR_CLI_PORT=/dev/ttyUSB0 RADAR_DATA_PORT=/dev/ttyUSB1 python start_radar.py
"""

import glob
import os
import sys


def _pick(paths, cli_tag, data_tag):
    cli = [p for p in paths if cli_tag in p]
    data = [p for p in paths if data_tag in p]
    if cli and data:
        return cli[0], data[0]
    return None


def _linux_ports():
    by_id = sorted(glob.glob("/dev/serial/by-id/*"))

    # Standalone ISK: CP2105 (interface 0 = CLI, interface 1 = DATA)
    found = _pick([p for p in by_id if "CP2105" in p], "-if00", "-if01")
    if found:
        return found

    # ISK on mmWaveICBoost: XDS110 (interface 0 = CLI, interface 3 = DATA)
    found = _pick([p for p in by_id if "XDS110" in p], "-if00", "-if03")
    if found:
        return found

    for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*"):
        ports = sorted(glob.glob(pattern))
        if len(ports) >= 2:
            return ports[0], ports[1]

    return "/dev/ttyUSB0", "/dev/ttyUSB1"


if sys.platform.startswith("win"):
    _cli, _data = "COM4", "COM3"
else:
    _cli, _data = _linux_ports()

CLI_PORT = os.environ.get("RADAR_CLI_PORT", _cli)
DATA_PORT = os.environ.get("RADAR_DATA_PORT", _data)


if __name__ == "__main__":
    print("CLI  port:", CLI_PORT)
    print("DATA port:", DATA_PORT)
