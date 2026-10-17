"""Experimental fixed-mount surface comparison for TI mmWave SDK 3.x OOB UART.
No pretrained ice detector. Range values remain in raw firmware units.
"""
import argparse
import hashlib
import json
from pathlib import Path
import queue
import struct
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np
import serial
from serial.tools import list_ports

MAGIC = bytes.fromhex('0201040306050807')
LABELS = ('dry', 'wet', 'ice')
ROOT = Path(__file__).resolve().parent


def config(path):
    raw = Path(path).read_bytes()
    lines = [s.split('%')[0].strip() for s in raw.decode('utf-8-sig').splitlines()]
    lines = [s for s in lines if s]
    p = next(s.split() for s in lines if s.startswith('profileCfg '))
    n = 1 << (int(p[10])-1).bit_length()
    spacing = 299792458 * float(p[11])*1000 / (2*float(p[8])*1e12*n)
    return lines, n, spacing, hashlib.sha256(raw).hexdigest()


class Decoder:
    def __init__(self, bins):
        self.buf = bytearray()
        self.bins = bins
        self.bad = 0

    def feed(self, data):
        self.buf.extend(data)
        out = []
        while True:
            i = self.buf.find(MAGIC)
            if i < 0:
                self.buf[:] = self.buf[-7:]
                break
            if i:
                del self.buf[:i]
            if len(self.buf) < 40:
                break
            version, size, platform, frame, cycles, objects, count, sub = struct.unpack_from('<8I', self.buf, 8)
            if size < 40 or size > 1048576 or count > 64:
                del self.buf[0]
                self.bad += 1
                continue
            if len(self.buf) < size:
                # Resynchronize if a corrupt length masks a subsequent complete packet.
                j = self.buf.find(MAGIC, 8)
                if j >= 0 and len(self.buf) >= j+40:
                    next_size = struct.unpack_from('<I', self.buf, j+12)[0]
                    if 40 <= next_size <= len(self.buf)-j:
                        del self.buf[:j]
                        self.bad += 1
                        continue
                break
            packet = bytes(self.buf[:size])
            del self.buf[:size]
            pos, profile, valid = 40, None, True
            for _ in range(count):
                if pos+8 > size:
                    valid = False
                    break
                typ, length = struct.unpack_from('<II', packet, pos)
                pos += 8
                # SDK 3.x OOB length excludes the 8-byte TLV header.
                if pos+length > size:
                    valid = False
                    break
                if typ == 2:
                    if length != self.bins*2:
                        valid = False
                        break
                    profile = np.frombuffer(packet, dtype='<u2', count=self.bins, offset=pos).astype(float)
                pos += length
            if valid and profile is not None and sub == 0:
                out.append((frame, profile))
            elif not valid:
                self.bad += 1
        return out


def fit(sessions):
    x = np.array([np.median(s['windows'], axis=0) for s in sessions])
    y = np.array([s['label'] for s in sessions])
    scale = np.maximum(np.std(x, axis=0), 32.0)
    centers = np.array([np.mean(x[y == k], axis=0) for k in LABELS])
    radii = []
    for k, c in zip(LABELS, centers):
        windows = np.concatenate([s['windows'] for s in sessions if s['label'] == k])
        d = np.sqrt(np.mean(((windows-c)/scale)**2, axis=1))
        radii.append(max(0.35, float(np.quantile(d, .95))*1.5))
    return centers, scale, np.array(radii)


def predict(model, x):
    centers, scale, radii = model
    d = np.sqrt(np.mean(((centers-x)/scale)**2, axis=1))
    order = np.argsort(d)
    k = order[0]
    margin = float((d[order[1]]-d[k])/max(d[order[1]], 1e-9))
    accepted = d[k] <= radii[k] and margin >= .25
    return LABELS[k] if accepted else 'unknown', margin


