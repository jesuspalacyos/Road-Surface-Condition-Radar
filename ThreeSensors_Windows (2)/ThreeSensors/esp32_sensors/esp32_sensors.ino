// Target: Seeed Studio XIAO ESP32-S3. Enable USB CDC On Boot.
// Firmware v2:
//  - Accelerometer sampled at ~1 kHz; each 100 ms report carries the window MEAN
//    (ax_mv/ay_mv/az_mv, same fields as v1) plus the window MIN/MAX per axis, so
//    short pothole/bump jolts are no longer averaged away.
//  - VL53L0X runs in continuous mode (non-blocking), so the distance sensor no
//    longer stalls the accelerometer sampling.
#include <Wire.h>
#include <Adafruit_VL53L0X.h>
#include <TinyGPS++.h>

const uint8_t PIN_AX = 1, PIN_AY = 2, PIN_AZ = 3;   // D0 / D1 / D2
const uint32_t REPORT_MS = 100;                     // 10 reports per second
const uint32_t SAMPLE_US = 1000;                    // ~1 kHz accelerometer sampling

Adafruit_VL53L0X tof;
TinyGPSPlus gps;
HardwareSerial gpsSerial(1);
bool tofOK = false;

uint16_t lastDistance = 65535;
int lastRangeStatus = -1;

uint32_t lastReport = 0, lastSample = 0;

struct Axis {
  uint32_t sum = 0, n = 0;
  uint16_t lo = 65535, hi = 0;
  void add(uint16_t v) { sum += v; n++; if (v < lo) lo = v; if (v > hi) hi = v; }
  void reset() { sum = 0; n = 0; lo = 65535; hi = 0; }
  uint32_t mean() const { return n ? sum / n : 0; }
};
Axis ax, ay, az;

void pollGPS() {
  while (gpsSerial.available()) gps.encode(gpsSerial.read());
}

void pollToF() {
  if (tofOK && tof.isRangeComplete()) {
    lastDistance = tof.readRangeResult();      // 0xFFFF when out of range
    lastRangeStatus = tof.readRangeStatus();
  }
}

void setup() {
  Serial.begin(115200);
  delay(1200);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  Wire.begin(5, 7);                 // SDA = D4 (GPIO5), SCL = D8 (GPIO7) - matches the actual wiring
  Wire.setTimeOut(100);
  gpsSerial.setRxBufferSize(2048);
  gpsSerial.begin(9600, SERIAL_8N1, 44, 43);   // D7 RX, D6 TX
  tofOK = tof.begin(0x29, false, &Wire);
  if (tofOK) tof.startRangeContinuous(33);     // new range about every 33 ms
}

void printNum(const char *key, uint32_t v) { Serial.print(key); Serial.print(v); }

void loop() {
  pollGPS();
  // Each ToF check is an I2C transaction; only check every 5 ms so it does not
  // steal time from the ~1 kHz accelerometer sampling.
  static uint32_t lastTofPoll = 0;
  if (millis() - lastTofPoll >= 5) { lastTofPoll = millis(); pollToF(); }

  uint32_t nowUs = micros();
  if (nowUs - lastSample >= SAMPLE_US) {
    lastSample = nowUs;
    ax.add(analogReadMilliVolts(PIN_AX));
    ay.add(analogReadMilliVolts(PIN_AY));
    az.add(analogReadMilliVolts(PIN_AZ));
  }

  if (millis() - lastReport < REPORT_MS) return;
  lastReport = millis();

  bool fix = gps.location.isValid() && gps.location.age() < 3000;
  bool distOK = tofOK && lastRangeStatus == 0 && lastDistance != 65535;

  Serial.print("{\"v\":2,\"ms\":"); Serial.print(millis());
  Serial.print(",\"tof_ok\":"); Serial.print(tofOK ? "true" : "false");
  Serial.print(",\"distance_mm\":"); if (distOK) Serial.print(lastDistance); else Serial.print("null");
  Serial.print(",\"range_status\":"); Serial.print(lastRangeStatus);
  printNum(",\"ax_mv\":", ax.mean()); printNum(",\"ay_mv\":", ay.mean()); printNum(",\"az_mv\":", az.mean());
  printNum(",\"ax_min_mv\":", ax.n ? ax.lo : 0); printNum(",\"ax_max_mv\":", ax.hi);
  printNum(",\"ay_min_mv\":", ay.n ? ay.lo : 0); printNum(",\"ay_max_mv\":", ay.hi);
  printNum(",\"az_min_mv\":", az.n ? az.lo : 0); printNum(",\"az_max_mv\":", az.hi);
  printNum(",\"acc_n\":", az.n);
  Serial.print(",\"gps_fix\":"); Serial.print(fix ? "true" : "false");
  Serial.print(",\"lat\":"); if (fix) Serial.print(gps.location.lat(), 7); else Serial.print("null");
  Serial.print(",\"lon\":"); if (fix) Serial.print(gps.location.lng(), 7); else Serial.print("null");
  Serial.print(",\"speed_kmph\":");
  if (fix && gps.speed.isValid() && gps.speed.age() < 3000) Serial.print(gps.speed.kmph(), 2);
  else Serial.print("null");
  Serial.print(",\"satellites\":");
  if (gps.satellites.isValid() && gps.satellites.age() < 3000) Serial.print(gps.satellites.value());
  else Serial.print("null");
  Serial.print(",\"gps_chars\":"); Serial.print(gps.charsProcessed());
  Serial.println("}");

  ax.reset(); ay.reset(); az.reset();
}
