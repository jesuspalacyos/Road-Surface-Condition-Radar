import serial
import time

CLI_PORT = "COM4"
CLI_BAUD = 115200

print("Opening radar CLI on COM4...")

cli = serial.Serial(
    CLI_PORT,
    CLI_BAUD,
    timeout=0.5
)

time.sleep(1)

cli.reset_input_buffer()

print("COM4 opened.\n")


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

print("COM4 closed.")