/* RoadMonitor v2 — Seeed XIAO ESP32-S3, Arduino ESP32 core 3.x.
   Libraries: Adafruit VL53L0X (+ dependencies), TinyGPSPlus by Mikal Hart.
   BLE only: no Wi-Fi initialization. See README.md before wiring.
   Sensors are a research prototype, not a validated hazard detector. */
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_VL53L0X.h>
#include <TinyGPSPlus.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <atomic>
#include <math.h>

// GPIO numbers, NOT physical header positions.
constexpr int AX=1, AY=2, AZ=3, SDA_PIN=5, SCL_PIN=7 /*D8, matches wiring*/, GPS_RX=44;
constexpr float ZERO_MV=1650.0f, MV_PER_G=330.0f; // nominal for ADXL335 at 3.3 V
constexpr char SERVICE[]="8e2a0001-7c43-4f58-90f0-7a5e90401a01";
constexpr char DATA[]   ="8e2a0002-7c43-4f58-90f0-7a5e90401a01";
constexpr char COMMAND[]="8e2a0003-7c43-4f58-90f0-7a5e90401a01";
Adafruit_VL53L0X tof;
TinyGPSPlus gps;
HardwareSerial gpsSerial(1);
BLECharacteristic *dataChar;
std::atomic<bool> connected{false}, restartAdvertising{false}, wantCalibration{false};
bool tofReady=false, tofValid=false, accelValid=false, accelCal=false, tofCal=false, calibrating=false;
uint32_t lastTof=0, lastAccel=0, lastTx=0, lastGpsTx=0, calStart=0, lastPoll=0;
uint16_t distanceMM=65535, baselineMM=65535;
float a[3]={0}, resting[3]={0}, sum[3]={0}, sumSq[3]={0}, peakG=0;
float rangeSum=0, rangeSq=0;
unsigned accelSamples=0, rangeSamples=0;

