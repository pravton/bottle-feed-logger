// =============================================================================
// Bottle Feed Logger — ESP32 firmware
//
// Hardware: ESP32 DevKit V1 + 1kg load cell + HX711 + button(s) + SSD1306 OLED
// Logs each feed (start, end, duration, volume) to a Notion database.
//
// Pin map (see hardware/pinout.md):
//   HX711 DT  -> GPIO 16
//   HX711 SCK -> GPIO 17
//   Button    -> GPIO 25  (to GND, uses internal pull-up)
//   Tare/Cal  -> GPIO 26  (to GND, uses internal pull-up) [optional]
//   OLED SDA  -> GPIO 21
//   OLED SCL  -> GPIO 22
//
// Volume trick: consumed = startWeight - endWeight. The bottle is in both
// readings, so its weight cancels — no per-bottle tare needed.
//
// NOT a medical device. See docs/safety-notes.md.
// =============================================================================

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <HX711.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <time.h>

#include "config.h"

#if ENABLE_TELEGRAM
  #include <UniversalTelegramBot.h>
#endif

// -----------------------------------------------------------------------------
// Pins
// -----------------------------------------------------------------------------
#define HX711_DT        16
#define HX711_SCK       17
#define BUTTON_PIN      25
#define TARE_PIN        26
#define I2C_SDA         21
#define I2C_SCL         22

// -----------------------------------------------------------------------------
// OLED
// -----------------------------------------------------------------------------
#define OLED_W   128
#define OLED_H   64
#define OLED_ADDR 0x3C
Adafruit_SSD1306 display(OLED_W, OLED_H, &Wire, -1);

// -----------------------------------------------------------------------------
// Globals
// -----------------------------------------------------------------------------
HX711       scale;
Preferences prefs;

WiFiClientSecure secured;
#if ENABLE_TELEGRAM
  UniversalTelegramBot bot(BOT_TOKEN, secured);
#endif

float calibrationFactor = DEFAULT_CALIBRATION_FACTOR;

enum FeedState { IDLE, FEEDING };
FeedState   state         = IDLE;
float       startWeight   = 0.0f;
time_t      startEpoch    = 0;

// last-feed display cache
float       lastVolume    = 0.0f;
int         lastDuration  = 0;
bool        haveLastFeed  = false;

unsigned long lastDisplay   = 0;
unsigned long lastWifiCheck = 0;

// button debounce
unsigned long lastBtnMs  = 0;
unsigned long lastTareMs = 0;
const unsigned long DEBOUNCE_MS = 250;

// -----------------------------------------------------------------------------
// Forward declarations
// -----------------------------------------------------------------------------
time_t now();
float  readGrams();
void   setupWifi();
void   ensureWifi();
bool   syncTime();
bool   timeIsValid();
String isoTimestamp(time_t t);
void   doCalibration();
void   handleFeedButton();
void   handleTareButton();
void   logFeed(float volumeMl, time_t s, time_t e);
bool   postToNotion(float volumeMl, int durationMin, time_t s, time_t e);
void   drawIdle(float g);
void   drawFeeding(float elapsedMin);
void   drawMessage(const String &l1, const String &l2);

// =============================================================================
// SETUP
// =============================================================================
void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println(F("\n[Feed Logger] Booting..."));

    pinMode(BUTTON_PIN, INPUT_PULLUP);
    pinMode(TARE_PIN,   INPUT_PULLUP);

    // ---- OLED ----
    Wire.begin(I2C_SDA, I2C_SCL);
    if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
        display.begin(SSD1306_SWITCHCAPVCC, 0x3D);
    }
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    drawMessage("Feed Logger", "booting...");

    // ---- HX711 ----
    scale.begin(HX711_DT, HX711_SCK);
    unsigned long t0 = millis();
    while (!scale.is_ready() && millis() - t0 < 3000) delay(50);
    if (scale.is_ready()) Serial.println(F("HX711 ready"));
    else                  Serial.println(F("HX711 NOT responding — check wiring"));

    // ---- Load saved calibration ----
    prefs.begin("feedlogger", false);
    calibrationFactor = prefs.getFloat("calFactor", DEFAULT_CALIBRATION_FACTOR);
    long savedOffset  = prefs.getLong("tareOffset", 0);
    Serial.printf("Calibration factor: %.3f, tare offset: %ld\n", calibrationFactor, savedOffset);
    scale.set_scale(calibrationFactor);
    if (savedOffset != 0) scale.set_offset(savedOffset);
    else                  scale.tare();

    // ---- Calibration mode if tare button held at boot ----
    if (digitalRead(TARE_PIN) == LOW) {
        doCalibration();
    }

    // ---- Wi-Fi ----
    setupWifi();
    secured.setInsecure();   // v1: skip cert validation (harden with setCACert for production)

    // ---- Time ----
    if (syncTime()) Serial.println(F("NTP time synced"));
    else            Serial.println(F("NTP sync failed — will retry"));

    Serial.println(F("[Feed Logger] Ready."));
}

