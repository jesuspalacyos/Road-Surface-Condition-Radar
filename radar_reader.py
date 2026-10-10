import serial
import radar_ports
import time
import os

CLI_PORT = radar_ports.CLI_PORT
DATA_PORT = radar_ports.DATA_PORT
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.cfg")

print(f"Opening {CLI_PORT}...")
cli = serial.Serial(
    port=CLI_PORT,
    baudrate=115200,
    timeout=1
)

print(f"Opening {DATA_PORT}...")
data = serial.Serial(
    port=DATA_PORT,
    baudrate=921600,
    timeout=1
)

print("Ports opened successfully.")

time.sleep(1)

# Clear old data
cli.reset_input_buffer()
data.reset_input_buffer()

print("\nSending radar configuration...\n")

with open(CONFIG_FILE, "r") as cfg:

    for line in cfg:

        command = line.strip()

        # Skip blank lines and comments
        if not command or command.startswith("%"):
            continue

        print("------------------------------------------------")
        print("SEND:", command)

        cli.write((command + "\n").encode())
        cli.flush()

        # Give the radar time to process the command
        time.sleep(0.3)

        response = cli.read_all().decode(
            errors="ignore"
        )

        if response:
            print("RADAR RESPONSE:")
            print(response)
        else:
            print("NO RESPONSE FROM CLI")

print("\n================================================")
print("Configuration finished.")
print(f"Checking {DATA_PORT} for radar data...")
print("================================================\n")

while True:

    waiting = data.in_waiting

    if waiting > 0:

        radar_data = data.read(waiting)

        print(
            "RECEIVED:",
            len(radar_data),
            "bytes"
        )

    else:
        print("Waiting for radar data...")

    time.sleep(1)