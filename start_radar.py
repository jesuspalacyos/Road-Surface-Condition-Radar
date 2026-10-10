import serial
import radar_ports
import time
import sys
import os


# ============================================================
# SETTINGS
# ============================================================

CLI_PORT = radar_ports.CLI_PORT
CLI_BAUD = 115200

DATA_PORT = radar_ports.DATA_PORT
DATA_BAUD = 921600

# Look for the cfg next to this script, not in the current working folder
CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.cfg")

# Optional: pass a different cfg on the command line
#   python start_radar.py ..\oob_6843_isk_test.cfg
if len(sys.argv) > 1:
    CFG_FILE = os.path.abspath(sys.argv[1])


# ============================================================
# CHECK CONFIG FILE
# ============================================================

if not os.path.exists(CFG_FILE):

    print()
    print("ERROR:")
    print(f"Cannot find configuration file: {CFG_FILE}")
    print()
    print("Put the .cfg file in the same folder as this script.")
    print()

    sys.exit(1)


# ============================================================
# OPEN DATA PORT FIRST
# ============================================================

print("=" * 65)
print("TI AWR6843 RADAR STARTUP")
print("=" * 65)

print()
print(f"Opening DATA port {DATA_PORT} at {DATA_BAUD}...")

try:

    data = serial.Serial(
        DATA_PORT,
        DATA_BAUD,
        timeout=0
    )

except serial.SerialException as e:

    print("Could not open DATA port.")
    print(e)

    sys.exit(1)


print("DATA port opened successfully.")


# Clear any old bytes
data.reset_input_buffer()


# ============================================================
# OPEN CLI PORT
# ============================================================

print()
print(f"Opening CLI port {CLI_PORT} at {CLI_BAUD}...")

try:

    cli = serial.Serial(
        CLI_PORT,
        CLI_BAUD,
        timeout=0.1
    )

except serial.SerialException as e:

    print("Could not open CLI port.")
    print(e)

    data.close()

    sys.exit(1)


print("CLI port opened successfully.")

time.sleep(1)

cli.reset_input_buffer()


# ============================================================
# READ CLI RESPONSE
# ============================================================

def read_response(timeout=2.0):

    response = b""

    start = time.time()

    while time.time() - start < timeout:

        waiting = cli.in_waiting

        if waiting > 0:

            response += cli.read(waiting)

            # Radar prompt means command is finished
            if b"mmwDemo:/>" in response:

                break

        time.sleep(0.01)

    return response.decode(
        errors="ignore"
    )


# ============================================================
# SEND CLI COMMAND
# ============================================================

def send_command(command):

    command = command.strip()

    if not command:
        return True


    print(f">>> {command}")


    cli.write(
        (command + "\n").encode()
    )


    response = read_response()


    if response:

        print(response.strip())


    # --------------------------------------------------------
    # DETECT ERRORS
    # --------------------------------------------------------

    lower_response = response.lower()

    if (
        "error" in lower_response
        or "failed" in lower_response
    ):

        print()
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("CONFIGURATION ERROR")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

        return False


    print("-" * 65)

    return True


# ============================================================
# CHECK CURRENT RADAR STATUS
# ============================================================

print()
print("Checking radar status...")
print()

send_command(
    "queryDemoStatus"
)


# ============================================================
# LOAD CONFIGURATION FILE
# ============================================================

print()
print("=" * 65)
print(f"LOADING CONFIGURATION: {CFG_FILE}")
print("=" * 65)
print()


sensor_start_found = False


with open(
    CFG_FILE,
    "r",
    encoding="utf-8",
    errors="ignore"
) as config:

    for line_number, line in enumerate(
        config,
        start=1
    ):

        command = line.strip()


        # ----------------------------------------------------
        # IGNORE EMPTY LINES
        # ----------------------------------------------------

        if not command:
            continue


        # ----------------------------------------------------
        # IGNORE COMMENTS
        # ----------------------------------------------------

        if command.startswith("%"):
            continue

        if command.startswith("#"):
            continue


        # ----------------------------------------------------
        # REMEMBER IF CFG ALREADY CONTAINS SENSORSTART
        # ----------------------------------------------------

        if command.lower().startswith(
            "sensorstart"
        ):

            sensor_start_found = True


        # ----------------------------------------------------
        # SEND COMMAND
        # ----------------------------------------------------

        success = send_command(
            command
        )


        if not success:

            print()
            print(
                f"Configuration failed at "
                f"line {line_number}:"
            )

            print(command)

            print()
            print(
                "Stopping so we do not continue "
                "with a bad radar configuration."
            )

            cli.close()
            data.close()

            sys.exit(1)


        # Small delay between commands
        time.sleep(0.03)


# ============================================================
# START SENSOR IF CFG DID NOT DO IT
# ============================================================

if not sensor_start_found:

    print()
    print("Configuration loaded.")
    print("Sending sensorStart...")
    print()

    success = send_command(
        "sensorStart"
    )


    if not success:

        print()
        print("Radar could not start.")

        cli.close()
        data.close()

        sys.exit(1)


# ============================================================
# WAIT FOR RADAR
# ============================================================

print()
print("=" * 65)
print("RADAR CONFIGURATION COMPLETE")
print("=" * 65)

print()
print(f"Waiting for {DATA_PORT} radar data...")
print()


time.sleep(1)


# ============================================================
# CHECK DATA PORT (watch for 10 s to confirm the stream keeps going)
# ============================================================

total_received = 0

for second in range(1, 11):

    # Poll every 10 ms. Linux keeps only ~4 KB in the serial buffer,
    # so reading once per second would drop data and cap the count.
    got = 0
    end = time.time() + 1.0
    while time.time() < end:
        waiting = data.in_waiting
        if waiting > 0:
            got += len(data.read(waiting))
        time.sleep(0.01)

    total_received += got

    print(f"Second {second:2d}: {got:6d} bytes   (total {total_received})")

print()

if total_received == 0:
    print(f"WARNING: no binary data was detected on {DATA_PORT}.")
else:
    print(f"Received {total_received} bytes in 10 s from the AWR6843.")


# --- check the sensor is still running ---
print()
send_command("queryDemoStatus")


# ============================================================
# CLOSE PORTS
# ============================================================

cli.close()
data.close()

print()
print("Ports closed.")
print()

# Non-zero exit code so launchers can tell the stream never started
if total_received == 0:
    sys.exit(2)
