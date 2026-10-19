// Target: Seeed Studio XIAO ESP32-S3. Enable USB CDC On Boot.
#include <Wire.h>
#include <Adafruit_VL53L0X.h>
#include <TinyGPS++.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// Arduino-ESP32 bundled BLE library (not NimBLE). USB JSON remains available.
BLECharacteristic *tx;
volatile bool connected=false;
volatile bool restartAdvertising=false;
uint16_t sequence=0;
class Callbacks: public BLEServerCallbacks {
  void onConnect(BLEServer*) override { connected=true; }
  void onDisconnect(BLEServer*) override { connected=false; restartAdvertising=true; }
};
class PacketPrint: public Print {
 public:
  String text;
  size_t write(uint8_t c) override { text+=(char)c; return 1; }
} packet;
void sendPacket() {
  Serial.print(packet.text);
  if (!connected) return;
  uint16_t seq=sequence++;
  size_t total=(packet.text.length()+15)/16;
  for (size_t part=0;part<total && connected;part++) {
    uint8_t chunk[20];
    chunk[0]=seq & 255;chunk[1]=seq>>8;chunk[2]=part;chunk[3]=total;
    size_t count=min((size_t)16,packet.text.length()-part*16);
    memcpy(chunk+4,packet.text.c_str()+part*16,count);
    tx->setValue(chunk,count+4);tx->notify();delay(3);
  }
}

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
  BLEDevice::init("RoadMonitor-S3");
  BLEServer *server=BLEDevice::createServer();
  server->setCallbacks(new Callbacks());
  BLEService *service=server->createService("6e400001-b5a3-f393-e0a9-e50e24dcca9e");
  tx=service->createCharacteristic("6e400003-b5a3-f393-e0a9-e50e24dcca9e",BLECharacteristic::PROPERTY_NOTIFY);
  tx->addDescriptor(new BLE2902());service->start();
  BLEAdvertising *advertising=BLEDevice::getAdvertising();
  advertising->addServiceUUID(service->getUUID());advertising->setScanResponse(true);
  advertising->start();
  packet.text.reserve(512);
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
  if (restartAdvertising) { restartAdvertising=false; BLEDevice::startAdvertising(); }
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
  packet.text="";
  packet.print("{\"ms\":"); packet.print(millis());
  packet.print(",\"tof_ok\":"); packet.print(tofOK ? "true" : "false");
  packet.print(",\"distance_mm\":");
  if (tofOK && rangeStatus == 0 && distance != 65535) packet.print(distance);
  else packet.print("null");
  packet.print(",\"range_status\":"); packet.print(rangeStatus);
  packet.print(",\"ax_mv\":"); packet.print(ax);
  packet.print(",\"ay_mv\":"); packet.print(ay);
  packet.print(",\"az_mv\":"); packet.print(az);
  packet.print(",\"gps_fix\":"); packet.print(fix ? "true" : "false");
  packet.print(",\"lat\":"); if (fix) packet.print(gps.location.lat(), 7); else packet.print("null");
  packet.print(",\"lon\":"); if (fix) packet.print(gps.location.lng(), 7); else packet.print("null");
  packet.print(",\"speed_kmph\":");
  if (fix && gps.speed.isValid() && gps.speed.age() < 3000) packet.print(gps.speed.kmph(), 2);
  else packet.print("null");
  packet.print(",\"satellites\":");
  if (gps.satellites.isValid() && gps.satellites.age() < 3000) packet.print(gps.satellites.value());
  else packet.print("null");
  packet.print(",\"gps_chars\":"); packet.print(gps.charsProcessed());
  packet.println("}");
  sendPacket();
}
