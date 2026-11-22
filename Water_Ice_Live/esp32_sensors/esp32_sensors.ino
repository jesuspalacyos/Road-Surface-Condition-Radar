// Seeed XIAO ESP32-S3 firmware for Water_Ice_Live / ESP32 USB serial monitor.
// This is a SENSOR ONLY sketch: TI radar continues running on separate USB ports.
// Libraries: Adafruit_VL53L0X, TinyGPSPlus. Select USB CDC On Boot = ENABLED.
// Pin mapping below matches the project's RoadMonitorPi USB firmware. If your
// existing ToF uses GPIO6 (D5) for SCL, change PIN_SCL from 7 to 6 before upload.
// Calibration is performed by the Python dashboard on 30 valid stationary reports.

#include <Wire.h>
#include <Adafruit_VL53L0X.h>
#include <TinyGPS++.h>

const uint8_t PIN_AX = 1, PIN_AY = 2, PIN_AZ = 3;
const uint8_t PIN_SDA = 5, PIN_SCL = 7;  // IMPORTANT: verify wiring; some sketches use SCL=6
const uint8_t GPS_RX = 44, GPS_TX = 43;
const uint32_t REPORT_MS = 100;   // 10 sensor reports/second
const uint32_t SAMPLE_US = 1000;  // aim for 1 kHz accel sampling

Adafruit_VL53L0X tof;
TinyGPSPlus gps;
HardwareSerial gpsSerial(1);
bool tofOK = false;
uint16_t lastDistance = 65535;
int lastRangeStatus = -1;
uint32_t lastReport = 0, lastSample = 0, lastDistanceAt = 0;

struct Axis {
  uint32_t sum = 0, n = 0;
  uint16_t lo = 65535, hi = 0;
  void add(uint16_t v) {
    sum += v;
    n++;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  void reset() { sum = 0; n = 0; lo = 65535; hi = 0; }
  uint32_t mean() const { return n ? sum / n : 0; }
};
Axis ax, ay, az;

void pollGPS() {
  while (gpsSerial.available()) gps.encode(gpsSerial.read());
}

void pollToF() {
  if (tofOK && tof.isRangeComplete()) {
    lastDistance = tof.readRangeResult();
    lastRangeStatus = tof.readRangeStatus();
    lastDistanceAt = millis();
  }
  if (millis() - lastDistanceAt > 300) {
    lastRangeStatus = -1;  // stale reading is invalid, not a valid distance
  }
}

void setup() {
  Serial.begin(115200);
  delay(1200); // allow USB CDC to enumerate; does not affect steady-state sampling
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setTimeOut(100);
  gpsSerial.setRxBufferSize(2048);
  gpsSerial.begin(9600, SERIAL_8N1, GPS_RX, GPS_TX);
  tofOK = tof.begin(0x29, false, &Wire);
  if (tofOK) tof.startRangeContinuous(33); // ~30 Hz ToF ranging, 10 Hz JSON reporting
}

void printNum(const char *key, uint32_t value) {
  Serial.print(key);
  Serial.print(value);
}

void loop() {
  pollGPS();

  static uint32_t lastTofPoll = 0;
  if (millis() - lastTofPoll >= 5) {
    lastTofPoll = millis();
    pollToF();
  }

  uint32_t nowUs = micros();
  if (nowUs - lastSample >= SAMPLE_US) {
    lastSample = nowUs;
    ax.add(analogReadMilliVolts(PIN_AX));
    ay.add(analogReadMilliVolts(PIN_AY));
    az.add(analogReadMilliVolts(PIN_AZ));
  }

  if (millis() - lastReport < REPORT_MS) return;
  lastReport = millis();

  const bool gpsFix = gps.location.isValid() && gps.location.age() < 3000;
  const bool distOK = tofOK && lastRangeStatus == 0 && lastDistance != 65535;

  Serial.print("{\"v\":2,\"ms\":"); Serial.print(millis());
  Serial.print(",\"tof_ok\":"); Serial.print(tofOK ? "true" : "false");
  Serial.print(",\"distance_mm\":");
  if (distOK) Serial.print(lastDistance);
  else Serial.print("null");
  Serial.print(",\"range_status\":"); Serial.print(lastRangeStatus);
  printNum(",\"ax_mv\":", ax.mean());
  printNum(",\"ay_mv\":", ay.mean());
  printNum(",\"az_mv\":", az.mean());
  printNum(",\"ax_min_mv\":", ax.n ? ax.lo : 0);
  printNum(",\"ax_max_mv\":", ax.hi);
  printNum(",\"ay_min_mv\":", ay.n ? ay.lo : 0);
  printNum(",\"ay_max_mv\":", ay.hi);
  printNum(",\"az_min_mv\":", az.n ? az.lo : 0);
  printNum(",\"az_max_mv\":", az.hi);
  printNum(",\"acc_n\":", az.n);
  Serial.print(",\"gps_fix\":"); Serial.print(gpsFix ? "true" : "false");
  Serial.print(",\"lat\":");
  if (gpsFix) Serial.print(gps.location.lat(), 7);
  else Serial.print("null");
  Serial.print(",\"lon\":");
  if (gpsFix) Serial.print(gps.location.lng(), 7);
  else Serial.print("null");
  Serial.print(",\"speed_kmph\":");
  if (gpsFix && gps.speed.isValid() && gps.speed.age() < 3000)
    Serial.print(gps.speed.kmph(), 2);
  else Serial.print("null");
  Serial.print(",\"satellites\":");
  if (gps.satellites.isValid() && gps.satellites.age() < 3000)
    Serial.print(gps.satellites.value());
  else Serial.print("null");
  Serial.print(",\"gps_chars\":"); Serial.print(gps.charsProcessed());
  Serial.println("}");

  ax.reset(); ay.reset(); az.reset();
}
