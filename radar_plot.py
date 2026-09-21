import serial
import struct
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import time

MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'
CLI_PORT = "/dev/ttyUSB0"
DATA_PORT = "/dev/ttyUSB1"
BAUD_RATE = 921600
PRINT_EVERY = 10
MIN_DISTANCE = 0.15

# ============================================================
# OPEN BOTH PORTS FIRST
# ============================================================

print("Opening CLI port...")
cli = serial.Serial(CLI_PORT, 115200, timeout=1)
time.sleep(0.5)
cli.reset_input_buffer()

print("Opening data port...")
data = serial.Serial(DATA_PORT, BAUD_RATE, timeout=1)
data.reset_input_buffer()

# ============================================================
# SEND CONFIG — CLI STAYS OPEN
# ============================================================

print("Sending config...")

with open('profile.cfg', 'r') as f:
    for line in f:
        cmd = line.strip()
        if not cmd or cmd.startswith('%'):
            continue
        print(f">>> {cmd}")
        cli.write((cmd + '\n').encode())
        time.sleep(0.05)
        resp = cli.read(cli.in_waiting)
        if resp:
            print(resp.decode(errors='ignore').strip())

print("Config sent — CLI port staying open.")
print("Waiting 3 seconds for radar to start...")
time.sleep(3)

# ============================================================
# VERIFY DATA FLOWING
# ============================================================

waiting = data.in_waiting
print(f"Bytes waiting on data port: {waiting}")

if waiting == 0:
    print("WARNING: No data yet — waiting 3 more seconds...")
    time.sleep(3)
    waiting = data.in_waiting
    print(f"Bytes waiting now: {waiting}")

# ============================================================
# SETUP PLOTS
# ============================================================

fig_top, ax_top = plt.subplots(figsize=(8, 7))
top_scatter = ax_top.scatter([], [])
ax_top.set_title("Radar Top View")
ax_top.set_xlabel("X — Left/Right (m)")
ax_top.set_ylabel("Y — Forward (m)")
ax_top.set_xlim(-5, 5)
ax_top.set_ylim(0, 10)
ax_top.grid(True)

fig_side, ax_side = plt.subplots(figsize=(8, 6))
side_scatter = ax_side.scatter([], [])
ax_side.set_title("Radar Side View")
ax_side.set_xlabel("Y — Forward (m)")
ax_side.set_ylabel("Z — Height (m)")
ax_side.set_xlim(0, 10)
ax_side.set_ylim(-3, 3)
ax_side.grid(True)

# ============================================================
# MAIN LOOP
# ============================================================

print("Reading radar data...")
print("Press Ctrl+C to stop.\n")

buffer = b''

try:
    while True:

        chunk = data.read(data.in_waiting or 1)
        buffer += chunk

        if len(buffer) % 1000 == 0 and len(buffer) > 0:
            print(f"Buffer: {len(buffer)} bytes")

        start = buffer.find(MAGIC_WORD)

        if start == -1:
            if len(buffer) > 10000:
                buffer = buffer[-8:]
            continue

        buffer = buffer[start:]

        if len(buffer) < 40:
            continue

        try:
            (
                version,
                total_packet_len,
                platform,
                frame_number,
                time_cpu_cycles,
                num_detected_obj,
                num_tlvs,
                subframe_number
            ) = struct.unpack("<8I", buffer[8:40])

        except struct.error:
            continue

        if len(buffer) < total_packet_len:
            continue

        frame = buffer[:total_packet_len]
        buffer = buffer[total_packet_len:]

        if frame_number % PRINT_EVERY != 0:
            continue

        x_points = []
        y_points = []
        z_points = []
        velocity_points = []

        offset = 40

        for tlv_index in range(num_tlvs):

            if offset + 8 > len(frame):
                break

            tlv_type, tlv_length = struct.unpack(
                "<II", frame[offset:offset + 8]
            )
            offset += 8

            if tlv_type == 1:
                for i in range(num_detected_obj):
                    point_start = offset + i * 16
                    point_end = point_start + 16

                    if point_end > len(frame):
                        break

                    x, y, z, velocity = struct.unpack(
                        "<ffff", frame[point_start:point_end]
                    )

                    distance = math.sqrt(x*x + y*y + z*z)

                    if distance < MIN_DISTANCE:
                        continue

                    x_points.append(x)
                    y_points.append(y)
                    z_points.append(z)
                    velocity_points.append(velocity)

            offset += tlv_length - 8

        print(f"Frame {frame_number} | Points: {len(x_points)}")

        for i in range(len(x_points)):
            print(
                f"  Point {i+1}: "
                f"X={x_points[i]:.2f} | "
                f"Y={y_points[i]:.2f} | "
                f"Z={z_points[i]:.2f} | "
                f"V={velocity_points[i]:.2f} m/s"
            )

        if x_points:
            top_scatter.set_offsets(list(zip(x_points, y_points)))
        else:
            top_scatter.set_offsets([])

        ax_top.set_title(
            f"Radar Top View | Frame {frame_number} | Points: {len(x_points)}"
        )

        if y_points:
            side_scatter.set_offsets(list(zip(y_points, z_points)))
        else:
            side_scatter.set_offsets([])

        ax_side.set_title(
            f"Radar Side View | Frame {frame_number} | Points: {len(y_points)}"
        )

        fig_top.savefig('/home/admin/Desktop/top_view.png')
        fig_side.savefig('/home/admin/Desktop/side_view.png')
        print("Plots saved to Desktop")

finally:
    cli.close()
    data.close()
    print("Ports closed.")
