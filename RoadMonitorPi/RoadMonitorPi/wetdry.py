#!/usr/bin/env python3
"""Wet/dry road-surface test using the AWR6843 range profile (TLV 2).

Physics: rough dry pavement scatters 60 GHz energy back toward the radar;
a water film or ice is smoother and mirrors it away, so backscatter from the
road bins should DROP when the surface is wet. This script measures that.

Bench only: the range profile is the zero-Doppler slice, so the radar and the
surface must be stationary relative to each other. clutterRemoval must be OFF.

  1) capture   record N frames with a label          (needs the radar)
  2) compare   dry vs wet statistics + plot           (no radar needed)
  3) live      print power vs a dry reference, 1/s    (needs the radar)

Examples (stop app.py first - only one program can own the radar ports):
  python wetdry.py capture --label dry --height 0.6 --pitch 25
  python wetdry.py capture --label wet --height 0.6 --pitch 25
  python wetdry.py compare captures/wetdry_*.json
  python wetdry.py live --ref captures/wetdry_dry_*.json
Windows: add  --cli COM4 --data COM3
"""
import argparse, glob, json, math, queue, sys, threading, time
from datetime import datetime
from pathlib import Path

from radar import RadarParser

HERE = Path(__file__).resolve().parent
C = 299792458.0
DB_PER_LSB = 20 * math.log10(2) / 512        # TLV 2 is log2(magnitude) in Q9


# ----------------------------------------------------------------- config / geometry
def read_cfg(path):
    lines = [l.strip() for l in Path(path).read_text().splitlines()]
    lines = [l for l in lines if l and not l.startswith(('%', '#'))]
    info = {'lines': lines}
    for l in lines:
        f = l.split()
        if f[0] == 'profileCfg':
            info['slope_mhz_us'] = float(f[8]); info['adc_samples'] = int(f[10]); info['fs_ksps'] = float(f[11])
        elif f[0] == 'guiMonitor':
            info['range_profile_on'] = f[3] == '1'
        elif f[0] == 'clutterRemoval':
            info['clutter_removal'] = f[2] == '1'
    return info


def bin_size_m(info, nbins):
    return C * info['fs_ksps'] * 1e3 / (2 * info['slope_mhz_us'] * 1e12 * nbins)


def ground_m(r, h):
    return math.sqrt(r * r - h * h) if r > h else float('nan')


# ----------------------------------------------------------------- radar I/O
def ports(args):
    if args.cli and args.data:
        return args.cli, args.data
    try:
        from app import find_ports
        f = find_ports()
        return f['radar_cli'], f['radar_data']
    except Exception:
        sys.exit('Could not auto-detect radar ports. Pass --cli and --data (Windows: --cli COM4 --data COM3).')


def send_cfg(cli_port, info):
    import serial
    with serial.Serial(cli_port, 115200, timeout=.2) as cmd:
        time.sleep(.5); cmd.reset_input_buffer()
        for line in info['lines']:
            cmd.write((line + '\n').encode()); cmd.flush()
            # sensorStart runs the RF calibration and can take several seconds
            deadline = time.monotonic() + (10 if line.startswith('sensorStart') else 3); reply = b''
            while time.monotonic() < deadline:
                reply += cmd.read(cmd.in_waiting or 1)
                if b'Done' in reply or b'Error' in reply or b'not recognized' in reply:
                    break
            if b'Done' not in reply:
                sys.exit(f'Radar rejected "{line}": {reply.decode(errors="replace").strip()}')


