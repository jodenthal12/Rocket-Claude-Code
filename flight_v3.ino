// ============================================================
// Water Rocket Flight Computer - Phase 2 Flight Firmware v5
// Target: Teensy 4.1 | All SPI on SPI0
// Changes from v4:
//  - Added remote SAFE/ARM commands over LoRa
//  - Added SD card telemetry logging
// ============================================================
#include <Arduino.h>
#include <SPI.h>
#include <RH_RF95.h>
#include <Adafruit_BMP3XX.h>
#include <Adafruit_NeoPixel.h>
#include <SD.h>
#include <math.h>

// ---------- Pin map ----------
constexpr uint8_t PIN_LORA_RST   = 0;
constexpr uint8_t PIN_LORA_G0    = 1;
constexpr uint8_t PIN_PYRO1_FIRE = 2;
constexpr uint8_t PIN_BUZZER     = 3;
constexpr uint8_t PIN_PYRO2_FIRE = 5;
constexpr uint8_t PIN_CS_GYRO    = 7;
constexpr uint8_t PIN_CS_ACCEL   = 8;
constexpr uint8_t PIN_CS_BMP     = 9;
constexpr uint8_t PIN_CS_LORA    = 10;
constexpr uint8_t PIN_CS_SD      = 6;   // SD card chip select
constexpr uint8_t PIN_BUTTON     = 16;
constexpr uint8_t PIN_ARM_SW     = 15;  // physical arm switch
constexpr uint8_t PIN_CONT1      = 19;
constexpr uint8_t PIN_CONT2      = 21;
constexpr uint8_t PIN_VBAT_DIV   = 22;
constexpr uint8_t PIN_SK6812     = 24;

// ---------- Flight parameters ----------
constexpr float    LAUNCH_ACCEL_G    = 3.0f;
constexpr uint8_t  LAUNCH_SAMPLES    = 3;
constexpr float    BURNOUT_ACCEL_G   = 1.3f;
constexpr uint8_t  BURNOUT_SAMPLES   = 3;
constexpr float    APOGEE_DROP_M     = 1.0f;
constexpr uint8_t  APOGEE_SAMPLES    = 4;
constexpr uint32_t MIN_COAST_MS      = 300;
constexpr uint32_t APOGEE_BACKUP_MS  = 3000;
constexpr uint32_t PYRO_FIRE_MS      = 500;
constexpr uint32_t LANDED_STILL_MS   = 3000;
constexpr float    LANDED_ALT_BAND   = 0.8f;
constexpr uint32_t FLIGHT_TIMEOUT_MS = 120000;
constexpr float    VBAT_MIN          = 7.0f;
constexpr int      CONT_MIN_RAW      = 500;
constexpr int      CONT_MAX_RAW      = 3800;
constexpr float    SEA_LEVEL_HPA     = 1013.25f;

constexpr uint8_t NUM_LEDS = 4;
enum { LED_PWR=0, LED_ARM=1, LED_P1=2, LED_P2=3 };

// BMI088 accel registers
constexpr uint8_t ACC_CHIP_ID  = 0x00;
constexpr uint8_t ACC_DATA     = 0x12;
constexpr uint8_t ACC_CONF     = 0x40;
constexpr uint8_t ACC_RANGE    = 0x41;
constexpr uint8_t ACC_PWR_CONF = 0x7C;
constexpr uint8_t ACC_PWR_CTRL = 0x7D;
constexpr uint8_t ACC_SOFTRESET= 0x7E;

// BMI088 gyro registers (separate chip, PIN_CS_GYRO)
constexpr uint8_t GYR_CHIP_ID = 0x00;  // expected 0x0F
constexpr uint8_t GYR_DATA    = 0x02;  // 6 bytes burst: gx_lo,gx_hi,gy_lo,gy_hi,gz_lo,gz_hi
constexpr uint8_t GYR_RANGE   = 0x0F;  // 0x00 = ±2000 °/s
constexpr uint8_t GYR_BAND    = 0x10;  // 0x00 = 2000 Hz ODR, unfiltered
constexpr uint8_t GYR_LPM1   = 0x11;  // 0x00 = normal mode

static const SPISettings BMI_SPI(5000000, MSBFIRST, SPI_MODE0);

// Gyro state (body-frame rates in °/s)
float gx_dps = 0.0f, gy_dps = 0.0f, gz_dps = 0.0f;
constexpr float GYR_SCALE = 2000.0f / 32768.0f;  // °/s per LSB at ±2000 °/s