class App:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.lines, self.bins, self.spacing, self.digest = config(args.cfg)
        self.events = queue.Queue(maxsize=1000)
        self.stop = threading.Event()
        self.worker = None
        self.sessions, self.model = [], None
        self.recording = None
        self.batch, self.window_start = [], time.monotonic()
        self.last_frame = 0
        self.meta = None
        self.history = []
        root.title('AWR6843ISK • Experimental Ice Surface Comparison')
        root.geometry('960x680')
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Surface comparison lab', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Experimental sample matching • No calibrated probability • Fixed mounting required').pack(anchor='w')
        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=14)
        self.cli, self.data = tk.StringVar(value=args.cli), tk.StringVar(value=args.data)
        ports = [p.device for p in list_ports.comports()]
        for title, var in [('CLI port', self.cli), ('DATA port', self.data)]:
            ttk.Label(controls, text=title).pack(side='left', padx=4)
            ttk.Combobox(controls, textvariable=var, values=ports, width=10).pack(side='left')
        self.lo, self.hi = tk.StringVar(value='0.5'), tk.StringVar(value='1.5')
        for title, var in [('Range min (m)', self.lo), ('max (m)', self.hi)]:
            ttk.Label(controls, text=title).pack(side='left', padx=4)
            ttk.Entry(controls, textvariable=var, width=6).pack(side='left')
        self.connect_btn = ttk.Button(controls, text='Connect', command=self.connect)
        self.connect_btn.pack(side='left', padx=10)
        self.result = tk.StringVar(value='NOT CALIBRATED')
        ttk.Label(frame, textvariable=self.result, font=('Segoe UI', 24, 'bold')).pack(anchor='w')
        self.status = tk.StringVar(value=f'Range-bin spacing: {self.spacing:.3f} m. Select ports and a range window around the surface.')
        ttk.Label(frame, textvariable=self.status, wraplength=900).pack(anchor='w', pady=8)
        self.canvas = tk.Canvas(frame, background='#101b2b', height=230, highlightthickness=0)
        self.canvas.pack(fill='x')
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=12)
        for label in LABELS:
            ttk.Button(buttons, text=f'Record {label.upper()} (15 s)', command=lambda k=label:self.record(k)).pack(side='left', padx=4)
        ttk.Button(buttons, text='Build / validate model', command=self.train).pack(side='left', padx=8)
        self.counts = tk.StringVar(value='Record at least 3 independent sessions per surface; 5–10 recommended.')
        ttk.Label(frame, textvariable=self.counts).pack(anchor='w')
        self.log = tk.Text(frame, height=7, wrap='word')
        self.log.pack(fill='both', expand=True, pady=8)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(60, self.poll)

    def note(self, text):
        self.log.insert('end', text+'\n')
        self.log.see('end')

    def connect(self):
        try:
            if self.worker and self.worker.is_alive():
                raise ValueError('Previous connection is still closing; retry in a moment.')
            self.stop.clear()
            self.model = None
            self.batch, self.history = [], []
            self.window_start = time.monotonic()
            if self.cli.get() == self.data.get():
                raise ValueError('CLI and DATA must be different ports.')
            lo, hi = float(self.lo.get()), float(self.hi.get())
            if not 0 < lo < hi <= (self.bins-1)*self.spacing:
                raise ValueError('Enter a valid positive range interval.')
            self.indices = np.where((np.arange(self.bins)*self.spacing >= lo)&(np.arange(self.bins)*self.spacing <= hi))[0]
            if len(self.indices) < 3:
                raise ValueError('Select at least 3 range bins (a wider range window).')
            self.meta = {'cfg_sha256':self.digest, 'bins':self.bins, 'indices':self.indices.tolist(), 'features':'median_raw_range_v1'}
            if self.args.samples.exists():
                saved = json.loads(self.args.samples.read_text())
                if saved['metadata'] != self.meta:
                    raise ValueError('Saved samples use a different configuration/range. Restore that range or use --samples new_samples.json.')
                self.sessions = saved['sessions']
                self.update_counts()
            self.connect_btn.config(state='disabled')
            self.worker = threading.Thread(target=self.acquire, args=(self.cli.get(), self.data.get()), daemon=True)
            self.worker.start()
        except Exception as e:
            messagebox.showerror('Connection', str(e))

    def acquire(self, cli_port, data_port):
        cli = data = None
        try:
            cli = serial.Serial(cli_port, 115200, timeout=.15, write_timeout=2)
            data = serial.Serial(data_port, self.args.baud, timeout=.1)
            decoder = Decoder(self.bins)
            with open(ROOT/'cli_log.txt', 'w', encoding='utf-8') as log:
                for line in self.lines:
                    if self.stop.is_set():
                        return
                    cli.reset_input_buffer()
                    cli.write((line+'\n').encode())
                    response = bytearray()
                    deadline = time.monotonic()+5
                    while time.monotonic() < deadline:
                        response.extend(cli.read(cli.in_waiting or 1))
                        if b'Done' in response or b'Error' in response or b'not recognized' in response:
                            break
                    answer = response.decode(errors='replace')
                    log.write(line+'\n'+answer+'\n')
                    log.flush()
                    if 'Done' not in answer or 'Error' in answer or 'not recognized' in answer:
                        raise RuntimeError(f'Configuration rejected/timed out at: {line}\n{answer}\nSee cli_log.txt; verify SDK 3.6 OOB firmware.')
            self.events.put(('note', 'Configuration accepted. Waiting for range-profile TLV 2.'))
            last = time.monotonic()
            while not self.stop.is_set():
                for item in decoder.feed(data.read(data.in_waiting or 1)):
                    last = time.monotonic()
                    try:
                        self.events.put_nowait(('frame', item))
                    except queue.Full:
                        raise RuntimeError('Display cannot keep up; recording stopped to avoid stale classification.')
                if time.monotonic()-last > 10:
                    raise RuntimeError(f'No valid range profile for 10 s. Check DATA port, baud and SDK OOB firmware. Malformed packets: {decoder.bad}')
        except Exception as e:
            self.events.put(('error', str(e)))
        finally:
            if cli:
                try:
                    cli.write(b'sensorStop\n')
                except Exception:
                    pass
                cli.close()
            if data:
                data.close()

    def update_counts(self):
        self.counts.set('Saved sessions: '+ ' | '.join(f'{k.upper()}: {sum(s["label"] == k for s in self.sessions)}' for k in LABELS))

    def record(self, label):
        if time.monotonic()-self.last_frame > 2 or not self.meta:
            messagebox.showinfo('Recording', 'Connect and wait for live data first.')
            return
        if self.recording:
            return
        if not messagebox.askokcancel('Confirm known surface', f'Is the surface actually {label.upper()}?\nUse independent ground truth, the same substrate, and the same mounting. Keep people and hands out of view during recording.'):
            return
        self.recording = {'label':label, 'started':time.time(), 'windows':[]}
        self.record_end = time.monotonic()+15
        self.batch = []
        self.window_start = time.monotonic()
        self.model = None
        self.result.set('RECORDING '+label.upper())

    def train(self):
        if self.recording:
            return
        if any(sum(s['label']==k for s in self.sessions)<3 for k in LABELS):
            messagebox.showinfo('More samples needed', 'Record at least 3 independent sessions for EACH of dry, wet and ice.')
            return
        matrix = {k:{p:0 for p in (*LABELS,'unknown')} for k in LABELS}
        for i, held in enumerate(self.sessions):
            model = fit(self.sessions[:i]+self.sessions[i+1:])
            for x in held['windows']:
                label, _ = predict(model, np.array(x))
                matrix[held['label']][label] += 1
        self.note('Leave-one-session-out results (held-out windows; not field accuracy):')
        for k, row in matrix.items():
            self.note(k.upper()+': '+str(row))
        report = {'method':'leave-one-session-out; all windows from held session excluded', 'counts':matrix,
                  'warning':'Same-mount lab check only. Adjacent windows are correlated. Validate on new days and specimens.'}
        self.args.samples.with_suffix('.validation.json').write_text(json.dumps(report, indent=2))
        self.model = fit(self.sessions)
        self.history = []
        self.note('Model built. UNKNOWN means ambiguous or outside sample envelope. Matching thresholds are heuristics.')

    def draw(self, profile):
        c = self.canvas
        c.delete('all')
        n = min(self.bins, max(20, int(self.indices[-1])+5))
        values = profile[:n]
        w, h = max(c.winfo_width(), 600), 230
        low, high = float(values.min()), float(values.max())
        coords = []
        for i, v in enumerate(values):
            coords.extend((45+i*(w-65)/(n-1), 185-(v-low)/max(high-low,1)*145))
        for idx in [self.indices[0], self.indices[-1]]:
            x = 45+idx*(w-65)/(n-1)
            c.create_line(x,25,x,190,fill='#f4cb70',dash=(4,4))
        c.create_line(*coords, fill='#63ddd0', width=2)
        c.create_text(12,10,anchor='nw',fill='white',text=f'Range profile • raw firmware units • auto-scaled [{low:.0f}, {high:.0f}]')
        c.create_text(45,210,anchor='w',fill='white',text=f'0 m                        Distance from radar (slant range)                        {(n-1)*self.spacing:.2f} m')

    def on_frame(self, item):
        frame, profile = item
        now = time.monotonic()
        self.last_frame = now
        self.batch.append(profile[self.indices])
        self.draw(profile)
        self.status.set(f'Frame {frame} | Surface window: {self.indices[0]*self.spacing:.2f}–{self.indices[-1]*self.spacing:.2f} m | Receiving range data')
        if now-self.window_start < 1:
            return
        batch, self.batch = self.batch, []
        self.window_start = now
        if len(batch)<5:
            self.result.set('UNKNOWN — insufficient fresh frames')
            self.history = []
            return
        x = np.median(batch, axis=0)
        if self.recording:
            self.recording['windows'].append(x.tolist())
            self.result.set(f'RECORDING {self.recording["label"].upper()} — {max(0,int(self.record_end-now))} s')
            if now >= self.record_end:
                if len(self.recording['windows']) >= 10:
                    self.sessions.append(self.recording)
                    payload = {'metadata':self.meta,'sessions':self.sessions}
                    temp = self.args.samples.with_suffix('.tmp')
                    temp.write_text(json.dumps(payload))
                    temp.replace(self.args.samples)
                    self.note('Saved '+self.recording['label']+' session. Change/reprepare the sample before the next session.')
                else:
                    self.note('Discarded session: insufficient valid windows.')
                self.recording = None
                self.update_counts()
                self.result.set('Build model after recording all surfaces')
        elif self.model:
            label, margin = predict(self.model, x)
            self.history = (self.history+[label])[-3:]
            stable = len(self.history)==3 and len(set(self.history))==1
            result = label if stable else 'unknown'
            text = 'ICE-LIKE SAMPLE MATCH' if result=='ice' else result.upper()
            self.result.set(text)
        else:
            self.result.set('NOT CALIBRATED — record samples / build model')

    def poll(self):
        try:
            for _ in range(100):
                kind, payload = self.events.get_nowait()
                if kind=='frame':
                    self.on_frame(payload)
                elif kind=='error':
                    self.note('ERROR: '+payload)
                    self.result.set('DISCONNECTED / NO VALID DATA')
                    self.recording = None
                    self.batch, self.history = [], []
                    self.last_frame = 0
                    self.connect_btn.config(state='normal')
                else:
                    self.note(payload)
        except queue.Empty:
            pass
        except Exception as e:
            self.note('ERROR: '+str(e))
            self.recording = None
            self.stop.set()
        if self.last_frame and time.monotonic()-self.last_frame>2:
            self.result.set('UNKNOWN — stale data')
            self.recording = None
            self.batch, self.history = [], []
        self.root.after(60, self.poll)

    def close(self):
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=1)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cfg', type=Path, default=ROOT/'road_profile.cfg')
    parser.add_argument('--cli', default='COM4')
    parser.add_argument('--data', default='COM3')
    parser.add_argument('--baud', type=int, default=921600)
    parser.add_argument('--samples', type=Path, default=ROOT/'surface_samples.json')
    args = parser.parse_args()
    root = tk.Tk()
    App(root, args)
    root.mainloop()


if __name__ == '__main__':
    main()
