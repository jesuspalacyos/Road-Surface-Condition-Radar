#include <BLEDevice.h>
#include <BLEAdvertising.h>

void setup() {
  Serial.begin(115200);

  // Initialize Bluetooth
  BLEDevice::init("CAR_XIAO");

  // Create the Bluetooth advertisement
  BLEAdvertisementData advData;

  advData.setFlags(0x06);
  advData.setName("CAR_XIAO");

  // Send "Hello" as BLE service data
  advData.setServiceData(BLEUUID((uint16_t)0xFFF0), "Hello");

  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();

  pAdvertising->setAdvertisementData(advData);
  pAdvertising->start();

  Serial.println("Bluetooth transmitter started!");
}

void loop() {
  Serial.println("Broadcasting: Hello");
  delay(1000);
}