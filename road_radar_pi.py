#!/usr/bin/env python3

import argparse
import csv
import math
import statistics
import struct
import time
from datetime import datetime

import serial


# ============================================================
# TI mmWave UART definitions
# ============================================================

MAGIC_WORD = b"\x02\x01\x04\x03\x06\x05\x08\x07"

# TI SDK OOB header:
# magicWord
# version
# totalPacketLen
# platform
# frameNumber
# timeCpuCycles
# numDetectedObj
# numTLVs
# subFrameNumber

HEADER_FORMAT = "<8s8I"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Common TI SDK TLVs
TLV_DETECTED_POINTS = 1
TLV_SIDE_INFO = 7


# ============================================================
# Send profile.cfg to radar
# ============================================================

def send_config(cli_port, config_file):

    print(f"\nOpening CLI port {cli_port} @ 115200...")

    cli = serial.Serial(
        cli_port,
        115200,
        timeout=0.2
    )

    time.sleep(0.5)
    cli.reset_input_buffer()

    with open(config_file, "r") as file:

        for line in file:

            # Remove TI % comments
            line = line.split("%")[0].strip()

            if not line:
                continue

            print("Sending:", line)

            cli.write((line + "\n").encode())
            cli.flush()

            time.sleep(0.05)

    cli.close()

    print("\nRadar configuration sent.")
    print("Radar should now be running.\n")


# ============================================================
# Read packets from DATA UART
# ============================================================

class RadarReader:

    def __init__(self, port):

        print(f"Opening radar DATA port {port} @ 921600...")

        self.serial = serial.Serial(
            port,
            921600,
            timeout=0.05
        )

        self.buffer = bytearray()

    def close(self):
        self.serial.close()

    def get_packet(self):

        while True:

            waiting = self.serial.in_waiting

            if waiting:
                data = self.serial.read(waiting)
            else:
                data = self.serial.read(1)

            if data:
                self.buffer.extend(data)

            # Search for TI magic word
            start = self.buffer.find(MAGIC_WORD)

            if start == -1:

                # Keep only enough bytes to still find a partial magic word
                if len(self.buffer) > 8:
                    self.buffer = self.buffer[-7:]

                continue

            # Remove junk before packet
            if start > 0:
                del self.buffer[:start]

            # Wait until full header exists
            if len(self.buffer) < HEADER_SIZE:
                continue

            header = struct.unpack_from(
                HEADER_FORMAT,
                self.buffer,
                0
            )

            total_packet_length = header[2]

            # Protect against corrupted packets
            if total_packet_length < HEADER_SIZE:
                del self.buffer[0]
                continue

            if total_packet_length > 1000000:
                del self.buffer[0]
                continue

            # Wait for complete packet
            if len(self.buffer) < total_packet_length:
                continue

            packet = bytes(
                self.buffer[:total_packet_length]
            )

            del self.buffer[:total_packet_length]

            return packet


# ============================================================
# Parse TI packet
# ============================================================

def parse_packet(packet):

    (
        magic,
        version,
        total_length,
        platform,
        frame_number,
        cpu_cycles,
        number_objects,
        number_tlvs,
        subframe
    ) = struct.unpack_from(
        HEADER_FORMAT,
        packet,
        0
    )

    if magic != MAGIC_WORD:
        return None

    offset = HEADER_SIZE

    points = []
    side_info = []

    for _ in range(number_tlvs):

        if offset + 8 > len(packet):
            break

        tlv_type, tlv_length = struct.unpack_from(
            "<II",
            packet,
            offset
        )

        offset += 8

        payload_start = offset
        payload_end = offset + tlv_length

        if payload_end > len(packet):
            break

        # ----------------------------------------------------
        # TLV 1
        # x, y, z, radial velocity
        # ----------------------------------------------------

        if tlv_type == TLV_DETECTED_POINTS:

            number_points = min(
                number_objects,
                tlv_length // 16
            )

            for i in range(number_points):

                position = payload_start + (i * 16)

                x, y, z, velocity = struct.unpack_from(
                    "<ffff",
                    packet,
                    position
                )

                points.append({
                    "x": x,
                    "y": y,
                    "z": z,
                    "velocity": velocity,
                    "snr": None,
                    "noise": None
                })

        # ----------------------------------------------------
        # TLV 7
        # SNR and noise
        # ----------------------------------------------------

        elif tlv_type == TLV_SIDE_INFO:

            number_points = min(
                number_objects,
                tlv_length // 4
            )

            for i in range(number_points):

                position = payload_start + (i * 4)

                snr_raw, noise_raw = struct.unpack_from(
                    "<hh",
                    packet,
                    position
                )

                side_info.append({
                    "snr": snr_raw * 0.1,
                    "noise": noise_raw * 0.1
                })

        offset = payload_end

    # Add SNR information to each radar point
    for i in range(min(len(points), len(side_info))):

        points[i]["snr"] = side_info[i]["snr"]
        points[i]["noise"] = side_info[i]["noise"]

    return {
        "frame": frame_number,
        "points": points
    }


