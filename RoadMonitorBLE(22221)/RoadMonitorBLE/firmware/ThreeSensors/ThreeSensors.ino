// ASSUMPTIONS: XIAO ESP32-S3, ADXL335 analog accelerometer, VL53L0X, NEO-6M.
// Arduino board: XIAO_ESP32S3; USB CDC On Boot: Enabled.
// Libraries: Adafruit VL53L0X, TinyGPSPlus (Library Manager).
// All signals must be 3.3 V safe. Change pins to match existing wiring before upload.
#include <Wire.h>
#include <Adafruit_VL53L0X.h>
#include <TinyGPSPlus.h>
Adafruit_VL53L0X tof;
TinyGPSPlus gps;
HardwareSerial GPS(1);
bool tofReady=false;
const int AX=1,AY=2,AZ=3; // D0, D1, D2
const float ZERO_MV=1650.0, MV_PER_G=330.0; // approximate ADXL335 at 3.3V; calibrate per axis
unsigned long lastSend=0;
float accel(int pin){unsigned long sum=0;for(int i=0;i<8;i++)sum+=analogReadMilliVolts(pin);return (sum/8.0-ZERO_MV)/MV_PER_G;}
void setup(){Serial.begin(115200);Wire.begin(5,6); // D4 SDA, D5 SCL
 GPS.begin(9600,SERIAL_8N1,44,43); // GPS TX -> D7 RX; optional GPS RX <- D6 TX
 analogReadResolution(12);analogSetAttenuation(ADC_11db);
 tofReady=tof.begin();}
void loop(){while(GPS.available())gps.encode(GPS.read());
 if(millis()-lastSend<100)return;lastSend=millis();
 VL53L0X_RangingMeasurementData_t measure;
 bool valid=false;if(tofReady){tof.rangingTest(&measure,false);valid=measure.RangeStatus==0;}
 bool fix=gps.location.isValid()&&gps.location.age()<2000;
 Serial.print("{\"schema\":\"road-v1\",\"tof_mm\":");if(valid)Serial.print(measure.RangeMilliMeter);else Serial.print("null");
 Serial.printf(",\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"gps_fix\":%s",accel(AX),accel(AY),accel(AZ),fix?"true":"false");
 Serial.print(",\"lat\":");if(fix)Serial.print(gps.location.lat(),7);else Serial.print("null");
 Serial.print(",\"lon\":");if(fix)Serial.print(gps.location.lng(),7);else Serial.print("null");
 Serial.print(",\"speed_kmh\":");if(fix&&gps.speed.isValid()&&gps.speed.age()<2000)Serial.print(gps.speed.kmph(),2);else Serial.print("null");
 Serial.print(",\"satellites\":");if(gps.satellites.isValid())Serial.print(gps.satellites.value());else Serial.print("null");Serial.println("}");
}
