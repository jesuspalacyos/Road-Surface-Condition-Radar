import sys
import serial
import struct
import math
import time

from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import QTimer
import pyqtgraph as pg


# ============================================================
# SETTINGS
# ============================================================

MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'

# IMPORTANT:
# This MUST be the radar DATA port, NOT the CLI/configuration port.
DATA_PORT = "COM3"

DATA_BAUD = 921600

MAX_FORWARD = 10.0
MAX_SIDE = 5.0

# Graph update rate
UPDATE_MS = 50


# ============================================================
# OPEN RADAR
# ============================================================

print("=" * 60)
print("TI AWR6843 LIVE RADAR")
print("=" * 60)

print(f"\nOpening DATA port {DATA_PORT} at {DATA_BAUD} baud...")

try:
    radar = serial.Serial(
        DATA_PORT,
        DATA_BAUD,
        timeout=0
    )

except serial.SerialException as e:
    print("\nERROR OPENING RADAR:")
    print(e)
    sys.exit(1)


print(f"{DATA_PORT} opened successfully.")
print()
print("Waiting for radar binary packets...")
print()


# ============================================================
# VARIABLES
# ============================================================

radar_buffer = bytearray()

latest_x = []
latest_y = []
latest_velocity = []

latest_frame = 0

total_bytes = 0
packet_count = 0
magic_count = 0
bad_packets = 0

last_debug_time = time.time()
last_byte_count = 0


# ============================================================
# WINDOW
# ============================================================

app = QApplication(sys.argv)

window = QMainWindow()

window.setWindowTitle(
    "TI AWR6843 Live Radar"
)

window.resize(
    1100,
    850
)


plot = pg.PlotWidget()

window.setCentralWidget(
    plot
)


plot.setBackground("k")


plot.setTitle(
    "TI AWR6843 — Waiting for Radar Data..."
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
    MAX_SIDE,
    padding=0
)


plot.setYRange(
    0,
    MAX_FORWARD,
    padding=0
)


plot.showGrid(
    x=True,
    y=True,
    alpha=0.3
)


# ============================================================
# RADAR POINTS
# ============================================================

points = pg.ScatterPlotItem(
    size=14,
    symbol="o"
)

plot.addItem(
    points
)


# ============================================================
# RADAR CENTER LINE
# ============================================================

center_line = pg.InfiniteLine(
    pos=0,
    angle=90
)

plot.addItem(
    center_line
)


# ============================================================
# RADAR LOCATION
# ============================================================

radar_marker = pg.ScatterPlotItem(
    [0],
    [0],
    size=20,
    symbol="t"
)

plot.addItem(
    radar_marker
)


window.show()


# ============================================================
# PARSE ONE COMPLETE FRAME
# ============================================================

def parse_frame(frame):

    global latest_x
    global latest_y
    global latest_velocity

    global latest_frame
    global packet_count
    global bad_packets

    # --------------------------------------------------------
    # FRAME MUST CONTAIN HEADER
    # --------------------------------------------------------

    if len(frame) < 40:
        return


    # --------------------------------------------------------
    # PARSE HEADER
    # --------------------------------------------------------

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

        ) = struct.unpack_from(
            "<8I",
            frame,
            8
        )

    except struct.error:

        bad_packets += 1
        return


    # --------------------------------------------------------
    # SANITY CHECK
    # --------------------------------------------------------

    if packet_length != len(frame):

        bad_packets += 1
        return


    # --------------------------------------------------------
    # TEMPORARY POINT ARRAYS
    # --------------------------------------------------------

    x_values = []
    y_values = []
    velocity_values = []


    offset = 40


    # ========================================================
    # PARSE TLVs
    # ========================================================

    for tlv_index in range(num_tlvs):

        # Need at least 8 bytes for TLV header
        if offset + 8 > len(frame):
            break


        try:

            tlv_type, tlv_length = struct.unpack_from(
                "<II",
                frame,
                offset
            )

        except struct.error:
            break


        # ----------------------------------------------------
        # IMPORTANT
        #
        # TLV LENGTH IS PAYLOAD LENGTH.
        #
        # TLV format:
        #
        # 4 bytes type
        # 4 bytes length
        # N bytes payload
        #
        # ----------------------------------------------------

        payload_start = offset + 8

        payload_end = (
            payload_start +
            tlv_length
        )


        if payload_end > len(frame):

            print(
                f"\nWARNING: Bad TLV length "
                f"type={tlv_type}, "
                f"length={tlv_length}"
            )

            break


        # ====================================================
        # TLV TYPE 1
        # DETECTED POINT CLOUD
        # ====================================================

        if tlv_type == 1:

            # Each point:
            #
            # X        float32
            # Y        float32
            # Z        float32
            # velocity float32
            #
            # Total = 16 bytes

            available_points = (
                tlv_length // 16
            )


            # Don't blindly trust num_objects
            points_to_read = min(
                num_objects,
                available_points
            )


            for i in range(points_to_read):

                point_offset = (
                    payload_start +
                    i * 16
                )


                try:

                    x, y, z, velocity = struct.unpack_from(
                        "<ffff",
                        frame,
                        point_offset
                    )

                except struct.error:
                    break


                # --------------------------------------------
                # CHECK FOR INVALID FLOAT VALUES
                # --------------------------------------------

                if not all(
                    math.isfinite(value)
                    for value in (
                        x,
                        y,
                        z,
                        velocity
                    )
                ):
                    continue


                distance = math.sqrt(
                    x * x +
                    y * y +
                    z * z
                )


                # --------------------------------------------
                # REMOVE VERY CLOSE RADAR CLUTTER
                # --------------------------------------------

                if distance < 0.10:
                    continue


                # --------------------------------------------
                # ONLY OBJECTS IN FRONT
                # --------------------------------------------

                if y < 0:
                    continue


                # --------------------------------------------
                # DISPLAY AREA
                # --------------------------------------------

                if y > MAX_FORWARD:
                    continue


                if abs(x) > MAX_SIDE:
                    continue


                x_values.append(
                    x
                )


                y_values.append(
                    y
                )


                velocity_values.append(
                    velocity
                )


        # ====================================================
        # MOVE TO NEXT TLV
        # ====================================================

        offset = payload_end


    # ========================================================
    # SAVE LATEST FRAME
    # ========================================================

    latest_x = x_values
    latest_y = y_values
    latest_velocity = velocity_values

    latest_frame = frame_number

    packet_count += 1


