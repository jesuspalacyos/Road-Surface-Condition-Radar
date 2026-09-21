import sys
import serial
import struct
import math

from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import QTimer
import pyqtgraph as pg


# ============================================================
# RADAR SETTINGS
# ============================================================

MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'

DATA_PORT = "COM3"
BAUD_RATE = 921600

MAX_FORWARD_DISTANCE = 10.0

# How often graph refreshes
# 30 ms is about 33 updates/second
GRAPH_UPDATE_MS = 30


# ============================================================
# OPEN RADAR
# ============================================================

print("Opening COM3...")

radar = serial.Serial(
    port=DATA_PORT,
    baudrate=BAUD_RATE,
    timeout=0
)

print("COM3 connected.")
print("Starting fast radar display...")
print("Close the graph window to stop.\n")


# ============================================================
# GLOBAL RADAR BUFFER
# ============================================================

radar_buffer = b""

latest_y = []
latest_z = []

latest_frame = 0
latest_objects = 0


# ============================================================
# QT WINDOW
# ============================================================

app = QApplication(sys.argv)

window = QMainWindow()
window.setWindowTitle("AWR6843 Road Condition Radar")
window.resize(1100, 650)

plot = pg.PlotWidget()

window.setCentralWidget(plot)

plot.setTitle(
    "TI AWR6843 — Live Road Profile"
)

plot.setLabel(
    "bottom",
    "Forward Distance",
    units="m"
)

plot.setLabel(
    "left",
    "Height Z",
    units="m"
)

plot.setXRange(
    0,
    MAX_FORWARD_DISTANCE
)

plot.setYRange(
    -2,
    2
)

plot.showGrid(
    x=True,
    y=True
)

# One line object.
# We update this instead of rebuilding the graph.
road_line = plot.plot(
    [],
    [],
    symbol="o"
)

window.show()


# ============================================================
# RADAR READER FUNCTION
# ============================================================

def read_radar():

    global radar_buffer
    global latest_y
    global latest_z
    global latest_frame
    global latest_objects

    waiting = radar.in_waiting

    if waiting <= 0:
        return

    radar_buffer += radar.read(waiting)

    # --------------------------------------------------------
    # Process as many complete frames as currently available
    # --------------------------------------------------------

    while True:

        magic_index = radar_buffer.find(
            MAGIC_WORD
        )

        if magic_index == -1:

            # Prevent unlimited buffer growth
            if len(radar_buffer) > 20000:
                radar_buffer = radar_buffer[-8:]

            return

        radar_buffer = radar_buffer[
            magic_index:
        ]

        # Need complete header
        if len(radar_buffer) < 40:
            return

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

        # Basic corruption protection
        if packet_length <= 40:
            radar_buffer = radar_buffer[8:]
            continue

        if packet_length > 65536:
            radar_buffer = radar_buffer[8:]
            continue

        # Wait for entire frame
        if len(radar_buffer) < packet_length:
            return

        frame = radar_buffer[
            :packet_length
        ]

        radar_buffer = radar_buffer[
            packet_length:
        ]

        # ====================================================
        # PARSE TLVs
        # ====================================================

        y_points = []
        z_points = []

        offset = 40

        for tlv_number in range(num_tlvs):

            if offset + 8 > len(frame):
                break

            tlv_type, tlv_length = struct.unpack(
                "<II",
                frame[offset:offset + 8]
            )

            offset += 8

            # -----------------------------------------------
            # TLV TYPE 1 = DETECTED POINTS
            # -----------------------------------------------

            if tlv_type == 1:

                for i in range(num_objects):

                    point_start = (
                        offset +
                        (i * 16)
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

                    # Ignore detections almost touching radar
                    if distance < 0.15:
                        continue

                    # Only forward points
                    if y < 0:
                        continue

                    if y > MAX_FORWARD_DISTANCE:
                        continue

                    y_points.append(y)
                    z_points.append(z)

            # Move to next TLV
            offset += tlv_length - 8

        # Sort by forward distance
        if len(y_points) > 0:

            points = sorted(
                zip(
                    y_points,
                    z_points
                ),
                key=lambda p: p[0]
            )

            latest_y = [
                p[0]
                for p in points
            ]

            latest_z = [
                p[1]
                for p in points
            ]

        else:

            latest_y = []
            latest_z = []

        latest_frame = frame_number
        latest_objects = len(latest_y)


# ============================================================
# GRAPH UPDATE FUNCTION
# ============================================================

def update_graph():

    read_radar()

    road_line.setData(
        latest_y,
        latest_z
    )

    plot.setTitle(
        f"TI AWR6843 — Live Road Profile  |  "
        f"Frame {latest_frame}  |  "
        f"Points {latest_objects}"
    )


# ============================================================
# TIMER
# ============================================================

timer = QTimer()

timer.timeout.connect(
    update_graph
)

timer.start(
    GRAPH_UPDATE_MS
)


# ============================================================
# START
# ============================================================

try:

    sys.exit(
        app.exec()
    )

finally:

    radar.close()

    print("COM3 closed.")