// ---------- 1D Kalman Filter for altitude ----------
// State: [altitude, vertical_velocity]
// Measurement: barometric altitude
// Input: vertical acceleration from accelerometer
struct KalmanAlt {
  float alt;       // estimated altitude (m AGL)
  float vel;       // estimated vertical velocity (m/s)
  float p00, p01;  // covariance matrix row 0
  float p10, p11;  // covariance matrix row 1
  float q_alt;     // process noise for altitude
  float q_vel;     // process noise for velocity
  float r_baro;    // measurement noise for barometer
  bool  initialized;

  void init(float initial_alt) {
    alt = initial_alt;
    vel = 0.0f;
    p00 = 1.0f;  p01 = 0.0f;
    p10 = 0.0f;  p11 = 1.0f;
    q_alt  = 0.1f;   // process noise — altitude
    q_vel  = 2.0f;   // process noise — velocity (accel is noisy)
    r_baro = 0.5f;   // barometer measurement noise
    initialized = true;
  }

  void predict(float dt, float accel_vertical_ms2) {
    // State prediction: x = F*x + B*u
    alt += vel * dt + 0.5f * accel_vertical_ms2 * dt * dt;
    vel += accel_vertical_ms2 * dt;

    // Covariance prediction: P = F*P*F' + Q
    float f01_dt = dt;
    float new_p00 = p00 + f01_dt * p10 + (p01 + f01_dt * p11) * f01_dt + q_alt;
    float new_p01 = p01 + f01_dt * p11;
    float new_p10 = p10 + p11 * f01_dt;
    float new_p11 = p11 + q_vel;
    p00 = new_p00; p01 = new_p01;
    p10 = new_p10; p11 = new_p11;
  }

  void update(float baro_alt) {
    // Kalman gain: K = P*H' / (H*P*H' + R)
    // H = [1, 0] — we measure altitude only
    float s = p00 + r_baro;  // innovation covariance
    float k0 = p00 / s;      // gain for altitude
    float k1 = p10 / s;      // gain for velocity

    // State update
    float y = baro_alt - alt;  // innovation
    alt += k0 * y;
    vel += k1 * y;

    // Covariance update: P = (I - K*H) * P
    float new_p00 = p00 - k0 * p00;
    float new_p01 = p01 - k0 * p01;
    float new_p10 = p10 - k1 * p00;
    float new_p11 = p11 - k1 * p01;
    p00 = new_p00; p01 = new_p01;
    p10 = new_p10; p11 = new_p11;
  }
};

// ---------- State ----------
enum FlightState {
  ST_IDLE, ST_READY, ST_ARMED, ST_BOOST, ST_COAST, ST_DESCENT, ST_LANDED, ST_FAULT
};

// Subclass to expose the protected handleInterrupt() for DIO0 polling.
// DIO0 on Teensy 4.1 pin 1 shares Serial1 TX — hardware interrupts never fire,
// so we poll the pin and call handleInterrupt() manually.
class PollableRF95 : public RH_RF95 {
public:
  PollableRF95(uint8_t cs, uint8_t irq) : RH_RF95(cs, irq), _dio0(irq) {}
  void poll() {
    if (digitalRead(_dio0)) handleInterrupt();
  }
private:
  uint8_t _dio0;
};

PollableRF95 rf95(PIN_CS_LORA, PIN_LORA_G0);
Adafruit_BMP3XX bmp;
Adafruit_NeoPixel leds(NUM_LEDS, PIN_SK6812, NEO_GRB + NEO_KHZ800);
KalmanAlt kf;
File log_file;
bool sd_ok = false;

FlightState state = ST_IDLE;
float    ground_alt = 0.0f;
float    max_alt    = 0.0f;
float    accel_range_g = 24.0f;
uint32_t t_launch = 0;
uint32_t t_coast  = 0;
uint32_t t_landed_start = 0;
uint32_t pyro_fire_start = 0;
bool     pyro_active = false;
bool     pyro_fired  = false;
bool     prev_arm_sw = false;
bool     remote_safe = false;  // set by ground station CMD,SAFE
uint8_t  launch_streak  = 0;
uint8_t  burnout_streak = 0;
uint8_t  apogee_streak  = 0;
float    landed_ref_alt = 0.0f;
float    last_baro_alt = NAN;
bool     baro_fresh = false;
uint32_t last_predict_ms = 0;

