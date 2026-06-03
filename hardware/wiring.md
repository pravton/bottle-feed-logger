# Wiring

## Overview

Two stages: the **load cell wires to the HX711** (soldered), and the **HX711, OLED, and button wire to the ESP32** (jumpers).

## Stage 1: Load cell → HX711 (soldered)

The load cell has four thin wires. Solder them to the HX711's measurement pads:

| Load cell wire (typical color) | HX711 pad | Notes |
|--------------------------------|-----------|-------|
| Red | E+ | Excitation + |
| Black | E− | Excitation − |
| White | A− | Signal − |
| Green | A+ | Signal + |

> **Confirmed for your kit:** the 5 kg kit's documentation specifies red→E+, black→E−, green→A+, white→A−, which matches the table above exactly. Solder it as labelled.
>
> If readings ever come out **negative or backwards**, swap A+ and A− (or just negate in software).

The HX711 has a `B+/B−` channel too — leave it unused.

## Stage 2: HX711 → ESP32

| HX711 pin | ESP32 pin | Wire color (suggested) | Notes |
|-----------|-----------|------------------------|-------|
| VCC | 3.3V | Red | **3.3V, not 5V** — keeps DT logic safe for ESP32 |
| GND | GND | Black | |
| DT (DOUT) | GPIO 16 | Yellow | Data |
| SCK | GPIO 17 | Green | Clock |

## Stage 3: OLED → ESP32 (I2C)

| OLED pin | ESP32 pin | Wire color | Notes |
|----------|-----------|------------|-------|
| VCC | 3.3V | Orange | |
| GND | GND | Black | |
| SDA | GPIO 21 | Blue | I2C data |
| SCL | GPIO 22 | White | I2C clock |

## Stage 4: Button(s) → ESP32

| Button | ESP32 pin | Notes |
|--------|-----------|-------|
| Feed button, leg 1 | GPIO 25 | Internal pull-up enabled in firmware |
| Feed button, leg 2 | GND | |
| Tare/calibrate button, leg 1 (optional) | GPIO 26 | Hold at boot = calibration mode |
| Tare/calibrate button, leg 2 (optional) | GND | |

No external resistors needed — the firmware uses the ESP32's internal pull-ups, so the button just shorts the pin to ground when pressed.

## Power requirements

| Rail | Source | Draw |
|------|--------|------|
| 5V (VIN) | USB wall adapter | ESP32: ~150–250 mA (Wi-Fi) |
| 3.3V (ESP32 LDO) | onboard regulator | HX711: ~1.5 mA, OLED: ~20 mA |

Total ~250 mA. A 5V/1A adapter is overkill in a good way.

## Safety checks before first power-on

- [ ] HX711 VCC goes to **3.3V**, not 5V
- [ ] Load cell solder joints are clean, no bridges between E+/E−/A+/A−
- [ ] OLED and HX711 share GND with the ESP32
- [ ] SDA→21, SCL→22 (not swapped)
- [ ] DT→16, SCK→17 (not swapped)
- [ ] Load cell is mounted (cantilever) before you trust any reading — see `assembly.md`
- [ ] No bare wire touching the load cell body

## Cabling tips

- Keep the **load cell wires short** — they carry a tiny analog signal and pick up noise over long runs. Mount the HX711 close to the load cell.
- The HX711→ESP32 digital lines (DT/SCK) can be longer without issue.
- Strain-relieve the load cell wires so movement of the platform doesn't flex the solder joints.

## Going permanent (Phase 2)

- Solder onto perfboard with female headers so the ESP32/OLED stay removable
- Add a 100 nF cap across the HX711 VCC/GND
- Mount the HX711 to the base with double-sided tape, wires dressed and strain-relieved
