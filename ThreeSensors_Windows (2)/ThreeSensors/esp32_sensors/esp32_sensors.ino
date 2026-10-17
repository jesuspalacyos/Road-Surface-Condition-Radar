// Target: Seeed Studio XIAO ESP32-S3. Enable USB CDC On Boot.
#include <Wire.h>
#include <Adafruit_VL53L0X.h>
#include <TinyGPS++.h>

Adafruit_VL53L0X tof;
TinyGPSPlus gps;
HardwareSerial gpsSerial(1);
bool tofOK = false;
uint32_t lastSample = 0;

uint32_t averageMV(int pin) {
  uint32_t sum = 0;
  for (int i = 0; i < 16; ++i) sum += analogReadMilliVolts(pin);
  return sum / 16;
}
void pollGPS() {
  while (gpsSerial.available()) gps.encode(gpsSerial.read());
}
void setup() {
  Serial.begin(115200);
  delay(1200);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  Wire.begin(5, 6); // D4 SDA, D5 SCL
  Wire.setTimeOut(100);
  gpsSerial.setRxBufferSize(2048);
  gpsSerial.begin(9600, SERIAL_8N1, 44, 43); // D7 RX, D6 TX
  tofOK = tof.begin(0x29, false, &Wire);
}
void loop() {
  pollGPS();
  if (millis() - lastSample < 100) return;
  lastSample = millis();
  uint16_t distance = 65535;
  int rangeStatus = -1;
  if (tofOK) {
    distance = tof.readRange();
    rangeStatus = tof.readRangeStatus();
  }
  pollGPS();
  uint32_t ax = averageMV(1), ay = averageMV(2), az = averageMV(3);
  bool fix = gps.location.isValid() && gps.location.age() < 3000;
  Serial.print("{\"ms\":"); Serial.print(millis());
  Serial.print(",\"tof_ok\":"); Serial.print(tofOK ? "true" : "false");
  Serial.print(",\"distance_mm\":");
  if (tofOK && rangeStatus == 0 && distance != 65535) Serial.print(distance);
  else Serial.print("null");
  Serial.print(",\"range_status\":"); Serial.print(rangeStatus);
  Serial.print(",\"ax_mv\":"); Serial.print(ax);
  Serial.print(",\"ay_mv\":"); Serial.print(ay);
  Serial.print(",\"az_mv\":"); Serial.print(az);
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
}
