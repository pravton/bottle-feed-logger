# Build Guide

From parts on the desk to a feed logged in Notion. One weekend, comfortably.

> Read this once before starting. Do the **Notion setup first** (it has the most unknowns), then hardware, then calibration, then a real test.

## Tools

- Soldering iron + solder
- Computer + USB data cable
- VS Code + PlatformIO (or Arduino IDE)
- Breadboard + Dupont jumpers
- Small screwdriver / hex key for the load cell screws
- A **known weight** for calibration (a measured 250 mL of water = 250 g is perfect, or use labeled gym weights / a kitchen-scale-verified object)
- 3D printer or print service

## Safety precautions

- Power off before changing wiring
- HX711 on 3.3V, never 5V
- Keep liquid away from electronics (see `docs/safety-notes.md`)
- This is not a medical device — it logs, it doesn't advise

## Pre-build checklist

- [ ] Notion integration created, database built, **shared with the integration**, IDs copied
- [ ] Notion `curl` test returns a row (optional but recommended)
- [ ] Parts present (`bom/bill-of-materials.md`)
- [ ] PlatformIO installed
- [ ] Wi-Fi credentials + Notion token/DB ID in hand
- [ ] Known calibration weight ready

---

## Saturday: bench build

### Step 1 — Notion setup (do this first)

Follow `software/README.md` end to end: create the integration, build the **Feed Log** database with the six properties, share the database with the integration, copy the token and database ID. Run the `curl` test if you can — it isolates cloud problems from device problems.

### Step 2 — Solder the load cell to the HX711

Per `hardware/wiring.md`. Four wires: red→E+, black→E−, white→A−, green→A+ (verify against your load cell's datasheet). Clean joints, no bridges.

### Step 3 — Wire HX711 + OLED + button to the ESP32

| HX711 | ESP32 | | OLED | ESP32 | | Button | ESP32 |
|---|---|---|---|---|---|---|---|
| VCC | 3.3V | | VCC | 3.3V | | leg 1 | GPIO 25 |
| GND | GND | | GND | GND | | leg 2 | GND |
| DT | GPIO 16 | | SDA | GPIO 21 | | | |
| SCK | GPIO 17 | | SCL | GPIO 22 | | | |

Optional tare/cal button: GPIO 26 ↔ GND.

### Step 4 — Configure + flash

1. `cp firmware/src/config.h.example firmware/src/config.h`
2. Fill in Wi-Fi, `NOTION_TOKEN`, `NOTION_DB_ID`, confirm `PROP_*` match your columns, set time-zone offsets (Eastern is preset)
3. Build → Upload → open serial monitor (115200)
4. Confirm: `HX711 ready`, `WiFi OK`, `NTP time synced`, `Ready.`

### Step 5 — Calibrate (the important one)

The factory has no idea how your specific load cell + mount convert force to grams, so you calibrate once.

1. With the **stand empty**, hold the **tare/cal button (GPIO 26)** while pressing the ESP32 **reset** button → it enters calibration mode
2. OLED: "Remove all weight" → it tares the empty platform (saves offset)
3. OLED: "Place weight: 250 g" → place your known weight within a few seconds
4. It reads, computes the calibration factor, and **saves it to flash**
5. OLED: "Calibrated!" with the factor → remove the weight
6. Back in normal mode, an empty stand should read ~0 g and your known weight should read ~250 g

If the reading is **negative**, your load cell's signal pair is reversed — swap A+ and A− at the HX711 (or note it and re-run). If it's wildly off, re-check the mount has a real air gap.

> Calibration persists across reboots. You only redo it if you change the mechanical setup.

### Step 6 — Bench test a fake feed

1. Put a water bottle on the stand
2. Tap the feed button → OLED "Feeding…", elapsed timer counting
3. Pour out ~50 mL of water (simulating what the baby drank)
4. Put the bottle back, tap again → OLED "Fed ~50 mL"
5. **Check Notion** — a new row with start/end/duration/volume should appear within a few seconds

Verify the volume is within ±5 mL of what you poured (measure the poured water to check). If it's off by a scale factor, recalibrate. If timestamps are wrong, check the time-zone offsets and that NTP synced.

---

## Sunday: print + finalize

### Step 7 — Print the stand

While bench-testing, print a load-cell scale stand (see `design/cad/README.md` for MakerWorld search terms or the included OpenSCAD starter). The print must give the load cell a **cantilever mount with an air gap** — most scale-stand models do.

### Step 8 — Mount everything

Per `hardware/assembly.md`: load cell cantilevered between base and platform, HX711 close by, ESP32 + OLED + button placed for one-handed use. Re-verify the empty stand reads ~0 and your known weight reads correctly after mounting (the mount change can shift the tare — just tap the tare button).

### Step 9 — Place it where bottles happen

Counter, bottle station, or nightstand. Flat, stable, near power and Wi-Fi. Add a wipeable surface or coaster on the platform for milk drips.

### Step 10 — Use it for real

Next bottle: set it down, tap, feed, set it down, tap. Open Notion — your first real feed is logged. 

---

## Tuning over the first few days

| Symptom | Fix |
|---------|-----|
| Readings jumpy | Increase `SAMPLES_PER_READING`; make sure the surface doesn't vibrate; shorten load cell wires |
| Volume consistently off by a factor | Recalibrate with a more accurate known weight |
| Tiny negative volumes on quick feeds | Normal sensor noise; the `MIN_FEED_ML` guard ignores them |
| Empty stand drifts from 0 over hours | Tap tare occasionally, or rely on the per-feed subtraction (drift over one feed is tiny) |
| Wrong AM/PM or hour in Notion | Check `GMT_OFFSET_SEC` / `DST_OFFSET_SEC` |

## "Done" for the weekend

- [ ] Calibrated and reading accurately
- [ ] A real feed logged to Notion with correct time + volume
- [ ] Stand mounted and placed where you'll actually use it
