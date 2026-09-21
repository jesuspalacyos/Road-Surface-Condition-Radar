import serial
import struct
import math
import matplotlib.pyplot as plt
import numpy as np

# ============================================================
# SETTINGS
# ============================================================

MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'

DATA_PORT = "COM3"
BAUD_RATE = 921600

# Update more often than before
UPDATE_EVERY = 5

# Useful radar region
MIN_DISTANCE = 0.20
MAX_FORWARD_DISTANCE = 8.0
MAX_SIDE_DISTANCE = 2.0

# Divide road ahead into distance sections
BIN_SIZE = 0.25

# ============================================================
# SERIAL
# ============================================================

data = serial.Serial(
    port=DATA_PORT,
    baudrate=BAUD_RATE,
    timeout=1
)

buffer = b''

print("======================================")
print(" ROAD CONDITION RADAR")
print("======================================")
print("COM3 connected")
print("Live road profile starting...")
print("Press Ctrl+C to stop.\n")

# ============================================================
# CREATE ONE FAST LINE PLOT
# ============================================================

plt.ion()

fig, ax = plt.subplots(figsize=(10, 6))

road_line, = ax.plot([], [], marker="o")

ax.set_title("AWR6843 Road Surface Profile")
ax.set_xlabel("Forward Distance Y (m)")
ax.set_ylabel("Road Height Z (m)")

ax.set_xlim(0, MAX_FORWARD_DISTANCE)
ax.set_ylim(-2, 2)

ax.grid(True)

# Distance bins
bins = np.arange(
    0,
    MAX_FORWARD_DISTANCE + BIN_SIZE,
    BIN_SIZE
)

# ============================================================
# MAIN LOOP
# ============================================================

while True:

    chunk = data.read(data.in_waiting or 1)
    buffer += chunk

    # --------------------------------------------------------
    # FIND FRAME
    # --------------------------------------------------------

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

        ) = struct.unpack(
            "<8I",
            buffer[8:40]
        )

    except struct.error:
        continue

    if len(buffer) < total_packet_len:
        continue

    frame = buffer[:total_packet_len]
    buffer = buffer[total_packet_len:]

    # Only process some frames
    if frame_number % UPDATE_EVERY != 0:
        continue

    # ========================================================
    # EXTRACT POINTS
    # ========================================================

    x_points = []
    y_points = []
    z_points = []

    offset = 40

    for tlv_index in range(num_tlvs):

        if offset + 8 > len(frame):
            break

        tlv_type, tlv_length = struct.unpack(
            "<II",
            frame[offset:offset + 8]
        )

        offset += 8

        if tlv_type == 1:

            point_size = 16

            for i in range(num_detected_obj):

                start_point = offset + i * point_size
                end_point = start_point + point_size

                if end_point > len(frame):
                    break

                x, y, z, velocity = struct.unpack(
                    "<ffff",
                    frame[start_point:end_point]
                )

                distance = math.sqrt(
                    x*x +
                    y*y +
                    z*z
                )

                # Remove useless / unlikely road points
                if distance < MIN_DISTANCE:
                    continue

                if y < 0 or y > MAX_FORWARD_DISTANCE:
                    continue

                if abs(x) > MAX_SIDE_DISTANCE:
                    continue

                x_points.append(x)
                y_points.append(y)
                z_points.append(z)

        offset += tlv_length - 8

    # ========================================================
    # CREATE ROAD PROFILE
    # ========================================================

    profile_y = []
    profile_z = []

    if len(y_points) > 0:

        y_array = np.array(y_points)
        z_array = np.array(z_points)

        # Examine road in small forward-distance bins
        for i in range(len(bins) - 1):

            lower = bins[i]
            upper = bins[i + 1]

            mask = (
                (y_array >= lower) &
                (y_array < upper)
            )

            if np.any(mask):

                # Median is more resistant to random radar points
                z_estimate = np.median(
                    z_array[mask]
                )

                y_center = (
                    lower + upper
                ) / 2

                profile_y.append(
                    y_center
                )

                profile_z.append(
                    z_estimate
                )

    # ========================================================
    # SIMPLE ROAD CONDITION ESTIMATION
    # ========================================================

    condition = "UNKNOWN"

    if len(profile_z) >= 3:

        z_np = np.array(profile_z)

        median_height = np.median(z_np)

        deviations = (
            z_np - median_height
        )

        lowest = np.min(deviations)
        highest = np.max(deviations)

        # TEMPORARY THRESHOLDS
        # We will calibrate these from real test data later.

        if lowest < -0.20:

            condition = "POSSIBLE POTHOLE"

        elif highest > 0.20:

            condition = "POSSIBLE DEBRIS / BUMP"

        else:

            condition = "ROAD APPEARS NORMAL"

    # ========================================================
    # UPDATE GRAPH
    # ========================================================

    road_line.set_data(
        profile_y,
        profile_z
    )

    ax.set_title(
        "AWR6843 Road Surface Profile\n"
        f"Frame {frame_number} | "
        f"{condition}"
    )

    fig.canvas.draw_idle()

    # Short pause makes GUI responsive without huge lag
    plt.pause(0.001)

    # ========================================================
    # SIMPLE TERMINAL OUTPUT
    # ========================================================

    print(
        f"Frame {frame_number} | "
        f"Points: {len(y_points)} | "
        f"Profile: {len(profile_y)} | "
        f"{condition}"
    )