// ============================================================
// Water Rocket Ground Receiver
// Receives telemetry from flight computer via RFM95W LoRa,
// forwards to USB serial for the Python ground station GUI.
//
// Output format (one line per packet):
//   R,<rssi>,<snr>,<payload>
//
// Target: any Arduino/Teensy with RFM95W on SPI0
// ============================================================
#include <Arduino.h>
#include <SPI.h>
#include <RH_RF95.h>

// --- Pin map (match your ground receiver wiring) ---
constexpr uint8_t PIN_CS_LORA   = 10;
constexpr uint8_t PIN_LORA_G0   = 2;   // DIO0 interrupt pin
constexpr uint8_t PIN_LORA_RST  = 9;
constexpr uint8_t PIN_LED       = 13;   // on-board LED for RX blink

RH_RF95 rf95(PIN_CS_LORA, PIN_LORA_G0);

void setup() {
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

  Serial.begin(115200);
  while (!Serial && millis() < 3000) {}
  Serial.println("GROUND_RX_READY");

  // Reset radio
  pinMode(PIN_LORA_RST, OUTPUT);
  digitalWrite(PIN_LORA_RST, LOW);  delay(10);
  digitalWrite(PIN_LORA_RST, HIGH); delay(10);

  if (!rf95.init()) {
    Serial.println("ERROR:RFM95W init failed");
    while (1) { digitalWrite(PIN_LED, !digitalRead(PIN_LED)); delay(200); }
  }

  rf95.setFrequency(915.0);
  rf95.setTxPower(13, false);

  Serial.println("GROUND_RX_LISTENING");
}

void loop() {
  // --- Receive telemetry from flight computer ---
  if (rf95.available()) {
    uint8_t buf[200];
    uint8_t len = sizeof(buf) - 1;

    if (rf95.recv(buf, &len) && len > 0) {
      buf[len] = '\0';

      int16_t rssi = rf95.lastRssi();
      // RH_RF95_REG_19_PKT_SNR_VALUE: signed byte, value = SNR * 4
      int8_t  snr_raw = (int8_t)rf95.spiRead(0x19);
      float   snr = snr_raw / 4.0f;

      digitalWrite(PIN_LED, HIGH);
      Serial.print(F("R,"));
      Serial.print(rssi);
      Serial.print(F(","));
      Serial.print(snr, 1);
      Serial.print(F(","));
      Serial.println((char*)buf);
      digitalWrite(PIN_LED, LOW);
    }
  }

  // --- Forward commands from ground station GUI to flight computer ---
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() > 0 && cmd.startsWith("CMD,")) {
      // Transmit command over LoRa to flight computer
      rf95.send((uint8_t*)cmd.c_str(), cmd.length());
      rf95.waitPacketSent();
      Serial.print(F("TX_CMD:"));
      Serial.println(cmd);
      digitalWrite(PIN_LED, HIGH);
      delay(10);
      digitalWrite(PIN_LED, LOW);
    }
  }
}
