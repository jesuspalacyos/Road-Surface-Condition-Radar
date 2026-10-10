import serial
import radar_ports
import time

CLI_PORT = radar_ports.CLI_PORT
CLI_BAUD = 115200

print(f"Opening radar CLI on {CLI_PORT}...")

cli = serial.Serial(
    CLI_PORT,
    CLI_BAUD,
    timeout=0.5
)

time.sleep(1)

cli.reset_input_buffer()

print(f"{CLI_PORT} opened.\n")


def send_command(command):

    print(f">>> {command}")

    cli.write(
        (command + "\n").encode()
    )

    time.sleep(1)

    response = cli.read(
        cli.in_waiting
    )

    print(
        response.decode(
            errors="ignore"
        )
    )

    print("-" * 60)


# ============================================================
# CHECK STATUS
# ============================================================

send_command(
    "queryDemoStatus"
)


# ============================================================
# TRY STARTING SENSOR
# ============================================================

send_command(
    "sensorStart"
)


cli.close()

print(f"{CLI_PORT} closed.")