// =============================================================================
// LOOP
// =============================================================================
void loop() {
    // Wi-Fi health
    if (millis() - lastWifiCheck > 30000) {
        lastWifiCheck = millis();
        ensureWifi();
    }

    // Buttons
    handleFeedButton();
    handleTareButton();

    // Display refresh (twice per second)
    if (millis() - lastDisplay > 500) {
        lastDisplay = millis();
        if (state == IDLE) {
            drawIdle(readGrams());
        } else {
            float elapsedMin = (now() - startEpoch) / 60.0f;
            drawFeeding(elapsedMin);
        }
    }
}

// helper to get epoch now()
time_t now() { time_t t; time(&t); return t; }

// =============================================================================
// Weight
// =============================================================================
float readGrams() {
    if (!scale.is_ready()) return NAN;
    return scale.get_units(SAMPLES_PER_READING);
}

// =============================================================================
// Buttons
// =============================================================================
void handleFeedButton() {
    if (digitalRead(BUTTON_PIN) == LOW && millis() - lastBtnMs > DEBOUNCE_MS) {
        lastBtnMs = millis();

        if (state == IDLE) {
            // Start a feed
            if (!timeIsValid()) { drawMessage("No time yet", "wait for NTP"); delay(1200); return; }
            startWeight = readGrams();
            startEpoch  = now();
            state = FEEDING;
            Serial.printf("Feed START: %.1f g at %s\n", startWeight, isoTimestamp(startEpoch).c_str());
        } else {
            // End a feed
            float endWeight = readGrams();
            time_t endEpoch = now();
            float volume = startWeight - endWeight;     // bottle cancels out
            int   durMin = (int)round((endEpoch - startEpoch) / 60.0);

            state = IDLE;

            if (volume < MIN_FEED_ML || volume > MAX_FEED_ML) {
                Serial.printf("Feed IGNORED: %.1f mL (outside %.0f-%.0f)\n", volume, MIN_FEED_ML, MAX_FEED_ML);
                drawMessage("Ignored", String(volume,0) + " mL?");
                delay(1500);
                return;
            }

            Serial.printf("Feed END: %.1f g -> consumed %.1f mL over %d min\n", endWeight, volume, durMin);
            logFeed(volume, startEpoch, endEpoch);
        }
    }
}

void handleTareButton() {
    if (digitalRead(TARE_PIN) == LOW && millis() - lastTareMs > 600) {
        lastTareMs = millis();
        drawMessage("Taring...", "");
        scale.tare();
        prefs.putLong("tareOffset", scale.get_offset());
        Serial.println(F("Tared."));
        delay(600);
    }
}

// =============================================================================
// Calibration (guided, saves to flash)
// =============================================================================
void doCalibration() {
    Serial.println(F("=== CALIBRATION ==="));
    drawMessage("Calibration", "remove all weight");
    delay(2500);

    scale.set_scale();      // reset scale factor to 1
    scale.tare();           // zero with empty platform
    prefs.putLong("tareOffset", scale.get_offset());
    Serial.println(F("Tared empty."));

    drawMessage("Place weight:", String(CALIBRATION_KNOWN_WEIGHT_G,0) + " g");
    Serial.printf("Place %.0f g now...\n", CALIBRATION_KNOWN_WEIGHT_G);
    delay(6000);            // give the user time to place the known weight

    long raw = scale.get_value(20);                         // averaged raw reading
    calibrationFactor = raw / CALIBRATION_KNOWN_WEIGHT_G;    // counts per gram
    scale.set_scale(calibrationFactor);
    prefs.putFloat("calFactor", calibrationFactor);

    Serial.printf("New calibration factor: %.3f\n", calibrationFactor);
    drawMessage("Calibrated!", String(calibrationFactor,1));
    delay(2500);
    drawMessage("Remove weight", "");
    delay(2500);
}

// =============================================================================
// Logging
// =============================================================================
void logFeed(float volumeMl, time_t s, time_t e) {
    drawMessage("Logging...", String(volumeMl,0) + " mL");
    int durMin = (int)round((e - s) / 60.0);

    bool ok = postToNotion(volumeMl, durMin, s, e);

    if (ok) {
        lastVolume   = volumeMl;
        lastDuration = durMin;
        haveLastFeed = true;
        drawMessage("Fed " + String(volumeMl,0) + " mL", String(durMin) + " min  OK");
#if ENABLE_TELEGRAM
        String msg = "🍼 Fed " + String(volumeMl,0) + " mL in " + String(durMin) + " min";
        bot.sendMessage(CHAT_ID, msg, "");
#endif
    } else {
        drawMessage("Notion FAILED", "see serial");
    }
    delay(2000);
}

