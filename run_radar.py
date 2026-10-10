"""
One command to configure the radar and start a viewer or the logger.

    python run_radar.py              # configure + live X/Y view
    python run_radar.py profile      # configure + side view (distance vs height)
    python run_radar.py road         # configure + road profile
    python run_radar.py log          # configure + headless CSV logger (Pi / boot)

Optional: --cfg other.cfg   --retries N
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

VIEWS = {
    "xy": "fast_xy_radar.py",
    "profile": "fast_radar_plot.py",
    "road": "road_profile.py",
    "log": "log_radar.py",
}


def run(script, *args):
    return subprocess.call([sys.executable, os.path.join(HERE, script), *args])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("view", nargs="?", default="xy", choices=VIEWS)
    p.add_argument("--cfg", default=os.path.join(HERE, "profile.cfg"))
    p.add_argument("--retries", type=int, default=3,
                   help="attempts at starting the radar (it can take a few seconds to enumerate)")
    a = p.parse_args()

    for attempt in range(1, a.retries + 1):
        print(f"\n=== Starting radar (attempt {attempt}/{a.retries}) ===")
        code = run("start_radar.py", a.cfg)
        if code == 0:
            break
        print(f"start_radar.py failed (exit {code}).")
        if attempt < a.retries:
            print("Retrying in 5 s... (power-cycle the radar if it keeps failing)")
            time.sleep(5)
    else:
        sys.exit(1)

    print(f"\n=== Launching {VIEWS[a.view]} ===")
    sys.exit(run(VIEWS[a.view]))


if __name__ == "__main__":
    main()
