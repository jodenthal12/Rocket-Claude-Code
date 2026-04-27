// ============================================================
// MINIMAL RX TEST — flash to the TEENSY 4.1 (the rocket)
// Listens for any LoRa packet and prints it. No flight logic.
// Tries BOTH polled DIO0 and a forced-RX-mode poll loop.
// ============================================================
#include <SPI.h>
#include <RH_RF95.h>

// ---- Same pins as flight_v3_test ----
constexpr uint8_t PIN_LORA_RST = 0;
constexpr uint8_t PIN_LORA_G0  = 1;   // DIO0
constexpr uint8_t PIN_CS_LORA  = 10;
constexpr uint8_t PIN_LED      = 13;  // built-in LED

// Polled subclass (same trick as flight code)
class PollableRF95 : public RH_RF95 {
public:
  PollableRF95(uint8_t cs, uint8_t irq) : RH_RF95(cs, 0xFF), _dio0(irq) {}
  void poll() {
    if (digitalRead(_dio0)) handleInterrupt();
  }
private:
  uint8_t _dio0;
};

PollableRF95 rf95(PIN_CS_LORA, PIN_LORA_G0);

void setup() {
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
  while (!Serial && millis() < 3000) {}
  Serial.println("\n=== TEENSY RX TEST ===");

  pinMode(PIN_LORA_RST, OUTPUT);
  digitalWrite(PIN_LORA_RST, LOW);  delay(10);
  digitalWrite(PIN_LORA_RST, HIGH); delay(10);

  pinMode(PIN_LORA_G0, INPUT);

  if (!rf95.init()) {
    Serial.println("RFM95W init FAILED");
    while (1) { digitalWrite(PIN_LED, !digitalRead(PIN_LED)); delay(200); }
  }
  rf95.setFrequency(915.0);
  rf95.setTxPower(13, false);
  rf95.setModeRx();
  Serial.println("RFM95W OK — listening on 915 MHz");
}

void loop() {
  // Manually poll DIO0
  rf95.poll();

  // ALSO poll the IRQ flag register over SPI directly — bypasses DIO0
  // entirely.  If a packet is received and DIO0 doesn't fire, we'll
  // catch it here.
  uint8_t irq = rf95.spiRead(0x12);   // REG_IRQ_FLAGS
  if (irq != 0) {
    Serial.print("IRQ flags = 0x");
    Serial.println(irq, HEX);
    rf95.handleInterrupt();           // process whatever fired
  }

  if (rf95.available()) {
    uint8_t buf[64];
    uint8_t len = sizeof(buf) - 1;
    bool ok = rf95.recv(buf, &len);
    if (ok && len > 0) {
      buf[len] = '\0';
      Serial.print("RX: ");
      Serial.print((char*)buf);
      Serial.print("  RSSI=");
      Serial.print(rf95.lastRssi());
      Serial.print("  len=");
      Serial.println(len);
      digitalWrite(PIN_LED, HIGH);
      delay(20);
      digitalWrite(PIN_LED, LOW);
    } else {
      Serial.print("RX FAIL: ok=");
      Serial.print(ok);
      Serial.print(" len=");
      Serial.println(len);
    }
  }

  // Heartbeat every 2 seconds so we know the sketch is alive
  static uint32_t last_hb = 0;
  uint32_t now = millis();
  if (now - last_hb >= 2000) {
    last_hb = now;
    uint8_t op    = rf95.spiRead(0x01);   // REG_OP_MODE
    uint8_t flags = rf95.spiRead(0x12);   // REG_IRQ_FLAGS
    uint8_t rssi  = rf95.spiRead(0x1A);   // REG_RSSI_VALUE  (-157 + raw)
    Serial.print("alive  dio0=");
    Serial.print(digitalRead(PIN_LORA_G0));
    Serial.print("  mode=");
    Serial.print(rf95.mode());
    Serial.print("  op=0x");
    Serial.print(op, HEX);
    Serial.print("  flags=0x");
    Serial.print(flags, HEX);
    Serial.print("  rssi=");
    Serial.println((int)rssi - 157);
  }
}
