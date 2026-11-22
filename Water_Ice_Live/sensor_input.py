"""Independent ESP32 USB/serial input, normalization and stationary baseline calibration.

Accepted firmware JSON formats:
- RoadMonitorPi v2: distance_mm, ax_mv, ay_mv, az_mv, tof_ok, range_status
- RoadMonitorBLEee road-v1: tof_mm, ax, ay, az (acceleration in g)

Calibration is ONLY a local ToF/accelerometer baseline, not a radar water/ice
classifier calibration. An ESP32 must be connected over USB serial, not BLE.
"""
import json
import math
import threading
import time
from collections import deque
from datetime import datetime, timezone

import serial
from serial.tools import list_ports

CALIBRATION_SAMPLES = 30
SENSOR_STALE_SECONDS = 2.0


def _finite_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def normalize_packet(packet):
    """Convert either supported sensor firmware into the same units and names."""
    if not isinstance(packet, dict):
        raise ValueError('Sensor input must be a JSON object')
    if 'distance_mm' in packet:
        d = packet.get('distance_mm')
        xyz = (packet.get('ax_mv'), packet.get('ay_mv'), packet.get('az_mv'))
        fw = 'RoadMonitorPi JSON (mV)'
    elif packet.get('schema') == 'road-v1' or 'tof_mm' in packet:
        d = packet.get('tof_mm')
        readings = (packet.get('ax'), packet.get('ay'), packet.get('az'))
        xyz = tuple(1650.0 + 330.0 * v if _finite_number(v) else None for v in readings)
        fw = 'road-v1 JSON (g)'
    else:
        raise ValueError('Unknown firmware JSON; expected distance_mm or tof_mm')
    if not any(_finite_number(v) for v in xyz):
        raise ValueError('Missing accelerometer readings; check ESP32 firmware')

    status = packet.get('range_status')
    tof_ok = packet.get('tof_ok', d is not None)
    distance_valid = (tof_ok is True and (status is None or status == 0)
                      and _finite_number(d) and 0 < d < 8000)
    gps_fix = packet.get('gps_fix') is True
    lat, lon = packet.get('lat'), packet.get('lon')
    gps_valid = (gps_fix and _finite_number(lat) and _finite_number(lon)
                 and abs(lat) <= 90 and abs(lon) <= 180)
    speed = packet.get('speed_kmph', packet.get('speed_kmh'))
    return {
        'firmware': fw,
        'device_ms': packet.get('ms') if _finite_number(packet.get('ms')) else None,
        'distance_mm': float(d) if distance_valid else None,
        'distance_valid': bool(distance_valid),
        'tof_ok': tof_ok is True,
        'range_status': status,
        'ax_mv': float(xyz[0]) if _finite_number(xyz[0]) else None,
        'ay_mv': float(xyz[1]) if _finite_number(xyz[1]) else None,
        'az_mv': float(xyz[2]) if _finite_number(xyz[2]) else None,
        'ax_min_mv': packet.get('ax_min_mv') if _finite_number(packet.get('ax_min_mv')) else None,
        'ax_max_mv': packet.get('ax_max_mv') if _finite_number(packet.get('ax_max_mv')) else None,
        'ay_min_mv': packet.get('ay_min_mv') if _finite_number(packet.get('ay_min_mv')) else None,
        'ay_max_mv': packet.get('ay_max_mv') if _finite_number(packet.get('ay_max_mv')) else None,
        'az_min_mv': packet.get('az_min_mv') if _finite_number(packet.get('az_min_mv')) else None,
        'az_max_mv': packet.get('az_max_mv') if _finite_number(packet.get('az_max_mv')) else None,
        'gps_fix': gps_valid,
        'lat': float(lat) if gps_valid else None,
        'lon': float(lon) if gps_valid else None,
        'speed_kmph': float(speed) if gps_valid and _finite_number(speed) else None,
        'satellites': packet.get('satellites') if _finite_number(packet.get('satellites')) else None,
    }


