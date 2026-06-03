# Bottle Feed Logger

> A weighing bottle stand that automatically logs how much your baby drank, when
> the feed started, and how long it took, straight to a Notion database. No more
> one-handed phone tapping at 3am.

A 3D-printed stand with a load cell weighs the bottle. You tap a button when a
feed starts and again when it ends; the device works out the **volume consumed**
(weight before minus weight after) and the **duration**, then logs the feed to
Notion. A small OLED shows live weight and the last feed, and real wall-clock
timestamps come from NTP.

## The key insight

Because it measures **start weight minus end weight**, and both readings include
the bottle itself, the **bottle's weight cancels out**. You never tare per bottle
or tell it which bottle you're using. Set it down full, feed, set it back down.

## At a glance

| | |
|---|---|
| Difficulty | Beginner to Intermediate |
| Cost | ~$15 in core electronics |
| Build time | A weekend, comfortably |
| Logs to | Notion (optional Telegram ping) |

## What you need

| Part | Qty | Est. cost |
|------|-----|-----------|
| ESP32 DevKit V1 | 1 | $5–8 |
| Load cell, 1 kg bar type | 1 | $2–5 |
| HX711 amplifier board | 1 | $1–2 |
| Momentary push button | 1–2 | $0.50 |
| SSD1306 0.96" OLED (I2C) | 1 | $4–7 |
| Breadboard + jumper wires | 1 set | $5 |
| USB power adapter | 1 | $5 |
| 3D-printed stand | 1 | ~$1 filament |

Full BOM, buying guide, and alternatives: [`bom/`](./bom/).

## Quick start

1. **Set up Notion first** (it has the most unknowns): create an integration, build
   a "Feed Log" database, share it with the integration, and copy the token and
   database ID. See [`software/README.md`](./software/README.md).
2. **Wire it up** on a breadboard: load cell to the HX711, then HX711 + OLED +
   button to the ESP32. See [`hardware/wiring.md`](./hardware/wiring.md).
3. **Flash the firmware**: copy `firmware/src/config.h.example` to `config.h`, fill
   in your Wi-Fi + Notion credentials, build and upload. See [`firmware/`](./firmware/).
4. **Calibrate once** with a known weight, then **bench-test a fake feed** and
   confirm a row appears in Notion.
5. **Print and mount the stand**, place it where bottles happen, and use it.

The fast path is in [`QUICK_START.md`](./QUICK_START.md); the full walkthrough is
in [`docs/build-guide.md`](./docs/build-guide.md).

## Documentation

| | |
|---|---|
| [`QUICK_START.md`](./QUICK_START.md) | Fastest path from parts to a logged feed |
| [`docs/build-guide.md`](./docs/build-guide.md) | Full step-by-step build |
| [`hardware/`](./hardware/) | Wiring, pinout, assembly |
| [`software/README.md`](./software/README.md) | Notion integration + database setup |
| [`bom/`](./bom/) | Bill of materials, buying guide, alternatives |
| [`design/cad/`](./design/cad/) | 3D-print notes + an OpenSCAD starter stand |
| [`docs/troubleshooting.md`](./docs/troubleshooting.md) | Tuning and fixes |
| [`docs/safety-notes.md`](./docs/safety-notes.md) | Safety |

## Firmware

A PlatformIO project in [`firmware/`](./firmware/) (ESP32 + HX711 + SSD1306). Your
secrets live in `firmware/src/config.h`, which is git-ignored. Copy the provided
`config.h.example` and fill it in.

## Safety

This is **not a medical device.** It logs feeds; it does not advise on them. Keep
liquids away from the electronics, power the HX711 from 3.3V (never 5V), and see
[`docs/safety-notes.md`](./docs/safety-notes.md).

## License

[MIT](./LICENSE).
