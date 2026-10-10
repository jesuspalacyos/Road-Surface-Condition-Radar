"""
Headless radar logger: reads the data port and writes every detected point
to a CSV in ../captures/. No GUI, so it can run on a Raspberry Pi at boot.

Run start_radar.py first (or use run_radar.py, which does both).

CSV columns: time_s, frame, x, y, z, velocity, snr_db, noise_db
"""

import csv
import math
import os
import signal
import struct
import sys
import time
from datetime import datetime

import serial
import radar_ports

MAGIC = b"\x02\x01\x04\x03\x06\x05\x08\x07"
DATA_BAUD = 921600

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "captures")

running = True


def stop(*_):
    global running
    running = False


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)


def parse_frame(frame):
    """Return (frame_number, [(x, y, z, v, snr_db, noise_db), ...])."""
    (_, length, _, frame_no, _, num_obj, num_tlvs, _) = struct.unpack_from("<8I", frame, 8)

    points = []
    side = []
    off = 40
    for _ in range(num_tlvs):
        if off + 8 > len(frame):
            break
        tlv_type, tlv_len = struct.unpack_from("<II", frame, off)
        start = off + 8
        end = start + tlv_len
        if end > len(frame):
            break

        if tlv_type == 1:                       # detected points: x, y, z, v (float32)
            for i in range(min(num_obj, tlv_len // 16)):
                points.append(struct.unpack_from("<ffff", frame, start + 16 * i))
        elif tlv_type == 7:                     # side info: snr, noise (int16, 0.1 dB)
            for i in range(min(num_obj, tlv_len // 4)):
                snr, noise = struct.unpack_from("<hh", frame, start + 4 * i)
                side.append((snr / 10.0, noise / 10.0))
        off = end

    rows = []
    for i, (x, y, z, v) in enumerate(points):
        if not all(math.isfinite(a) for a in (x, y, z, v)):
            continue
        snr, noise = side[i] if i < len(side) else (float("nan"), float("nan"))
        rows.append((x, y, z, v, snr, noise))
    return frame_no, rows


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, datetime.now().strftime("radar_%Y%m%d_%H%M%S.csv"))

    port = serial.Serial(radar_ports.DATA_PORT, DATA_BAUD, timeout=0.05)
    print(f"Logging {radar_ports.DATA_PORT} -> {path}")
    print("Ctrl+C to stop.")

    buf = bytearray()
    frames = 0
    t0 = time.time()
    last_report = t0
    last_data = t0

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "frame", "x", "y", "z", "velocity", "snr_db", "noise_db"])

        while running:
            chunk = port.read(port.in_waiting or 1)
            if chunk:
                buf.extend(chunk)
                last_data = time.time()

            while True:
                i = buf.find(MAGIC)
                if i < 0:
                    del buf[:-7]
                    break
                if i:
                    del buf[:i]
                if len(buf) < 40:
                    break
                length = struct.unpack_from("<I", buf, 12)[0]
                if length < 40 or length > 65536:
                    del buf[:8]
                    continue
                if len(buf) < length:
                    break
                frame = bytes(buf[:length])
                del buf[:length]
                try:
                    frame_no, rows = parse_frame(frame)
                except struct.error:
                    continue
                t = round(time.time() - t0, 3)
                for r in rows:
                    w.writerow([t, frame_no, *(round(v, 4) for v in r)])
                frames += 1

            now = time.time()
            if now - last_report >= 5:
                f.flush()
                os.fsync(f.fileno())          # survive a sudden power cut
                print(f"{frames} frames logged")
                last_report = now
            if now - last_data > 5:
                print("No data for 5 s - is the sensor running?")
                last_data = now

    port.close()
    print(f"Stopped. {frames} frames saved to {path}")


if __name__ == "__main__":
    main()
