"""No hardware required: protocol, model, stationary calibration, and HTTP tests.

Install requirements first: python -m pip install -r requirements.txt
Then: python -m unittest discover -s tests -v
"""
import hashlib
import json
import socket
import struct
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Make tests runnable in offline CI environments without pyserial. The real app
# still requires pyserial and installs it through requirements.txt.
try:
    import serial  # noqa
except ImportError:
    serial = types.ModuleType('serial')
    serial.SerialException = OSError
    serial.Serial = lambda *args, **kwargs: None
    tools = types.ModuleType('serial.tools')
    list_ports = types.ModuleType('serial.tools.list_ports')
    list_ports.comports = lambda: []
    tools.list_ports = list_ports
    serial.tools = tools
    sys.modules.update({'serial': serial, 'serial.tools': tools,
                        'serial.tools.list_ports': list_ports})

import numpy as np
from sensor_input import SensorMonitor, normalize_packet, _find_sensor_port
from radar_decoder import Decoder, MAGIC
from radar_model import load_model, classify
from live import State, start_web


class Args:
    cli = 'RADAR_CLI'
    data = 'RADAR_DATA'
    baud = 921600


def sample_v2(distance=450, az=1980):
    return {'v': 2, 'ms': 123456, 'distance_mm': distance,
            'tof_ok': True, 'range_status': 0,
            'ax_mv': 1650, 'ay_mv': 1650, 'az_mv': az,
            'az_min_mv': az - 4, 'az_max_mv': az + 4,
            'gps_fix': True, 'lat': 32.985, 'lon': -96.75,
            'speed_kmph': 4.1, 'satellites': 9}


class ModelTests(unittest.TestCase):
    def test_radar_config_hash_matches_training_samples(self):
        meta = load_model()[0]
        self.assertEqual(hashlib.sha256((ROOT / 'road_profile.cfg').read_bytes()).hexdigest(),
                         meta['cfg_sha256'])
        self.assertEqual(meta['bins'], 256)

    def test_radar_classifier_unchanged(self):
        model = load_model()
        _, _, centers, _, _ = model
        labels = [classify(center, model)[0] for center in centers]
        self.assertEqual(labels, ['dry', 'water/wet', 'ice'])

    def test_radar_decoder_valid_tlv2(self):
        profile = np.arange(256, dtype='<u2')
        payload = struct.pack('<II', 2, 512) + profile.tobytes()
        header = MAGIC + struct.pack('<8I', 0x03060000, 40 + len(payload), 0x6843, 12,
                                     0, 0, 1, 0)
        decoded = Decoder(256).feed(header + payload)
        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0][0], 12)
        self.assertEqual(decoded[0][1][3], 3)


class SensorTests(unittest.TestCase):
    def test_v2_normalization(self):
        s = normalize_packet(sample_v2())
        self.assertTrue(s['distance_valid'])
        self.assertTrue(s['gps_fix'])
        self.assertEqual(s['distance_mm'], 450)
        self.assertEqual(s['az_mv'], 1980)

    def test_road_v1_normalization(self):
        s = normalize_packet({'schema': 'road-v1', 'tof_mm': 455,
                              'ax': 0.0, 'ay': -0.2, 'az': 1.0,
                              'gps_fix': False})
        self.assertTrue(s['distance_valid'])
        self.assertEqual(s['az_mv'], 1980)
        self.assertEqual(s['distance_mm'], 455)
        self.assertFalse(s['gps_fix'])

    def test_calibration_and_live_deltas(self):
        m = SensorMonitor(port='COM5')
        self.assertTrue(m.receive_line(json.dumps(sample_v2())))
        result = m.start_calibration()
        self.assertTrue(result['ok'])
        for i in range(30):
            self.assertTrue(m.receive_line(json.dumps(sample_v2(450 + i % 3, 1980 + i % 3))))
        s = m.snapshot()
        self.assertEqual(s['calibration']['status'], 'calibrated')
        m.receive_line(json.dumps(sample_v2(550, 2100)))
        s = m.snapshot()
        self.assertAlmostEqual(s['calibration']['delta_mm'], 99., delta=1.1)
        self.assertGreater(s['calibration']['peak_g'], 0.3)
        self.assertTrue(s['sensor_online'])

    def test_calibration_rejects_movement(self):
        m = SensorMonitor(port='COM5')
        m.receive_line(json.dumps(sample_v2()))
        m.start_calibration()
        for i in range(30):
            m.receive_line(json.dumps(sample_v2(450 if i < 15 else 520)))
        self.assertEqual(m.snapshot()['calibration']['status'], 'failed')
        self.assertIsNone(m.snapshot()['calibration']['baseline'])

    def test_invalid_tof_disables_calibration(self):
        m = SensorMonitor(port='COM5')
        p = sample_v2(distance=None)
        p['tof_ok'] = False
        m.receive_line(json.dumps(p))
        with self.assertRaisesRegex(ValueError, 'ToF distance is invalid'):
            m.start_calibration()

    def test_ignores_nonjson_startup_chatter(self):
        m = SensorMonitor(port='COM5')
        self.assertFalse(m.receive_line('Booting ESP32'))
        self.assertFalse(m.receive_line('{bad-json'))
        self.assertEqual(m.snapshot()['sensor_bad_packets'], 1)

    def test_auto_port_avoids_radar_ports(self):
        devices = [types.SimpleNamespace(device='COM3', description='TI radar DATA',
                                         manufacturer='', hwid=''),
                   types.SimpleNamespace(device='COM4', description='TI radar CLI',
                                         manufacturer='', hwid=''),
                   types.SimpleNamespace(device='COM5', description='Espressif USB',
                                         manufacturer='Espressif', hwid='')]
        with patch('sensor_input.list_ports.comports', return_value=devices):
            port, error = _find_sensor_port('COM4', 'COM3')
        self.assertEqual(port, 'COM5')
        self.assertIsNone(error)


class WebTests(unittest.TestCase):
    def test_http_state_and_calibrate(self):
        sensors = SensorMonitor(port='COM5')
        state = State(load_model()[0], Args, ROOT / 'unused.csv', sensors)
        srv = start_web(state, '127.0.0.1', 0)
        url = f'http://127.0.0.1:{srv.server_address[1]}'
        try:
            with urlopen(url + '/api/state', timeout=2) as f:
                data = json.loads(f.read())
            self.assertIn('feature_bins', data)
            self.assertIn('sensor', data)
            self.assertFalse(data['sensor_online'])
            with self.assertRaises(HTTPError) as err:
                urlopen(Request(url + '/api/calibrate', method='POST'), timeout=2)
            self.assertEqual(err.exception.code, 400)
            sensors.receive_line(json.dumps(sample_v2()))
            with urlopen(Request(url + '/api/calibrate', method='POST'), timeout=2) as f:
                result = json.loads(f.read())
            self.assertTrue(result['ok'])
            with urlopen(url + '/api/state', timeout=2) as f:
                latest = json.loads(f.read())
            self.assertEqual(latest['calibration']['status'], 'collecting')
            with self.assertRaises(HTTPError) as err:
                urlopen(Request(url + '/api/calibrate', method='POST',
                                headers={'Origin': 'http://evil.example'}), timeout=2)
            self.assertEqual(err.exception.code, 403)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == '__main__':
    unittest.main()
