// =============================================================================
// Bottle Feed Logger: ESP32 firmware
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
// readings, so its weight cancels; no per-bottle tare needed.
//
// NOT a medical device. See docs/safety-notes.md.
// =============================================================================

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <ArduinoOTA.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <esp_wifi.h>
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
// Tunables (override in config.h if you want; sensible defaults otherwise)
// -----------------------------------------------------------------------------
// How many recent raw HX711 samples to median-filter for the live display. A
// median ignores isolated spikes entirely (one bad read can't move it), which
// is the whole point: the HX711 glitches on long/loose load-cell wiring and a
// single spike used to throw the number by hundreds of grams.
#ifndef SCALE_MEDIAN_SAMPLES
  #define SCALE_MEDIAN_SAMPLES 7
#endif
// Bound it: 0 would be a modulo-by-zero in the ring buffer, and a huge value
// would overflow the per-loop stack array `long tmp[SCALE_MEDIAN_SAMPLES]` (and
// must stay within medianRawBlocking's 31-sample buffer).
static_assert(SCALE_MEDIAN_SAMPLES >= 3 && SCALE_MEDIAN_SAMPLES <= 31,
              "SCALE_MEDIAN_SAMPLES must be between 3 and 31");
// Considered "stable" when the spread (max-min) across the median window is
// within this many grams. Tare / calibration / feed-capture wait for stability.
#ifndef SCALE_STABLE_SPREAD_G
  #define SCALE_STABLE_SPREAD_G 2.0f
#endif

// Button gesture hold times (ms).
#define CALIB_HOLD_MS    3000   // hold FEED + TARE together this long -> calibrate
#define RESTART_HOLD_MS  4000   // hold TARE alone this long -> restart

// Calibration "weight present" threshold, in raw HX711 counts (sign-independent).
// The placed reference weight must move the reading at least this far from the
// tared zero before we measure. It's a raw-count floor (not grams) chosen to sit
// well above sensor noise (~hundreds of counts) yet below a real weight on a
// typical cell. Lower it if calibrating with a very light reference or a
// low-sensitivity cell; raise it if noise ever trips a false "settled".
#ifndef CAL_MIN_LOAD_COUNTS
  #define CAL_MIN_LOAD_COUNTS 3000
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
WebServer   server(80);

WiFiClientSecure secured;
#if ENABLE_TELEGRAM
  UniversalTelegramBot bot(BOT_TOKEN, secured);
#endif

float calibrationFactor = DEFAULT_CALIBRATION_FACTOR;
float calKnownWeight    = CALIBRATION_KNOWN_WEIGHT_G;   // last-used reference weight (NVS)

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

// median filter + stability (see sampleScale)
long          rawBuf[SCALE_MEDIAN_SAMPLES];
int           rawCount = 0;
int           rawHead  = 0;
long          lastMedianRaw = 0;        // most recent median raw count (diagnostics)
bool          scaleStable  = false;     // reading settled within SCALE_STABLE_SPREAD_G

// button state machine (tap vs hold; see handleButtons)
bool          feedPrev = false, tarePrev = false;
unsigned long feedDownMs = 0, tareDownMs = 0, bothDownMs = 0;
bool          feedConsumed = false, tareConsumed = false;  // press already used by a hold-gesture
bool          calibFired = false, restartFired = false;
unsigned long lastFeedActMs = 0, lastTareActMs = 0;
bool          gestureHintActive = false;  // a hold countdown owns the OLED right now
const unsigned long DEBOUNCE_MS = 250;

// web-requested restart, deferred so the HTTP response flushes first
unsigned long pendingRestartMs = 0;

// -----------------------------------------------------------------------------
// Forward declarations
// -----------------------------------------------------------------------------
time_t now();
void   setupWifi(bool forcePortal);
void   runWifiPortal(bool onDemand);
String wifiStatusStr(wl_status_t s);
void   ensureWifi();
void   setupOTA();
void   setupWeb();
bool   syncTime();
bool   timeIsValid();
String isoTimestamp(time_t t);
String clockTime(time_t t);
void   drawWifiIcon(bool connected);
// scale sampling / calibration
bool   readRawValid(long &out);
long   medianOf(long *arr, int n);
void   sampleScale();
long   medianRawBlocking(int n, unsigned long timeoutMs);
float  rawToGrams(long raw);
float  captureGrams();
void   tareRobust();
bool   applyCalibration(float knownG);
void   clearCalibration();
bool   waitStable(unsigned long timeoutMs);
bool   waitStableLoaded(unsigned long timeoutMs, long minDeltaCounts);
void   doCalibration();
void   doRestart();
// buttons
void   handleButtons();
void   onFeedTap();
void   onTareTap();
void   forceRedraw();
void   logFeed(float volumeMl, time_t s, time_t e);
bool   postToNotion(float volumeMl, int durationMin, time_t s, time_t e);
void   drawIdle(float g);
void   drawFeeding(float elapsedMin);
void   drawMessage(const String &l1, const String &l2);
// boot / connection UI
void   centerText(const String &s, int y);
void   drawBottle(int cx, int topY, int fillPct);
void   drawSpinner(int cx, int cy, int r, int frame);
void   drawWifiArcs(int cx, int dotY);
void   drawBootSplash();
void   drawConnecting(const String &ssid, int frame);
void   drawConnected(const String &ssid, const String &ip);
void   drawPortalInfo(const String &ap);
String savedStaSsid();
bool   connectSavedAnimated(unsigned long timeoutMs);

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
    drawBootSplash();

    // ---- HX711 ----
    scale.begin(HX711_DT, HX711_SCK);
    unsigned long t0 = millis();
    while (!scale.is_ready() && millis() - t0 < 3000) delay(50);
    if (scale.is_ready()) Serial.println(F("HX711 ready"));
    else                  Serial.println(F("HX711 NOT responding: check wiring"));

    // ---- Load saved calibration ----
    prefs.begin("feedlogger", false);
    calibrationFactor = prefs.getFloat("calFactor", DEFAULT_CALIBRATION_FACTOR);
    calKnownWeight    = prefs.getFloat("knownG", CALIBRATION_KNOWN_WEIGHT_G);
    long savedOffset  = prefs.getLong("tareOffset", 0);
    // The factor is SIGNED (negative for a cell that reads down under load), so
    // validate its MAGNITUDE, not its sign. A zero/NaN/out-of-range value would
    // make every reading inf/garbage; fall back to the compiled default then.
    // (A positive-only check here would silently wipe a valid negative calibration
    // on every reboot -- the same range applyCalibration() accepts.)
    if (isnan(calibrationFactor) ||
        fabsf(calibrationFactor) < 1.0f || fabsf(calibrationFactor) > 100000.0f)
        calibrationFactor = DEFAULT_CALIBRATION_FACTOR;
    // Same idea for the reference weight: a NaN/out-of-range value here would
    // show up as a broken "Set weight: nan g" screen and an invalid-JSON
    // /status response (knownG:nan), so clamp it to the same range the
    // on-device stepper (constrain(10, 2000)) already enforces.
    if (isnan(calKnownWeight) || calKnownWeight < 10.0f || calKnownWeight > 2000.0f)
        calKnownWeight = CALIBRATION_KNOWN_WEIGHT_G;
    Serial.printf("Calibration factor: %.3f, known weight: %.0f g, tare offset: %ld\n",
                  calibrationFactor, calKnownWeight, savedOffset);
    scale.set_scale(calibrationFactor);
    if (savedOffset != 0) scale.set_offset(savedOffset);
    else                  tareRobust();   // median tare (a stray spike can't poison the zero)

    // ---- Restore last feed from flash so the display survives a reboot ----
    lastFeedEnd  = (time_t)prefs.getLong("lastEnd", 0);
    lastVolume   = prefs.getFloat("lastVol", 0.0f);
    lastDuration = prefs.getInt("lastDur", 0);
    haveLastFeed = (lastFeedEnd != 0);
    if (haveLastFeed)
        Serial.printf("Restored last feed: %.0f mL, %d min, ended epoch %ld\n",
                      lastVolume, lastDuration, (long)lastFeedEnd);

    // Calibration is no longer triggered at boot (that clashed with a habitual
    // tare-on-power-up). Run it any time from the buttons: hold FEED + TARE for
    // 3s, or from the web page. See handleButtons() / doCalibration().

    // ---- Wi-Fi ----
    // Hold the FEED button (D25) at boot to force the setup portal even if a
    // network is already saved (use this to switch networks at a new place).
    bool forcePortal = (digitalRead(BUTTON_PIN) == LOW);
    if (forcePortal) Serial.println(F("FEED held at boot -> forcing WiFi portal"));
    setupWifi(forcePortal);
    secured.setInsecure();   // v1: skip cert validation (see firmware/README.md TLS note)

    // ---- OTA (Wi-Fi firmware updates, no cable needed after this flash) ----
    setupOTA();

    // ---- Web control page (tare / calibrate / restart from a phone) ----
    setupWeb();

    // ---- Time ----
    if (syncTime()) Serial.println(F("NTP time synced"));
    else            Serial.println(F("NTP sync failed, will retry"));

    Serial.println(F("[Feed Logger] Ready."));
}