// ---------- SD card logging ----------
void log_telemetry(uint32_t now, float alt_agl, float max_alt, float accel_g, float vel_est) {
  if (!sd_ok || !log_file) return;

  char buf[96];
  int n = snprintf(buf, sizeof(buf),
                   "%lu,%d,%.1f,%.1f,%.2f,%.1f,%d,%d",
                   now, (int)state, alt_agl, max_alt, accel_g, vel_est, pyro_fired, remote_safe);
  if (n > 0) {
    log_file.println(buf);
    // Flush every 10 writes to SD (batching for performance)
    static uint8_t flush_counter = 0;
    if (++flush_counter >= 10) {
      log_file.flush();
      flush_counter = 0;
    }
  }
}

// ---------- Pyro safety ----------
void pyro_safe() {
  pinMode(PIN_PYRO1_FIRE, OUTPUT); digitalWrite(PIN_PYRO1_FIRE, LOW);
  pinMode(PIN_PYRO2_FIRE, OUTPUT); digitalWrite(PIN_PYRO2_FIRE, LOW);
  pyro_active = false;
}

// ---------- Helpers ----------
void beep(uint16_t f, uint16_t ms) { tone(PIN_BUZZER, f, ms); delay(ms + 20); }
void led(uint8_t i, uint32_t c)    { leds.setPixelColor(i, c); leds.show(); }

bool check(const char* name, bool ok) {
  Serial.printf("  [%s] %s\n", ok ? " OK " : "FAIL", name);
  if (ok) {
    tone(PIN_BUZZER, 2500, 30); delay(40);   // quick chirp = pass
  } else {
    beep(400, 300); beep(400, 300);           // two low tones = fail
  }
  return ok;
}

float read_vbat() {
  return analogRead(PIN_VBAT_DIV) * (3.3f / 4095.0f) * 2.0f;
}

bool continuity_ok() {
  int c1 = analogRead(PIN_CONT1);
  int c2 = analogRead(PIN_CONT2);
  return (c1 > CONT_MIN_RAW && c1 < CONT_MAX_RAW) &&
         (c2 > CONT_MIN_RAW && c2 < CONT_MAX_RAW);
}

float pressure_to_alt(float pressure_pa) {
  float atm_hpa = pressure_pa / 100.0f;
  return 44330.0f * (1.0f - powf(atm_hpa / SEA_LEVEL_HPA, 0.1903f));
}

// ---------- BMI088 driver ----------
void bmi_write(uint8_t cs, uint8_t reg, uint8_t val) {
  SPI.beginTransaction(BMI_SPI);
  digitalWrite(cs, LOW);
  SPI.transfer(reg & 0x7F);
  SPI.transfer(val);
  digitalWrite(cs, HIGH);
  SPI.endTransaction();
}

uint8_t bmi_read1(uint8_t cs, uint8_t reg, bool dummy) {
  SPI.beginTransaction(BMI_SPI);
  digitalWrite(cs, LOW);
  SPI.transfer(reg | 0x80);
  if (dummy) SPI.transfer(0x00);
  uint8_t v = SPI.transfer(0x00);
  digitalWrite(cs, HIGH);
  SPI.endTransaction();
  return v;
}

void bmi_read_accel_raw(int16_t &x, int16_t &y, int16_t &z) {
  uint8_t b[6];
  SPI.beginTransaction(BMI_SPI);
  digitalWrite(PIN_CS_ACCEL, LOW);
  SPI.transfer(ACC_DATA | 0x80);
  SPI.transfer(0x00);
  for (int i = 0; i < 6; i++) b[i] = SPI.transfer(0x00);
  digitalWrite(PIN_CS_ACCEL, HIGH);
  SPI.endTransaction();
  x = (int16_t)((b[1] << 8) | b[0]);
  y = (int16_t)((b[3] << 8) | b[2]);
  z = (int16_t)((b[5] << 8) | b[4]);
}

// Returns accel components in g (ax, ay, az) and magnitude
float read_accel_mag_g(float &az_out) {
  int16_t x, y, z;
  bmi_read_accel_raw(x, y, z);
  float scale = (accel_range_g * 2.0f) / 65536.0f;
  float ax = x * scale, ay = y * scale, az = z * scale;
  az_out = az;  // Z-axis for vertical accel estimate
  return sqrtf(ax*ax + ay*ay + az*az);
}

bool bmi088_gyro_init() {
  // Wake gyro (SPI activate — first read is a dummy on BMI088 gyro)
  bmi_read1(PIN_CS_GYRO, GYR_CHIP_ID, false);
  delay(10);
  bmi_write(PIN_CS_GYRO, GYR_LPM1, 0x00);   // normal mode
  delay(30);
  bmi_write(PIN_CS_GYRO, GYR_RANGE, 0x00);  // ±2000 °/s
  delay(5);
  bmi_write(PIN_CS_GYRO, GYR_BAND, 0x00);   // 2000 Hz ODR
  delay(5);
  return bmi_read1(PIN_CS_GYRO, GYR_CHIP_ID, false) == 0x0F;
}

