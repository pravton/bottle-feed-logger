# Troubleshooting

---

### Problem: HX711 "NOT responding" at boot

**Likely cause:** Wiring error or wrong pins.
**Fix:**
1. Confirm DT→GPIO 16, SCK→GPIO 17, VCC→3.3V, GND→GND.
2. Check the load cell's four wires are soldered to E+/E−/A+/A− with no bridges.
3. Try swapping DT and SCK if you mixed them up.
4. Confirm the HX711 board has power (measure 3.3V across its VCC/GND).

---

### Problem: Weight readings are negative

**Likely cause:** Load cell signal pair reversed, or arrow pointing up.
**Fix:**
1. Swap the **A+ and A−** wires at the HX711.
2. Or confirm the load cell's force arrow points **down**.
3. Quick software workaround: negate the value (multiply calibration factor handling by −1) — but fixing the wiring is cleaner.

---

### Problem: Readings are wild / jumpy / never settle

**Likely cause:** Bad mount (no air gap), vibration, or long load cell wires.
**Fix:**
1. Verify the load cell is **cantilever-mounted with a real air gap** — this is the #1 cause. Press the platform; it should deflect slightly and return.
2. Make sure nothing rubs between platform and base.
3. Put the stand on a solid, non-vibrating surface.
4. Increase `SAMPLES_PER_READING` (e.g. 10 → 20).
5. Shorten the load cell wires; keep the HX711 close to the cell.

---

### Problem: Calibration gives a crazy factor or wrong readings

**Likely cause:** Weight placed too early/late, or mount flexing inconsistently.
**Fix:**
1. Re-run calibration; place the known weight only when the OLED says to, and keep still.
2. Use an accurately known weight (a measured 250 mL of water = 250 g; or a scale-verified object).
3. Confirm the empty tare happened with truly nothing on the platform.
4. Check the mount air gap.

---

### Problem: Empty stand reads ~0 but a known weight is off by a constant factor

**Likely cause:** Calibration factor slightly wrong.
**Fix:** Recalibrate. If 250 g reads as 270 g, your factor is off by ~8%; one clean recalibration fixes it.

---

### Problem: Wi-Fi won't connect

**Likely cause:** 5 GHz network, wrong password, weak signal.
**Fix:**
1. ESP32 is **2.4 GHz only** — confirm the SSID is 2.4 GHz.
2. Re-check the password quoting in `config.h`.
3. Move closer to the router to rule out signal.

---

### Problem: Timestamps wrong / showing 1970 / wrong hour

**Likely cause:** NTP didn't sync, or time-zone offset wrong.
**Fix:**
1. Confirm "NTP time synced" appears in serial; the firmware blocks feed start until time is valid.
2. Check `GMT_OFFSET_SEC` (−5×3600 for Eastern) and `DST_OFFSET_SEC` (3600).
3. If the hour is off by exactly 1, it's a DST mismatch — adjust `DST_OFFSET_SEC` for the season, or accept the 1-hour edge around DST changes.

---

### Problem: Notion returns an error (no row appears)

**Likely cause:** Integration not shared with the database, wrong DB ID, or property-name mismatch.
**Fix:**
1. **Most common:** open the database → ••• → Connections → add your integration. Without this, you get a permission/404 error.
2. Read the serial monitor — the firmware prints the HTTP code and Notion's error body, which usually names the exact problem.
3. Confirm every `PROP_*` in `config.h` matches your Notion column names **exactly** (including capitalization and the "(min)"/"(mL)" suffixes).
4. Confirm `NOTION_DB_ID` is the 32-char ID from the database URL, not a view or page ID.
5. Confirm the date properties have **"include time"** enabled.
6. Run the `curl` test from `software/README.md` to isolate device-vs-cloud.

---

### Problem: Notion returns 401 Unauthorized

**Likely cause:** Wrong or expired token.
**Fix:** Re-copy the Internal Integration Secret from notion.so/my-integrations into `NOTION_TOKEN`. Regenerate it if needed.

---

### Problem: Notion 400 "validation_error" mentioning a property

**Likely cause:** Property name or type mismatch.
**Fix:** The error names the property. Make the Notion column type match what the firmware sends (Start/End = Date with time, Duration/Volume = Number, Notes = Text, Name = Title).

---

### Problem: Volume logs as far too small / negative on real feeds

**Likely cause:** Bottle was topped up mid-feed, or you tapped "stop" before setting the bottle back.
**Fix:**
1. Always set the bottle back on the stand before tapping stop.
2. Don't add milk mid-feed; if you must, stop and start a new feed.
3. The `MIN_FEED_ML` guard rejects obviously-wrong tiny/negative values.

---

### Problem: Telegram not sending (when enabled)

**Likely cause:** `ENABLE_TELEGRAM` not set, wrong token/chat ID, or 401.
**Fix:**
1. Set `ENABLE_TELEGRAM 1` and rebuild.
2. Verify token + chat ID; message the bot once from your phone first.
3. A 401 means a bad token — regenerate via @BotFather (same as the earlier bot issue).

---

### Problem: Device crashes / reboots after hours

**Likely cause:** Memory leak or power issue.
**Fix:**
1. Watch `heap=` (add to loop if needed) — if it declines steadily, update libraries.
2. Use a solid 5V/1A wall adapter, not a flaky hub.
3. As a cheap workaround, add a daily `ESP.restart()`.
