WINDOWS THREE-SENSOR READER
Assumes Seeed Studio XIAO ESP32-S3 + VL53L0X breakout + ADXL335 breakout + NEO-6M GPS breakout.
If your board or sensors differ, do not use this pin table without adapting it.
Python runs on Windows. Arduino firmware runs on the ESP32, which connects to Windows over USB.
Uploading this sketch replaces the existing ESP32 application (including any BLE firmware); save your old sketch first.

1. WIRING (disconnect USB power while wiring)
VL53L0X SDA -> XIAO D4 / GPIO5
VL53L0X SCL -> XIAO D5 / GPIO6
ADXL335 X OUT -> XIAO D0 / GPIO1
ADXL335 Y OUT -> XIAO D1 / GPIO2
ADXL335 Z OUT -> XIAO D2 / GPIO3
NEO-6M TX -> XIAO D7 / GPIO44 (RX)
NEO-6M RX -> leave disconnected; no commands are sent to GPS
All sensor GND -> XIAO GND
Power the ADXL335 and VL53L0X breakouts at 3.3 V only if their specific breakout supports that input.
Power the GPS breakout at its documented input voltage. Some boards have a regulator and need a different VIN than the bare module.
All signals entering XIAO must be 3.3 V compatible; never connect 5 V signals to GPIO.
The ADXL335 bare chip is rated 1.8-3.6 V. Breakout regulator requirements may differ.

2. UPLOAD FIRMWARE ONCE
Install Arduino IDE from https://www.arduino.cc/en/software
In Boards Manager install 'esp32' by Espressif Systems.
Select board 'XIAO_ESP32S3'. Enable Tools > USB CDC On Boot > Enabled if present.
In Library Manager install:
  Adafruit VL53L0X (accept its dependencies)
  TinyGPSPlus by Mikal Hart
Open esp32_sensors/esp32_sensors.ino from the extracted folder.
Connect XIAO using a USB DATA cable. Select its COM port and Upload.
If upload fails, hold BOOT while connecting USB, release BOOT, select the new port and retry.
After upload press RESET if needed. The normal COM port may differ from the upload port.
Close Arduino Serial Monitor before running Python.
Firmware assumes GPS UART is 9600 baud; change it if previously reconfigured.

3. RUN ON WINDOWS
Extract the ZIP first; do not run inside the compressed folder.
Double-click START_WINDOWS.bat. Enter the ESP32 COM port when prompted.
It installs pyserial using your existing Python launcher, displays live readings,
and writes timestamped CSV files beside read_sensors.py. Internet is needed for the initial install.
Alternatively, open the extracted ThreeSensors folder in File Explorer,
click the address bar, type powershell and press Enter. Then run:
  py -m pip install -r requirements.txt
  py read_sensors.py --list-ports
  py read_sensors.py --port COM5
Replace COM5 with your ESP32 port. Stop with Ctrl+C.
Optional new CSV path:
  py read_sensors.py --port COM5 --csv my_readings.csv
Existing files are protected from overwrite.

4. WHAT YOU SEE
ToF distance is in millimeters. Invalid measurements are empty in CSV, not zero.
Range status -1 means sensor initialization failed; 0 is a valid measurement.
Fix wiring and press RESET after reconnecting a missing ToF.
Accelerometer values are measured output voltages in millivolts, not calibrated acceleration.
Disconnected analog pins can float and produce plausible readings; verify the wiring.
GPS latitude, longitude and speed are only logged with a recent valid fix.
GPS may need several minutes outdoors with its antenna facing the sky.
GPS bytes staying at zero suggests power, TX/RX wiring or baud-rate trouble.
Increasing bytes with no fix suggests reception or NMEA configuration trouble.
The firmware emits approximately 10 packets/second; GPS updates at its own rate.
This is a bench reader, not a high-speed road-event detector.

5. OPTIONAL ACCELEROMETER CALIBRATION
For each axis, record its millivolt value while pointing that axis up (+1 g)
and down (-1 g). Let these values be Vplus and Vminus.
Offset = (Vplus + Vminus)/2; sensitivity = (Vplus - Vminus)/2 mV/g.
Acceleration in g = (measured_mV - offset)/sensitivity.
Gravity is included: a stationary sensor normally has total magnitude near 1 g.
Use measurements rather than assuming exactly 1650 mV offset or 330 mV/g sensitivity.

6. TROUBLESHOOTING
'Cannot open requirements.txt' or 'read_sensors.py': open PowerShell inside the extracted folder,
or double-click START_WINDOWS.bat, which changes directories automatically.
'py is not recognized': install Python for Windows with the Python launcher.
'Access denied' on COM port: close Serial Monitor and any other reader using that port.
No COM port: try a data cable and another USB port; check Device Manager.
No packets: confirm this firmware is uploaded, USB CDC is enabled and the correct COM port is selected.
A USB disconnect ends the program with an error; reconnect and run it again.

VALIDATION
Python syntax and packet parsing were checked locally. Physical sensor operation and Arduino
compilation were not tested here; hardware and Arduino toolchain are unavailable.

REFERENCES
https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/
https://github.com/adafruit/Adafruit_VL53L0X
https://github.com/mikalhart/TinyGPSPlus
https://docs.espressif.com/projects/arduino-esp32/en/latest/api/adc.html
https://www.analog.com/en/products/adxl335.html
