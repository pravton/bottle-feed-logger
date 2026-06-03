# Firmware

ESP32 firmware for the Bottle Feed Logger.

## Stack

- **Board:** ESP32 DevKit V1 (38-pin)
- **Framework:** Arduino via PlatformIO
- **Language:** C++

## Key libraries

| Library | Version | Purpose |
|---------|---------|---------|
| `bogde/HX711` | ^0.7.5 | Read the load cell via the HX711 amplifier |
| `adafruit/Adafruit SSD1306` | ^2.5.13 | OLED display |
| `adafruit/Adafruit GFX Library` | ^1.11.10 | Graphics for the OLED |
| `bblanchon/ArduinoJson` | ^7.0.4 | Build the Notion JSON body |
| `witnessmenow/UniversalTelegramBot` | ^1.3.0 | Optional Telegram confirmation |

`WiFi`, `WiFiClientSecure`, `HTTPClient`, `Preferences`, and `time.h` are part of the ESP32 Arduino core — no install needed.

## Setup

### 1. Install PlatformIO
Install VS Code + the "PlatformIO IDE" extension, then restart VS Code.

### 2. Open `firmware/`
File → Open Folder → the `firmware/` folder (the one with `platformio.ini`). PlatformIO downloads dependencies on first open.

### 3. Configure
```bash
cp src/config.h.example src/config.h
```
Edit `src/config.h`: Wi-Fi, Notion token + database ID, time zone offsets, and (optionally) Telegram. Make sure the `PROP_*` names exactly match your Notion column names.

### 4. Build → Upload → Monitor
- Build (first compile is slow)
- Upload (hold BOOT on the ESP32 if upload won't start)
- Monitor at 115200 baud

## Expected serial output on first boot

```
[Feed Logger] Booting...
HX711 ready
Calibration factor: 420.000, tare offset: 0
WiFi OK 192.168.x.x
NTP time synced
[Feed Logger] Ready.
```

## How calibration works

The firmware enters **calibration mode** when the **tare button (GPIO 26) is held during boot/reset**:

1. "Remove all weight" — it tares the empty platform and saves the offset
2. "Place weight: 250 g" — put your known weight on (default 250 g; change `CALIBRATION_KNOWN_WEIGHT_G`)
3. It reads, computes counts-per-gram, and **saves the factor to flash** (NVS)
4. Done — the value persists across reboots; you won't need to recalibrate unless you change the mechanical setup

If you never calibrate, it uses `DEFAULT_CALIBRATION_FACTOR`, which will be inaccurate — always calibrate once.

## How a feed is captured

- **Tap the feed button (GPIO 25)** → records start weight + start time, enters FEEDING
- **Tap again** → records end weight + end time, computes:
  - `volume = startWeight − endWeight` (mL; the bottle cancels out)
  - `duration = endTime − startTime`
- It rejects values outside `MIN_FEED_ML`..`MAX_FEED_ML` (accidental presses)
- Otherwise it POSTs a row to Notion and shows the result on the OLED

## Configuration variables

All in `src/config.h`. Highlights:

| Variable | Purpose |
|----------|---------|
| `WIFI_SSID` / `WIFI_PASSWORD` | Network |
| `NOTION_TOKEN` / `NOTION_DB_ID` | Notion integration + target database |
| `NOTION_VERSION` | Notion API version header (verify current) |
| `PROP_*` | Must match your Notion column names exactly |
| `GMT_OFFSET_SEC` / `DST_OFFSET_SEC` | Time zone (Eastern preset) |
| `ENABLE_TELEGRAM` | 0/1 toggle for the optional buzz |
| `CALIBRATION_KNOWN_WEIGHT_G` | Weight you place during calibration |
| `MIN_FEED_ML` / `MAX_FEED_ML` | Sanity bounds |
| `SAMPLES_PER_READING` | Smoothing (averaging) window |

## TLS note

v1 uses `secured.setInsecure()` — it skips certificate validation for the HTTPS calls. That's a reasonable trade-off for a hobby device on your home network. To harden it, load Notion's root CA and use `secured.setCACert(...)` instead.

## Notion JSON shape (for reference)

The firmware POSTs something like this to `https://api.notion.com/v1/pages`:

```json
{
  "parent": { "database_id": "<DB_ID>" },
  "properties": {
    "Name":           { "title":     [ { "text": { "content": "Feed 165 mL" } } ] },
    "Start":          { "date":      { "start": "2026-05-28T02:42:00-04:00" } },
    "End":            { "date":      { "start": "2026-05-28T03:01:00-04:00" } },
    "Duration (min)": { "number":    19 },
    "Volume (mL)":    { "number":    165 },
    "Notes":          { "rich_text": [ { "text": { "content": "Auto-logged by Feed Logger" } } ] }
  }
}
```

If a property name in `config.h` doesn't match your database exactly, Notion returns a validation error (visible in the serial monitor).

## Project structure

```
firmware/
├── platformio.ini
├── README.md            ← you are here
└── src/
    ├── main.cpp         ← full firmware (single-file MVP)
    ├── config.h.example ← template
    └── config.h         ← your secrets (gitignored)
```

## Phase 2 firmware ideas

- Auto lift/return feed detection (no buttons)
- Offline queue in SPIFFS for failed Notion writes
- Local web dashboard
- Feed-type tag (formula/breastmilk)
- Module split into separate files
