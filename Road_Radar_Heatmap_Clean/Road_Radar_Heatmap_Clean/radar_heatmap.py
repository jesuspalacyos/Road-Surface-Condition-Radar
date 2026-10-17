"""TI SDK 3.x static heatmap viewer. Labels are unvalidated anomaly hypotheses."""
import argparse
import struct
import time
from pathlib import Path
import numpy as np

MAGIC = bytes.fromhex('0201040306050807')


def configuration(path):
    lines = [s.strip() for s in Path(path).read_text().splitlines()
             if s.strip() and not s.lstrip().startswith('%')]
    commands = {s.split()[0]: s.split() for s in lines}
    p, c = commands['profileCfg'], commands['channelCfg']
    samples = int(p[10]); bins = 1 << (samples - 1).bit_length()
    rx = int(c[1]).bit_count()
    chirps = [s.split() for s in lines if s.startswith('chirpCfg ')]
    frame = commands['frameCfg']
    masks = set()
    for s in chirps:
        if int(s[1]) <= int(frame[2]) and int(s[2]) >= int(frame[1]):
            masks.add(int(s[8]))
    # ISK azimuth TX antennas are TX0 and TX2; this app supports one azimuth TX.
    if len(masks) != 1 or next(iter(masks)) not in (1, 4):
        raise ValueError('Use the supplied single-azimuth-TX configuration.')
    if rx < 2:
        raise ValueError('At least two RX antennas are required.')
    spacing = 299792458 * float(p[11]) * 1e3 / (2 * float(p[8]) * 1e12 * bins)
    return lines, bins, rx, spacing


class PacketStream:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        while True:
            start = self.buffer.find(MAGIC)
            if start < 0:
                self.buffer[:] = self.buffer[-7:]
                return
            del self.buffer[:start]
            if len(self.buffer) < 40:
                return
            header = struct.unpack_from('<8I', self.buffer, 8)
            length, frame, count = header[1], header[3], header[6]
            if length < 40 or length > 2_000_000 or count > 128:
                del self.buffer[0]
                continue
            if len(self.buffer) < length:
                return
            packet = bytes(self.buffer[:length]); del self.buffer[:length]
            pos = 40; tlvs = {}; valid = True
            for _ in range(count):
                if pos + 8 > length:
                    valid = False; break
                kind, size = struct.unpack_from('<II', packet, pos)
                pos += 8
                # Legacy SDK 3.x TLV length is payload length, excluding 8-byte header.
                if pos + size > length:
                    valid = False; break
                tlvs[kind] = packet[pos:pos + size]; pos += size
            if valid:
                yield frame, tlvs


def heatmap(payload, bins, antennas):
    if len(payload) != bins * antennas * 4:
        raise ValueError(f'TLV 4: expected {bins * antennas * 4} bytes, got {len(payload)}. Firmware/config mismatch.')
    iq = np.frombuffer(payload, dtype='<i2').reshape(bins, antennas, 2)
    symbols = iq[:, :, 1].astype(float) + 1j * iq[:, :, 0].astype(float)
    spectrum = np.fft.fftshift(np.fft.fft(symbols, n=64, axis=1), axes=1)
    return 20 * np.log10(np.maximum(np.abs(spectrum), 1))


