# Alternatives

Component and approach swaps, with trade-offs.

## Load cell rating

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **1 kg (recommended)** | Headroom for full bottle + glass; sub-gram resolution | — | **Pick this** |
| 500 g | Slightly finer resolution | Risk of overload with a heavy glass bottle + full feed | Only if plastic bottles only |
| 2 kg | Lots of headroom | Coarser resolution (still fine for mL) | Acceptable fallback |
| 5 kg | Robust; 5 kg kits often bundle the mount | Coarser resolution | 5 kg is fine; 10 kg+ is overkill |

## Amplifier

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **HX711 (recommended)** | Cheap, ubiquitous, great library support | — | **Pick this** |
| HX711 with screw terminals | No soldering | Slightly bulkier | Great if no soldering iron |
| NAU7802 | Better noise/precision, I2C | Less common, different library | Overkill here |

## Display

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **SSD1306 0.96" OLED (recommended)** | Cheap, crisp | Small | **Pick this** |
| SH1106 1.3" OLED | Bigger | Different init (minor code change) | Fine |
| No display | Cheapest | No at-a-glance status; rely on Notion/Telegram | OK if you don't want a screen |
| LED + buzzer only | Minimal | Less info | Minimalist option |

## Input

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **1 button (recommended MVP)** | Simplest | Recalibrate needs reflash (or add 2nd button) | **Pick this** |
| 2 buttons | Tare/calibrate without reflash | One more part | Nice if you have parts |
| Auto lift/return detection | No buttons at all | Complex, edge cases | Phase 2 |
| Capacitive touch pad | Sleek, wipeable | Tuning needed | Phase 2 |

## Microcontroller

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **ESP32 (recommended)** | Wi-Fi, plenty of GPIO | — | **Pick this** |
| ESP8266 | Cheaper, Wi-Fi | Fewer pins, tighter memory for TLS | Works, tighter |
| ESP32-C3/S3 | Modern, cheap | Pin map differs; adjust firmware | Fine with tweaks |
| Pi Pico W | Wi-Fi, cheap | Different ecosystem (rewrite firmware) | Not for this blueprint |

## Log destination

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Notion (recommended)** | Shared, filterable, structured history | Needs integration + token | **Pick this** |
| Google Sheets | Familiar, easy charts | Needs Apps Script or service auth | Solid alternative |
| Telegram only | Trivial, instant | No structured history | Good as a companion, not the record |
| Local SPIFFS + web page | No cloud | Less accessible, more code | Phase 2 nicety |

## Timekeeping

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **NTP (recommended)** | Free, accurate, no part | Needs Wi-Fi at boot (already required) | **Pick this** |
| DS3231 RTC | Works offline | Extra part + cost | Only if going offline |

## Stand

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **MakerWorld load-cell scale remix** | Mounting geometry solved for you | Find one matching your cell | **Easiest** |
| Included OpenSCAD starter | Parametric, fits your exact cell | You tweak + print | Great if you like CAD |
| Repurpose a cheap kitchen scale | Mount already correct | Gut it, fiddly | Hacky but works |