def profile_frames(data_port):
    """Yield range profiles. A reader thread drains the port so the small Linux tty buffer never overflows."""
    import serial
    q = queue.Queue(); stop = threading.Event()
    ser = serial.Serial(data_port, 921600, timeout=.05)
    def reader():
        while not stop.is_set():
            d = ser.read(ser.in_waiting or 1)
            if d: q.put(d)
    t = threading.Thread(target=reader, daemon=True); t.start()
    p = RadarParser(); last = time.monotonic()
    try:
        while True:
            try:
                d = q.get(timeout=.5)
            except queue.Empty:
                d = b''
            got = False
            for fr in p.feed(d):
                if fr.get('range_profile'):
                    got = True; last = time.monotonic()
                    yield fr['frame'], fr['range_profile']
            if not got and time.monotonic() - last > 5:
                sys.exit('No range-profile frames for 5 s. Is the radar configured (drop --no-config) '
                         'and is the 2nd guiMonitor field 1?')
    finally:
        stop.set(); t.join(1); ser.close()


def start_radar(args):
    info = read_cfg(args.cfg)
    if not info.get('range_profile_on'):
        sys.exit(f'{args.cfg}: guiMonitor 2nd field must be 1 to send the range profile.')
    if info.get('clutter_removal'):
        sys.exit(f'{args.cfg}: clutterRemoval is ON - it subtracts the static road. Set "clutterRemoval -1 0".')
    cli, data = ports(args)
    if not args.no_config:
        print(f'Configuring radar on {cli} ...'); send_cfg(cli, info)
    return info, data


# ----------------------------------------------------------------- capture
def cmd_capture(args):
    info, data = start_radar(args)
    print(f'Settling {args.settle:.0f} s (radar warm-up drifts the first frames) ...')
    frames = []; t0 = time.monotonic()
    for fid, prof in profile_frames(data):
        if time.monotonic() - t0 < args.settle:
            continue
        frames.append(prof)
        if len(frames) % 25 == 0:
            print(f'  {len(frames)}/{args.frames}')
        if len(frames) >= args.frames:
            break
    nb = len(frames[0])
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = out / f'wetdry_{args.label}_{stamp}.json'
    meta = dict(label=args.label, time=datetime.now().isoformat(timespec='seconds'), height_m=args.height,
                pitch_deg=args.pitch, surface=args.surface, notes=args.notes, nbins=nb,
                bin_m=bin_size_m(info, nb), cfg=str(args.cfg), db_per_lsb=DB_PER_LSB)
    path.write_text(json.dumps({'meta': meta, 'frames': frames}))
    print(f'Saved {len(frames)} frames -> {path}')


# ----------------------------------------------------------------- analysis
def load(paths):
    caps = []
    for pat in paths:
        for f in sorted(glob.glob(pat)) or [pat]:
            d = json.loads(Path(f).read_text()); d['path'] = f; caps.append(d)
    if not caps:
        sys.exit('No capture files found.')
    return caps


def to_db(np, frames):
    return np.asarray(frames, dtype=float) * DB_PER_LSB


def window(np, meta, near, far):
    r = np.arange(meta['nbins']) * meta['bin_m']
    g = np.array([ground_m(x, meta['height_m']) for x in r])
    sel = (g >= near) & (g <= far)
    if not sel.any():
        sys.exit(f'No range bins between {near} and {far} m ground distance - check --height / --near / --far.')
    return r, g, sel


def frame_power(np, db, sel, ref=None):
    """Per-frame mean power over the road bins (averaged in linear power, returned in dB)."""
    p = 10 * np.log10(np.mean(10 ** (db[:, sel] / 10), axis=1))
    if ref is not None:                                   # normalise to a fixed reflector, cancels gain drift
        p = p - db[:, ref].max(axis=1)
    return p


def ref_mask(np, r, spec):
    if not spec:
        return None
    a, b = (float(v) for v in spec.split(','))
    return (r >= a) & (r <= b)


def welch_t(a, b):
    import statistics as st
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = st.variance(a) / len(a), st.variance(b) / len(b)
    return (st.mean(a) - st.mean(b)) / math.sqrt(va + vb) if va + vb > 0 else float('inf')


