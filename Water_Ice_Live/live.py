"""Live TI radar range-profile logging; no generated data or replay.

Debug view is a web page by default (open http://<this machine>:8050 in a browser).
Use --window for the old matplotlib window instead.
"""
import argparse
import csv
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from collections import deque
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import numpy as np
import serial
from serial.tools import list_ports
from radar_decoder import Decoder
from radar_model import load_model, classify, plot

ROOT = Path(__file__).resolve().parent


def configure(cli, cfg, on_line=None):
    lines = [s.split('%')[0].strip() for s in cfg.read_text(encoding='utf-8-sig').splitlines()]
    with (ROOT/'cli_live_log.txt').open('w', encoding='utf-8') as log:
        for command in filter(None, lines):
            cli.reset_input_buffer()
            cli.write((command+'\n').encode())
            response = bytearray()
            deadline = time.monotonic()+5
            while time.monotonic()<deadline:
                response.extend(cli.read(cli.in_waiting or 1))
                if any(s in response for s in [b'Done', b'Error', b'not recognized']):
                    break
            answer = response.decode(errors='replace')
            log.write(command+'\n'+answer+'\n'); log.flush()
            ok = b'Done' in response and b'Error' not in response and b'not recognized' not in response
            if on_line: on_line(command, ok)
            if not ok:
                raise RuntimeError('Radar rejected or did not acknowledge: '+command+'\n'+answer)


# ---------------------------------------------------------------- shared state for the web page
class State:
    def __init__(self, meta, args, pred_path):
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.started = time.monotonic()
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
        with self.lock: self.s.update(kw)

    def config_line(self, command, ok):
        with self.lock:
            self.s['config_log'].append({'cmd': command, 'ok': ok})
            self.s['config_log'] = self.s['config_log'][-60:]

    def frame(self, profile, bad):
        now = time.monotonic()
        with self.lock:
            self._last_frame = now
            self._frame_times.append(now)
            while self._frame_times and now-self._frame_times[0] > 2: self._frame_times.popleft()
            self.s['frames'] += 1
            self.s['bad_packets'] = bad
            self.s['fps'] = round(len(self._frame_times)/2, 1)
            self.s['profile'] = [int(v) for v in profile]

    def prediction(self, row):
        with self.lock:
            self.s.update(prediction=row['predicted_surface'], margin=round(row['separation_margin'], 3),
                          distances={k: round(row['distance_'+k], 3) for k in ('dry', 'wet', 'ice')},
                          features={str(b): round(row[f'bin_{b:03d}'], 1) for b in self.s['feature_bins']})
            self.s['history'].append({'t': round(row['time_s'], 2), 'p': row['predicted_surface'],
                                      'd': [round(row['distance_'+k], 3) for k in ('dry', 'wet', 'ice')],
                                      'b': [round(row[f'bin_{b:03d}'], 1) for b in self.s['feature_bins']]})
            cutoff = row['time_s'] - 60
            while self.s['history'] and self.s['history'][0]['t'] < cutoff: self.s['history'].pop(0)

    def snapshot(self):
        with self.lock:
            out = dict(self.s)
            out['elapsed_s'] = round(time.monotonic()-self.started, 1)
            out['data_age_s'] = None if self._last_frame is None else round(time.monotonic()-self._last_frame, 1)
            return json.dumps(out)