void read_gyro() {
  uint8_t b[6];
  SPI.beginTransaction(BMI_SPI);
  digitalWrite(PIN_CS_GYRO, LOW);
  SPI.transfer(GYR_DATA | 0x80);
  for (int i = 0; i < 6; i++) b[i] = SPI.transfer(0x00);
  digitalWrite(PIN_CS_GYRO, HIGH);
  SPI.endTransaction();
  gx_dps = (int16_t)((b[1] << 8) | b[0]) * GYR_SCALE;
  gy_dps = (int16_t)((b[3] << 8) | b[2]) * GYR_SCALE;
  gz_dps = (int16_t)((b[5] << 8) | b[4]) * GYR_SCALE;
}

bool bmi088_accel_init() {
  bmi_read1(PIN_CS_ACCEL, ACC_CHIP_ID, true);
  delay(2);
  bmi_write(PIN_CS_ACCEL, ACC_SOFTRESET, 0xB6);
  delay(50);
  bmi_read1(PIN_CS_ACCEL, ACC_CHIP_ID, true);
  delay(2);
  bmi_write(PIN_CS_ACCEL, ACC_PWR_CTRL, 0x04);
  delay(50);
  bmi_write(PIN_CS_ACCEL, ACC_PWR_CONF, 0x00);
  delay(5);
  bmi_write(PIN_CS_ACCEL, ACC_RANGE, 0x03);  // ±24g
  accel_range_g = 24.0f;
  bmi_write(PIN_CS_ACCEL, ACC_CONF, 0xAA);   // 400 Hz
  delay(5);
  return bmi_read1(PIN_CS_ACCEL, ACC_CHIP_ID, true) == 0x1E;
}

// ---------- Pyro fire (non-blocking) ----------
bool start_pyro_fire() {
  if (pyro_fired) return true;
  if (remote_safe) {
    Serial.println("FIRE BLOCKED: remote safe active");
    return false;
  }
  if (!continuity_ok()) {
    Serial.println("FIRE RETRY: continuity fail");
    return false;
  }
  if (digitalRead(PIN_ARM_SW) != HIGH) {
    Serial.println("FIRE RETRY: arm switch off");
    return false;
  }
  pyro_fired = true;
  pyro_active = true;
  pyro_fire_start = millis();
  Serial.printf("*** FIRE PYROS @ %lu ms ***\n", pyro_fire_start);
  led(LED_P1, 0x200000);
  led(LED_P2, 0x200000);
  digitalWrite(PIN_PYRO1_FIRE, HIGH);
  digitalWrite(PIN_PYRO2_FIRE, HIGH);
  return true;
}

void service_pyro_timer(uint32_t now) {
  if (pyro_active && (now - pyro_fire_start) >= PYRO_FIRE_MS) {
    digitalWrite(PIN_PYRO1_FIRE, LOW);
    digitalWrite(PIN_PYRO2_FIRE, LOW);
    pyro_active = false;
    Serial.println("Pyro gates LOW (fire complete)");
  }
}

// ---------- Continuous LED status (runs every 100 ms) ----------
// LED_ARM  : GREEN if armed (switch ON and not remote-safed), RED if safe
// LED_P1   : GREEN if pyro 1 has continuity, RED if open
// LED_P2   : GREEN if pyro 2 has continuity, RED if open
// Pyro LEDs go bright red during active fire; restored on next tick.
void update_status_leds(uint32_t now) {
  static uint32_t last_ms = 0;
  if (now - last_ms < 100) return;
  last_ms = now;

  bool sw_on      = (digitalRead(PIN_ARM_SW) == HIGH);
  bool fully_armed = (state == ST_ARMED);
  if (fully_armed) {
    leds.setPixelColor(LED_ARM, 0x002000);                          // solid GREEN: fully armed
  } else if (sw_on && !remote_safe) {
    uint32_t c = ((now / 500) % 2 == 0) ? 0x002000 : 0x000000;    // flash GREEN: switch only
    leds.setPixelColor(LED_ARM, c);
  } else {
    leds.setPixelColor(LED_ARM, 0x200000);                          // RED: safe
  }

  if (!pyro_active) {
    int c1 = analogRead(PIN_CONT1);
    int c2 = analogRead(PIN_CONT2);
    bool c1_ok = (c1 > CONT_MIN_RAW && c1 < CONT_MAX_RAW);
    bool c2_ok = (c2 > CONT_MIN_RAW && c2 < CONT_MAX_RAW);
    leds.setPixelColor(LED_P1, c1_ok ? 0x002000 : 0x200000);
    leds.setPixelColor(LED_P2, c2_ok ? 0x002000 : 0x200000);

    // Print raw ADC every ~2 s for diagnostics
    static uint32_t last_cont_dbg = 0;
    if (now - last_cont_dbg >= 2000) {
      last_cont_dbg = now;
      Serial.printf("  CONT_RAW c1=%d(%s) c2=%d(%s)\n",
                    c1, c1_ok ? "OK" : "OPEN",
                    c2, c2_ok ? "OK" : "OPEN");
    }
  }
  leds.show();
}