def cmd_compare(args):
    import numpy as np
    caps = load(args.files)
    m0 = caps[0]['meta']
    if args.height is not None:
        for c in caps: c['meta']['height_m'] = args.height
    r, g, sel = window(np, m0, args.near, args.far)
    ref = ref_mask(np, r, args.ref_range)
    labels = {}
    for c in caps:
        if c['meta']['nbins'] != m0['nbins'] or abs(c['meta']['height_m'] - m0['height_m']) > 1e-6:
            print(f"WARNING: {c['path']} has a different config/height - comparison is not like-for-like.")
        db = to_db(np, c['frames'])
        fp = frame_power(np, db, sel, ref)
        c['db'] = db; c['fp'] = fp
        labels.setdefault(c['meta']['label'], []).append(c)

    print(f"\nRoad window: ground {args.near}-{args.far} m  (bins {np.flatnonzero(sel)[0]}-{np.flatnonzero(sel)[-1]},"
          f" {m0['bin_m']*100:.1f} cm/bin, radar height {m0['height_m']} m)" + ('  [normalised to reference]' if ref is not None else ''))
    print(f"\n{'label':10} {'captures':>8} {'frames':>7} {'power dB':>9} {'frame sd':>9} {'between-capture sd':>19}")
    summary = {}
    for lab, cs in labels.items():
        means = [float(c['fp'].mean()) for c in cs]
        allf = np.concatenate([c['fp'] for c in cs])
        bsd = float(np.std(means, ddof=1)) if len(means) > 1 else float('nan')
        summary[lab] = dict(means=means, frames=allf)
        print(f"{lab:10} {len(cs):8d} {len(allf):7d} {np.mean(means):9.2f} {allf.std():9.2f} {bsd:19.2f}")

    base = args.baseline if args.baseline in summary else next(iter(summary))
    print(f'\nVersus "{base}":')
    for lab, s in summary.items():
        if lab == base:
            continue
        b = summary[base]
        delta = np.mean(s['means']) - np.mean(b['means'])
        thr = (np.mean(s['frames']) + np.mean(b['frames'])) / 2          # midpoint single-frame classifier
        lower = np.mean(s['frames']) < np.mean(b['frames'])
        acc = (np.mean((s['frames'] < thr) == lower) + np.mean((b['frames'] >= thr) == lower)) / 2
        t = welch_t(s['means'], b['means'])
        print(f"  {lab}: {delta:+.2f} dB   single-frame accuracy {acc*100:.0f}% at {thr:.1f} dB"
              + (f"   capture-level t = {t:.1f}" if t is not None else
                 "   (only 1 capture per label - repeat 3-5x before trusting this)"))
    print('\nRead this honestly: frames inside one capture are highly correlated, so single-frame accuracy\n'
          'overstates confidence. The number that matters is the dry/wet gap compared with the\n'
          'between-capture sd (re-mount, re-wet, different day). Gap >> that sd = real effect.')

    if args.plot:
        plot(np, args, labels, r, g, sel, m0)


def plot(np, args, labels, r, g, sel, m0):
    try:
        import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    except ImportError:
        print('matplotlib not installed - skipping plot (pip install matplotlib)'); return
    colors = ['#2a6fdb', '#d9480f', '#2b8a3e', '#7048e8', '#c2255c', '#495057']
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 8), constrained_layout=True)
    x = np.where(np.isfinite(g), g, np.nan)
    for i, (lab, cs) in enumerate(labels.items()):
        col = colors[i % len(colors)]
        db = np.concatenate([c['db'] for c in cs])
        mean = 10 * np.log10(np.mean(10 ** (db / 10), axis=0)); sd = db.std(axis=0)
        a1.plot(x, mean, color=col, lw=1.6, label=f'{lab} ({len(cs)} capture{"s" * (len(cs) > 1)})')
        a1.fill_between(x, mean - sd, mean + sd, color=col, alpha=.15, lw=0)
        for c in cs:
            a2.plot(c['fp'], color=col, lw=1, alpha=.8)
        a2.plot([], [], color=col, label=lab)
    a1.axvspan(args.near, args.far, color='#adb5bd', alpha=.18, lw=0, label='road window')
    a1.set(xlabel='ground distance from radar (m)', ylabel='received power (dB, relative)',
           title='Range profile: mean ± 1 sd across frames', xlim=(0, np.nanmax(x)))
    a1.grid(alpha=.3); a1.legend(frameon=False)
    a2.set(xlabel='frame', ylabel='road-window power (dB)', title='Road-window power per frame (one line per capture)')
    a2.grid(alpha=.3); a2.legend(frameon=False)
    fig.savefig(args.plot, dpi=130); print(f'Plot saved -> {args.plot}')