class SensorMonitor:
    def __init__(self, port='auto', baud=115200, axis='az', mv_per_g=330.0):
        if axis not in ('ax', 'ay', 'az'):
            raise ValueError('axis must be ax, ay, or az')
        if mv_per_g <= 0:
            raise ValueError('mv_per_g must be positive')
        self.lock = threading.RLock()
        self.port_requested = port
        self.baud = baud
        self.axis = axis
        self.mv_per_g = mv_per_g
        self.port = None
        self.error = None
        self.packets = 0
        self.invalid_packets = 0
        self.last_received = None
        self.raw = ''
        self.sensor = {}
        self.packet_times = deque()
        self.cal_status = 'not calibrated'
        self.cal_error = None
        self.cal = []
        self.cal_started_at = None
        self.baseline = None
        self.clearance_delta_mm = None
        self.vertical_change_g = None
        self.vertical_peak_g = None

    def connection(self, port=None, error=None):
        with self.lock:
            self.port = port
            self.error = error

    def receive_line(self, line):
        if isinstance(line, bytes):
            line = line.decode('utf-8', errors='replace').strip()
        with self.lock:
            self.raw = line[:2000]
        if not line.startswith('{'):
            return False  # Ignore boot banners and other non-JSON serial chatter.
        try:
            s = normalize_packet(json.loads(line))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            with self.lock:
                self.invalid_packets += 1
                self.error = 'Invalid ESP32 data: ' + str(exc)
            return False
        now = time.monotonic()
        with self.lock:
            self.sensor = s
            self.last_received = now
            self.packets += 1
            self.packet_times.append(now)
            while self.packet_times and now - self.packet_times[0] > 2:
                self.packet_times.popleft()
            self.error = None
            if self.cal_status == 'collecting':
                a = s[self.axis + '_mv']
                if s['distance_valid'] and _finite_number(a):
                    self.cal.append((s['distance_mm'], a))
                    if len(self.cal) >= CALIBRATION_SAMPLES:
                        ds, aa = zip(*self.cal)
                        if max(ds) - min(ds) > 30 or max(aa) - min(aa) > 35:
                            self.cal_status = 'failed'
                            self.cal_error = 'Too much movement during calibration. Keep sensors still and retry.'
                            self.baseline = None
                        else:
                            self.baseline = {'distance_mm': sum(ds) / len(ds),
                                             'axis_mv': sum(aa) / len(aa), 'axis': self.axis}
                            self.cal_status = 'calibrated'
                            self.cal_error = None
            if self.baseline:
                if s['distance_valid']:
                    self.clearance_delta_mm = s['distance_mm'] - self.baseline['distance_mm']
                else:
                    self.clearance_delta_mm = None
                a = s[self.axis + '_mv']
                self.vertical_change_g = (abs(a - self.baseline['axis_mv']) / self.mv_per_g
                                          if _finite_number(a) else None)
                lo = s.get(self.axis + '_min_mv')
                hi = s.get(self.axis + '_max_mv')
                if _finite_number(lo) and _finite_number(hi):
                    self.vertical_peak_g = max(abs(lo - self.baseline['axis_mv']),
                                               abs(hi - self.baseline['axis_mv'])) / self.mv_per_g
                else:
                    self.vertical_peak_g = self.vertical_change_g
            else:
                self.clearance_delta_mm = None
                self.vertical_change_g = None
                self.vertical_peak_g = None
        return True

    def start_calibration(self):
        with self.lock:
            if self.last_received is None or time.monotonic() - self.last_received >= SENSOR_STALE_SECONDS:
                raise ValueError('ESP32 is not streaming. Connect its USB serial port first.')
            if not self.sensor.get('distance_valid'):
                raise ValueError('ToF distance is invalid. Check the VL53L0X wiring and surface distance.')
            if not _finite_number(self.sensor.get(self.axis + '_mv')):
                raise ValueError('Accelerometer axis is missing. Check ESP32 firmware.')
            self.cal = []
            self.cal_started_at = time.monotonic()
            self.baseline = None
            self.cal_status = 'collecting'
            self.cal_error = None
            self.clearance_delta_mm = None
            self.vertical_change_g = None
            self.vertical_peak_g = None
        return {'ok': True, 'message': f'Collecting {CALIBRATION_SAMPLES} stationary ESP32 reports'}

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            if (self.cal_status == 'collecting' and self.cal_started_at is not None
                    and now - self.cal_started_at > 15):
                self.cal_status = 'failed'
                self.cal_error = 'Calibration timed out after 15 seconds. Check ToF data or retry.'
            age = None if self.last_received is None else max(0., now - self.last_received)
            online = age is not None and age < SENSOR_STALE_SECONDS
            # Do not expose old GPS fixes or stale sensor numbers as live data.
            live = dict(self.sensor) if online else {}
            return {
                'sensor_enabled': self.port_requested is not None,
                'sensor_connected_port': self.port,
                'sensor_requested_port': self.port_requested,
                'sensor_baud': self.baud,
                'sensor_online': online,
                'sensor_age_s': round(age, 2) if age is not None else None,
                'sensor_error': self.error,
                'sensor_packets': self.packets,
                'sensor_bad_packets': self.invalid_packets,
                'sensor_rate_hz': round(len(self.packet_times) / 2, 1) if online else 0.0,
                'sensor': live,
                'sensor_raw': self.raw,
                'calibration': {
                    'status': self.cal_status,
                    'error': self.cal_error,
                    'samples': len(self.cal),
                    'required': CALIBRATION_SAMPLES,
                    'baseline': dict(self.baseline) if self.baseline else None,
                    'delta_mm': self.clearance_delta_mm if online else None,
                    'change_g': self.vertical_change_g if online else None,
                    'peak_g': self.vertical_peak_g if online else None,
                    'axis': self.axis,
                },
            }