// ---------- Preflight ----------
bool preflight() {
  Serial.println("\n--- PREFLIGHT ---");
  bool ok = true;
  ok &= check("Pyro1 GPIO cmd LOW", digitalRead(PIN_PYRO1_FIRE) == LOW);
  ok &= check("Pyro2 GPIO cmd LOW", digitalRead(PIN_PYRO2_FIRE) == LOW);
  ok &= check("ARM disarmed at boot", digitalRead(PIN_ARM_SW) == LOW);

  float vbat = read_vbat();
  Serial.printf("     VBAT = %.2f V\n", vbat);
  ok &= check("VBAT OK", vbat >= VBAT_MIN);
  ok &= check("Continuity OK", continuity_ok());
  ok &= check("BMI088 accel init", bmi088_accel_init());
  ok &= check("BMI088 gyro init",  bmi088_gyro_init());

  bool bmpOk = bmp.begin_SPI(PIN_CS_BMP);
  ok &= check("BMP390 init", bmpOk);
  if (bmpOk) {
    bmp.setPressureOversampling(BMP3_OVERSAMPLING_8X);
    bmp.setTemperatureOversampling(BMP3_OVERSAMPLING_2X);
    bmp.setIIRFilterCoeff(BMP3_IIR_FILTER_COEFF_3);
    bmp.setOutputDataRate(BMP3_ODR_50_HZ);
    ok &= check("BMP390 read", bmp.performReading());
  }

  pinMode(PIN_LORA_RST, OUTPUT);
  digitalWrite(PIN_LORA_RST, LOW);  delay(10);
  digitalWrite(PIN_LORA_RST, HIGH); delay(10);
  bool loraOk = rf95.init();
  if (loraOk) {
    rf95.setFrequency(915.0);
    rf95.setTxPower(13, false);
    // DIO0 on pin 1 shares the Teensy 4.1 Serial1 TX pad — the hardware
    // interrupt never fires.  Detach RadioHead's broken ISR and poll
    // DIO0 manually in loop() instead.
    detachInterrupt(digitalPinToInterrupt(PIN_LORA_G0));
  }
  ok &= check("RFM95W init", loraOk);

  // SD card init
  bool sdOk = SD.begin(PIN_CS_SD);
  if (sdOk) {
    // Delete old log if it exists, create new one
    if (SD.exists("FLIGHT.CSV")) SD.remove("FLIGHT.CSV");
    log_file = SD.open("FLIGHT.CSV", FILE_WRITE);
    if (log_file) {
      log_file.println("time_ms,state,alt_m,max_alt_m,accel_g,vel_ms,pyro,remote_safe");
      log_file.flush();
      sd_ok = true;
    }
  }
  // SD is optional — show result but do NOT fail preflight without it
  check("SD card", sd_ok);
  if (!sd_ok) Serial.println("     (no card — logging disabled)");

  if (bmpOk) {
    // Warm up — discard first readings so IIR filter settles
    for (int i = 0; i < 20; i++) { bmp.performReading(); delay(50); }

    // Average ground altitude from stable readings
    double sum = 0; int n = 0;
    for (int i = 0; i < 30; i++) {
      if (bmp.performReading()) {
        sum += pressure_to_alt(bmp.pressure);
        n++;
      }
      delay(50);
    }
    if (n > 0) ground_alt = sum / n;
    Serial.printf("     Ground alt = %.2f m\n", ground_alt);
  }

  // Initialize Kalman filter at ground level
  kf.init(0.0f);

  ok &= check("Pyro1 still LOW", digitalRead(PIN_PYRO1_FIRE) == LOW);
  ok &= check("Pyro2 still LOW", digitalRead(PIN_PYRO2_FIRE) == LOW);
  Serial.printf("--- PREFLIGHT %s ---\n\n", ok ? "PASS" : "FAIL");
  return ok;
}