# ============================================================
# READ SERIAL DATA
# ============================================================

def read_radar():

    global radar_buffer

    global total_bytes
    global magic_count
    global bad_packets


    # --------------------------------------------------------
    # SEE HOW MANY BYTES ARE WAITING
    # --------------------------------------------------------

    waiting = radar.in_waiting


    if waiting > 0:

        new_data = radar.read(
            waiting
        )

        total_bytes += len(
            new_data
        )

        radar_buffer.extend(
            new_data
        )


    # ========================================================
    # SEARCH BUFFER FOR COMPLETE FRAMES
    # ========================================================

    while True:

        # ----------------------------------------------------
        # FIND TI MAGIC WORD
        # ----------------------------------------------------

        magic_index = radar_buffer.find(
            MAGIC_WORD
        )


        # No packet beginning found
        if magic_index == -1:

            # Keep last 7 bytes because part of the
            # magic word might be split between reads.
            if len(radar_buffer) > 7:

                radar_buffer = radar_buffer[-7:]

            return


        magic_count += 1


        # Remove garbage before packet
        if magic_index > 0:

            del radar_buffer[
                :magic_index
            ]


        # ----------------------------------------------------
        # NEED COMPLETE 40-BYTE HEADER
        # ----------------------------------------------------

        if len(radar_buffer) < 40:
            return


        # ----------------------------------------------------
        # READ PACKET LENGTH
        # ----------------------------------------------------

        try:

            packet_length = struct.unpack_from(
                "<I",
                radar_buffer,
                12
            )[0]

        except struct.error:
            return


        # ----------------------------------------------------
        # SANITY CHECK PACKET LENGTH
        # ----------------------------------------------------

        if packet_length < 40:

            print(
                "\nBad packet length:",
                packet_length
            )

            bad_packets += 1

            del radar_buffer[0]

            continue


        if packet_length > 65536:

            print(
                "\nImpossible packet length:",
                packet_length
            )

            bad_packets += 1

            del radar_buffer[0]

            continue


        # ----------------------------------------------------
        # WAIT FOR ENTIRE PACKET
        # ----------------------------------------------------

        if len(radar_buffer) < packet_length:
            return


        # ----------------------------------------------------
        # EXTRACT FRAME
        # ----------------------------------------------------

        frame = bytes(
            radar_buffer[
                :packet_length
            ]
        )


        del radar_buffer[
            :packet_length
        ]


        # ----------------------------------------------------
        # PARSE FRAME
        # ----------------------------------------------------

        parse_frame(
            frame
        )


# ============================================================
# DEBUG INFORMATION
# ============================================================

def print_debug():

    global last_debug_time
    global last_byte_count


    now = time.time()


    if now - last_debug_time < 1.0:
        return


    bytes_this_second = (
        total_bytes -
        last_byte_count
    )


    print(
        f"\r"
        f"Bytes/s: {bytes_this_second:<7} | "
        f"Packets: {packet_count:<7} | "
        f"Frame: {latest_frame:<7} | "
        f"Objects: {len(latest_x):<3} | "
        f"Buffer: {len(radar_buffer):<6} | "
        f"Bad: {bad_packets:<5}",
        end=""
    )


    last_byte_count = total_bytes

    last_debug_time = now


# ============================================================
# UPDATE DISPLAY
# ============================================================

def update_display():

    # --------------------------------------------------------
    # READ RADAR FIRST
    # --------------------------------------------------------

    read_radar()


    # --------------------------------------------------------
    # UPDATE POINTS
    # --------------------------------------------------------

    points.setData(
        x=latest_x,
        y=latest_y
    )


    # --------------------------------------------------------
    # UPDATE TITLE
    # --------------------------------------------------------

    plot.setTitle(

        f"TI AWR6843 — Live Top View"
        f" | Frame {latest_frame}"
        f" | Objects {len(latest_x)}"
        f" | Packets {packet_count}"

    )


    # --------------------------------------------------------
    # DEBUG CONSOLE
    # --------------------------------------------------------

    print_debug()


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

    if radar.is_open:

        radar.close()


    print(
        f"\n\n{DATA_PORT} closed."
    )