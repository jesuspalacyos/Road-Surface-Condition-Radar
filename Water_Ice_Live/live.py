#!/usr/bin/env python3
"""LIVE TI AWR6843ISK water/ice bench radar + XIAO ESP32-S3 sensor monitor.

No demo data is generated. Radar and ESP32 use independent serial links:
  radar CLI 115200 baud, radar DATA 921600 baud, ESP32 USB 115200 baud.
The existing radar range-profile model is kept independent of ToF/accel calibration.
"""
import argparse
import csv
import hashlib
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import serial
from serial.tools import list_ports

from radar_decoder import Decoder
from radar_model import load_model, classify, plot
from sensor_input import SensorMonitor, sensor_loop

ROOT = Path(__file__).resolve().parent


def configure(cli, cfg, on_line=None):
    """Send the EXACT known-working radar configuration and verify acknowledgments."""
    lines = [line.split('%')[0].strip() for line in cfg.read_text(encoding='utf-8-sig').splitlines()]
    with (ROOT / 'cli_live_log.txt').open('w', encoding='utf-8') as log:
        for command in filter(None, lines):
            cli.reset_input_buffer()
            cli.write((command + '\n').encode())
            response = bytearray()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                response.extend(cli.read(cli.in_waiting or 1))
                if any(token in response for token in (b'Done', b'Error', b'not recognized')):
                    break
            answer = response.decode(errors='replace')
            log.write(command + '\n' + answer + '\n')
            log.flush()
            ok = b'Done' in response and b'Error' not in response and b'not recognized' not in response
            if on_line:
                on_line(command, ok)
            if not ok:
                raise RuntimeError('Radar rejected or did not acknowledge: ' + command + '\n' + answer)


class State:
    def __init__(self, meta, args, pred_path, sensors):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.started = time.monotonic()
        self.sensors = sensors
        self.s = {
            'status': 'starting', 'error': None,
            'cli': args.cli, 'data': args.data, 'baud': args.baud,
            'csv': str(pred_path), 'feature_bins': meta['indices'], 'bins': meta['bins'],
            'frames': 0, 'bad_packets': 0, 'fps': 0.0, 'data_age_s': None,
            'prediction': None, 'margin': None, 'distances': None, 'features': None,
            'profile': None, 'history': [], 'config_log': [],
        }
        self._frame_times = deque()
        self._last_frame = None

    def set(self, **kw):
        with self.lock:
            self.s.update(kw)

    def config_line(self, command, ok):
        with self.lock:
            self.s['config_log'].append({'cmd': command, 'ok': ok})
            self.s['config_log'] = self.s['config_log'][-60:]

    def frame(self, profile, bad):
        now = time.monotonic()
        with self.lock:
            self._last_frame = now
            self._frame_times.append(now)
            while self._frame_times and now - self._frame_times[0] > 2:
                self._frame_times.popleft()
            self.s['frames'] += 1
            self.s['bad_packets'] = bad
            self.s['fps'] = round(len(self._frame_times) / 2, 1)
            self.s['profile'] = [int(v) for v in profile]

    def prediction(self, row):
        with self.lock:
            self.s.update(
                prediction=row['predicted_surface'],
                margin=round(row['separation_margin'], 3),
                distances={k: round(row['distance_' + k], 3) for k in ('dry', 'wet', 'ice')},
                features={str(b): round(row[f'bin_{b:03d}'], 1) for b in self.s['feature_bins']},
            )
            self.s['history'].append({
                't': round(row['time_s'], 2), 'p': row['predicted_surface'],
                'd': [round(row['distance_' + k], 3) for k in ('dry', 'wet', 'ice')],
                'b': [round(row[f'bin_{b:03d}'], 1) for b in self.s['feature_bins']],
            })
            cutoff = row['time_s'] - 60
            while self.s['history'] and self.s['history'][0]['t'] < cutoff:
                self.s['history'].pop(0)

    def snapshot(self):
        with self.lock:
            out = dict(self.s)
            out['elapsed_s'] = round(time.monotonic() - self.started, 1)
            out['data_age_s'] = None if self._last_frame is None else round(time.monotonic() - self._last_frame, 1)
            # Return copies of mutable collections while holding their lock.
            out['history'] = list(self.s['history'])
            out['config_log'] = list(self.s['config_log'])
            if self.s['profile'] is not None:
                out['profile'] = list(self.s['profile'])
        out.update(self.sensors.snapshot())
        return json.dumps(out, allow_nan=False)