# ============================================================
# Convert sensor coordinates to vehicle/road coordinates
# ============================================================

def convert_coordinates(point, pitch_deg, radar_height):

    x = point["x"]
    y = point["y"]
    z = point["z"]

    # Positive pitch means radar is tilted DOWN
    pitch = math.radians(pitch_deg)

    # Rotate around X-axis
    forward = (
        y * math.cos(pitch)
        + z * math.sin(pitch)
    )

    vertical = (
        -y * math.sin(pitch)
        + z * math.cos(pitch)
    )

    lateral = x

    # Radar is radar_height above the road
    height_above_road = vertical + radar_height

    distance = math.sqrt(
        lateral ** 2
        + forward ** 2
        + vertical ** 2
    )

    return {
        **point,

        "lateral": lateral,
        "forward": forward,

        "height": height_above_road,

        "distance": distance
    }


# ============================================================
# Road analysis
# ============================================================

def analyze_road(
        radar_points,
        radar_height,
        pitch_deg
):

    processed = []

    for point in radar_points:

        p = convert_coordinates(
            point,
            pitch_deg,
            radar_height
        )

        processed.append(p)

    # --------------------------------------------------------
    # Only analyze points roughly in our lane
    #
    # +/- 1.5 m
    # 0.3 - 8 m ahead
    # --------------------------------------------------------

    road_points = []

    for p in processed:

        good_snr = (
            p["snr"] is None
            or p["snr"] >= 8
        )

        if (
            abs(p["lateral"]) <= 1.5
            and 0.30 <= p["forward"] <= 8.0
            and good_snr
        ):
            road_points.append(p)

    # --------------------------------------------------------
    # Raised object / debris
    #
    # About 8 cm - 80 cm above expected road surface
    # --------------------------------------------------------

    debris = []

    for p in road_points:

        if 0.08 <= p["height"] <= 0.80:
            debris.append(p)

    # --------------------------------------------------------
    # Depression / pothole candidate
    #
    # Return appears >7 cm below expected road surface
    # --------------------------------------------------------

    depressions = []

    for p in road_points:

        if p["height"] <= -0.07:
            depressions.append(p)

    # --------------------------------------------------------
    # Road surface returns
    # --------------------------------------------------------

    surface_points = []

    for p in road_points:

        if -0.25 <= p["height"] <= 0.25:
            surface_points.append(p)

    # --------------------------------------------------------
    # Surface roughness
    # --------------------------------------------------------

    roughness = 0

    if len(surface_points) >= 4:

        heights = []

        for p in surface_points:
            heights.append(p["height"])

        roughness = statistics.pstdev(heights)

    # --------------------------------------------------------
    # Nearest detection
    # --------------------------------------------------------

    nearest = None

    if road_points:

        nearest = min(
            road_points,
            key=lambda p: p["distance"]
        )

    # --------------------------------------------------------
    # Road condition assessment
    # --------------------------------------------------------

    warnings = []

    if len(debris) >= 3:

        warnings.append(
            "POSSIBLE DEBRIS / RAISED OBJECT"
        )

    if len(depressions) >= 3:

        warnings.append(
            "POSSIBLE POTHOLE / DEPRESSION"
        )

    if roughness >= 0.08:

        warnings.append(
            "UNEVEN ROAD SURFACE"
        )

    if not road_points:

        warnings.append(
            "NO STRONG ROAD RETURNS"
        )

    elif not warnings:

        warnings.append(
            "NO STRONG ANOMALY"
        )

    return {

        "road_points": road_points,

        "debris": debris,

        "depressions": depressions,

        "roughness": roughness,

        "nearest": nearest,

        "status": " | ".join(warnings)
    }


# ============================================================
# Human-readable position
# ============================================================

def lateral_text(x):

    if abs(x) < 0.10:
        return "center"

    if x > 0:
        return f"{x:.2f} m right"

    return f"{abs(x):.2f} m left"


