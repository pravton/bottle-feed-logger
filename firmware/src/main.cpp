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
#include <WiFiManager.h>
#include <ArduinoOTA.h>
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
time_t      lastFeedEnd   = 0;
bool        haveLastFeed  = false;

unsigned long lastDisplay   = 0;
unsigned long lastWifiCheck = 0;

// held/smoothed weight for a steady display (survives brief HX711 dropouts)
float         displayGrams    = NAN;
unsigned long lastGoodReadMs  = 0;
const unsigned long STALE_MS  = 2000;   // show "--" only after this long with no read

// button debounce
unsigned long lastBtnMs  = 0;
unsigned long lastTareMs = 0;
const unsigned long DEBOUNCE_MS = 250;

// -----------------------------------------------------------------------------
// Forward declarations
// -----------------------------------------------------------------------------
time_t now();
float  readGrams();
void   setupWifi(bool forcePortal);
void   runWifiPortal(bool onDemand);
String wifiStatusStr(wl_status_t s);
void   ensureWifi();
void   setupOTA();
bool   syncTime();
bool   timeIsValid();
String isoTimestamp(time_t t);
String clockTime(time_t t);
void   drawWifiIcon(bool connected);
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

    // ---- Restore last feed from flash so the display survives a reboot ----
    lastFeedEnd  = (time_t)prefs.getLong("lastEnd", 0);
    lastVolume   = prefs.getFloat("lastVol", 0.0f);
    lastDuration = prefs.getInt("lastDur", 0);
    haveLastFeed = (lastFeedEnd != 0);
    if (haveLastFeed)
        Serial.printf("Restored last feed: %.0f mL, %d min, ended epoch %ld\n",
                      lastVolume, lastDuration, (long)lastFeedEnd);

    // ---- Calibration mode if tare button held at boot ----
    if (digitalRead(TARE_PIN) == LOW) {
        doCalibration();
    }

    // ---- Wi-Fi ----
    // Hold the FEED button (D25) at boot to force the setup portal even if a
    // network is already saved (use this to switch networks at a new place).
    bool forcePortal = (digitalRead(BUTTON_PIN) == LOW);
    if (forcePortal) Serial.println(F("FEED held at boot -> forcing WiFi portal"));
    setupWifi(forcePortal);
    secured.setInsecure();   // v1: skip cert validation (harden with setCACert for production)

    // ---- OTA (Wi-Fi firmware updates, no cable needed after this flash) ----
    setupOTA();

    // ---- Time ----
    if (syncTime()) Serial.println(F("NTP time synced"));
    else            Serial.println(F("NTP sync failed — will retry"));

    Serial.println(F("[Feed Logger] Ready."));
}

