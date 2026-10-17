# RoadMonitor v2 protocol

BLE name: RoadMonitor-S3
Service: 8e2a0001-7c43-4f58-90f0-7a5e90401a01
Notify: 8e2a0002-7c43-4f58-90f0-7a5e90401a01
Write-with-response: 8e2a0003-7c43-4f58-90f0-7a5e90401a01
Write one ASCII byte C (0x43) to start calibration. Completion is reported in flags.

All telemetry packets are exactly 20 bytes, so no larger BLE MTU or JSON-fragment
assembly is required. All multibyte values are little-endian. Byte 0 is packet type;
byte 1 is protocol version (1). Timestamp is milliseconds since boot, wrapping at 2^32.
Missing unsigned readings are 65535; the matching validity flags must also be checked.
The link does not configure BLE pairing/encryption: nearby clients may access readings
and request calibration. Use in a controlled setting; authentication is separate work.

## Type 1: sensors, about 10 Hz

| Offset | Type | Meaning |
|---:|---|---|
| 0 | u8 | 1 |
| 1 | u8 | 1 |
| 2 | u8 | Flags: bit 0 accel calibrated; 1 ToF initialized; 2 distance valid; 3 analog plausible; 4 ToF calibrated; 5 calibration active |
| 3 | u8 | Reserved 0 |
| 4 | u32 | Device uptime ms |
| 8 | u16 | Interval peak vector change, milli-g; 65535 unavailable |
| 10 | u16 | Ground distance mm; 65535 unavailable |
| 12 | u16 | Flat-ground reference mm; 65535 unavailable |
| 14 | i16 | Nominal raw X acceleration, milli-g |
| 16 | i16 | Nominal raw Y acceleration, milli-g |
| 18 | i16 | Nominal raw Z acceleration, milli-g |

X/Y/Z include gravity and nominal sensor offset error; validity is indicated by bit 3.
They are not individually six-position calibrated. Calibrating uses 3 seconds of
stationary readings, at least 100 valid acceleration samples and 20 valid distance
samples. Acceleration summed-axis standard deviation must be <0.10 g; distance
standard deviation must be <15 mm. Independent calibration flags allow partial results.

## Type 2: GPS, about 2 Hz

| Offset | Type | Meaning |
|---:|---|---|
| 0 | u8 | 2 |
| 1 | u8 | 1 |
| 2 | u8 | Flags: bit 0 fix age <2500 ms; 1 speed valid and age <2500 ms with fix; 2 any UART bytes received since boot |
| 3 | u8 | Satellites; 255 unavailable/stale |
| 4 | u32 | Device uptime ms |
| 8 | i32 | Latitude × 10^7 (0 placeholder without fix) |
| 12 | i32 | Longitude × 10^7 (0 placeholder without fix) |
| 16 | u16 | Speed km/h × 100; 65535 unavailable |
| 18 | u16 | HDOP × 100; 65535 unavailable/stale |

Satellite and HDOP readings must be younger than 3000 ms. HDOP is a geometry metric,
not accuracy in meters. Map routing uses only valid fixes. It does not reject all GPS
outliers; event locations inherit receiver accuracy and transmission delay. Lost fixes
must clear live speed/location, while an earlier route may remain visible as history.
