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

// (Truncated — see local file for full source)
