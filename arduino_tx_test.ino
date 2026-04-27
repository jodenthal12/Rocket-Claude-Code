// ============================================================
// MINIMAL TX TEST — flash to the GROUND RECEIVER Arduino
// Sends "TEST,<n>" over LoRa once per second. Nothing else.
// ============================================================
#include <SPI.h>
#include <RH_RF95.h>

// ---- Same pins as ground_receiver.ino ----
constexpr uint8_t PIN_CS_LORA  = 10;
constexpr uint8_t PIN_LORA_G0  = 2;
constexpr uint8_t PIN_LORA_RST = 9;
constexpr uint8_t PIN_LED      = 13;

RH_RF95 rf95(PIN_CS_LORA, PIN_LORA_G0);

void setup() {
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
  while (!Serial && millis() < 3000) {}
  Serial.println("\n=== GROUND TX TEST ===");

  pinMode(PIN_LORA_RST, OUTPUT);
  digitalWrite(PIN_LORA_RST, LOW);  delay(10);
  digitalWrite(PIN_LORA_RST, HIGH); delay(10);

  if (!rf95.init()) {
    Serial.println("RFM95W init FAILED");
    while (1) { digitalWrite(PIN_LED, !digitalRead(PIN_LED)); delay(200); }
  }
  rf95.setFrequency(915.0);
  rf95.setTxPower(13, false);
  Serial.println("RFM95W OK — transmitting on 915 MHz");
}

void loop() {
  static uint32_t n = 0;
  static uint32_t last_tx = 0;
  uint32_t now = millis();

  if (now - last_tx >= 1000) {
    last_tx = now;
    char buf[24];
    int len = snprintf(buf, sizeof(buf), "TEST,%lu", n++);

    digitalWrite(PIN_LED, HIGH);
    rf95.send((uint8_t*)buf, len);
    rf95.waitPacketSent();
    digitalWrite(PIN_LED, LOW);

    Serial.print("TX: ");
    Serial.println(buf);
  }
}
