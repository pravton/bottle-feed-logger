# Bill of Materials

Prices approximate, USD unless noted. `[Needs verification]` = confirm before buying.

---

## Electronics

### ESP32 development board
- **Item:** ESP32 DevKit V1 (38-pin)
- **Qty:** 1 · **Required:** Yes · **Status:** ~$5â8 (commonly on hand)
- **Notes:** 30-pin variant fine. Avoid S2/C3/CAM unless you adapt the firmware.

### Load cell
- **Item:** 1 kg bar-type load cell (recommended). A 5 kg bar cell also works (slightly coarser, but plenty for ±5 mL) and often comes as a kit with the mount.
- **Qty:** 1 · **Required:** Yes
- **Est:** $2–6 · **Where:** sold as a kit with the HX711 + mounting hardware
- **Notes:** Many bar-cell kits bundle the HX711, 2 discs, nylon guide columns, M3×10 screws, and a Dupont cable. Resolution after averaging is ~1-2 g, well within ±5 mL. A 1 kg cell is a touch finer; a 5 kg cell has more headroom.

### Load cell amplifier
- **Item:** HX711 module
- **Qty:** 1 · **Required:** Yes
- **Est:** $1–2 · **Where:** same as load cell
- **Notes:** Green or red board, both fine. A version with screw terminals avoids soldering the cell.

### Display
- **Item:** SSD1306 0.96" I2C OLED, 128×64
- **Qty:** 1 · **Required:** Yes
- **Est:** $4–7 · **Notes:** addr usually 0x3C; firmware tries 0x3D too.

### Button(s)
- **Item:** Momentary tactile push button (6mm), or a larger arcade-style button for feel
- **Qty:** 1 (MVP) or 2 (adds tare/calibrate without reflashing)
- **Est:** $0.50–2 · **Notes:** internal pull-ups used; no resistor needed.

---

## Prototyping / power

- **Half-size breadboard** — 1 — $3–5
- **Dupont jumper wires (M-F, F-F)** — 1 set — $3–5
- **USB data cable** (micro or USB-C to match your ESP32) — 1 — $3 — *charge-only won't work*
- **5V/1A USB wall adapter** — 1 — $5–8

---

## 3D printing

- **PLA filament** — ~30–60 g — ~$1 from a spool — for base + platform. (Consider a wipeable top surface or a silicone coaster; see safety-notes.)

---

## Tools (one-time)

- Soldering iron + solder (for load cell → HX711)
- Computer + PlatformIO/Arduino IDE
- Small screwdriver / hex key for load cell screws
- Multimeter (optional, power-rail checks)
- A known calibration weight (a measured 250 mL water = 250 g, or scale-verified object)
- 3D printer or print service

---

## Consumables

- M4 / M5 screws for the load cell (often included with the cell)
- Double-sided tape (mount HX711)
- Optional: silicone coaster for the platform (wipeable, food-friendly)

---

## Optional upgrades (Phase 2+)

- Second/third buttons for diaper + sleep logging — ~$1
- Slide switch for feed-type tag — ~$0.50
- LiPo + TP4056 charger for portability — ~$6
- Larger / e-paper display — $15–25
- Raspberry Pi Zero 2 W for summaries/dashboard — ~$15

---

## Total cost

| Scenario | USD |
|----------|-----|
| New parts beyond an ESP32 + OLED | **~$8–12** |
| New parts (also buying OLED + breadboard + wires) | ~$20–28 |
| Phase 2 additions | +$5–25 |