// =============================================================================
// LOOP
// =============================================================================
void loop() {
    // Service OTA so a Wi-Fi firmware push can interrupt normal operation.
    ArduinoOTA.handle();

    // Wi-Fi health
    if (millis() - lastWifiCheck > 30000) {
        lastWifiCheck = millis();
        ensureWifi();
        setupOTA();   // start OTA if Wi-Fi came up after boot (no-op once started)
        // Re-kick NTP if Wi-Fi is up but time never synced (e.g. Wi-Fi came up
        // after boot). configTime() is non-blocking; SNTP fills time in the
        // background. Without this, timeIsValid() stays false and feeds are
        // blocked until a reboot.
        if (WiFi.status() == WL_CONNECTED && !timeIsValid()) {
            configTime(GMT_OFFSET_SEC, DST_OFFSET_SEC, NTP_SERVER);
        }
    }

    // Buttons
    handleFeedButton();
    handleTareButton();

    // Sample the scale continuously and HOLD the last good reading. The HX711
    // occasionally misses a cycle on breadboard wiring; rather than blanking the
    // display to "-- g" on every hiccup, we keep the last valid weight and only
    // give up if the sensor is truly gone for STALE_MS. Light smoothing (EMA)
    // keeps the displayed number steady.
    if (scale.is_ready()) {
        long raw = scale.read();
        float g = (raw - scale.get_offset()) / calibrationFactor;
        if (isnan(displayGrams)) displayGrams = g;            // first reading
        else displayGrams = displayGrams * 0.8f + g * 0.2f;   // EMA smoothing
        lastGoodReadMs = millis();
    }

    // Display refresh (twice per second)
    if (millis() - lastDisplay > 500) {
        lastDisplay = millis();
        if (state == IDLE) {
            bool stale = (millis() - lastGoodReadMs) > STALE_MS;
            drawIdle(stale ? NAN : displayGrams);
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

// Robust read for capturing a feed weight: the HX711 can miss a cycle on
// breadboard wiring, and a single nan there poisons the logged volume
// ((int)nan becomes 2147483647). Retry for up to ~1s to get a real average;
// fall back to the smoothed display value rather than ever returning nan.
float readGramsBlocking() {
    unsigned long t0 = millis();
    while (millis() - t0 < 1000) {
        if (scale.is_ready()) return scale.get_units(SAMPLES_PER_READING);
        delay(20);
    }
    return displayGrams;   // last smoothed value (may be nan only if never read)
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
            startWeight = readGramsBlocking();
            if (isnan(startWeight)) { drawMessage("Scale error", "no reading"); delay(1500); return; }
            startEpoch  = now();
            state = FEEDING;
            Serial.printf("Feed START: %.1f g at %s\n", startWeight, isoTimestamp(startEpoch).c_str());
        } else {
            // End a feed
            float endWeight = readGramsBlocking();
            time_t endEpoch = now();
            float volume = startWeight - endWeight;     // bottle cancels out
            int   durMin = (int)round((endEpoch - startEpoch) / 60.0);

            state = IDLE;

            // Reject bad reads first: a nan slips past the range check below
            // (every comparison with nan is false) and logs as 2147483647.
            if (isnan(volume)) {
                Serial.println("Feed IGNORED: scale read failed (nan)");
                drawMessage("Scale error", "try again");
                delay(1500);
                return;
            }

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
        lastFeedEnd  = e;
        haveLastFeed = true;
        // Persist to flash so "Last fed" survives a power cycle / reset.
        prefs.putLong("lastEnd", (long)e);
        prefs.putFloat("lastVol", volumeMl);
        prefs.putInt("lastDur", durMin);
        drawMessage("Fed " + String(volumeMl,0) + " mL", String(durMin) + " min  OK");
#if ENABLE_TELEGRAM
        // Nicely formatted multi-line summary (HTML parse mode for bold).
        String msg = "🍼 <b>Feed logged</b>\n"
                   + String("\n") + "🥛 Volume: <b>" + String((int)round(volumeMl)) + " mL</b>\n"
                   + "⏱ Duration: <b>" + String(durMin) + " min</b>\n"
                   + "🟢 Started: " + clockTime(s) + "\n"
                   + "🔴 Ended: " + clockTime(e);
        bot.sendMessage(CHAT_ID, msg, "HTML");
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

    // Notes (rich_text) — a clear, human-readable summary of the feed.
    String summary = "🍼 Fed " + String((int)round(volumeMl)) + " mL  •  "
                   + "⏱ " + String(durationMin) + " min  •  "
                   + "🟢 Started " + clockTime(s) + "  •  "
                   + "🔴 Ended " + clockTime(e);
    JsonArray notes = props[PROP_NOTES]["rich_text"].to<JsonArray>();
    notes[0]["text"]["content"] = summary;

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
    if (code != 200) Serial.println(resp);   // print Notion's error message only on failure
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

// Short local clock like "2:42 AM" / "11:05 PM" for the display and messages.
String clockTime(time_t t) {
    struct tm tmv;
    localtime_r(&t, &tmv);
    int h = tmv.tm_hour;
    const char *ap = h < 12 ? "AM" : "PM";
    int h12 = h % 12; if (h12 == 0) h12 = 12;
    char buf[14];
    snprintf(buf, sizeof(buf), "%d:%02d %s", h12, tmv.tm_min, ap);
    return String(buf);
}

// =============================================================================
// Wi-Fi  (managed by WiFiManager — no re-flash needed to change networks)
//
// Behaviour:
//   - Remembers the last network it connected to (WiFiManager stores creds in
//     its own NVS), so at a known place it just reconnects.
//   - If it can't connect, it opens a setup hotspot "BottleFeedLogger-Setup".
//     Join it from a phone/laptop; a page lets you pick a network + password.
//   - Force the portal on demand by holding the FEED button (D25) at boot.
//   - WiFiManager owns the saved credentials (in its own NVS namespace); config.h
//     WIFI_SSID/WIFI_PASSWORD are no longer used.
// =============================================================================
const char *AP_NAME = "BottleFeedLogger-Setup";

// Human-readable reason for a Wi-Fi connect failure (don't assume it's auth).
String wifiStatusStr(wl_status_t s) {
    switch (s) {
        case WL_NO_SSID_AVAIL: return "network not found";
        case WL_CONNECT_FAILED: return "connect failed";   // generic: bad pw, handshake, AP unreachable, ...
        case WL_CONNECTION_LOST: return "connection lost";
        case WL_DISCONNECTED: return "no connection";
        case WL_IDLE_STATUS: return "idle/timeout";
        default: return String("status ") + (int)s;
    }
}

// Bring the portal up and block until the user configures Wi-Fi (or times out).
void runWifiPortal(bool onDemand) {
    WiFiManager wm;
    // On-demand (button-forced) portal: stay up until configured, no timeout, so
    // the hotspot doesn't vanish mid-setup. Auto (boot) portal: give up after 5
    // min and continue booting unconfigured (the device keeps running offline;
    // hold FEED at the next reset to open the portal again).
    wm.setConfigPortalTimeout(onDemand ? 0 : 300);
    // Fail over to the setup hotspot quickly when a saved network isn't around
    // (this device moves between locations). ~1 try x ~12s instead of ~40s.
    wm.setConnectTimeout(12);
    wm.setConnectRetries(1);
    // Only break-after-config on the AUTO (boot) portal, so a failed attempt
    // returns control and the device keeps running. For the ON-DEMAND portal we
    // leave it off so a typoed password keeps the portal up to retry instead of
    // closing it (which would force a reboot + FEED-hold to try again).
    wm.setBreakAfterConfig(!onDemand);

    // Show "Connecting..." the instant the form is submitted, BEFORE the blocking
    // connect (~up to 13s), so the OLED doesn't sit on the setup screen. Use the
    // public getWiFiSSID(false) — the non-persistent (in-RAM) value, which holds
    // the just-submitted network. (getWiFiSSID(true) returns the OLD saved value,
    // which is why the display previously showed a stale name.) Fired by
    // setPreSaveConfigCallback, which runs in the WiFi-save handler before connect.
    wm.setPreSaveConfigCallback([&wm]() {
        String ssid = wm.getWiFiSSID(false);   // newly-entered SSID (in-RAM, not saved)
        Serial.printf("Portal submit -> connecting to \"%s\"...\n", ssid.c_str());
        drawMessage("Connecting to", ssid.length() ? ssid : String("..."));
    });

    drawMessage("WiFi setup", String("Join: ") + AP_NAME);
    Serial.printf("Opening config portal AP \"%s\"...\n", AP_NAME);

    bool ok = onDemand ? wm.startConfigPortal(AP_NAME)   // forced: always show portal
                       : wm.autoConnect(AP_NAME);        // auto: portal only if needed

    // WiFi.SSID() reflects the network actually used (unlike the saved getter).
    String usedSsid = WiFi.SSID();

    if (ok) {
        Serial.printf("WiFi OK %s on \"%s\"\n",
                      WiFi.localIP().toString().c_str(), usedSsid.c_str());
        // Line 1: which network; line 2: the IP it got.
        drawMessage(usedSsid.length() ? usedSsid : String("WiFi connected"),
                    WiFi.localIP().toString());
    } else {
        // Failure can be wrong password, network not found, portal timeout,
        // etc. — report the actual WiFi status rather than assuming a cause.
        String why = wifiStatusStr(WiFi.status());
        Serial.printf("WiFi FAILED: SSID=\"%s\" status=%s\n", usedSsid.c_str(), why.c_str());
        // Line 1: which network failed (if known); line 2: the reason.
        drawMessage(usedSsid.length() ? ("WiFi: " + usedSsid) : String("WiFi failed"), why);
    }
    delay(3000);
}

void setupWifi(bool forcePortal) {
    WiFi.mode(WIFI_STA);
    // WiFiManager owns the credentials: autoConnect() reconnects to the last
    // saved network and only opens the portal if that fails. We deliberately do
    // NOT WiFi.begin() with config.h creds here — doing so overwrote the saved
    // network on every boot, so a portal-configured network was never remembered.
    runWifiPortal(forcePortal);
}

void ensureWifi() {
    if (WiFi.status() == WL_CONNECTED) return;
    // Let WiFiManager's stored credentials reconnect; don't block the loop.
    WiFi.reconnect();
}

// Enable Over-The-Air updates: once this firmware is running, future builds can
// be pushed over Wi-Fi (PlatformIO: upload_protocol = espota) with no cable.
// The device appears as "bottle-feed-logger" on the network. Safe to call
// repeatedly: it only starts once, and only after Wi-Fi is up (so it also works
// when Wi-Fi connects after boot, called from the loop's health check).
void setupOTA() {
    static bool otaStarted = false;
    if (otaStarted || WiFi.status() != WL_CONNECTED) return;

    ArduinoOTA.setHostname("bottle-feed-logger");
    // Require a password if OTA_PASSWORD is set in config.h. Without it, anyone on
    // the LAN could push firmware — strongly recommended to set one.
#ifdef OTA_PASSWORD
    ArduinoOTA.setPassword(OTA_PASSWORD);
#else
    Serial.println(F("WARNING: OTA has no password (set OTA_PASSWORD in config.h)"));
#endif
    ArduinoOTA.onStart([]() { drawMessage("OTA update", "receiving..."); });
    ArduinoOTA.onEnd([]()   { drawMessage("OTA update", "done, reboot"); });
    ArduinoOTA.onError([](ota_error_t e) { drawMessage("OTA failed", String("err ") + e); });
    ArduinoOTA.begin();
    otaStarted = true;
    Serial.println(F("OTA ready: bottle-feed-logger"));
}

// =============================================================================
// Display helpers
// =============================================================================
// Small Wi-Fi indicator in the top-right corner. Three solid ascending signal
// bars when connected; when disconnected, the bars are replaced by a small "x"
// so "no signal" reads at a glance instead of faint hollow bars.
void drawWifiIcon(bool connected) {
    const int x = 113, baseY = 9;   // bottom-right anchor
    if (connected) {
        for (int i = 0; i < 3; i++) {
            int bx = x + i * 5;
            int h  = 3 + i * 3;     // 3, 6, 9 px tall
            display.fillRect(bx, baseY - h, 3, h, SSD1306_WHITE);
        }
    } else {
        // small X over the icon footprint = no connection
        int x0 = x, y0 = baseY - 8, x1 = x + 8, y1 = baseY;
        display.drawLine(x0, y0, x1, y1, SSD1306_WHITE);
        display.drawLine(x0, y1, x1, y0, SSD1306_WHITE);
    }
}

void drawIdle(float g) {
    display.clearDisplay();

    display.setTextSize(1);
    display.setCursor(0, 0);
    display.print(F("Ready - tap"));
    drawWifiIcon(WiFi.status() == WL_CONNECTED);

    display.setTextSize(2);
    display.setCursor(0, 16);
    if (isnan(g)) {
        display.println("-- g");
    } else {
        // The scale can't hold negative mass; clamp so we never show -5 or "-0".
        // (Small negatives are just drift/noise around an empty platform.)
        float shown = g < 0.0f ? 0.0f : g;
        display.printf("%.0f g\n", shown);
    }

    display.setTextSize(1);
    if (haveLastFeed) {
        display.setCursor(0, 40);
        display.printf("Last: %.0f mL / %d min\n", lastVolume, lastDuration);
        display.setCursor(0, 52);
        display.printf("Fed at %s\n", clockTime(lastFeedEnd).c_str());
    } else {
        display.setCursor(0, 46);
        display.println(F("Last: no feeds yet"));
    }
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
