import sys
import serial
import struct
import math

from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import QTimer
import pyqtgraph as pg


# ============================================================
# SETTINGS
# ============================================================

MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'

DATA_PORT = "COM3"
BAUD_RATE = 921600

MAX_FORWARD = 10.0
MAX_SIDE = 5.0

# About 20 updates per second
UPDATE_MS = 50


# ============================================================
# OPEN RADAR
# ============================================================

print("Opening COM3...")

radar = serial.Serial(
    DATA_PORT,
    BAUD_RATE,
    timeout=0
)

print("COM3 connected.")
print("Starting live X-Y radar...")
print("Move an object left/right and toward/away from radar.\n")


# ============================================================
# VARIABLES
# ============================================================

radar_buffer = b""

latest_x = []
latest_y = []
latest_velocity = []

latest_frame = 0


# ============================================================
# WINDOW
# ============================================================

app = QApplication(sys.argv)

window = QMainWindow()
window.setWindowTitle("TI AWR6843 Live Radar")
window.resize(900, 750)

plot = pg.PlotWidget()

window.setCentralWidget(plot)

plot.setTitle(
    "TI AWR6843 — Live Top View"
)

plot.setLabel(
    "bottom",
    "Left / Right X",
    units="m"
)

plot.setLabel(
    "left",
    "Forward Distance Y",
    units="m"
)

plot.setXRange(
    -MAX_SIDE,
    MAX_SIDE
)

plot.setYRange(
    0,
    MAX_FORWARD
)

plot.showGrid(
    x=True,
    y=True
)


# Radar points
points = pg.ScatterPlotItem(
    size=12
)

plot.addItem(points)


# Center line showing radar direction
center_line = pg.InfiniteLine(
    pos=0,
    angle=90
)

plot.addItem(center_line)


window.show()


# ============================================================
# READ RADAR
# ============================================================

def read_radar():

    global radar_buffer
    global latest_x
    global latest_y
    global latest_velocity
    global latest_frame

    waiting = radar.in_waiting

    if waiting <= 0:
        return

    radar_buffer += radar.read(waiting)

    while True:

        # ----------------------------------------------------
        # FIND FRAME
        # ----------------------------------------------------

        magic_index = radar_buffer.find(
            MAGIC_WORD
        )

        if magic_index == -1:

            if len(radar_buffer) > 20000:
                radar_buffer = radar_buffer[-8:]

            return

        radar_buffer = radar_buffer[
            magic_index:
        ]

        if len(radar_buffer) < 40:
            return


        # ----------------------------------------------------
        # HEADER
        # ----------------------------------------------------

        try:

            (
                version,
                packet_length,
                platform,
                frame_number,
                cpu_cycles,
                num_objects,
                num_tlvs,
                subframe

            ) = struct.unpack(
                "<8I",
                radar_buffer[8:40]
            )

        except struct.error:
            return


        if packet_length <= 40:
            radar_buffer = radar_buffer[8:]
            continue

        if packet_length > 65536:
            radar_buffer = radar_buffer[8:]
            continue


        if len(radar_buffer) < packet_length:
            return


        frame = radar_buffer[
            :packet_length
        ]

        radar_buffer = radar_buffer[
            packet_length:
        ]


        # ====================================================
        # PARSE POINTS
        # ====================================================

        x_values = []
        y_values = []
        velocity_values = []

        offset = 40


        for tlv_index in range(num_tlvs):

            if offset + 8 > len(frame):
                break


            tlv_type, tlv_length = struct.unpack(
                "<II",
                frame[offset:offset + 8]
            )

            offset += 8


            # ================================================
            # TLV TYPE 1 = DETECTED POINTS
            # ================================================

            if tlv_type == 1:

                for i in range(num_objects):

                    point_start = (
                        offset +
                        i * 16
                    )

                    point_end = (
                        point_start +
                        16
                    )

                    if point_end > len(frame):
                        break


                    x, y, z, velocity = struct.unpack(
                        "<ffff",
                        frame[
                            point_start:
                            point_end
                        ]
                    )


                    distance = math.sqrt(
                        x*x +
                        y*y +
                        z*z
                    )


                    # Remove very-close radar clutter
                    if distance < 0.15:
                        continue


                    # Ignore objects behind radar
                    if y < 0:
                        continue


                    # Plot area limits
                    if y > MAX_FORWARD:
                        continue

                    if abs(x) > MAX_SIDE:
                        continue


                    x_values.append(x)

                    y_values.append(y)

                    velocity_values.append(
                        velocity
                    )


            offset += tlv_length - 8


        latest_x = x_values
        latest_y = y_values
        latest_velocity = velocity_values

        latest_frame = frame_number


# ============================================================
# UPDATE DISPLAY
# ============================================================

def update_display():

    read_radar()

    # Update radar points
    points.setData(
        latest_x,
        latest_y
    )


    plot.setTitle(
        f"TI AWR6843 — Live Top View  |  "
        f"Frame {latest_frame}  |  "
        f"Objects {len(latest_x)}"
    )


    # Print occasionally so we can verify movement
    if len(latest_x) > 0:

        print(
            f"\rFrame {latest_frame} | "
            f"Objects: {len(latest_x)} | "
            f"X: {latest_x[0]:.2f} m | "
            f"Y: {latest_y[0]:.2f} m | "
            f"V: {latest_velocity[0]:.2f} m/s",
            end=""
        )


# ============================================================
# TIMER
# ============================================================

timer = QTimer()

timer.timeout.connect(
    update_display
)

timer.start(
    UPDATE_MS
)


# ============================================================
# START PROGRAM
# ============================================================

try:

    sys.exit(
        app.exec()
    )

finally:

    radar.close()

    print("\nCOM3 closed.")