def start_web(state, host, port):
    page = (ROOT/'debug.html').read_bytes()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def send(self, body, typ='application/json', code=200):
            if isinstance(body, str): body = body.encode()
            self.send_response(code); self.send_header('Content-Type', typ)
            self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store')
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if self.path in ('/', '/index.html'): self.send(page, 'text/html; charset=utf-8')
            elif self.path == '/api/state': self.send(state.snapshot())
            else: self.send('not found', 'text/plain', 404)
        def do_POST(self):
            if self.path == '/api/stop':
                state.stop.set(); self.send('{"ok":true}')
            else: self.send('not found', 'text/plain', 404)

    srv = ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--list-ports', action='store_true')
    p.add_argument('--cli', help='CLI/Application UART, e.g. COM4 or /dev/ttyUSB0')
    p.add_argument('--data', help='DATA/Auxiliary UART, e.g. COM3 or /dev/ttyUSB1')
    p.add_argument('--baud', type=int, default=921600)
    p.add_argument('--cfg', type=Path, default=ROOT/'road_profile.cfg')
    p.add_argument('--window', action='store_true', help='use the old matplotlib window instead of the web page')
    p.add_argument('--host', default='0.0.0.0', help='web page address (0.0.0.0 = reachable from other devices)')
    p.add_argument('--port', type=int, default=8050, help='web page port')
    args=p.parse_args()
    if args.list_ports:
        for port in list_ports.comports(): print(port.device, '-', port.description)
        return
    if not args.cli or not args.data: p.error('Specify --cli and --data; use --list-ports to find them.')
    if args.cli.lower()==args.data.lower(): p.error('CLI and DATA ports must be different.')
    model=load_model(); meta=model[0]
    if hashlib.sha256(args.cfg.read_bytes()).hexdigest()!=meta['cfg_sha256']:
        p.error('Configuration does not match saved training samples. Use bundled road_profile.cfg.')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    plt = None
    if args.window:
        import matplotlib.pyplot as plt
    output=ROOT/'outputs'; output.mkdir(exist_ok=True)
    stem=output/('live_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    raw_path=stem.with_name(stem.name+'_raw').with_suffix('.csv')
    pred_path=stem.with_name(stem.name+'_predictions').with_suffix('.csv')
    info={'source':'live_serial', 'ground_truth':'unlabeled', 'cli':args.cli,'data':args.data,
          'baud':args.baud,'cfg_sha256':meta['cfg_sha256'],'feature_indices':meta['indices'],
          'feature_window_seconds':1,'note':'Experimental wet/ice sample matching; scores are not probabilities.'}
    stem.with_suffix('.metadata.json').write_text(json.dumps(info,indent=2))

    state = State(meta, args, pred_path)
    srv = None
    if not args.window:
        srv = start_web(state, args.host, args.port)
        print(f'Debug page: http://localhost:{args.port}  (from another device: http://<this machine IP>:{args.port})')

    cli=data=None; rows=[]; history=deque(); failure=None; fig=None
    try:
        cli=serial.Serial(args.cli,115200,timeout=.1,write_timeout=2)
        data=serial.Serial(args.data,args.baud,timeout=.01)
        print('Sending the bundled radar configuration...')
        state.set(status='configuring')
        configure(cli,args.cfg,state.config_line)
        decoder=Decoder(meta['bins'])
        state.set(status='waiting for data')
        if args.window:
            fig=plt.figure(figsize=(11,8)); fig.canvas.manager.set_window_title('LIVE radar — close to stop and save')
            fig.text(.1,.5,'Waiting for live range-profile data (TLV 2)...')
            plt.show(block=False)
        running = (lambda: plt.fignum_exists(fig.number)) if args.window else (lambda: not state.stop.is_set())
        started=time.monotonic(); last_frame=started; last_plot=0; last_pred=0; first_frame=None
        with raw_path.open('w',newline='',encoding='utf-8') as rf, pred_path.open('w',newline='',encoding='utf-8') as pf:
            raw=csv.writer(rf)
            raw.writerow(['timestamp_utc','unix_time_s','frame','condition']+[f'bin_{i:03d}' for i in range(meta['bins'])]); rf.flush()
            fields=['time_s','frame','source','scenario_label','predicted_surface','separation_margin']+[f'bin_{b:03d}' for b in meta['indices']]+['distance_dry','distance_wet','distance_ice']
            writer=csv.DictWriter(pf,fieldnames=fields); writer.writeheader(); pf.flush()
            print('LIVE acquisition started. '+('Close the plot' if args.window else 'Press Stop on the page')+' or press Ctrl+C to stop.\nCSV:',pred_path)
            while running():
                packets=decoder.feed(data.read(data.in_waiting or 1))
                for frame, profile in packets:
                    now=time.monotonic(); wall=time.time(); last_frame=now
                    if first_frame is None:
                        first_frame=now; state.set(status='live')
                    raw.writerow([datetime.fromtimestamp(wall,timezone.utc).isoformat(),wall,frame,'unlabeled',*profile.astype(int)])
                    state.frame(profile, decoder.bad)
                    history.append((now,profile[meta['indices']]))
                    while history and now-history[0][0]>1: history.popleft()
                    if now-first_frame>=1 and now-last_pred>=.2:
                        x=np.median([v for _,v in history],axis=0)
                        label,margin,dist=classify(x,model)
                        row=dict(time_s=round(now-started,6),frame=frame,source='live_serial',scenario_label='unlabeled',predicted_surface=label,separation_margin=margin,
                                 **{f'bin_{b:03d}':float(v) for b,v in zip(meta['indices'],x)},
                                 **{f'distance_{k}':float(v) for k,v in zip(['dry','wet','ice'],dist)})
                        rows.append(row); writer.writerow(row); pf.flush(); last_pred=now
                        state.prediction(row)
                if packets: rf.flush()
                now=time.monotonic()
                if now-last_frame>10: raise RuntimeError(f'No valid TLV 2 range profile for 10 seconds. Check DATA port/baud and firmware. Malformed packets: {decoder.bad}')
                if args.window:
                    if rows and now-last_plot>=.5:
                        plot(fig,rows[-300:],len(rows[-300:]),'live')
                        fig.suptitle('LIVE radar | '+rows[-1]['predicted_surface'].upper()+'\nExperimental sample matching • ground truth unknown',fontsize=13)
                        fig.axes[-1].set_xlabel('Elapsed acquisition time (seconds)')
                        for ax in fig.axes: ax.set_xlim(max(0,rows[-1]['time_s']-60),max(1,rows[-1]['time_s']))
                        fig.canvas.draw_idle(); last_plot=now
                    plt.pause(.01)
    except KeyboardInterrupt:
        print('\nStopped by user.')
    except Exception as exc:
        failure=exc
        state.set(status='error', error=str(exc))
    finally:
        if cli is not None:
            try: cli.write(b'sensorStop\n')
            except serial.SerialException: pass
            cli.close()
        if data is not None: data.close()
        if rows:
            saved=Figure(figsize=(11,8)); FigureCanvasAgg(saved)
            plot(saved,rows,len(rows),'live')
            saved.suptitle('LIVE radar results — ground truth unknown\nExperimental sample matching • scores are not probabilities',fontsize=13)
            saved.axes[-1].set_xlabel('Elapsed acquisition time (seconds)')
            saved.savefig(stem.with_suffix('.png'),dpi=160)
            print('Saved full-session line plot:',stem.with_suffix('.png'))
        print('Output folder:',output)
        if fig is not None: plt.close(fig)
        if failure is None: state.set(status='stopped')
        if srv is not None:
            time.sleep(1.5)          # let the page fetch the final status
            srv.shutdown()
    if failure: raise SystemExit('LIVE ERROR: '+str(failure))

if __name__=='__main__': main()
