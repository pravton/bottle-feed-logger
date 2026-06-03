# Quick Start

Fastest path from parts-in-hand to a feed logged in Notion. Target: ~2–3 hours (plus print time in parallel).

> **Do the Notion setup first** (Step 0). It's the part most likely to trip you up, and you want the token + database ID ready before you flash.

## Prerequisites checklist

- [ ] ESP32 DevKit V1
- [ ] 1 kg bar load cell + HX711 board
- [ ] Momentary push button (1, optionally 2)
- [ ] SSD1306 0.96" I2C OLED
- [ ] Breadboard + jumper wires
- [ ] Soldering iron (load cell wires → HX711)
- [ ] USB cable (data, not charge-only) + wall adapter
- [ ] A known weight for calibration (a measured 250 mL of water = 250 g works great)
- [ ] PlatformIO (VS Code) or Arduino IDE
- [ ] Notion account

## Step 0: Notion setup (20 min) — do this first

1. Go to **notion.so/my-integrations** → **New integration** → name it "Feed Logger" → copy the **Internal Integration Secret** (starts with `ntn_` or `secret_`)
2. In Notion, create a new database (table) called **Feed Log** with these properties:
   - `Name` (title) — auto-exists
   - `Start` — type **Date** (enable "include time")
   - `End` — type **Date** (include time)
   - `Duration (min)` — type **Number**
   - `Volume (mL)` — type **Number**
   - `Notes` — type **Text**
3. Open the database as a full page → click the **•••** menu → **Connections** → add your "Feed Logger" integration
4. Copy the **database ID** from the URL: `notion.so/<workspace>/<DATABASE_ID>?v=...` — it's the 32-character hex chunk before the `?`

Full walkthrough with screenshots-worth-of-detail: [`software/README.md`](./software/README.md)

## Step 1: Solder the load cell to the HX711 (15 min)

The load cell has four thin wires. Solder them to the HX711's `E+ E- A+ A-` pads:

| Load cell wire (typical) | HX711 pad |
|--------------------------|-----------|
| Red | E+ |
| Black | E- |
| White | A- |
| Green | A+ |

Wire colors vary by manufacturer — check your load cell's datasheet. If readings come out negative or backwards later, swap A+ and A−.

## Step 2: Wire everything to the ESP32 (15 min)

| HX711 | ESP32 |
|-------|-------|
| VCC | 3.3V |
| GND | GND |
| DT (DOUT) | GPIO 16 |
| SCK | GPIO 17 |

| OLED | ESP32 |
|------|-------|
| VCC | 3.3V |
| GND | GND |
| SDA | GPIO 21 |
| SCL | GPIO 22 |

| Button | ESP32 |
|--------|-------|
| One leg | GPIO 25 |
| Other leg | GND |

(Optional 2nd button for tare/calibrate: GPIO 26 ↔ GND.)

Full details: [`hardware/wiring.md`](./hardware/wiring.md)

## Step 3: Configure + flash (20 min)

1. Open `firmware/` in VS Code (PlatformIO)
2. Copy `firmware/src/config.h.example` → `firmware/src/config.h`
3. Fill in:
   ```cpp
   #define WIFI_SSID      "YourWiFi"
   #define WIFI_PASSWORD  "YourPassword"
   #define NOTION_TOKEN   "ntn_..."
   #define NOTION_DB_ID   "your32charhexdatabaseid"
   #define GMT_OFFSET_SEC (-5 * 3600)   // Eastern Time. DST handled below.
   #define DST_OFFSET_SEC (3600)
   ```
4. Build → Upload → open serial monitor (115200 baud)
5. You should see Wi-Fi connect, NTP sync, and `HX711 ready`

## Step 4: Calibrate once (10 min)

1. With nothing on the stand, **hold the tare/calibrate button while pressing reset** (or follow the serial prompt) to enter calibration mode
2. The OLED/serial says "Empty stand — taring." Leave it empty, wait
3. It says "Place known weight: 250 g." Put your known weight on
4. It computes and **saves the calibration factor to flash** (persists across reboots)
5. Remove the weight — the display should read ~0 g

Detailed calibration: [`docs/build-guide.md`](./docs/build-guide.md) § "Calibration."

## Step 5: Test a fake feed (10 min)

1. Put a water bottle on the stand
2. Tap the button → OLED shows "Feeding…"
3. Pour out ~50 mL of water (simulating a feed)
4. Put the bottle back, tap the button → OLED shows "Fed ~50 mL"
5. **Check Notion** — a new row should appear with start/end/duration/volume

If the row doesn't appear, see [`docs/troubleshooting.md`](./docs/troubleshooting.md) § "Notion."

## Step 6: Print + mount the stand (parallel)

While testing on the breadboard, print a load-cell scale stand (see `design/cad/README.md`). Mount the load cell **cantilever-style** — one end to the base, the other to the platform, with a gap so it can flex. This is the one mechanical detail that matters.

You're done. Tap start, feed, tap stop — the log writes itself.
