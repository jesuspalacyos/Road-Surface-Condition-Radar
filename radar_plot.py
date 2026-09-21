import serial
import struct
import math
import matplotlib.pyplot as plt

# ============================================================
# SETTINGS
# ============================================================

MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'

DATA_PORT = "COM3"
BAUD_RATE = 921600

# Higher number = slower plot updates
PRINT_EVERY = 50

# Ignore detections extremely close to the radar
MIN_DISTANCE = 0.15

# Plot ranges
X_MIN = -5
X_MAX = 5

Y_MIN = 0
Y_MAX = 10

Z_MIN = -3
Z_MAX = 3


# ============================================================
# OPEN RADAR SERIAL PORT
# ============================================================

print("Opening radar data port...")

data = serial.Serial(
    port=DATA_PORT,
    baudrate=BAUD_RATE,
    timeout=1
)

print("COM3 opened successfully.")
print("Reading TI AWR6843 radar...")
print("Press Ctrl+C to stop.\n")

buffer = b''


# ============================================================
# TOP VIEW
# X vs Y
# ============================================================

plt.ion()

fig_top = plt.figure(figsize=(8, 7))
ax_top = fig_top.add_subplot(111)

top_scatter = ax_top.scatter([], [])

ax_top.set_title("Radar Top View")
ax_top.set_xlabel("X position — Left / Right (m)")
ax_top.set_ylabel("Y position — Forward Distance (m)")

ax_top.set_xlim(X_MIN, X_MAX)
ax_top.set_ylim(Y_MIN, Y_MAX)

ax_top.grid(True)


# ============================================================
# SIDE VIEW
# Y vs Z
# ============================================================

fig_side = plt.figure(figsize=(8, 6))
ax_side = fig_side.add_subplot(111)

side_scatter = ax_side.scatter([], [])

ax_side.set_title("Radar Side View")
ax_side.set_xlabel("Y position — Forward Distance (m)")
ax_side.set_ylabel("Z position — Height (m)")

ax_side.set_xlim(Y_MIN, Y_MAX)
ax_side.set_ylim(Z_MIN, Z_MAX)

ax_side.grid(True)


# ============================================================
# MAIN RADAR LOOP
# ============================================================

while True:

    # Read incoming radar bytes
    chunk = data.read(data.in_waiting or 1)

    buffer += chunk


    # --------------------------------------------------------
    # FIND START OF FRAME
    # --------------------------------------------------------

    start = buffer.find(MAGIC_WORD)

    if start == -1:

        if len(buffer) > 10000:
            buffer = buffer[-8:]

        continue


    # Remove garbage before magic word
    buffer = buffer[start:]


    # --------------------------------------------------------
    # CHECK HEADER
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # WAIT FOR COMPLETE FRAME
    # --------------------------------------------------------

    if len(buffer) < total_packet_len:
        continue


    frame = buffer[:total_packet_len]

    buffer = buffer[total_packet_len:]


    # --------------------------------------------------------
    # SLOW DOWN DISPLAY
    # --------------------------------------------------------

    if frame_number % PRINT_EVERY != 0:
        continue


    # Storage for current frame
    x_points = []
    y_points = []
    z_points = []

    velocity_points = []


    # TLVs begin after 40-byte header
    offset = 40


    # ========================================================
    # READ TLVs
    # ========================================================

    for tlv_index in range(num_tlvs):

        if offset + 8 > len(frame):
            break


        tlv_type, tlv_length = struct.unpack(
            "<II",
            frame[offset:offset + 8]
        )


        # Move past TLV header
        offset += 8


        # ====================================================
        # TLV TYPE 1 = DETECTED POINT CLOUD
        # ====================================================

        if tlv_type == 1:

            point_size = 16

            for i in range(num_detected_obj):

                point_start = offset + i * point_size

                point_end = point_start + point_size


                if point_end > len(frame):
                    break


                x, y, z, velocity = struct.unpack(
                    "<ffff",
                    frame[point_start:point_end]
                )


                # Calculate total distance
                distance = math.sqrt(
                    x*x +
                    y*y +
                    z*z
                )


                # Ignore very-close clutter
                if distance < MIN_DISTANCE:
                    continue


                # Save useful points
                x_points.append(x)

                y_points.append(y)

                z_points.append(z)

                velocity_points.append(velocity)


        # Move to next TLV
        offset += tlv_length - 8


    # ========================================================
    # PRINT CURRENT FRAME
    # ========================================================

    print("\n====================================")

    print("FRAME:", frame_number)

    print(
        "Valid radar points:",
        len(x_points)
    )

    print("====================================")


    for i in range(len(x_points)):

        print(
            f"Point {i+1}: "
            f"X={x_points[i]:.2f} m | "
            f"Y={y_points[i]:.2f} m | "
            f"Z={z_points[i]:.2f} m | "
            f"V={velocity_points[i]:.2f} m/s"
        )


    # ========================================================
    # UPDATE TOP VIEW
    # ========================================================

    if len(x_points) > 0:

        top_scatter.set_offsets(
            list(
                zip(
                    x_points,
                    y_points
                )
            )
        )

    else:

        top_scatter.set_offsets([])


    ax_top.set_title(
        "Radar Top View\n"
        f"Frame {frame_number} | "
        f"Points: {len(x_points)}"
    )


    # ========================================================
    # UPDATE SIDE VIEW
    # ========================================================

    if len(y_points) > 0:

        side_scatter.set_offsets(
            list(
                zip(
                    y_points,
                    z_points
                )
            )
        )

    else:

        side_scatter.set_offsets([])


    ax_side.set_title(
        "Radar Side View\n"
        f"Frame {frame_number} | "
        f"Points: {len(y_points)}"
    )


    # Update both figures
    fig_top.canvas.draw_idle()
    fig_side.canvas.draw_idle()

    plt.pause(0.05)