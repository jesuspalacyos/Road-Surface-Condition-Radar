HardwareSerial gps(1);
const int pins[] = {44, 43};               // D7, D6
const long bauds[] = {9600, 38400, 4800, 115200};
void setup(){ Serial.begin(115200); delay(1500); }
void loop(){
  for (int rx : pins) for (long b : bauds) {
    gps.end(); gps.begin(b, SERIAL_8N1, rx, -1);
    uint32_t t = millis(); int n = 0; String s;
    while (millis() - t < 1500) while (gps.available()) { char c = gps.read(); n++; if (s.length() < 80) s += c; }
    Serial.printf("RX=GPIO%d baud=%ld: %d bytes  %s\n", rx, b, n, n ? s.c_str() : "");
  }
  Serial.println("----");
}