bool postToNotion(float volumeMl, int durationMin, time_t s, time_t e) {
    if (WiFi.status() != WL_CONNECTED) { Serial.println(F("No WiFi")); return false; }

    // Build JSON body
    JsonDocument doc;
    doc["parent"]["database_id"] = NOTION_DB_ID;
    JsonObject props = doc["properties"].to<JsonObject>();

    // Title
    JsonArray title = props[PROP_TITLE]["title"].to<JsonArray>();
    title[0]["text"]["content"] = "Feed " + String(volumeMl, 0) + " mL";

    // Start / End dates
    props[PROP_START]["date"]["start"] = isoTimestamp(s);
    props[PROP_END]["date"]["start"]   = isoTimestamp(e);

    // Numbers
    props[PROP_DURATION]["number"] = durationMin;
    props[PROP_VOLUME]["number"]   = (int)round(volumeMl);

    // Notes (rich_text)
    JsonArray notes = props[PROP_NOTES]["rich_text"].to<JsonArray>();
    notes[0]["text"]["content"] = "Auto-logged by Feed Logger";

    String body;
    serializeJson(doc, body);

    HTTPClient https;
    https.begin(secured, "https://api.notion.com/v1/pages");
    https.addHeader("Authorization", String("Bearer ") + NOTION_TOKEN);
    https.addHeader("Content-Type", "application/json");
    https.addHeader("Notion-Version", NOTION_VERSION);

    int code = https.POST(body);
    String resp = https.getString();
    https.end();

    Serial.printf("Notion HTTP %d\n", code);
    if (code != 200) Serial.println(resp);
    return code == 200;
}

// =============================================================================
// Time
// =============================================================================
bool syncTime() {
    configTime(GMT_OFFSET_SEC, DST_OFFSET_SEC, NTP_SERVER);
    unsigned long t0 = millis();
    while (!timeIsValid() && millis() - t0 < 10000) delay(250);
    return timeIsValid();
}

bool timeIsValid() {
    time_t t = now();
    struct tm tmv;
    localtime_r(&t, &tmv);
    return (tmv.tm_year + 1900) >= 2025;
}

String isoTimestamp(time_t t) {
    struct tm tmv;
    localtime_r(&t, &tmv);
    // Offset in ±HH:MM
    long off = GMT_OFFSET_SEC + (tmv.tm_isdst > 0 ? DST_OFFSET_SEC : 0);
    char sign = off < 0 ? '-' : '+';
    long aoff = labs(off);
    char buf[40];
    snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d%c%02ld:%02ld",
             tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday,
             tmv.tm_hour, tmv.tm_min, tmv.tm_sec,
             sign, aoff / 3600, (aoff % 3600) / 60);
    return String(buf);
}

// =============================================================================
// Wi-Fi
// =============================================================================
void setupWifi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    drawMessage("WiFi", "connecting...");
    unsigned long t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) { delay(400); Serial.print("."); }
    if (WiFi.status() == WL_CONNECTED)
        Serial.printf("\nWiFi OK %s\n", WiFi.localIP().toString().c_str());
    else
        Serial.println(F("\nWiFi FAILED — retrying in loop"));
}

void ensureWifi() {
    if (WiFi.status() == WL_CONNECTED) return;
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// =============================================================================
// Display helpers
// =============================================================================
void drawIdle(float g) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println(F("Ready - tap to start"));

    display.setTextSize(2);
    display.setCursor(0, 14);
    if (isnan(g)) display.println("-- g");
    else          display.printf("%.0f g\n", g);

    display.setTextSize(1);
    display.setCursor(0, 40);
    if (haveLastFeed) {
        display.printf("Last: %.0f mL / %d min\n", lastVolume, lastDuration);
    } else {
        display.println("Last: --");
    }
    display.setCursor(0, 56);
    display.print(WiFi.status() == WL_CONNECTED ? "WiFi OK" : "WiFi ...");
    display.display();
}

void drawFeeding(float elapsedMin) {
    display.clearDisplay();
    display.setTextSize(2);
    display.setCursor(0, 0);
    display.println(F("Feeding"));
    display.setTextSize(1);
    display.setCursor(0, 22);
    display.printf("Elapsed: %.0f min\n", elapsedMin);
    display.setCursor(0, 36);
    display.printf("Start: %.0f g\n", startWeight);
    display.setCursor(0, 52);
    display.println(F("Tap again to finish"));
    display.display();
}

void drawMessage(const String &l1, const String &l2) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(0, 8);
    display.println(l1);
    display.setCursor(0, 24);
    display.println(l2);
    display.display();
}
