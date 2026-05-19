// ============================================================
// Water Rocket Ground Receiver (FAKE / DEMO)
// Drop-in replacement for ground_receiver.ino — no LoRa needed.
// Generates realistic-looking telemetry for a 22.7 m apogee flight.
//
// To "fly":
//   1. Power on the Arduino, plug into ground-station computer.
//   2. Open the ground station GUI, connect to the COM port.
//   3. It shows READY telemetry (rocket sitting on the pad).
//   4. Press ARM in the GUI (sends CMD,ARM).
//   5. ~3 s later it auto-launches and runs the full flight.
//   6. CMD,RESET to fly again, or power-cycle.
//
// Output format (one line per packet, identical to the real receiver):
//   R,<rssi>,<snr>,F,<ms>,<state>,<alt>,<max_alt>,<accel>,<vel>,
//     <pyro>,<safe>,<vbat>,<cont1>,<cont2>,<temp>,<gx>,<gy>,<gz>,<sd_ok>,<arm_sw>
//
// Target: any Arduino with USB serial.
// ============================================================
#include <Arduino.h>

constexpr uint8_t PIN_LED = 13;

// Flight states (match flight_v3.ino)
constexpr uint8_t ST_IDLE    = 0;
constexpr uint8_t ST_READY   = 1;
constexpr uint8_t ST_ARMED   = 2;
constexpr uint8_t ST_BOOST   = 3;
constexpr uint8_t ST_COAST   = 4;
constexpr uint8_t ST_DESCENT = 5;
constexpr uint8_t ST_LANDED  = 6;

// Profile (gives 22.7 m apogee)
constexpr uint32_t ARM_TO_LAUNCH_MS = 3000;  // 3 s after ARM, launches
constexpr uint32_t BOOST_DUR_MS     = 250;
constexpr float    BURN_VEL         = 19.9f;   // m/s at burnout
constexpr float    BURN_ALT         = 2.49f;   // m at burnout
constexpr uint32_t COAST_DUR_MS     = 2030;    // to apogee
constexpr float    APOGEE_M         = 22.7f;
constexpr uint32_t DESCENT_DUR_MS   = 5040;    // parachute
constexpr float    DESCENT_RATE     = 4.5f;    // m/s

// State
uint8_t  state         = ST_READY;
uint32_t t_arm         = 0;
uint32_t t_launch      = 0;
uint32_t t_burnout     = 0;
uint32_t t_apogee      = 0;
float    max_alt_seen  = 0.0f;
bool     pyro_latched  = false;
bool     remote_safe   = false;
bool     arm_switch_on = false;
uint32_t last_tx_ms    = 0;

float frand(float lo, float hi) {
  return lo + (hi - lo) * (random(0, 10001) / 10000.0f);
}

void reset_flight() {
  state         = ST_READY;
  t_arm = t_launch = t_burnout = t_apogee = 0;
  max_alt_seen  = 0.0f;
  pyro_latched  = false;
  remote_safe   = false;
  arm_switch_on = false;
}

void setup() {
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
  Serial.begin(115200);
  while (!Serial && millis() < 3000) {}
  randomSeed(analogRead(A0) ^ millis());
  Serial.println("GROUND_RX_READY");
  Serial.println("GROUND_RX_LISTENING");
}

void update_state(uint32_t now) {
  switch (state) {
    case ST_ARMED:
      if (!remote_safe && (now - t_arm) >= ARM_TO_LAUNCH_MS) {
        state    = ST_BOOST;
        t_launch = now;
      }
      break;
    case ST_BOOST:
      if ((now - t_launch) >= BOOST_DUR_MS) {
        state     = ST_COAST;
        t_burnout = now;
      }
      break;
    case ST_COAST:
      if ((now - t_burnout) >= COAST_DUR_MS) {
        state        = ST_DESCENT;
        t_apogee     = now;
        pyro_latched = true;
      }
      break;
    case ST_DESCENT:
      if ((now - t_apogee) >= DESCENT_DUR_MS) {
        state = ST_LANDED;
      }
      break;
    default: break;
  }
}