class ServerEvents : public BLEServerCallbacks {
  void onConnect(BLEServer*) override { connected=true; }
  void onDisconnect(BLEServer*) override { connected=false; restartAdvertising=true; }
};
class CommandEvents : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    auto value=c->getValue();
    if(value.length()==1 && value[0]=='C') wantCalibration=true;
  }
};
void put16(uint8_t *b,int p,uint16_t n){ b[p]=n; b[p+1]=n>>8; }
void put32(uint8_t *b,int p,uint32_t n){ for(int i=0;i<4;i++) b[p+i]=n>>(8*i); }
uint16_t positive(float value){ return (uint16_t)constrain(lroundf(value),0L,65534L); }
void send(uint8_t *b){ if(connected){ dataChar->setValue(b,20); dataChar->notify(); } }
void beginCalibration(){
  calibrating=true; accelCal=false; tofCal=false; calStart=millis();
  accelSamples=rangeSamples=0; rangeSum=rangeSq=0; peakG=0;
  for(int i=0;i<3;i++){sum[i]=0;sumSq[i]=0;}
  Serial.println("Calibration: keep still, distance sensor pointing down at flat ground for 3 seconds.");
}
void finishCalibration(){
  calibrating=false;
  if(accelSamples>=100){
    float variance=0;
    for(int i=0;i<3;i++){
      resting[i]=sum[i]/accelSamples;
      variance+=fmaxf(0,sumSq[i]/accelSamples-resting[i]*resting[i]);
    }
    accelCal=sqrtf(variance)<0.10f;
  }
  if(rangeSamples>=20){
    float mean=rangeSum/rangeSamples;
    float sd=sqrtf(fmaxf(0,rangeSq/rangeSamples-mean*mean));
    tofCal=sd<15;
    baselineMM=tofCal?positive(mean):65535;
  }
  peakG=0;
  Serial.printf("Calibration done: acceleration=%s, distance=%s\n",accelCal?"OK":"retry/check wiring",tofCal?"OK":"retry/check range");
}
void setup(){
  Serial.begin(115200); // Never wait for Serial: BLE must work on battery power.
  analogReadResolution(12);
  analogSetPinAttenuation(AX,ADC_11db); analogSetPinAttenuation(AY,ADC_11db); analogSetPinAttenuation(AZ,ADC_11db);
  // No pulls: internal pull resistors would load the ADXL335 analog outputs.
  pinMode(AX,INPUT); pinMode(AY,INPUT); pinMode(AZ,INPUT);
  gpsSerial.setRxBufferSize(2048);
  gpsSerial.begin(9600,SERIAL_8N1,GPS_RX,-1); // GPS TX -> D7; GPS RX left disconnected
  // Start BLE BEFORE looking for sensors: a missing sensor cannot prevent advertising.
  BLEDevice::init("RoadMonitor-S3");
  BLEServer *server=BLEDevice::createServer(); server->setCallbacks(new ServerEvents());
  BLEService *service=server->createService(SERVICE);
  dataChar=service->createCharacteristic(DATA,BLECharacteristic::PROPERTY_NOTIFY);
  dataChar->addDescriptor(new BLE2902());
  auto command=service->createCharacteristic(COMMAND,BLECharacteristic::PROPERTY_WRITE);
  command->setCallbacks(new CommandEvents());
  service->start();
  auto advertising=BLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE); advertising->setScanResponse(true); advertising->start();
  Serial.println("BLE advertising: RoadMonitor-S3. Open dashboard in Chrome, then Connect.");
  Wire.begin(SDA_PIN,SCL_PIN); Wire.setClock(100000); Wire.setTimeOut(50);
  tofReady=tof.begin();
  if(tofReady) tofReady=tof.startRangeContinuous(50);
  Serial.printf("VL53L0X: %s. GPS: waiting for NMEA at 9600 baud.\n",tofReady?"ready":"not found");
}
void loop(){
  uint32_t now=millis();
  while(gpsSerial.available()) gps.encode(gpsSerial.read());
  if(restartAdvertising.exchange(false)) BLEDevice::startAdvertising();
  if(wantCalibration.exchange(false)) beginCalibration();
  if(Serial.available() && (Serial.read()=='C')) beginCalibration();
  now=millis();
  if(now-lastAccel>=10){ // roughly 100 Hz; BLE sends the interval's peak vibration
    lastAccel=now; accelValid=true;
    const int pins[3]={AX,AY,AZ};
    for(int i=0;i<3;i++){
      uint32_t mv=0; for(int j=0;j<4;j++) mv+=analogReadMilliVolts(pins[i]); mv/=4;
      if(mv<150 || mv>3100) accelValid=false;
      a[i]=((float)mv-ZERO_MV)/MV_PER_G;
    }
    if(calibrating && accelValid){
      accelSamples++; for(int i=0;i<3;i++){sum[i]+=a[i];sumSq[i]+=a[i]*a[i];}
    }
    if(accelValid && accelCal){
      float energy=0; for(int i=0;i<3;i++) energy+=(a[i]-resting[i])*(a[i]-resting[i]);
      peakG=fmaxf(peakG,sqrtf(energy));
    }
  }
  if(tofReady && now-lastPoll>=10){
    lastPoll=now;
    if(tof.isRangeComplete()){
      distanceMM=tof.readRangeResult();
      tofValid=tof.Status==VL53L0X_ERROR_NONE && tof.readRangeStatus()==0 && distanceMM>=30 && distanceMM<=1200;
      lastTof=now;
      if(calibrating && tofValid){rangeSamples++;rangeSum+=distanceMM;rangeSq+=(float)distanceMM*distanceMM;}
    }
  }
  if(now-lastTof>300) tofValid=false;
  if(calibrating && now-calStart>=3000) finishCalibration();
  if(now-lastTx>=100){
    lastTx=now; uint8_t b[20]={1,1,0,0};
    b[2]=(accelCal?1:0)|(tofReady?2:0)|(tofValid?4:0)|(accelValid?8:0)|(tofCal?16:0)|(calibrating?32:0);
    put32(b,4,now); put16(b,8,accelCal&&accelValid?positive(peakG*1000):65535);
    put16(b,10,tofValid?distanceMM:65535); put16(b,12,tofCal?baselineMM:65535);
    for(int i=0;i<3;i++) put16(b,14+2*i,(uint16_t)(int16_t)constrain(lroundf(a[i]*1000),-32768L,32767L));
    send(b); peakG=0;
  }
  // Offset the GPS notification to avoid sending two notifications simultaneously.
  if(now-lastGpsTx>=500 && now-lastTx>=30){
    lastGpsTx=now; uint8_t b[20]={2,1,0,0};
    bool fix=gps.location.isValid() && gps.location.age()<2500;
    bool speed=fix && gps.speed.isValid() && gps.speed.age()<2500;
    bool serialOK=gps.charsProcessed()>0; // has received bytes since boot, not a current-fix guarantee
    b[2]=(fix?1:0)|(speed?2:0)|(serialOK?4:0);
    b[3]=gps.satellites.isValid()&&gps.satellites.age()<3000?(uint8_t)constrain(gps.satellites.value(),0UL,254UL):255;
    put32(b,4,now);
    put32(b,8,fix?(uint32_t)(int32_t)lround(gps.location.lat()*1e7):0);
    put32(b,12,fix?(uint32_t)(int32_t)lround(gps.location.lng()*1e7):0);
    put16(b,16,speed?positive(gps.speed.kmph()*100):65535);
    put16(b,18,gps.hdop.isValid()&&gps.hdop.age()<3000?positive(gps.hdop.hdop()*100):65535);
    send(b);
  }
  delay(1);
}