# ============================================================
# Display radar information
# ============================================================

def display(frame, result):

    print("\n" + "=" * 70)

    print(
        f"FRAME: {frame['frame']}"
    )

    print(
        f"Radar detections: {len(frame['points'])}"
    )

    print(
        f"Useful road detections: "
        f"{len(result['road_points'])}"
    )

    print()
    print(
        "ROAD CONDITION:",
        result["status"]
    )

    print(
        "Surface roughness:",
        f"{result['roughness']:.3f} m"
    )

    print(
        "Debris candidate points:",
        len(result["debris"])
    )

    print(
        "Depression candidate points:",
        len(result["depressions"])
    )

    # --------------------------------------------------------
    # Nearest object
    # --------------------------------------------------------

    if result["nearest"]:

        p = result["nearest"]

        print()
        print("NEAREST RETURN")

        print(
            f"  Distance ahead : "
            f"{p['forward']:.2f} m"
        )

        print(
            f"  Position       : "
            f"{lateral_text(p['lateral'])}"
        )

        print(
            f"  Road height    : "
            f"{p['height']:+.2f} m"
        )

        print(
            f"  Radial speed   : "
            f"{p['velocity']:+.2f} m/s"
        )

        if p["snr"] is not None:

            print(
                f"  SNR            : "
                f"{p['snr']:.1f} dB"
            )

    # --------------------------------------------------------
    # Closest 5 radar points
    # --------------------------------------------------------

    points = sorted(
        result["road_points"],
        key=lambda p: p["distance"]
    )

    points = points[:5]

    if points:

        print()
        print("CLOSEST ROAD POINTS")
        print(
            "Ahead(m) | Left/Right      | Height(m) | Speed(m/s) | SNR"
        )

        for p in points:

            if p["snr"] is None:
                snr = "N/A"
            else:
                snr = f"{p['snr']:.1f}"

            print(
                f"{p['forward']:8.2f} | "
                f"{lateral_text(p['lateral']):15} | "
                f"{p['height']:+9.2f} | "
                f"{p['velocity']:+10.2f} | "
                f"{snr}"
            )


# ============================================================
# Main program
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--cli-port",
        default="/dev/ttyUSB0"
    )

    parser.add_argument(
        "--data-port",
        default="/dev/ttyUSB1"
    )

    parser.add_argument(
        "--config",
        default=None
    )

    parser.add_argument(
        "--radar-height",
        type=float,
        default=0.60,
        help="Radar height above road in meters"
    )

    parser.add_argument(
        "--pitch",
        type=float,
        default=0,
        help="Radar downward angle in degrees"
    )

    parser.add_argument(
        "--print-every",
        type=int,
        default=5
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Configure radar if profile.cfg supplied
    # --------------------------------------------------------

    if args.config:

        send_config(
            args.cli_port,
            args.config
        )

    # --------------------------------------------------------
    # Start data reader
    # --------------------------------------------------------

    radar = RadarReader(
        args.data_port
    )

    # --------------------------------------------------------
    # CSV file
    # --------------------------------------------------------

    csv_file = open(
        "road_radar_log.csv",
        "a",
        newline=""
    )

    writer = csv.writer(csv_file)

    writer.writerow([
        "time",
        "frame",
        "radar_points",
        "road_points",
        "debris_points",
        "depression_points",
        "roughness",
        "road_status"
    ])

    frame_counter = 0

    print()
    print("========================================")
    print(" ROAD CONDITION RADAR STARTED")
    print("========================================")
    print()

    try:

        while True:

            packet = radar.get_packet()

            frame = parse_packet(packet)

            if frame is None:
                continue

            analysis = analyze_road(
                frame["points"],
                args.radar_height,
                args.pitch
            )

            frame_counter += 1

            # Don't flood terminal
            if frame_counter % args.print_every == 0:

                display(
                    frame,
                    analysis
                )

            writer.writerow([

                datetime.now().isoformat(
                    timespec="milliseconds"
                ),

                frame["frame"],

                len(frame["points"]),

                len(analysis["road_points"]),

                len(analysis["debris"]),

                len(analysis["depressions"]),

                analysis["roughness"],

                analysis["status"]
            ])

            csv_file.flush()

    except KeyboardInterrupt:

        print("\nRadar stopped.")

    finally:

        radar.close()

        csv_file.close()


if __name__ == "__main__":
    main()