def _find_sensor_port(cli, data):
    """Select an unused USB port, preferring a clearly identified ESP32 board."""
    used = {str(x).lower() for x in (cli, data) if x}
    candidates = [p for p in list_ports.comports() if p.device.lower() not in used]
    if not candidates:
        return None, 'ESP32 USB serial port not found. Check cable/driver or use --sensor-port COMx.'
    preferred = [p for p in candidates if any(tag in (' '.join(str(x or '') for x in
                 (p.description, p.manufacturer, p.hwid))).lower()
                 for tag in ('esp32', 'espressif', 'xiao', 'seeed'))]
    if len(preferred) == 1:
        return preferred[0].device, None
    if len(candidates) == 1:
        return candidates[0].device, None
    return None, 'Multiple possible ESP32 ports: ' + ', '.join(p.device for p in candidates) + '. Specify --sensor-port explicitly.'


def sensor_loop(monitor, requested_port, cli_port, data_port, stop):
    """Read independently of radar. Reopen after disconnects or USB changes."""
    while not stop.is_set():
        actual = requested_port
        if requested_port == 'auto':
            actual, reason = _find_sensor_port(cli_port, data_port)
            if actual is None:
                monitor.connection(error=reason)
                stop.wait(2)
                continue
        try:
            with serial.Serial(actual, monitor.baud, timeout=0.5) as conn:
                monitor.connection(port=actual)
                while not stop.is_set():
                    line = conn.readline()
                    if len(line) > 4096:
                        monitor.connection(port=actual, error='ESP32 line exceeds 4096 bytes')
                        continue
                    if line:
                        monitor.receive_line(line)
        except (serial.SerialException, OSError, ValueError) as exc:
            monitor.connection(error=f'Cannot read ESP32 on {actual}: {exc}')
            stop.wait(2)
        finally:
            monitor.connection(port=None, error=monitor.error)