def start_web(state, host, port):
    page = (ROOT / 'debug.html').read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body, typ='application/json; charset=utf-8', code=200):
            if isinstance(body, str):
                body = body.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', typ)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.path in ('/', '/index.html'):
                self.send(page, 'text/html; charset=utf-8')
            elif self.path == '/api/state':
                self.send(state.snapshot())
            else:
                self.send('Not found', 'text/plain; charset=utf-8', 404)

        def do_POST(self):
            # Reject cross-origin browser requests; no service accounts or cloud keys involved.
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc.lower() != self.headers.get('Host', '').lower():
                return self.send(json.dumps({'error': 'Cross-origin request rejected'}), code=403)
            if self.path == '/api/calibrate':
                try:
                    result = state.sensors.start_calibration()
                    self.send(json.dumps(result))
                except ValueError as exc:
                    self.send(json.dumps({'ok': False, 'error': str(exc)}), code=400)
            elif self.path == '/api/stop':
                state.stop.set()
                self.send('{"ok":true}')
            else:
                self.send('Not found', 'text/plain; charset=utf-8', 404)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--list-ports', action='store_true', help='show radar and ESP32 serial ports')
    p.add_argument('--cli', help='radar CLI/Application UART, e.g. COM4 or /dev/ttyUSB0')
    p.add_argument('--data', help='radar DATA/Auxiliary UART, e.g. COM3 or /dev/ttyUSB1')
    p.add_argument('--baud', type=int, default=921600, help='radar DATA baud; default 921600')
    p.add_argument('--cfg', type=Path, default=ROOT / 'road_profile.cfg')
    p.add_argument('--sensor-port', default='auto',
                   help='ESP32 USB serial COM port; auto detects an extra port; none disables sensors')
    p.add_argument('--sensor-baud', type=int, default=115200)
    p.add_argument('--cal-axis', choices=['ax', 'ay', 'az'], default='az',
                   help='physically vertical accelerometer axis (default az)')
    p.add_argument('--accel-mv-per-g', type=float, default=330.0)
    p.add_argument('--window', action='store_true', help='old radar matplotlib window instead of browser')
    p.add_argument('--host', default='0.0.0.0', help='web interface address')
    p.add_argument('--port', type=int, default=8050, help='web interface port')
    args = p.parse_args()
    if args.list_ports:
        ports = list(list_ports.comports())
        if not ports:
            print('No serial ports detected.')
        for port in ports:
            print(f'{port.device:16} {port.description} | {port.hwid}')
        return
    if not args.cli or not args.data:
        p.error('Specify --cli and --data; use --list-ports to find them.')
    if args.cli.lower() == args.data.lower():
        p.error('Radar CLI and DATA ports must be different.')
    if args.sensor_port.lower() in ('off', 'none', 'disabled'):
        args.sensor_port = None
    if args.sensor_port and args.sensor_port != 'auto' and args.sensor_port.lower() in (args.cli.lower(), args.data.lower()):
        p.error('ESP32 --sensor-port must differ from radar --cli and --data.')
    if args.accel_mv_per_g <= 0:
        p.error('--accel-mv-per-g must be positive.')

    model = load_model()
    meta = model[0]
    if hashlib.sha256(args.cfg.read_bytes()).hexdigest() != meta['cfg_sha256']:
        p.error('Radar config does not match saved surface samples. Use the supplied road_profile.cfg unchanged.')

    # Lazy import keeps --list-ports usable without loading Matplotlib.
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    plt = None
    if args.window:
        import matplotlib.pyplot as plt

    output = ROOT / 'outputs'
    output.mkdir(exist_ok=True)
    stem = output / ('live_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    raw_path = stem.with_name(stem.name + '_raw').with_suffix('.csv')
    pred_path = stem.with_name(stem.name + '_predictions').with_suffix('.csv')
    info = {
        'source': 'live_serial', 'ground_truth': 'unlabeled', 'cli': args.cli, 'data': args.data,
        'baud': args.baud, 'sensor_port': args.sensor_port, 'sensor_baud': args.sensor_baud,
        'cfg_sha256': meta['cfg_sha256'], 'feature_indices': meta['indices'],
        'feature_window_seconds': 1,
        'note': 'Experimental radar wet/ice matching; local ToF/accel calibration is independent.',
    }
    stem.with_suffix('.metadata.json').write_text(json.dumps(info, indent=2), encoding='utf-8')

    sensors = SensorMonitor(args.sensor_port, args.sensor_baud, axis=args.cal_axis, mv_per_g=args.accel_mv_per_g)
    state = State(meta, args, pred_path, sensors)
    if args.sensor_port:
        threading.Thread(target=sensor_loop,
                         args=(sensors, args.sensor_port, args.cli, args.data, state.stop),
                         daemon=True, name='esp32-reader').start()
        print('ESP32 USB sensor port:', args.sensor_port, '|', args.sensor_baud, 'baud')
    else:
        print('ESP32 input disabled. Radar-only mode.')

    srv = None
    if not args.window:
        srv = start_web(state, args.host, args.port)
        print(f'Browser: http://localhost:{args.port} (remote device: http://<this computer IP>:{args.port})')

    cli = data = None
    rows, history = [], deque()
    failure = None
    fig = None
    try:
        cli = serial.Serial(args.cli, 115200, timeout=.1, write_timeout=2)
        data = serial.Serial(args.data, args.baud, timeout=.01)
        print('Sending unchanged radar configuration...')
        state.set(status='configuring')
        configure(cli, args.cfg, state.config_line)
        decoder = Decoder(meta['bins'])
        state.set(status='waiting for data')
        if args.window:
            fig = plt.figure(figsize=(11, 8))
            fig.canvas.manager.set_window_title('LIVE radar — close to stop and save')
            fig.text(.1, .5, 'Waiting for live range-profile data (TLV 2)...')
            plt.show(block=False)
        running = (lambda: plt.fignum_exists(fig.number)) if args.window else (lambda: not state.stop.is_set())
        started = time.monotonic()
        last_frame = started
        last_plot = last_pred = 0
        first_frame = None
        with raw_path.open('w', newline='', encoding='utf-8') as rf, pred_path.open('w', newline='', encoding='utf-8') as pf:
            raw = csv.writer(rf)
            raw.writerow(['timestamp_utc', 'unix_time_s', 'frame', 'condition'] +
                         [f'bin_{i:03d}' for i in range(meta['bins'])])
            rf.flush()
            fields = ['time_s', 'frame', 'source', 'scenario_label', 'predicted_surface', 'separation_margin'] + \
                     [f'bin_{b:03d}' for b in meta['indices']] + ['distance_dry', 'distance_wet', 'distance_ice']
            writer = csv.DictWriter(pf, fieldnames=fields)
            writer.writeheader()
            pf.flush()
            print('LIVE radar started. Calibration is available in the browser when ESP32 packets arrive.')
            while running():
                packets = decoder.feed(data.read(data.in_waiting or 1))
                for frame, profile in packets:
                    now = time.monotonic()
                    wall = time.time()
                    last_frame = now
                    if first_frame is None:
                        first_frame = now
                        state.set(status='live')
                    raw.writerow([datetime.fromtimestamp(wall, timezone.utc).isoformat(), wall,
                                  frame, 'unlabeled', *profile.astype(int)])
                    state.frame(profile, decoder.bad)
                    history.append((now, profile[meta['indices']]))
                    while history and now - history[0][0] > 1:
                        history.popleft()
                    if now - first_frame >= 1 and now - last_pred >= .2:
                        x = np.median([v for _, v in history], axis=0)
                        label, margin, dist = classify(x, model)
                        row = dict(
                            time_s=round(now - started, 6), frame=frame, source='live_serial',
                            scenario_label='unlabeled', predicted_surface=label, separation_margin=margin,
                            **{f'bin_{b:03d}': float(v) for b, v in zip(meta['indices'], x)},
                            **{f'distance_{k}': float(v) for k, v in zip(['dry', 'wet', 'ice'], dist)},
                        )
                        rows.append(row)
                        writer.writerow(row)
                        pf.flush()
                        last_pred = now
                        state.prediction(row)
                if packets:
                    rf.flush()
                now = time.monotonic()
                if now - last_frame > 10:
                    raise RuntimeError(f'No valid radar TLV 2 range profile for 10 seconds. '
                                       f'Check radar DATA port and firmware. Malformed packets: {decoder.bad}')
                if args.window:
                    if rows and now - last_plot >= .5:
                        plot(fig, rows[-300:], len(rows[-300:]), 'live')
                        fig.suptitle('LIVE radar | ' + rows[-1]['predicted_surface'].upper() +
                                     '\nExperimental sample matching • ground truth unknown', fontsize=13)
                        fig.axes[-1].set_xlabel('Elapsed acquisition time (seconds)')
                        for ax in fig.axes:
                            ax.set_xlim(max(0, rows[-1]['time_s'] - 60), max(1, rows[-1]['time_s']))
                        fig.canvas.draw_idle()
                        last_plot = now
                    plt.pause(.01)
    except KeyboardInterrupt:
        print('\nStopped by user.')
    except Exception as exc:
        failure = exc
        state.set(status='error', error=str(exc))
    finally:
        state.stop.set()
        if cli is not None:
            try:
                cli.write(b'sensorStop\n')
            except (serial.SerialException, OSError):
                pass
            cli.close()
        if data is not None:
            data.close()
        if rows:
            saved = Figure(figsize=(11, 8))
            FigureCanvasAgg(saved)
            plot(saved, rows, len(rows), 'live')
            saved.suptitle('LIVE radar results — ground truth unknown\n'
                           'Experimental sample matching • scores are not probabilities', fontsize=13)
            saved.axes[-1].set_xlabel('Elapsed acquisition time (seconds)')
            png = stem.with_suffix('.png')
            saved.savefig(png, dpi=160)
            print('Saved full-session plot:', png)
        print('Output folder:', output)
        if fig is not None:
            plt.close(fig)
        if failure is None:
            state.set(status='stopped')
        if srv is not None:
            time.sleep(1.5)  # permit final status to load
            srv.shutdown()
            srv.server_close()
    if failure:
        raise SystemExit('LIVE ERROR: ' + str(failure))


if __name__ == '__main__':
    main()