// ---------- Setup ----------
void setup() {
  pyro_safe();

  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_ARM_SW, INPUT_PULLDOWN);   // switch to 3.3V = ARMED, open = SAFE
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_CONT1, INPUT_PULLDOWN);    // disconnected pyro reads 0 (OPEN/RED)
  pinMode(PIN_CONT2, INPUT_PULLDOWN);    // connected pyro+resistor pulls into 500-3800 band (OK/GREEN)
  delay(10);  // let pins settle
  Serial.printf("  CONT_RAW: c1=%d c2=%d (threshold %d-%d)\n",
                analogRead(PIN_CONT1), analogRead(PIN_CONT2),
                CONT_MIN_RAW, CONT_MAX_RAW);
  pinMode(PIN_VBAT_DIV, INPUT);
  analogReadResolution(12);

  for (uint8_t cs : {PIN_CS_ACCEL, PIN_CS_GYRO, PIN_CS_BMP, PIN_CS_LORA, PIN_CS_SD}) {
    pinMode(cs, OUTPUT); digitalWrite(cs, HIGH);
  }

  leds.begin();
  led(LED_PWR, 0x000020); led(LED_ARM, 0); led(LED_P1, 0); led(LED_P2, 0);

  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 2000) {}
  Serial.println("\n=== Phase 2 FLIGHT v4 ===");

  SPI.begin();
  bool pass = preflight();

  if (pass) {
    state = ST_READY;
    led(LED_PWR, 0x002000);
    beep(2000, 80); beep(2500, 80); beep(3000, 120);   // rising = all good
  } else {
    state = ST_FAULT;
    led(LED_PWR, 0x200000);
    beep(400, 300); beep(300, 300); beep(200, 500);     // descending = fail
  }
  pyro_safe();
  prev_arm_sw = (digitalRead(PIN_ARM_SW) == HIGH);
  last_predict_ms = millis();
}

// ---------- Loop (100 Hz) ----------
uint32_t last_tick = 0;