# ----------------------------------------------------------------- live
def cmd_live(args):
    import numpy as np
    caps = load(args.ref); m0 = caps[0]['meta']
    if args.height is not None: m0['height_m'] = args.height
    r, g, sel = window(np, m0, args.near, args.far)
    ref = ref_mask(np, r, args.ref_range)
    base_fp = np.concatenate([frame_power(np, to_db(np, c['frames']), sel, ref) for c in caps])
    base, sd = float(base_fp.mean()), float(base_fp.std())
    print(f'Dry reference: {base:.2f} dB (frame sd {sd:.2f}).  Flag when > {args.threshold} dB below.  Ctrl+C to stop.')
    args.height = m0['height_m']
    info, data = start_radar(args)
    buf = []; t = time.monotonic()
    try:
        for _, prof in profile_frames(data):
            if len(prof) != m0['nbins']:
                sys.exit('Live config has a different number of range bins than the reference capture.')
            buf.append(prof)
            if time.monotonic() - t >= 1:
                p = float(frame_power(np, to_db(np, buf), sel, ref).mean()); d = p - base
                tag = 'WET / SMOOTH?' if d < -args.threshold else ('brighter than dry' if d > args.threshold else 'dry-like')
                print(f'{datetime.now():%H:%M:%S}  {p:7.2f} dB  {d:+6.2f} dB  {tag}')
                buf = []; t = time.monotonic()
    except KeyboardInterrupt:
        pass


# ----------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    def radar_opts(p):
        p.add_argument('--cli'); p.add_argument('--data')
        p.add_argument('--cfg', default=str(HERE / 'profile.cfg'))
        p.add_argument('--no-config', action='store_true', help='radar already running; do not re-send the cfg')

    def window_opts(p):
        p.add_argument('--near', type=float, default=0.4, help='road window start, ground metres (default 0.4)')
        p.add_argument('--far', type=float, default=3.0, help='road window end, ground metres (default 3.0)')
        p.add_argument('--ref-range', help='slant range "a,b" m of a fixed metal reflector to normalise against')
        p.add_argument('--height', type=float, help='override radar height (m) stored in the captures')

    c = sub.add_parser('capture', help='record labelled frames'); radar_opts(c)
    c.add_argument('--label', required=True, help='e.g. dry, wet, puddle, ice')
    c.add_argument('--frames', type=int, default=200)
    c.add_argument('--settle', type=float, default=3.0, help='seconds to discard first')
    c.add_argument('--height', type=float, required=True, help='radar height above the surface, m')
    c.add_argument('--pitch', type=float, required=True, help='downward tilt, degrees')
    c.add_argument('--surface', default='', help='e.g. concrete, asphalt')
    c.add_argument('--notes', default='')
    c.add_argument('--out', default=str(HERE / 'captures'))

    k = sub.add_parser('compare', help='compare labelled captures'); window_opts(k)
    k.add_argument('files', nargs='+')
    k.add_argument('--baseline', default='dry')
    k.add_argument('--plot', default='wetdry.png', help='output PNG ("" to skip)')

    l = sub.add_parser('live', help='live power vs a dry reference'); radar_opts(l); window_opts(l)
    l.add_argument('--ref', nargs='+', required=True, help='dry capture file(s)')
    l.add_argument('--threshold', type=float, default=3.0, help='dB drop that counts as wet (set from compare)')

    args = ap.parse_args()
    {'capture': cmd_capture, 'compare': cmd_compare, 'live': cmd_live}[args.cmd](args)


if __name__ == '__main__':
    main()
