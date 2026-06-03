# Hardware

Physical build docs for the Bottle Feed Logger.

## Files

- [`wiring.md`](./wiring.md) — wiring tables, power, safety checks
- [`pinout.md`](./pinout.md) — ESP32 GPIO assignments
- [`assembly.md`](./assembly.md) — physical assembly + load cell mounting

## Build summary

Three things connect to the ESP32:

1. **Load cell → HX711 → ESP32** (the scale; HX711 talks over two GPIOs)
2. **OLED** (I2C, two GPIOs)
3. **Button(s)** (one or two GPIOs to ground)

The only soldering is attaching the load cell's four thin wires to the HX711 (unless you bought a pre-wired kit). Everything else is Dupont jumpers.

## Skill level

**Beginner–Intermediate.** The mechanical load-cell mount is the one part to get right — see `assembly.md`.

## Power

~150–250 mA at 5V over USB. Any phone charger works.