void loop() {
  // Poll DIO0 — replaces the broken hardware interrupt on pin 1
  rf95.poll();

  uint32_t now = millis();
  if (now - last_tick < 10) return;
  last_tick = now;

  service_pyro_timer(now);
  update_status_leds(now);

  // --- Baro: ONE performReading() per loop, use bmp.pressure directly ---
  float raw_baro_alt = isnan(last_baro_alt) ? NAN : last_baro_alt;
  baro_fresh = false;
  if (bmp.performReading()) {
    float a = pressure_to_alt(bmp.pressure) - ground_alt;
    last_baro_alt = a;
    raw_baro_alt = a;
    baro_fresh = true;
  }

  // --- Read accel + gyro ---
  float az_g = 0.0f;
  float accel_g = read_accel_mag_g(az_g);
  read_gyro();
  bool  arm_sw  = digitalRead(PIN_ARM_SW) == HIGH;

  // --- Kalman filter predict + update ---
  float dt = (now - last_predict_ms) / 1000.0f;
  last_predict_ms = now;
  if (kf.initialized && dt > 0.0f && dt < 0.5f) {
    // Vertical accel: subtract 1g gravity (assuming Z-up orientation)
    float accel_vert_ms2 = (az_g - 1.0f) * 9.80665f;
    kf.predict(dt, accel_vert_ms2);
    if (baro_fresh) {
      kf.update(raw_baro_alt);
    }
  }

  // Use Kalman-filtered altitude for flight decisions
  float alt_agl = kf.initialized ? kf.alt : raw_baro_alt;
  float vel_est = kf.initialized ? kf.vel : 0.0f;

  // --- Arm switch edge detection ---
  if (state == ST_READY && !prev_arm_sw && arm_sw) {
    state = ST_ARMED;
    Serial.println(">> ARMED");
    beep(1500, 60); beep(1500, 60); beep(1500, 60);
    // LEDs handled continuously by update_status_leds()
  }
  prev_arm_sw = arm_sw;

  // --- State machine ---
  switch (state) {
    case ST_IDLE:
    case ST_FAULT:
      pyro_safe();
      break;

    case ST_READY: {
      pyro_safe();
      // LEDs now handled continuously by update_status_leds()
      break;
    }

    case ST_ARMED: {
      // LEDs now handled continuously by update_status_leds()
      if (!arm_sw) {
        state = ST_READY;
        Serial.println(">> DISARMED");
        break;
      }
      if (accel_g > LAUNCH_ACCEL_G) {
        if (++launch_streak >= LAUNCH_SAMPLES) {
          state = ST_BOOST;
          t_launch = now;
          max_alt = isnan(alt_agl) ? 0.0f : alt_agl;
          kf.init(max_alt);  // re-init Kalman at launch
          last_predict_ms = now;
          Serial.printf(">> BOOST @ %lu ms, a=%.2f g\n", now, accel_g);
        }
      } else {
        launch_streak = 0;
      }
      break;
    }

    case ST_BOOST:
      if (alt_agl > max_alt) max_alt = alt_agl;
      if (accel_g < BURNOUT_ACCEL_G && (now - t_launch) > 100) {
        if (++burnout_streak >= BURNOUT_SAMPLES) {
          state = ST_COAST;
          t_coast = now;  // BUG FIX: track coast entry time
          Serial.printf(">> COAST @ %lu ms\n", now);
        }
      } else {
        burnout_streak = 0;
      }
      break;

    case ST_COAST: {
      if (alt_agl > max_alt) max_alt = alt_agl;
      // BUG FIX: lockout measured from coast entry, not launch
      bool past_lockout = (now - t_coast) > MIN_COAST_MS;

      if (past_lockout && !isnan(alt_agl)
          && alt_agl < (max_alt - APOGEE_DROP_M)) {
        if (++apogee_streak >= APOGEE_SAMPLES) {
          Serial.printf(">> APOGEE (baro) @ %lu ms, max=%.2f m\n", now, max_alt);
          if (start_pyro_fire()) state = ST_DESCENT;
        }
      } else {
        apogee_streak = 0;
      }

      if (!pyro_fired && (now - t_launch) > APOGEE_BACKUP_MS) {
        Serial.printf(">> APOGEE (timeout) @ %lu ms\n", now);
        if (start_pyro_fire()) state = ST_DESCENT;
      }
      break;
    }

    case ST_DESCENT: {
      if (t_landed_start == 0) {
        t_landed_start = now;
        landed_ref_alt = isnan(alt_agl) ? 0.0f : alt_agl;
      }
      if (!isnan(alt_agl)
          && fabsf(alt_agl - landed_ref_alt) < LANDED_ALT_BAND
          && fabsf(accel_g - 1.0f) < 0.25f) {
        if ((now - t_landed_start) > LANDED_STILL_MS) {
          state = ST_LANDED;
          Serial.printf(">> LANDED @ %lu ms\n", now);
        }
      } else {
        t_landed_start = now;
        landed_ref_alt = isnan(alt_agl) ? 0.0f : alt_agl;
      }
      if ((now - t_launch) > FLIGHT_TIMEOUT_MS) {
        state = ST_LANDED;
        Serial.println(">> LANDED (timeout)");
      }
      break;
    }

    case ST_LANDED:
      pyro_safe();
      // Flush SD card on landing (once)
      static bool landed_logged = false;
      if (!landed_logged && sd_ok && log_file) {
        log_file.flush();
        log_file.close();
        landed_logged = true;
        Serial.println(">> SD card finalized");
      }
      if ((now / 1000) % 3 == 0 && (now % 1000) < 50) beep(3000, 40);
      // LED_ARM still reflects switch state via update_status_leds()
      break;
  }

  // --- Check for incoming commands from ground station ---
  if (rf95.available()) {
    uint8_t rxbuf[32];
    uint8_t rxlen = sizeof(rxbuf);
    if (rf95.recv(rxbuf, &rxlen) && rxlen > 0) {
      rxbuf[rxlen] = '\0';
      Serial.printf("RX CMD: %s\n", (char*)rxbuf);
      if (strncmp((char*)rxbuf, "CMD,SAFE", 8) == 0) {
        remote_safe = true;
        pyro_safe();
        pyro_fired = false;
        Serial.println(">> REMOTE SAFE — pyros disabled");
        beep(800, 200);
        if (state == ST_ARMED) {
          state = ST_READY;
          Serial.println(">> DISARMED (remote)");
        } else if (state == ST_COAST) {
          state = ST_DESCENT;
          Serial.println(">> COAST->DESCENT (remote safe, no pyro fire)");
        }
        led(LED_P1, 0x200020);  // purple = remotely safed
        led(LED_P2, 0x200020);
      }
      if (strncmp((char*)rxbuf, "CMD,PING", 8) == 0) {
        rf95.setModeIdle();
        const char* pong = "PONG";
        rf95.send((uint8_t*)pong, 4);
        Serial.println(">> PING — PONG sent");
        beep(2000, 50);
      }
      if (strncmp((char*)rxbuf, "CMD,BUZZ", 8) == 0) {
        beep(1000, 80); beep(2000, 80); beep(3000, 120);
        Serial.println(">> Buzzer test");
      }
      if (strncmp((char*)rxbuf, "CMD,LED", 7) == 0) {
        for (int i = 0; i < 3; i++) {
          leds.fill(0x202020); leds.show(); delay(100);
          leds.fill(0);        leds.show(); delay(100);
        }
        Serial.println(">> LED test");
      }
      if (strncmp((char*)rxbuf, "CMD,ZEROALT", 11) == 0) {
        double sum = 0; int cnt = 0;
        for (int i = 0; i < 10; i++) {
          if (bmp.performReading()) { sum += pressure_to_alt(bmp.pressure); cnt++; }
          delay(50);
        }
        if (cnt > 0) {
          ground_alt = sum / cnt;
          kf.init(0.0f);
          Serial.printf(">> Zero alt: ground=%.2f m\n", ground_alt);
          beep(2000, 60); beep(2500, 60);
        }
      }
      if (strncmp((char*)rxbuf, "CMD,CALPRES", 11) == 0) {
        // Re-sample ground pressure average over 1 s
        double sum = 0; int cnt = 0;
        for (int i = 0; i < 20; i++) {
          if (bmp.performReading()) { sum += bmp.pressure; cnt++; }
          delay(50);
        }
        if (cnt > 0) {
          ground_alt = pressure_to_alt(sum / cnt);
          kf.init(0.0f);
          Serial.printf(">> Cal pres: ground=%.2f m\n", ground_alt);
          beep(2000, 60); beep(2500, 60);
        }
      }
      if (strncmp((char*)rxbuf, "CMD,ARM", 7) == 0) {
        if (state == ST_READY || state == ST_LANDED || state == ST_DESCENT) {
          remote_safe = false;
          pyro_fired = false;
          pyro_active = false;
          launch_streak = 0;
          burnout_streak = 0;
          apogee_streak = 0;
          t_launch = 0;
          t_coast = 0;
          t_landed_start = 0;
          max_alt = 0.0f;
          kf.init(0.0f);
          // Only go to ARMED if arm switch is on; otherwise clear safe and stay READY
          if (digitalRead(PIN_ARM_SW) == HIGH) {
            state = ST_ARMED;
            Serial.println(">> REMOTE ARM — armed (switch is ON)");
            beep(1500, 60); beep(1500, 60); beep(1500, 60);
            led(LED_ARM, 0x200000);
          } else {
            state = ST_READY;
            Serial.println(">> SAFE CLEARED — flip arm switch to arm");
            beep(1500, 60); beep(2000, 60);
          }
          led(LED_P1, 0); led(LED_P2, 0);
        } else {
          Serial.printf(">> REMOTE ARM REJECTED (state=%d)\n", (int)state);
        }
      }
    }
  }

  // --- Telemetry ---
  // BUG FIX: fast rate (100ms) during flight, slow (1000ms) on ground
  static uint32_t last_tx = 0;
  bool critical = (state == ST_BOOST || state == ST_COAST || state == ST_DESCENT);
  uint32_t tx_interval = critical ? 100 : 1000;
  if (now - last_tx >= tx_interval && state >= ST_READY) {
    last_tx = now;
    char buf[180];
    int n = snprintf(buf, sizeof(buf),
                     "F,%lu,%d,%.1f,%.1f,%.2f,%.1f,%d,%d,%.1f,%d,%d,%.1f,%.1f,%.1f,%.1f,%d,%d",
                     now, (int)state,
                     isnan(alt_agl) ? 0.0f : alt_agl, max_alt,
                     accel_g, vel_est, pyro_fired, remote_safe,
                     read_vbat(),
                     analogRead(PIN_CONT1), analogRead(PIN_CONT2),
                     bmp.temperature,
                     gx_dps, gy_dps, gz_dps,
                     (int)sd_ok, (int)(digitalRead(PIN_ARM_SW) == HIGH));
    rf95.setModeIdle();          // ensure radio is idle before TX
    rf95.send((uint8_t*)buf, n);  // starts TX — do NOT call waitPacketSent()
    // waitPacketSent() would deadlock because poll() can't run while blocked
    Serial.println(buf);
  }

  // --- Log to SD card every tick (100 Hz) ---
  log_telemetry(now, alt_agl, max_alt, accel_g, vel_est);
}