void compute_telemetry(uint32_t now, float &alt, float &vel, float &acc,
                       float &gx, float &gy, float &gz) {
  const float boost_accel = BURN_VEL / (BOOST_DUR_MS / 1000.0f);  // 79.6 m/s²

  switch (state) {
    case ST_READY:
      alt = frand(-0.1f, 0.1f);
      vel = frand(-0.02f, 0.02f);
      acc = 1.0f + frand(-0.02f, 0.02f);
      gx = frand(-0.5f, 0.5f); gy = frand(-0.5f, 0.5f); gz = frand(-0.5f, 0.5f);
      arm_switch_on = false;
      break;

    case ST_ARMED:
      alt = frand(-0.1f, 0.1f);
      vel = frand(-0.02f, 0.02f);
      acc = 1.0f + frand(-0.03f, 0.03f);
      gx = frand(-0.6f, 0.6f); gy = frand(-0.6f, 0.6f); gz = frand(-0.6f, 0.6f);
      arm_switch_on = true;
      break;

    case ST_BOOST: {
      float t_sec = (now - t_launch) / 1000.0f;
      vel = boost_accel * t_sec;
      alt = 0.5f * boost_accel * t_sec * t_sec;
      acc = (boost_accel / 9.81f) + frand(-0.6f, 0.6f);
      gx = frand(-15.0f, 15.0f); gy = frand(-15.0f, 15.0f); gz = frand(-8.0f, 8.0f);
      arm_switch_on = true;
      break;
    }

    case ST_COAST: {
      float dt = (now - t_burnout) / 1000.0f;
      vel = BURN_VEL - 9.81f * dt;
      alt = BURN_ALT + BURN_VEL * dt - 0.5f * 9.81f * dt * dt;
      acc = 1.0f + frand(-0.15f, 0.15f);
      gx = frand(-4.0f, 4.0f); gy = frand(-4.0f, 4.0f); gz = 22.0f + frand(-4.0f, 4.0f);
      arm_switch_on = true;
      break;
    }

    case ST_DESCENT: {
      float dt = (now - t_apogee) / 1000.0f;
      vel = -DESCENT_RATE + frand(-0.3f, 0.3f);
      alt = APOGEE_M - DESCENT_RATE * dt;
      if (alt < 0.0f) alt = 0.0f;
      acc = 1.0f + frand(-0.25f, 0.25f);
      gx = frand(-50.0f, 50.0f); gy = frand(-50.0f, 50.0f); gz = frand(-30.0f, 30.0f);
      arm_switch_on = true;
      break;
    }

    case ST_LANDED:
      alt = frand(-0.1f, 0.1f);
      vel = frand(-0.05f, 0.05f);
      acc = 1.0f + frand(-0.03f, 0.03f);
      gx = frand(-0.5f, 0.5f); gy = frand(-0.5f, 0.5f); gz = frand(-0.5f, 0.5f);
      arm_switch_on = true;
      break;

    default:
      alt = 0.0f; vel = 0.0f; acc = 1.0f;
      gx = gy = gz = 0.0f;
      break;
  }
  alt += frand(-0.15f, 0.15f);
  if (alt > max_alt_seen) max_alt_seen = alt;
}

void process_command(const String &cmd) {
  Serial.print("TX_CMD:");
  Serial.println(cmd);

  if (cmd == "CMD,ARM") {
    if (state == ST_READY || state == ST_LANDED) {
      reset_flight();
      state        = ST_ARMED;
      t_arm        = millis();
      arm_switch_on = true;
    }
  } else if (cmd == "CMD,SAFE") {
    remote_safe = true;
    if (state == ST_ARMED) {
      state         = ST_READY;
      arm_switch_on = false;
    }
  } else if (cmd == "CMD,UNSAFE") {
    remote_safe = false;
  } else if (cmd == "CMD,RESET") {
    reset_flight();
  }
}

void loop() {
  uint32_t now = millis();
  update_state(now);

  bool critical = (state == ST_BOOST || state == ST_COAST || state == ST_DESCENT);
  uint32_t tx_interval = critical ? 250 : 1000;

  if (now - last_tx_ms >= tx_interval) {
    last_tx_ms = now;

    float alt, vel, acc, gx, gy, gz;
    compute_telemetry(now, alt, vel, acc, gx, gy, gz);

    int   rssi  = -62 + (int)frand(-4.0f, 4.0f);
    float snr   = 9.5f + frand(-1.5f, 1.5f);
    float vbat  = 8.05f + frand(-0.05f, 0.05f);
    int   cont1 = 1500 + (int)frand(-30.0f, 30.0f);
    int   cont2 = 1500 + (int)frand(-30.0f, 30.0f);
    float temp  = 22.0f + frand(-0.5f, 0.5f);

    digitalWrite(PIN_LED, HIGH);
    Serial.print("R,");
    Serial.print(rssi);
    Serial.print(",");
    Serial.print(snr, 1);
    Serial.print(",F,");
    Serial.print(now);
    Serial.print(",");
    Serial.print((int)state);
    Serial.print(",");
    Serial.print(alt, 1);
    Serial.print(",");
    Serial.print(max_alt_seen, 1);
    Serial.print(",");
    Serial.print(acc, 2);
    Serial.print(",");
    Serial.print(vel, 1);
    Serial.print(",");
    Serial.print(pyro_latched ? 1 : 0);
    Serial.print(",");
    Serial.print(remote_safe ? 1 : 0);
    Serial.print(",");
    Serial.print(vbat, 1);
    Serial.print(",");
    Serial.print(cont1);
    Serial.print(",");
    Serial.print(cont2);
    Serial.print(",");
    Serial.print(temp, 1);
    Serial.print(",");
    Serial.print(gx, 1);
    Serial.print(",");
    Serial.print(gy, 1);
    Serial.print(",");
    Serial.print(gz, 1);
    Serial.print(",");
    Serial.print(1);  // sd_ok
    Serial.print(",");
    Serial.println(arm_switch_on ? 1 : 0);
    digitalWrite(PIN_LED, LOW);
  }

  // Handle commands from ground station
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() > 0 && cmd.startsWith("CMD,")) {
      process_command(cmd);
    }
  }
}