class Baseline:
    def __init__(self):
        self.samples = []; self.reference = None; self.noise = None
        self.collecting = False; self.streak = None

    def start(self, _=None):
        self.__init__(); self.collecting = True

    def update(self, value, threshold, region):
        if self.collecting:
            self.samples.append(value.copy())
            if len(self.samples) >= 40:
                stack = np.stack(self.samples)
                self.reference = np.median(stack, axis=0)
                self.noise = np.maximum(1., 1.4826 * np.median(np.abs(stack - self.reference), axis=0))
                self.collecting = False; self.samples = []
                self.streak = np.zeros(value.shape, dtype=np.int16)
        if self.reference is None:
            return np.zeros_like(value), []
        delta = value - self.reference
        mask = (np.abs(delta) > np.maximum(threshold, 4 * self.noise)) & region
        self.streak = np.where(mask, np.minimum(self.streak + 1, 100), 0)
        events = []
        for sign, label in [(1, 'Stronger return: possible debris'), (-1, 'Weaker return: possible depression/pothole')]:
            selected = (self.streak >= 3) & (delta * sign > 0)
            if selected.any():
                scores = np.where(selected, sign * delta, -np.inf)
                index = np.unravel_index(np.argmax(scores), scores.shape)
                events.append((label, index, float(delta[index])))
        return delta, events


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', default=str(Path(__file__).with_name('heatmap_profile.cfg')))
    ap.add_argument('--cli', default='COM4'); ap.add_argument('--data', default='COM3')
    ap.add_argument('--baud', type=int, default=921600)
    ap.add_argument('--demo', action='store_true'); ap.add_argument('--no-config', action='store_true')
    ap.add_argument('--min-range', type=float, default=.3); ap.add_argument('--max-range', type=float, default=5)
    ap.add_argument('--threshold', type=float, default=8, help='Minimum relative amplitude change in dB')
    args = ap.parse_args()
    lines, bins, antennas, spacing = configuration(args.config)
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.widgets import Button
    port = cli = None
    if not args.demo:
        import serial
        if args.cli.upper() == args.data.upper():
            raise ValueError('CLI and DATA ports must be different.')
        try:
            port = serial.Serial(args.data, args.baud, timeout=0)
            if not args.no_config:
                cli = serial.Serial(args.cli, 115200, timeout=.1)
                time.sleep(.2); cli.reset_input_buffer()
                for line in lines:
                    cli.write((line + '\n').encode()); cli.flush()
                    reply = bytearray(); deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        reply.extend(cli.read(cli.in_waiting or 1))
                        if b'mmwDemo:/' in reply:
                            break
                    text = reply.decode(errors='replace')
                    print(line, '\n', text)
                    if 'Error' in text or 'not recognized' in text or not reply:
                        raise RuntimeError(f'Configuration failed at: {line}\n{text}')
        except Exception:
            if port: port.close()
            if cli: cli.close()
            raise
    angles = np.degrees(np.arcsin(np.arange(-32, 32) / 32))
    ranges = np.arange(bins) * spacing
    region = (ranges[:, None] >= args.min_range) & (ranges[:, None] <= args.max_range) & (np.abs(angles[None, :]) <= 60)
    plt.style.use('dark_background')
    background, panel, muted = '#0b1220', '#111c2e', '#94a3b8'
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.edgecolor': '#263449', 'text.color': '#e2e8f0',
                         'axes.labelcolor': muted, 'xtick.color': muted,
                         'ytick.color': muted})
    fig, axes = plt.subplots(1, 2, figsize=(14, 8), facecolor=background)
    fig.subplots_adjust(left=.075, right=.94, bottom=.33, top=.80, wspace=.34)
    fig.text(.075, .935, 'ROAD RADAR', fontsize=23, weight='bold')
    fig.text(.075, .892, 'Live surface scan  /  Static range–angle heatmap', color=muted, fontsize=11)
    badge = fig.text(.94, .935, 'SIMULATION' if args.demo else 'LIVE RADAR',
                     ha='right', color='#38bdf8', fontsize=11, weight='bold')
    display_angles = np.linspace(-60, 60, 241)
    def display_grid(values):
        # Interpolate for display only. This adds no physical angular resolution.
        return np.array([np.interp(display_angles, angles, row) for row in values])
    images = []
    for ax, title, cmap, limits in zip(axes,
            ['01  Radar return', '02  Change from clean road'],
            ['magma', 'RdBu_r'], [(0, 100), (-20, 20)]):
        ax.set_facecolor(panel)
        im = ax.imshow(np.zeros((bins, len(display_angles))),
                       extent=(-60, 60, 0, bins * spacing), origin='lower',
                       aspect='auto', interpolation='bilinear', cmap=cmap,
                       vmin=limits[0], vmax=limits[1])
        ax.set(title=title, xlabel='Left / right angle (degrees)',
               ylabel='Distance from radar (m)',
               ylim=(args.min_range, args.max_range), xlim=(-60, 60))
        ax.title.set_fontsize(12); ax.title.set_weight('bold'); ax.title.set_position((.5, 1.035))
        ax.set_xticks([-60, -30, 0, 30, 60])
        ax.tick_params(length=0, pad=9)
        for spine in ax.spines.values(): spine.set_visible(False)
        ax.axvline(0, color='white', alpha=.13, linewidth=.8)
        cb = fig.colorbar(im, ax=ax, pad=.025, fraction=.045)
        cb.outline.set_visible(False); cb.ax.tick_params(length=0)
        cb.set_label('Relative amplitude (dB)' if len(images) == 0 else 'Change (dB)', color=muted)
        images.append(im)
    status = fig.text(.075, .12, 'Waiting for radar data…', fontsize=11, linespacing=1.7)
    fig.text(.075, .045,
             'Experimental labels • Fixed mount required • Colors do not measure road depth',
             color=muted, fontsize=9)
    baseline = Baseline()
    button = Button(fig.add_axes([.075, .205, .26, .043]), 'Calibrate clean road',
                    color='#1e3a5f', hovercolor='#285282')
    button.label.set_color('white')
    button.on_clicked(baseline.start)
    stream = PacketStream(); last = time.monotonic(); frame_no = 0; markers = []; smoothed = None; color_limits = None
    rng = np.random.default_rng(4)
    synthetic = 45 + 8 * np.exp(-((ranges[:, None] - 2) / .5) ** 2) + np.zeros((bins, 64))
    def update(_):
        nonlocal last, frame_no, markers, smoothed, color_limits
        batches = []
        if args.demo:
            frame_no += 1; values = synthetic + rng.normal(0, .3, synthetic.shape)
            if baseline.reference is not None:
                values[35:42, 34:39] += 13; values[60:67, 23:28] -= 13
            batches.append((frame_no, values))
        else:
            for number, tlvs in stream.feed(port.read(port.in_waiting)):
                if 4 in tlvs:
                    try: batches.append((number, heatmap(tlvs[4], bins, antennas)))
                    except ValueError as error: status.set_text(str(error)); return
        for number, values in batches:
            last = time.monotonic(); delta, events = baseline.update(values, args.threshold, region)
            smoothed = values.copy() if smoothed is None else .25 * values + .75 * smoothed
            images[0].set_data(display_grid(smoothed))
            images[1].set_data(display_grid(delta))
            # Lock the return color scale after the first frame to prevent flicker.
            if color_limits is None:
                color_limits = (float(np.percentile(values, 5)), float(np.percentile(values, 99)) + 1)
                images[0].set_clim(*color_limits)
            for marker in markers: marker.remove()
            markers = []
            messages = []
            for label, (r, a), change in events:
                markers.append(axes[1].plot(angles[a], ranges[r], 'o', markerfacecolor='none', markeredgecolor='#f8fafc', markersize=13, markeredgewidth=1.8)[0])
                messages.append(f'{label} | {ranges[r]:.2f} m, {angles[a]:.0f} deg, {change:+.1f} dB')
            if baseline.collecting: message = f'Clean-road calibration: {len(baseline.samples)}/40 frames. Keep scene still.'
            elif baseline.reference is None: message = 'Aim at clean road, keep mount fixed, then click Calibrate.'
            else: message = '\n'.join(messages) or 'No persistent anomaly above threshold.'
            badge.set_text(('SIMULATION' if args.demo else 'LIVE RADAR') + f'  •  Frame {number}')
            status.set_text(message)
        if time.monotonic() - last > 3:
            status.set_text('No TLV 4 heatmap for 3 seconds. Check DATA port, firmware, guiMonitor, and sensorStart.')
    animation = FuncAnimation(fig, update, interval=100, cache_frame_data=False)
    try: plt.show()
    finally:
        if port: port.close()
        if cli: cli.close()


if __name__ == '__main__':
    main()