// =============================================================================
// LOOP
// =============================================================================
void loop() {
    // Service OTA so a Wi-Fi firmware push can interrupt normal operation.
    ArduinoOTA.handle();
    // Serve the web control page / endpoints.
    server.handleClient();

    // Deferred restart requested over the web (response has flushed by now).
    // Signed-difference compare so it stays correct across the ~49-day millis() wrap.
    if (pendingRestartMs && (long)(millis() - pendingRestartMs) >= 0) doRestart();

    // Wi-Fi health
    if (millis() - lastWifiCheck > 30000) {
        lastWifiCheck = millis();
        ensureWifi();
        setupOTA();   // start OTA if Wi-Fi came up after boot (no-op once started)
        setupWeb();   // start web server if Wi-Fi came up after boot (no-op once started)
        // Re-kick NTP if Wi-Fi is up but time never synced (e.g. Wi-Fi came up
        // after boot). configTime() is non-blocking; SNTP fills time in the
        // background. Without this, timeIsValid() stays false and feeds are
        // blocked until a reboot.
        if (WiFi.status() == WL_CONNECTED && !timeIsValid()) {
            configTime(GMT_OFFSET_SEC, DST_OFFSET_SEC, NTP_SERVER);
        }
    }

    // Buttons (taps + hold-gestures; may block while a gesture runs).
    handleButtons();

    // Sample the scale: one raw read per loop, median-filtered over the last
    // SCALE_MEDIAN_SAMPLES reads so a single HX711 glitch can't move the number.
    // Holds the last good value through brief dropouts (see sampleScale).
    sampleScale();

    // Display refresh (twice per second). Skip while a hold-gesture countdown
    // owns the screen so its message stays put.
    if (!gestureHintActive && millis() - lastDisplay > 500) {
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
// Weight  (median-filtered sampling + stability detection)
//
// Why median, not average: the HX711 occasionally returns a wildly wrong
// sample (missed clock cycle, EMI, a momentarily loose load-cell wire). A mean
// (which is what the library's get_units()/read_average() and the old EMA both
// used) gets dragged hundreds of grams by ONE such spike. A median of the last
// few reads simply discards any isolated outlier, so the number stays put.
// =============================================================================

// Read one raw sample, rejecting the HX711's saturation rails (returned when the
// sensor is disconnected or pegged). Returns false if no fresh/valid sample.
bool readRawValid(long &out) {
    if (!scale.is_ready()) return false;
    long r = scale.read();
    if (r >= 8388607L || r <= -8388608L) return false;   // 24-bit rail = bad read
    out = r;
    return true;
}

// Median of an array (sorts in place; caller passes a scratch copy).
static int cmpLong(const void *a, const void *b) {
    long x = *(const long *)a, y = *(const long *)b;
    return (x > y) - (x < y);
}
long medianOf(long *arr, int n) {
    qsort(arr, n, sizeof(long), cmpLong);
    return arr[n / 2];
}

float rawToGrams(long raw) {
    return (raw - scale.get_offset()) / calibrationFactor;
}

// Clear the median filter so the live reading re-converges from scratch. Call
// after anything that changes the zero offset or calibration factor.
void resetScaleFilter() {
    rawCount = 0; rawHead = 0; displayGrams = NAN; scaleStable = false;
}

// Called every loop: pushes one raw read into a ring buffer, then derives the
// displayed weight from the median and a "stable?" flag from the spread.
void sampleScale() {
    long raw;
    if (!readRawValid(raw)) return;   // no new valid sample this iteration

    rawBuf[rawHead] = raw;
    rawHead = (rawHead + 1) % SCALE_MEDIAN_SAMPLES;
    if (rawCount < SCALE_MEDIAN_SAMPLES) rawCount++;
    lastGoodReadMs = millis();

    long tmp[SCALE_MEDIAN_SAMPLES];
    for (int i = 0; i < rawCount; i++) tmp[i] = rawBuf[i];
    long med = medianOf(tmp, rawCount);   // sorts tmp in place, returns the middle
    lastMedianRaw = med;

    float g = rawToGrams(med);
    if (isnan(displayGrams)) displayGrams = g;            // first reading
    else displayGrams = displayGrams * 0.7f + g * 0.3f;   // gentle visual smoothing

    // Spread (max-min) of the now-sorted window, in grams -> stability.
    float spreadG = (tmp[rawCount - 1] - tmp[0]) / fabsf(calibrationFactor);
    scaleStable   = (rawCount >= SCALE_MEDIAN_SAMPLES) && (spreadG <= SCALE_STABLE_SPREAD_G);
}

// Collect up to n fresh valid raw reads (waiting up to timeoutMs) and return
// their median. Returns LONG_MIN if not a single sample could be read.
long medianRawBlocking(int n, unsigned long timeoutMs) {
    if (n > 31) n = 31;
    long buf[31];
    int c = 0;
    unsigned long t0 = millis();
    while (c < n && millis() - t0 < timeoutMs) {
        long r;
        if (readRawValid(r)) buf[c++] = r;
        else                 delay(5);
    }
    if (c == 0) return LONG_MIN;
    return medianOf(buf, c);
}

// Robust weight capture for logging a feed: median of fresh reads, never nan
// unless the sensor is truly dead (then we fall back to the live display value).
float captureGrams() {
    long med = medianRawBlocking(15, 1500);
    if (med == LONG_MIN) return displayGrams;   // last good value (may be nan)
    return rawToGrams(med);
}

// Block until the reading is stable (settled). Returns false on timeout.
bool waitStable(unsigned long timeoutMs) {
    unsigned long t0 = millis();
    while (millis() - t0 < timeoutMs) {
        sampleScale();
        if (scaleStable) return true;
        delay(15);
    }
    return false;
}

// Block until the reading is stable AND the load has clearly changed from the
// tared zero by at least minDeltaCounts, in EITHER direction. Sign-independent
// so it works whether the cell deflects positive or negative under load (this
// device's cell reads NEGATIVE under load). Used to detect the calibration weight.
bool waitStableLoaded(unsigned long timeoutMs, long minDeltaCounts) {
    unsigned long t0 = millis();
    while (millis() - t0 < timeoutMs) {
        sampleScale();
        if (scaleStable && labs(lastMedianRaw - scale.get_offset()) >= minDeltaCounts) return true;
        delay(15);
    }
    return false;
}

// Median-based tare: averages out glitches so a stray spike can't poison the
// zero offset (the old library tare() used a plain mean of 10).
void tareRobust() {
    long med = medianRawBlocking(20, 2000);
    if (med == LONG_MIN) { Serial.println(F("Tare FAILED: no scale read")); return; }
    scale.set_offset(med);
    prefs.putLong("tareOffset", med);
    // reset the display filter so it re-converges around the new zero
    resetScaleFilter();
    Serial.printf("Tared. offset=%ld\n", med);
}

// Compute and persist a calibration factor from a known reference weight.
// The factor is SIGNED: its sign is the cell's deflection direction (this
// device's cell reads negative under load, so its factor is negative). We
// validate the MAGNITUDE and refuse to save a nonsensical factor (too small =
// no real weight change / wrong reading; too large = noise) so a glitch can't
// corrupt the calibration.
bool applyCalibration(float knownG) {
    if (knownG < 1.0f) return false;
    long med = medianRawBlocking(20, 2500);
    if (med == LONG_MIN) { Serial.println(F("Cal FAILED: no scale read")); return false; }

    long value = med - scale.get_offset();        // counts vs empty (signed)
    float factor = (float)value / knownG;         // counts per gram (signed = direction)
    if (fabsf(factor) < 1.0f || fabsf(factor) > 100000.0f) {
        Serial.printf("Cal FAILED: factor %.2f implausible (delta=%ld counts) - weight on the scale?\n",
                      factor, value);
        return false;
    }

    calibrationFactor = factor;
    calKnownWeight    = knownG;
    scale.set_scale(calibrationFactor);
    prefs.putFloat("calFactor", calibrationFactor);
    prefs.putFloat("knownG", knownG);
    resetScaleFilter();   // re-converge with the new factor
    Serial.printf("Calibrated: known=%.0f g, delta=%ld counts -> factor=%.2f\n", knownG, value, factor);
    return true;
}

// Wipe saved calibration back to compiled defaults and re-zero. For recovering
// from a bad/confused state ("just clear it"). Exposed on the web page.
void clearCalibration() {
    prefs.remove("calFactor");
    prefs.remove("knownG");
    prefs.remove("tareOffset");
    calibrationFactor = DEFAULT_CALIBRATION_FACTOR;
    calKnownWeight    = CALIBRATION_KNOWN_WEIGHT_G;
    scale.set_scale(calibrationFactor);
    resetScaleFilter();
    Serial.println(F("Calibration cleared -> defaults"));
    tareRobust();   // fresh zero on the (hopefully empty) platform
}

// =============================================================================
// Buttons: unified state machine (taps vs hold-gestures)
//
//   Tap FEED            -> start / stop a feed
//   Tap TARE            -> zero the scale
//   Hold FEED + TARE 3s -> guided calibration
//   Hold TARE alone 4s  -> restart the device
//
// Tap actions fire on RELEASE (after a short press) so that starting a two-
// button combo doesn't also trigger a feed/tare. A press "consumed" by a hold-
// gesture is flagged so its release does nothing.
// =============================================================================
void forceRedraw() { lastDisplay = millis() - 1000; }   // trigger an immediate redraw

void onFeedTap() {
    if (state == IDLE) {
        // Start a feed
        if (!timeIsValid()) { drawMessage("No time yet", "wait for NTP"); delay(1200); forceRedraw(); return; }
        startWeight = captureGrams();
        if (isnan(startWeight)) { drawMessage("Scale error", "no reading"); delay(1500); forceRedraw(); return; }
        startEpoch = now();
        state = FEEDING;
        Serial.printf("Feed START: %.1f g at %s\n", startWeight, isoTimestamp(startEpoch).c_str());
    } else {
        // End a feed
        float endWeight = captureGrams();
        time_t endEpoch = now();
        float volume = startWeight - endWeight;     // bottle cancels out
        int   durMin = (int)round((endEpoch - startEpoch) / 60.0);

        state = IDLE;

        // Reject bad reads first: a nan slips past the range check below (every
        // comparison with nan is false) and would log as 2147483647.
        if (isnan(volume)) {
            Serial.println(F("Feed IGNORED: scale read failed (nan)"));
            drawMessage("Scale error", "try again");
            delay(1500); forceRedraw();
            return;
        }
        if (volume < MIN_FEED_ML || volume > MAX_FEED_ML) {
            Serial.printf("Feed IGNORED: %.1f mL (outside %.0f-%.0f)\n", volume, MIN_FEED_ML, MAX_FEED_ML);
            drawMessage("Ignored", String(volume,0) + " mL?");
            delay(1500); forceRedraw();
            return;
        }
        Serial.printf("Feed END: %.1f g -> consumed %.1f mL over %d min\n", endWeight, volume, durMin);
        logFeed(volume, startEpoch, endEpoch);
    }
    forceRedraw();
}

void onTareTap() {
    // Taring mid-feed would move the zero out from under the in-progress feed,
    // so the end-weight would be measured against a different baseline.
    if (state == FEEDING) { drawMessage("Feeding...", "tare after feed"); delay(1200); forceRedraw(); return; }
    drawMessage("Taring...", "");
    tareRobust();
    delay(500);
    forceRedraw();
}

void handleButtons() {
    unsigned long t = millis();
    bool f  = digitalRead(BUTTON_PIN) == LOW;
    bool tr = digitalRead(TARE_PIN)   == LOW;

    // Press edges
    if (f  && !feedPrev) { feedDownMs = t; feedConsumed = false; }
    if (tr && !tarePrev) { tareDownMs = t; tareConsumed = false; }

    // ---- Both held -> calibrate ----
    if (f && tr) {
        if (bothDownMs == 0) bothDownMs = t;
        feedConsumed = true; tareConsumed = true;   // suppress tap actions
        unsigned long held = t - bothDownMs;
        if (!calibFired) {
            if (held >= CALIB_HOLD_MS) {
                calibFired = true; gestureHintActive = false;
                if (state == FEEDING) {            // don't recalibrate under an open feed
                    drawMessage("Finish feed", "before calibrating");
                    delay(1500); forceRedraw();
                } else {
                    doCalibration();
                }
                // doCalibration's private button loops leave feedPrev/tarePrev and
                // the *DownMs timestamps stale; resync so a button still held (or its
                // release) can't fire a stray tap or an instant restart afterwards.
                feedDownMs = tareDownMs = millis();
                feedConsumed = tareConsumed = true;
                bothDownMs = 0; restartFired = false;
            } else if (held > 300) {
                gestureHintActive = true;
                int rem = (int)((CALIB_HOLD_MS - held) / 1000) + 1;
                drawMessage("Hold both...", "Calibrate " + String(rem));
            }
        }
    } else {
        bothDownMs = 0;
    }

    // ---- TARE alone held -> restart ----
    if (tr && !f) {
        unsigned long held = t - tareDownMs;
        if (!restartFired) {
            if (held >= RESTART_HOLD_MS) {
                restartFired = true; tareConsumed = true; gestureHintActive = false;
                if (state == FEEDING) {            // don't restart under an open feed
                    drawMessage("Finish feed", "before restarting");
                    delay(1500); forceRedraw();
                } else {
                    doRestart();
                }
            } else if (held > 1000) {
                gestureHintActive = true;
                int rem = (int)((RESTART_HOLD_MS - held) / 1000) + 1;
                drawMessage("Hold TARE...", "Restart " + String(rem));
            }
        }
    }

    // Release edges -> fire tap actions on release of an un-consumed press.
    // (A press "consumed" by the both-button combo is flagged so it never taps.)
    if (!f && feedPrev) {
        unsigned long held = t - feedDownMs;
        // FEED has no long-press gesture of its own, so any lone FEED press is a
        // feed toggle regardless of how long it was held (no silent dead zone).
        if (!feedConsumed && held >= 30 && t - lastFeedActMs > DEBOUNCE_MS) {
            lastFeedActMs = t;
            gestureHintActive = false;
            onFeedTap();
        }
        feedConsumed = false;
        if (gestureHintActive) { gestureHintActive = false; forceRedraw(); }
    }
    if (!tr && tarePrev) {
        unsigned long held = t - tareDownMs;
        // Releasing TARE before the restart threshold = tare (hold = restart,
        // release = just tare). No dead zone: a firm 1-3 s press still tares.
        if (!tareConsumed && held >= 30 && held < RESTART_HOLD_MS && t - lastTareActMs > DEBOUNCE_MS) {
            lastTareActMs = t;
            gestureHintActive = false;
            onTareTap();
        }
        tareConsumed = false; restartFired = false;
        if (gestureHintActive) { gestureHintActive = false; forceRedraw(); }
    }

    // Re-arm the calibrate gesture once both buttons are up
    if (!f && !tr) {
        calibFired = false;
        if (gestureHintActive) { gestureHintActive = false; forceRedraw(); }
    }

    feedPrev = f; tarePrev = tr;
}

// =============================================================================
// Calibration (guided, on-device known-weight selection, saves to flash)
// =============================================================================
void doCalibration() {
    Serial.println(F("=== CALIBRATION ==="));
    gestureHintActive = true;   // we own the OLED for the whole flow

    // Wait for both buttons to be released before we start reading inputs.
    while (digitalRead(BUTTON_PIN) == LOW || digitalRead(TARE_PIN) == LOW) delay(10);

    // ---- Step 1: zero on the empty platform ----
    drawMessage("Calibrate 1/3", "remove weight");
    delay(1500);
    waitStable(4000);           // let the empty reading settle (best-effort)
    drawMessage("Zeroing...", "");
    tareRobust();

    // ---- Step 2: choose the known reference weight ----
    // FEED = +10 g, TARE = -10 g (hold a button to auto-repeat). CONFIRM simply
    // by NOT touching either button for 3 s; no awkward two-button press.
    float knownG = calKnownWeight;
    bool  prevF = false, prevT = false, confirmed = false;
    unsigned long holdStart = 0, lastStep = 0, lastChange = millis(), overall = millis();
    int   lastRem = -99;
    drawMessage("Set weight: " + String(knownG,0) + "g", "F +10   T -10");
    while (!confirmed && millis() - overall < 90000) {
        bool f  = digitalRead(BUTTON_PIN) == LOW;
        bool tr = digitalRead(TARE_PIN)   == LOW;
        float before = knownG;

        if (f != tr) {                                   // exactly one button down
            int dir = f ? +10 : -10;
            unsigned long nowMs = millis();
            bool edge = (f && !prevF) || (tr && !prevT);
            if (edge) { knownG += dir; holdStart = nowMs; lastStep = nowMs; }      // first step on press
            else if (nowMs - holdStart > 500 && nowMs - lastStep > 150) {          // auto-repeat while held
                knownG += dir; lastStep = nowMs;
            }
            knownG = constrain(knownG, 10.0f, 2000.0f);
        }

        if (knownG != before) {
            lastChange = millis(); lastRem = -99;
            drawMessage("Set weight: " + String(knownG,0) + "g", "F +10   T -10");
        } else if (!f && !tr) {                          // idle -> count down to confirm
            unsigned long idle = millis() - lastChange;
            if (idle >= 3000) confirmed = true;
            else {
                int rem = 3 - (int)(idle / 1000);
                if (rem != lastRem) {
                    lastRem = rem;
                    drawMessage("Weight: " + String(knownG,0) + "g", "locking in " + String(rem) + "...");
                }
            }
        }
        prevF = f; prevT = tr;
        delay(20);
    }
    if (!confirmed) {
        drawMessage("Calib canceled", "no change");
        delay(2000); gestureHintActive = false; forceRedraw();
        return;
    }

    // ---- Step 3: place the weight, auto-detect when it settles ----
    // Sign-independent: detects the load whether the cell reads up or down.
    drawMessage("Place " + String(knownG,0) + "g", "then wait...");
    bool settled = waitStableLoaded(25000, CAL_MIN_LOAD_COUNTS);   // wait for a real, steady load
    if (!settled) {
        drawMessage("No steady weight", "calib canceled");
        delay(2500); gestureHintActive = false; forceRedraw();
        return;
    }
    drawMessage("Measuring...", String(knownG,0) + " g");
    if (applyCalibration(knownG)) {
        drawMessage("Calibrated!", "factor " + String(calibrationFactor,1));
    } else {
        drawMessage("Calib FAILED", "kept old value");
    }
    delay(2500);
    drawMessage("Remove weight", "");
    delay(1500);
    gestureHintActive = false;
    forceRedraw();
}

// =============================================================================
// Restart (graceful, with an on-screen countdown)
// =============================================================================
void doRestart() {
    pendingRestartMs = 0;
    gestureHintActive = true;
    for (int s = 3; s >= 1; s--) {
        drawMessage("Restarting", String(s) + "...");
        delay(650);
    }
    drawMessage("Restarting", "now");
    delay(250);
    ESP.restart();
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

    // Notes (rich_text): a clear, human-readable summary of the feed.
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
// Wi-Fi  (managed by WiFiManager; no re-flash needed to change networks)
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
// =============================================================================
// Boot / connection UI  (animated splash, connecting, connected, portal info)
// =============================================================================
// Center a single line of size-1 text horizontally at row y.
void centerText(const String &s, int y) {
    int16_t x1, y1; uint16_t w, h;
    display.setTextSize(1);
    display.getTextBounds(s.c_str(), 0, 0, &x1, &y1, &w, &h);
    int x = (OLED_W - (int)w) / 2; if (x < 0) x = 0;
    display.setCursor(x, y);
    display.print(s);
}

// A little baby-bottle logo. fillPct (0-100) is the milk level; the white fill
// against the dark empty space inside the white outline reads as a level.
void drawBottle(int cx, int topY, int fillPct) {
    display.fillRoundRect(cx - 2, topY,      4, 4, 1, SSD1306_WHITE);   // teat
    display.fillRoundRect(cx - 5, topY + 4, 10, 4, 1, SSD1306_WHITE);   // cap ring
    display.drawRect     (cx - 4, topY + 8,  8, 5,    SSD1306_WHITE);   // neck
    const int bw = 18, bh = 30, by = topY + 13;                         // body
    display.drawRoundRect(cx - bw / 2, by, bw, bh, 5, SSD1306_WHITE);
    if (fillPct > 0) {
        if (fillPct > 100) fillPct = 100;
        int innerH = bh - 4;
        int fh = innerH * fillPct / 100;
        display.fillRoundRect(cx - bw / 2 + 2, by + 2 + (innerH - fh), bw - 4, fh, 3, SSD1306_WHITE);
    }
}

// Rotating "comet" spinner: a bright head with a short fading trail.
void drawSpinner(int cx, int cy, int r, int frame) {
    const int N = 12;
    int head = frame % N;
    for (int i = 0; i < N; i++) {
        float a = -1.5707964f + i * (6.2831853f / N);   // start at top, clockwise
        int x = cx + (int)lroundf(cosf(a) * r);
        int y = cy + (int)lroundf(sinf(a) * r);
        int d = (head - i + N) % N;                     // how far behind the head
        if      (d == 0) display.fillCircle(x, y, 2, SSD1306_WHITE);
        else if (d <= 3) display.fillCircle(x, y, 1, SSD1306_WHITE);
    }
}

// Classic Wi-Fi arcs (dot + three upper arcs) centered on cx, dot at dotY.
void drawWifiArcs(int cx, int dotY) {
    display.fillCircle(cx, dotY, 1, SSD1306_WHITE);
    display.drawCircleHelper(cx, dotY, 5,  0x1 | 0x8, SSD1306_WHITE);   // top-left|top-right
    display.drawCircleHelper(cx, dotY, 9,  0x1 | 0x8, SSD1306_WHITE);
    display.drawCircleHelper(cx, dotY, 13, 0x1 | 0x8, SSD1306_WHITE);
}

// Boot splash: the bottle fills with milk, then the wordmark appears.
void drawBootSplash() {
    for (int p = 0; p <= 100; p += 7) {
        display.clearDisplay();
        drawBottle(64, 6, p);
        if (p >= 42) centerText("Feed Logger", 54);
        display.display();
        delay(40);
    }
    delay(550);   // brief hold on the finished logo
}

// One animated frame of the "connecting to Wi-Fi" screen.
void drawConnecting(const String &ssid, int frame) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.print(F("Feed Logger"));
    drawSpinner(64, 26, 9, frame);
    String dots; int n = (frame / 3) % 4; for (int i = 0; i < n; i++) dots += '.';
    centerText("Connecting" + dots, 40);
    centerText(ssid.length() ? ssid : String("saved network"), 51);
    // sweeping progress bar
    display.drawRoundRect(0, 59, OLED_W, 5, 2, SSD1306_WHITE);
    const int bw = 28, span = OLED_W + bw;
    int x = (frame * 6) % span - bw;
    int x0 = x < 2 ? 2 : x;
    int x1 = (x + bw > OLED_W - 2) ? OLED_W - 2 : x + bw;
    if (x1 > x0) display.fillRect(x0, 61, x1 - x0, 2, SSD1306_WHITE);
    display.display();
}

// Connected: a check-mark pops in, then the network IP, held briefly.
void drawConnected(const String &ssid, const String &ip) {
    (void)ssid;
    for (int s = 0; s <= 8; s++) {
        display.clearDisplay();
        display.drawCircle(64, 22, 6 + s, SSD1306_WHITE);
        if (s >= 4) {                                   // draw the tick once the ring is up
            display.drawLine(58, 23, 62, 28, SSD1306_WHITE);
            display.drawLine(62, 28, 71, 16, SSD1306_WHITE);
            display.drawLine(58, 24, 62, 29, SSD1306_WHITE);   // thicken
            display.drawLine(62, 29, 71, 17, SSD1306_WHITE);
        }
        display.display();
        delay(35);
    }
    centerText("Connected", 44);
    centerText(ip, 55);
    display.display();
    delay(1300);
}

// "Wi-Fi setup needed": shown only when we can't reconnect; tells you which
// hotspot to join to configure the network.
void drawPortalInfo(const String &ap) {
    display.clearDisplay();
    drawWifiArcs(64, 20);
    centerText("Wi-Fi setup needed", 30);
    centerText("Join this network:", 43);
    centerText(ap, 54);
    display.display();
}

// The SSID stored in the ESP32 Wi-Fi NVS (what WiFiManager saved), used to
// reconnect and to label the connecting screen. Empty if nothing is saved.
String savedStaSsid() {
    wifi_config_t conf;
    if (esp_wifi_get_config(WIFI_IF_STA, &conf) != ESP_OK) return String();
    // conf.sta.ssid is a 32-byte field with no guaranteed terminator, so copy
    // a bounded amount and force-terminate (a 32-char SSID would otherwise
    // over-read into the adjacent password bytes).
    char buf[33];
    memcpy(buf, conf.sta.ssid, 32);
    buf[32] = '\0';
    return String(buf);
}

// Reconnect to the saved network, animating the connecting screen for real
// (we drive the attempt ourselves so the spinner isn't frozen). Returns true
// once connected; false on timeout / no saved network / terminal failure.
bool connectSavedAnimated(unsigned long timeoutMs) {
    String ssid = savedStaSsid();
    if (ssid.length() == 0) return false;   // nothing saved -> go straight to portal
    WiFi.begin();                           // reconnect using stored credentials
    unsigned long t0 = millis();
    int frame = 0;
    while (millis() - t0 < timeoutMs) {
        wl_status_t st = WiFi.status();
        if (st == WL_CONNECTED) return true;
        // Give association a few seconds, then bail early on a clearly terminal
        // result (wrong password / network not found) instead of spinning the
        // whole timeout every boot at a known-bad location.
        if (millis() - t0 > 5000 && (st == WL_CONNECT_FAILED || st == WL_NO_SSID_AVAIL)) break;
        drawConnecting(ssid, frame++);
        delay(85);
    }
    if (WiFi.status() == WL_CONNECTED) return true;
    // Stop the half-open attempt so the portal starts from a clean state (keep
    // the saved credentials: eraseap=false).
    WiFi.disconnect(false, false);
    return false;
}

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
    // public getWiFiSSID(false): the non-persistent (in-RAM) value, which holds
    // the just-submitted network. (getWiFiSSID(true) returns the OLD saved value,
    // which is why the display previously showed a stale name.) Fired by
    // setPreSaveConfigCallback, which runs in the WiFi-save handler before connect.
    wm.setPreSaveConfigCallback([&wm]() {
        String ssid = wm.getWiFiSSID(false);   // newly-entered SSID (in-RAM, not saved)
        Serial.printf("Portal submit -> connecting to \"%s\"...\n", ssid.c_str());
        drawConnecting(ssid.length() ? ssid : String("..."), 0);
    });

    drawPortalInfo(AP_NAME);
    Serial.printf("Opening config portal AP \"%s\"...\n", AP_NAME);

    // The saved-network reconnect already happened in setupWifi(), so here we
    // open the portal directly (don't retry saved creds again).
    bool ok = wm.startConfigPortal(AP_NAME);

    // WiFi.SSID() reflects the network actually used (unlike the saved getter).
    String usedSsid = WiFi.SSID();

    if (ok) {
        Serial.printf("WiFi OK %s on \"%s\"\n",
                      WiFi.localIP().toString().c_str(), usedSsid.c_str());
        drawConnected(usedSsid, WiFi.localIP().toString());
        return;   // drawConnected already held the screen
    } else {
        // Failure can be wrong password, network not found, portal timeout,
        // etc.; report the actual WiFi status rather than assuming a cause.
        String why = wifiStatusStr(WiFi.status());
        Serial.printf("WiFi FAILED: SSID=\"%s\" status=%s\n", usedSsid.c_str(), why.c_str());
        // Line 1: which network failed (if known); line 2: the reason.
        drawMessage(usedSsid.length() ? ("WiFi: " + usedSsid) : String("WiFi failed"), why);
    }
    delay(3000);
}

void setupWifi(bool forcePortal) {
    WiFi.mode(WIFI_STA);
    // Normal boot: try to reconnect to the saved network with a live animated
    // "connecting" screen. Only if that fails (or FEED is held to force it) do we
    // open the setup portal and show the join-this-network instructions.
    // WiFiManager owns the credentials (its NVS); we reconnect via WiFi.begin()
    // with the stored creds, never with config.h values (which would clobber the
    // portal-saved network on every boot).
    if (!forcePortal && connectSavedAnimated(14000)) {
        Serial.printf("WiFi OK %s on \"%s\"\n",
                      WiFi.localIP().toString().c_str(), WiFi.SSID().c_str());
        drawConnected(WiFi.SSID(), WiFi.localIP().toString());
        return;
    }
    Serial.println(forcePortal ? F("FEED held at boot -> WiFi portal")
                               : F("Saved WiFi unavailable -> WiFi portal"));
    runWifiPortal(forcePortal);
}

void ensureWifi() {
    if (WiFi.status() == WL_CONNECTED) return;
    // Let WiFiManager's stored credentials reconnect; don't block the loop.
    WiFi.reconnect();
}

// Enable Over-The-Air updates: once this firmware is running, future builds can
// be pushed over Wi-Fi (PlatformIO: upload_protocol = espota) with no cable.
// The device appears as "bottle-feed-logger" on the network. Disabled unless
// OTA_PASSWORD is set (see below). Safe to call repeatedly: it only starts once,
// and only after Wi-Fi is up (so it also works when Wi-Fi connects after boot,
// called from the loop's health check).
void setupOTA() {
    static bool otaStarted = false;
    if (otaStarted || WiFi.status() != WL_CONNECTED) return;

    // Secure by default: OTA is DISABLED unless OTA_PASSWORD is set in config.h.
    // Unauthenticated OTA would let anyone on the LAN push arbitrary firmware
    // (remote code execution), so we require a password to enable it rather than
    // starting open with only a warning.
#ifndef OTA_PASSWORD
    static bool warned = false;
    if (!warned) {
        warned = true;
        Serial.println(F("OTA disabled: set OTA_PASSWORD in config.h to enable Wi-Fi updates"));
    }
    return;
#else
    ArduinoOTA.setHostname("bottle-feed-logger");
    ArduinoOTA.setPassword(OTA_PASSWORD);
    ArduinoOTA.onStart([]() { drawMessage("OTA update", "receiving..."); });
    ArduinoOTA.onEnd([]()   { drawMessage("OTA update", "done, reboot"); });
    ArduinoOTA.onError([](ota_error_t e) { drawMessage("OTA failed", String("err ") + e); });
    ArduinoOTA.begin();
    otaStarted = true;
    Serial.println(F("OTA ready: bottle-feed-logger"));
#endif
}

// =============================================================================
// Web control page  (tare / calibrate / restart / live weight from a phone)
//
// Served at http://bottle-feed-logger.local (or the device IP). The entire
// interface (the page, /status, and the mutating tare/calibrate/restart
// actions) can be protected with an optional shared key: define
// WEB_CONTROL_KEY in config.h and every route will require ?key=... . If you
// leave it undefined, everything is open to anyone on your Wi-Fi (fine for a
// trusted home network; the device is LAN-only and not exposed to the Internet).
// =============================================================================
static bool webAuthed() {
#ifdef WEB_CONTROL_KEY
    return server.hasArg("key") && server.arg("key") == WEB_CONTROL_KEY;
#else
    return true;
#endif
}

// Refuse zero/calibration while a feed is open: changing the offset or factor
// mid-feed would measure the start and end weights in different coordinate
// systems and log a garbage volume. Returns true (and answers 409) if busy.
static bool webRejectIfFeeding() {
    if (state == FEEDING) {
        server.send(409, "text/plain", "busy: feeding - finish the feed first");
        return true;
    }
    return false;
}

// status JSON for the live-updating page
static void handleStatus() {
    if (!webAuthed()) { server.send(403, "text/plain", "forbidden"); return; }
    bool stale = (millis() - lastGoodReadMs) > STALE_MS;
    // Build into a fixed buffer (this is polled ~1/s; avoid per-request heap churn).
    char gbuf[16];
    if (stale || isnan(displayGrams)) strcpy(gbuf, "null");
    else snprintf(gbuf, sizeof(gbuf), "%.1f", displayGrams);
    char json[256];
    int n = snprintf(json, sizeof(json),
        "{\"grams\":%s,\"stable\":%s,\"feeding\":%s,\"calFactor\":%.1f,"
        "\"knownG\":%.0f,\"raw\":%ld,\"offset\":%ld,\"haveLast\":%s,"
        "\"lastVol\":%.0f,\"lastDur\":%d,\"wifi\":%s}",
        gbuf,
        (!stale && scaleStable) ? "true" : "false",   // stale reading is never stable
        (state == FEEDING)      ? "true" : "false",
        calibrationFactor, calKnownWeight,
        lastMedianRaw, scale.get_offset(),
        haveLastFeed ? "true" : "false",
        lastVolume, lastDuration,
        (WiFi.status() == WL_CONNECTED) ? "true" : "false");
    // Guard against a truncated (invalid) body if the fields ever grow past the buffer.
    if (n < 0 || n >= (int)sizeof(json)) { server.send(500, "text/plain", "status encode error"); return; }
    server.send(200, "application/json", json);
}

// The control page is split into two PROGMEM halves with the (optional) auth
// key injected between them, then streamed straight from flash with a known
// content length, so rendering a ~14 KB page costs almost no RAM.
static const char PAGE_A[] PROGMEM = R"HZ(<!doctype html><html lang=en><head>
<meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=theme-color content="#14110f"><meta name=referrer content=no-referrer><title>Feed Logger</title>
<link rel=preconnect href="https://fonts.googleapis.com"><link rel=preconnect href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Outfit:wght@300;400;500;600&display=swap" rel=stylesheet>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#14110f;--card:#1e1a16;--card2:#251f19;--line:#332c25;--tx:#f4ede3;--mut:#a99c8c;--ac:#f0a04b;--ac2:#7bd39a;--dg:#e7715c;--r:18px;--sh:0 12px 34px rgba(0,0,0,.4)}
html{-webkit-text-size-adjust:100%}
body{font-family:Outfit,system-ui,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;line-height:1.45;background-image:radial-gradient(120% 80% at 50% -8%,#241c14 0%,var(--bg) 58%);-webkit-font-smoothing:antialiased}
header{display:flex;align-items:center;justify-content:space-between;padding:18px 22px;max-width:480px;margin:0 auto}
.brand{font-family:Fraunces,Georgia,serif;font-weight:600;font-size:20px;display:flex;align-items:center;gap:9px}
.mark{color:var(--ac);font-size:15px}
.dot{width:10px;height:10px;border-radius:50%;background:#6b5f54;transition:.3s}
.dot.on{background:var(--ac2);animation:pls 2.2s infinite}
.dot.off{background:var(--dg)}
@keyframes pls{0%{box-shadow:0 0 0 0 rgba(123,211,154,.45)}70%{box-shadow:0 0 0 7px rgba(123,211,154,0)}100%{box-shadow:0 0 0 0 rgba(123,211,154,0)}}
.seg{display:flex;gap:4px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:4px;max-width:448px;margin:0 auto;width:calc(100% - 32px)}
.seg-b{flex:1;background:none;border:0;color:var(--mut);font:inherit;font-weight:500;font-size:15px;padding:9px;border-radius:10px;cursor:pointer;transition:.2s}
.seg-b.active{background:var(--card2);color:var(--tx);box-shadow:var(--sh)}
main{max-width:480px;margin:0 auto;padding:8px 16px 48px}
.sec{display:none}.sec.active{display:block;animation:fade .45s ease both}
@keyframes fade{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:18px;margin-top:14px}
.hero{padding:34px 18px 24px;text-align:center;position:relative;overflow:hidden}
.hero:before{content:"";position:absolute;inset:0;background:radial-gradient(75% 60% at 50% 0,rgba(240,160,75,.12),transparent 70%);pointer-events:none}
.wrap{position:relative;display:flex;align-items:baseline;justify-content:center;gap:9px}
.wt{font-family:Fraunces,Georgia,serif;font-weight:600;font-size:84px;line-height:.95;letter-spacing:-2px;font-variant-numeric:tabular-nums}
.unit{font-family:Fraunces,Georgia,serif;font-size:26px;color:var(--mut)}
.status{display:inline-flex;align-items:center;gap:8px;margin-top:16px;font-size:13.5px;color:var(--mut);letter-spacing:.02em}
.status .ring{width:8px;height:8px;border-radius:50%;background:var(--mut)}
.status.ok .ring{background:var(--ac2)}.status.ok .lbl{color:var(--ac2)}
.status.wait .ring{background:var(--ac);animation:blink 1s infinite}
.status.feed .ring{background:var(--ac)}.status.feed .lbl{color:var(--ac);font-weight:500}
@keyframes blink{50%{opacity:.25}}
.lastrow{display:flex;justify-content:space-between;align-items:center}
.k{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.09em}
.v{font-size:16px;margin-top:3px}
.actions{display:grid;gap:10px;margin-top:14px}
.btn{display:flex;flex-direction:column;align-items:flex-start;gap:1px;background:var(--card);border:1px solid var(--line);color:var(--tx);font:inherit;font-weight:600;font-size:16.5px;padding:14px 18px;border-radius:14px;cursor:pointer;text-align:left;transition:transform .08s,border-color .2s,opacity .2s}
.btn small{font-weight:400;font-size:12px;color:var(--mut)}
.btn:active{transform:scale(.985)}
.btn.primary{background:linear-gradient(180deg,#f4a657,#e0872f);border-color:#f0a04b;color:#231505}
.btn.primary small{color:#6a431b}
.btn.danger{border-color:#4f372e;color:var(--dg)}.btn.danger small{color:#9a6356}
.btn[disabled]{opacity:.5;pointer-events:none}
.meta{text-align:center;color:var(--mut);font-size:12px;margin-top:18px;line-height:1.7}
.meta b{color:var(--tx);font-weight:600}.host{color:var(--ac)}
.g h3{font-family:Fraunces,Georgia,serif;font-weight:600;font-size:17px;margin-bottom:9px}
.g p{color:var(--mut);font-size:14px}
.kbd{display:grid;grid-template-columns:auto 1fr;gap:9px 14px;margin-top:2px}
.kbd dt{font-weight:600;font-size:13px;color:var(--ac);white-space:nowrap}
.kbd dd{font-size:13.5px;color:var(--mut)}
.ol{margin:2px 0 0;padding:0;counter-reset:s;list-style:none}
.ol li{color:var(--mut);font-size:13.5px;padding:4px 0 4px 28px;position:relative}
.ol li:before{counter-increment:s;content:counter(s);position:absolute;left:0;top:3px;width:19px;height:19px;border-radius:50%;background:var(--card2);color:var(--ac);font-size:11px;font-weight:600;display:grid;place-items:center}
.tip{border-left:2px solid var(--ac);padding-left:12px;color:var(--mut);font-size:13.5px;margin-top:4px}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.55);-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);display:none;align-items:flex-end;justify-content:center;z-index:9}
.modal.show{display:flex;animation:fade .2s}
.sheet{background:var(--card);border:1px solid var(--line);border-bottom:0;border-radius:24px 24px 0 0;width:100%;max-width:480px;padding:20px 18px calc(22px + env(safe-area-inset-bottom));box-shadow:var(--sh);animation:up .3s cubic-bezier(.2,.9,.3,1)}
@keyframes up{from{transform:translateY(100%)}to{transform:none}}
.sh-h{display:flex;justify-content:space-between;align-items:center;font-family:Fraunces,Georgia,serif;font-weight:600;font-size:19px}
.x{background:none;border:0;color:var(--mut);font-size:27px;line-height:1;cursor:pointer;padding:0 4px}
.cwt{text-align:center;margin:12px 0 14px}
.cwt span{font-family:Fraunces,Georgia,serif;font-size:38px;font-weight:600;font-variant-numeric:tabular-nums}
.cwt small{display:block;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.09em;margin-top:2px}
.steps{list-style:none}
.steps li{display:flex;gap:13px;align-items:flex-start;padding:13px 0;border-top:1px solid var(--line)}
.steps li b{width:24px;height:24px;border-radius:50%;background:var(--card2);color:var(--mut);display:grid;place-items:center;font-size:12.5px;flex:none;margin-top:1px;transition:.25s}
.steps li.done b{background:var(--ac2);color:#13261a}
.st{font-weight:500;font-size:14.5px;margin-bottom:9px}
.stp{display:inline-flex;align-items:center;gap:8px}
.stp button{width:40px;height:40px;border-radius:11px;border:1px solid var(--line);background:var(--card2);color:var(--tx);font-size:21px;cursor:pointer}
.stp input{width:82px;height:40px;text-align:center;font:inherit;font-size:18px;font-weight:600;border-radius:11px;border:1px solid var(--line);background:var(--bg);color:var(--tx)}
.stp .u{color:var(--mut)}
.cmsg{min-height:20px;text-align:center;font-size:13.5px;color:var(--ac);margin:8px 0 2px}
.cmsg.ok{color:var(--ac2)}.cmsg.err{color:var(--dg)}
.clear{width:100%;background:none;border:1px solid #4f372e;color:var(--dg);font:inherit;font-size:14px;padding:11px;border-radius:12px;margin-top:10px;cursor:pointer}
.toast{position:fixed;left:50%;bottom:26px;transform:translate(-50%,18px);background:var(--card2);border:1px solid var(--line);color:var(--tx);padding:11px 18px;border-radius:12px;font-size:13.5px;opacity:0;transition:.25s;pointer-events:none;box-shadow:var(--sh);z-index:20;max-width:88%;text-align:center}
.toast.show{opacity:1;transform:translate(-50%,0)}
input[type=number]::-webkit-inner-spin-button{opacity:0}
</style></head><body>
<header><div class=brand><span class=mark>&#9737;</span>Feed Logger</div><div id=dot class="dot off" title=connection></div></header>
<nav class=seg><button class="seg-b active" data-t=control onclick="tab('control')">Control</button><button class=seg-b data-t=guide onclick="tab('guide')">Guide</button></nav>
<main>
<section id=sec-control class="sec active">
 <div class="card hero"><div class=wrap><span id=wt class=wt>&mdash;</span><span class=unit>g</span></div>
 <div id=st class="status wait"><span class=ring></span><span class=lbl id=stl>connecting</span></div></div>
 <div class="card lastrow"><div><div class=k>Last feed</div><div id=last class=v>&mdash;</div></div></div>
 <div class=actions>
  <button class="btn" onclick="send('/tare',this)">Tare<small>zero the empty scale</small></button>
  <button class="btn primary" onclick=openCal()>Calibrate<small>match a known weight</small></button>
  <button class="btn danger" onclick=restart()>Restart<small>reboot the device</small></button>
 </div>
 <div class=meta>factor <b id=cf>&mdash;</b> &middot; reference <b id=kg>&mdash;</b><br><span class=host>bottle-feed-logger.local</span></div>
</section>
<section id=sec-guide class="sec g">
 <div class=card><h3>How it works</h3><p>It weighs the bottle before and after a feed; the drop in weight is how much was taken. The bottle is in both readings, so it cancels out &mdash; no per-bottle tare needed.</p></div>
 <div class=card><h3>Buttons</h3><dl class=kbd>
  <dt>Tap FEED</dt><dd>Start a feed, then tap again to finish &amp; log it</dd>
  <dt>Tap TARE</dt><dd>Zero the scale</dd>
  <dt>Hold FEED + TARE 3s</dt><dd>Guided calibration</dd>
  <dt>Hold TARE 4s</dt><dd>Restart the device</dd>
  <dt>Hold FEED at power-on</dt><dd>Open the Wi-Fi setup portal</dd>
 </dl></div>
 <div class=card><h3>Calibrate</h3><p>From this page: tap <b>Calibrate</b>, then</p><ol class=ol><li>Empty the scale &rarr; <b>Zero</b></li><li>Type your known weight</li><li>Put it on &rarr; <b>Capture</b></li></ol>
 <p class=tip>On the device: hold <b>FEED+TARE</b> 3s, set the grams with FEED (+10) / TARE (&minus;10), then just <b>stop pressing for 3s</b> to lock it in &mdash; then place the weight.</p></div>
 <div class=card><h3>Tare &amp; Restart</h3><p>Tap <b>Tare</b> (or the TARE button) whenever the empty scale doesn&#39;t read 0. <b>Restart</b> reboots safely &mdash; no reset button needed.</p></div>
 <div class=card><h3>Reset / fix odd readings</h3><p><b>Clear calibration</b> (in the Calibrate panel) wipes it back to defaults and re-zeros. Re-tare first; if it&#39;s still off, recalibrate.</p><p class=tip>If pressing hard on the platform doesn&#39;t move the number at all, the load cell isn&#39;t flexing &mdash; check the mount (one end fixed, the platform end free to bend).</p></div>
</section>
</main>
<div id=cal class=modal><div class=sheet>
 <div class=sh-h><span>Calibrate</span><button class=x onclick=closeCal()>&times;</button></div>
 <div class=cwt><span id=cwt>&mdash; g</span><small>live weight</small></div>
 <ul class=steps>
  <li id=s1><b>1</b><div><div class=st>Empty the scale</div><button class=clear style="width:auto;margin:0;padding:9px 16px;color:var(--tx);border-color:var(--line)" id=zbtn onclick=zero()>Zero (empty)</button></div></li>
  <li id=s2><b>2</b><div><div class=st>Known weight</div><div class=stp><button onclick=bump(-10)>&minus;</button><input id=kw type=number value=200 min=10 step=10><button onclick=bump(10)>+</button><span class=u>g</span></div></div></li>
  <li id=s3><b>3</b><div><div class=st>Put it on the scale, then</div><button class="btn primary" style="padding:11px 18px;align-items:center" onclick=capture()>Capture</button></div></li>
 </ul>
 <div id=cmsg class=cmsg></div>
 <button class=clear onclick=clearCal()>Clear calibration</button>
</div></div>
<div id=toast class=toast></div>
<script>)HZ";

static const char PAGE_B[] PROGMEM = R"HZ(
var $=function(s){return document.querySelector(s)};
function q(p){return WKEY?p+(p.indexOf('?')<0?'?':'&')+'key='+encodeURIComponent(WKEY):p}
var kgTouched=false;
async function poll(){
 try{
  var d=await (await fetch(q('/status'),{cache:'no-store'})).json();
  var g=d.grams;
  $('#wt').innerHTML=(g==null?'&mdash;':Math.round(g));
  $('#st').className='status '+(d.feeding?'feed':(d.stable?'ok':'wait'));
  $('#stl').textContent=(g==null?'no reading':(d.feeding?'feeding':(d.stable?'stable':'settling')));
  $('#dot').className='dot on';
  $('#cf').textContent=d.calFactor;
  $('#kg').textContent=d.knownG+' g';
  $('#last').textContent=d.haveLast?(d.lastVol+' mL · '+d.lastDur+' min'):'no feeds yet';
  $('#cwt').textContent=(g==null?'-':Math.round(g))+' g';
  if(d.knownG&&!kgTouched)$('#kw').value=d.knownG;
 }catch(e){$('#dot').className='dot off';$('#stl').textContent='offline'}
}
setInterval(poll,1000);poll();
function tab(n){document.querySelectorAll('.sec').forEach(function(e){e.classList.toggle('active',e.id=='sec-'+n)});document.querySelectorAll('.seg-b').forEach(function(e){e.classList.toggle('active',e.dataset.t==n)})}
var _tt;function toast(t){var e=$('#toast');e.textContent=t;e.classList.add('show');clearTimeout(_tt);_tt=setTimeout(function(){e.classList.remove('show')},2600)}
async function send(p,btn){try{if(btn)btn.disabled=true;var t=await (await fetch(q(p))).text();toast(t)}catch(e){toast('error')}finally{if(btn)btn.disabled=false}}
function restart(){if(confirm('Restart the device?'))send('/restart')}
function openCal(){$('#cal').classList.add('show');$('#s1').classList.remove('done');$('#s3').classList.remove('done');cmsg('',0)}
function closeCal(){$('#cal').classList.remove('show')}
function cmsg(t,k){var e=$('#cmsg');e.textContent=t;e.className='cmsg'+(k==1?' ok':k==-1?' err':'')}
function bump(d){var i=$('#kw');i.value=Math.max(10,(parseInt(i.value)||0)+d);kgTouched=true}
$('#kw').addEventListener('input',function(){kgTouched=true});
async function zero(){var b=$('#zbtn');b.disabled=true;b.textContent='Zeroing…';try{await fetch(q('/cal/zero'));$('#s1').classList.add('done');cmsg('Zeroed, now place the weight',1)}catch(e){cmsg('zero failed',-1)}b.textContent='Zero (empty)';b.disabled=false}
async function capture(){var g=parseInt($('#kw').value)||0;if(g<10){cmsg('Set the weight first',-1);return}cmsg('Measuring…',0);try{var t=await (await fetch(q('/cal/capture?g='+g))).text();var ok=t.indexOf('OK')==0;cmsg(t,ok?1:-1);if(ok)$('#s3').classList.add('done')}catch(e){cmsg('capture failed',-1)}}
async function clearCal(){if(!confirm('Clear calibration back to defaults?'))return;try{var t=await (await fetch(q('/cal/reset'))).text();cmsg(t,1);$('#s1').classList.remove('done');$('#s3').classList.remove('done')}catch(e){cmsg('reset failed',-1)}}
</script></body></html>)HZ";

static void handleRoot() {
    // Gate the page itself behind the key too. Otherwise the key would be
    // pointless: it's embedded in this page for the page's own fetches, so an
    // unauthenticated client could read it here and then call the mutating
    // endpoints. With WEB_CONTROL_KEY set, the whole UI requires ?key=... ; with
    // it unset, everything is open (the trusted-home-LAN default).
    if (!webAuthed()) { server.send(403, "text/plain", "forbidden (append ?key=...)"); return; }
    String mid = "var WKEY=\"";
#ifdef WEB_CONTROL_KEY
    // Escape the key so ANY string is safe inside the JS literal: backslash and
    // quote are escaped, '<' becomes \x3C so a key can't smuggle a </script>, and
    // control chars (< 0x20: newline, CR, tab, ...) become \xNN so they can't
    // break the string/line.
    for (const char *k = WEB_CONTROL_KEY; *k; ++k) {
        unsigned char c = (unsigned char)*k;
        if (c == '\\' || c == '"') { mid += '\\'; mid += (char)c; }
        else if (c == '<')         { mid += "\\x3C"; }
        else if (c < 0x20)         { char e[5]; snprintf(e, sizeof(e), "\\x%02X", c); mid += e; }
        else                         mid += (char)c;
    }
#endif
    mid += "\";";
    // Known length -> plain (non-chunked) response, streamed from flash.
    server.setContentLength(strlen_P(PAGE_A) + mid.length() + strlen_P(PAGE_B));
    server.send(200, "text/html", "");
    server.sendContent_P(PAGE_A);
    server.sendContent(mid);
    server.sendContent_P(PAGE_B);
}

void setupWeb() {
    static bool started = false;
    if (started || WiFi.status() != WL_CONNECTED) return;

    server.on("/",        HTTP_GET, handleRoot);
    server.on("/status",  HTTP_GET, handleStatus);

    server.on("/tare", HTTP_GET, []() {
        if (!webAuthed()) { server.send(403, "text/plain", "forbidden"); return; }
        if (webRejectIfFeeding()) return;
        drawMessage("Web: taring", "");
        tareRobust();
        forceRedraw();
        server.send(200, "text/plain", "tared");
    });

    server.on("/restart", HTTP_GET, []() {
        if (!webAuthed()) { server.send(403, "text/plain", "forbidden"); return; }
        if (webRejectIfFeeding()) return;
        server.send(200, "text/plain", "restarting...");
        pendingRestartMs = millis() + 600;   // restart after the response flushes
        if (pendingRestartMs == 0) pendingRestartMs = 1;   // 0 is the "no restart" sentinel
    });

    // Two-step web calibration (no buttons needed): zero empty, then capture
    // with the known weight on the scale.
    server.on("/cal/zero", HTTP_GET, []() {
        if (!webAuthed()) { server.send(403, "text/plain", "forbidden"); return; }
        if (webRejectIfFeeding()) return;
        drawMessage("Web calibrate", "zeroing...");
        tareRobust();
        forceRedraw();
        server.send(200, "text/plain", "zeroed - place weight then capture");
    });
    server.on("/cal/capture", HTTP_GET, []() {
        if (!webAuthed()) { server.send(403, "text/plain", "forbidden"); return; }
        if (webRejectIfFeeding()) return;
        float g = server.hasArg("g") ? server.arg("g").toFloat() : 0.0f;
        if (g < 10.0f || g > 2000.0f) { server.send(400, "text/plain", "g must be 10-2000"); return; }
        drawMessage("Web calibrate", "measuring...");
        // Require a real, steady load like the on-device flow (waitStableLoaded +
        // CAL_MIN_LOAD_COUNTS) -- a plain settle check would accept an empty,
        // already-quiescent platform and let ambient noise divided by g pass as
        // a "valid" factor.
        bool loaded = waitStableLoaded(5000, CAL_MIN_LOAD_COUNTS);
        bool ok = loaded && applyCalibration(g);
        forceRedraw();
        if (ok) server.send(200, "text/plain", "OK - calibrated, factor " + String(calibrationFactor, 1));
        else    server.send(500, "text/plain", "FAILED - no clear weight change (is the weight on? did you Zero first?)");
    });
    server.on("/cal/reset", HTTP_GET, []() {
        if (!webAuthed()) { server.send(403, "text/plain", "forbidden"); return; }
        if (webRejectIfFeeding()) return;
        drawMessage("Web calibrate", "clearing...");
        clearCalibration();
        forceRedraw();
        server.send(200, "text/plain", "cleared to defaults (factor " + String(calibrationFactor, 1) + ") + re-zeroed");
    });

    server.onNotFound([]() { server.send(404, "text/plain", "not found"); });

    server.begin();
    // Advertise http on mDNS so bottle-feed-logger.local resolves even when OTA
    // is disabled (ArduinoOTA would otherwise be the only thing starting mDNS).
    // Ensure the hostname is set, then advertise http regardless of begin()'s
    // return (mDNS may already be running -- e.g. ArduinoOTA started it -- in
    // which case begin() can report false but the service still needs adding).
    MDNS.begin("bottle-feed-logger");
    MDNS.addService("http", "tcp", 80);
    started = true;
    Serial.printf("Web control: http://bottle-feed-logger.local  (or http://%s)\n",
                  WiFi.localIP().toString().c_str());
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
