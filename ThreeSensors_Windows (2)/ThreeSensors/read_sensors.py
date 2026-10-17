"""Read JSON lines from the included XIAO ESP32-S3 firmware."""
import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import time

FIELDS = ['ms', 'tof_ok', 'distance_mm', 'range_status', 'ax_mv', 'ay_mv', 'az_mv',
          'gps_fix', 'lat', 'lon', 'speed_kmph', 'satellites', 'gps_chars']
# Extra fields sent by firmware v2 (accelerometer min/max per 100 ms window). Optional,
# so older firmware still works; they are blank in the CSV when absent.
OPTIONAL = ['v', 'ax_min_mv', 'ax_max_mv', 'ay_min_mv', 'ay_max_mv', 'az_min_mv', 'az_max_mv', 'acc_n']


def parse_packet(line):
    data = json.loads(line)
    if not isinstance(data, dict) or any(k not in data for k in FIELDS):
        raise ValueError('Not a sensor packet')
    if any(v is not None and (not isinstance(v, (int, float, bool)) or
                             not math.isfinite(v)) for v in data.values()):
        raise ValueError('Invalid sensor value')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list-ports', action='store_true')
    parser.add_argument('--port', help='For example COM5')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--csv', type=Path, help='New output file; existing files are protected')
    args = parser.parse_args()
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        print('Install the dependency: py -m pip install pyserial')
        return 1
    ports = list(list_ports.comports())
    if args.list_ports or not args.port:
        for i, p in enumerate(ports, 1):
            print(f'{i}. {p.device}: {p.description}')
        if not ports:
            print('No COM ports found. Connect the ESP32 with a USB DATA cable.')
            return 1
        if args.list_ports:
            return 0
        choice = input('Enter the ESP32 COM port (example COM5): ').strip()
        args.port = choice
    output = args.csv or Path(__file__).resolve().parent / ('readings_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.csv')
    try:
        with serial.Serial(args.port, args.baud, timeout=1) as connection, output.open('x', newline='', encoding='utf-8') as log:
            writer = csv.DictWriter(log, fieldnames=['pc_time_utc'] + FIELDS + OPTIONAL)
            writer.writeheader()
            print(f'Connected to {args.port}. Saving to {output}\nPress Ctrl+C to stop.')
            last_packet = time.monotonic()
            last_display = 0
            pending = bytearray()
            while True:
                pending.extend(connection.read(connection.in_waiting or 1))
                while b'\n' in pending:
                    raw, _, pending = pending.partition(b'\n')
                    try:
                        data = parse_packet(raw.decode('utf-8'))
                    except (ValueError, UnicodeError):
                        continue
                    writer.writerow({'pc_time_utc': datetime.now(timezone.utc).isoformat(), **{k: data[k] for k in FIELDS}, **{k: data.get(k) for k in OPTIONAL}})
                    log.flush()
                    last_packet = time.monotonic()
                    if last_packet - last_display >= 0.5:
                        distance = data['distance_mm']
                        tof = f'{distance} mm' if distance is not None else f"unavailable (status {data['range_status']})"
                        gps = f"{data['lat']}, {data['lon']}" if data['gps_fix'] else 'waiting for fix / stale'
                        print(f"ToF: {tof} | Accel mV: {data['ax_mv']}, {data['ay_mv']}, {data['az_mv']} | GPS: {gps} | Satellites: {data['satellites']} | GPS bytes: {data['gps_chars']}")
                        last_display = last_packet
                if len(pending) > 8192:
                    pending.clear()
                if time.monotonic() - last_packet > 5:
                    print('No valid packets for 5 seconds. Check firmware, USB CDC, COM port and baud rate.')
                    last_packet = time.monotonic()
    except KeyboardInterrupt:
        print('\nStopped. CSV saved.')
    except (serial.SerialException, OSError) as exc:
        print(f'Error: {exc}\nClose Arduino Serial Monitor; check the port and output filename, then run again.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
