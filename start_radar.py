import serial
import time
import sys
import os


# ============================================================
# SETTINGS
# ============================================================

CLI_PORT = "COM4"
CLI_BAUD = 115200

DATA_PORT = "COM3"
DATA_BAUD = 921600

CFG_FILE = "profile.cfg"


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
print("Waiting for COM3 radar data...")
print()


time.sleep(1)


# ============================================================
# CHECK DATA PORT
# ============================================================

for test_number in range(10):

    waiting = data.in_waiting

    print(
        f"Check {test_number + 1}: "
        f"{waiting} bytes waiting"
    )


    if waiting > 0:

        incoming = data.read(
            waiting
        )

        print()
        print("======================================")
        print("SUCCESS!")
        print("======================================")
        print()
        print(
            f"Received {len(incoming)} bytes "
            f"from the AWR6843."
        )

        print()
        print(
            "The radar is now streaming."
        )

        print(
            "You can now run the live graph."
        )

        break


    time.sleep(0.5)


else:

    print()
    print("======================================")
    print("WARNING")
    print("======================================")
    print()

    print(
        "Configuration completed, but no "
        "binary data was detected on COM3."
    )


# ============================================================
# CLOSE PORTS
# ============================================================

cli.close()
data.close()

print()
print("Ports closed.")
print()