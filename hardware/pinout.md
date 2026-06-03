# Pinout Reference

ESP32 DevKit V1 (38-pin) GPIO assignments.

## Pin assignment table

| GPIO | Function | Connected to | Direction | Notes |
|------|----------|--------------|-----------|-------|
| VIN (5V) | Power in | USB adapter | — | Board power |
| 3V3 | Power out | HX711 VCC, OLED VCC | OUT | 3.3V rail |
| GND | Ground | HX711, OLED, buttons | — | Common ground |
| GPIO 16 | HX711 data | HX711 DT/DOUT | IN | Bit-banged; any GPIO works |
| GPIO 17 | HX711 clock | HX711 SCK | OUT | Bit-banged |
| GPIO 21 | I2C SDA | OLED SDA | I/O | Default I2C SDA |
| GPIO 22 | I2C SCL | OLED SCL | OUT | Default I2C SCL |
| GPIO 25 | Feed button | Button → GND | IN (pull-up) | Start/stop a feed |
| GPIO 26 | Tare/cal button | Button → GND | IN (pull-up) | Hold at boot = calibrate; tap = tare |

## I2C addresses

| Device | Address | Notes |
|--------|---------|-------|
| OLED (SSD1306) | `0x3C` | Some clones `0x3D` (firmware tries both) |

(The HX711 is **not** I2C — it uses its own two-wire DT/SCK protocol on GPIO 16/17.)

## Why these pins

- **GPIO 16/17** for HX711: free, not strapping pins, conventionally the UART2 pins but used here as plain GPIO (the HX711 protocol is bit-banged, so any free GPIO is fine).
- **GPIO 21/22** for I2C: the ESP32 default I2C pins.
- **GPIO 25/26** for buttons: free, no boot-strapping conflicts, support internal pull-ups.

## Pins available for Phase 2

| GPIO | Possible use |
|------|--------------|
| GPIO 4, 5, 18, 19, 23 | Extra buttons (diaper/sleep logging), status LED |
| GPIO 32, 33 | Analog in, touch |
| GPIO 27, 14 | Spare digital |

## Pins to avoid

| GPIO | Why |
|------|-----|
| GPIO 0 | Boot strap (BOOT button) |
| GPIO 2 | Boot strap / onboard LED |
| GPIO 6–11 | Wired to onboard flash |
| GPIO 12 | Boot strap (flash voltage) |
| GPIO 15 | Boot strap |
| GPIO 34–39 | Input-only (no pull-ups) — bad for buttons |

## ASCII sketch (relevant pins)

```
                 ┌───────────────┐
            3V3 ─┤ ● HX711 VCC    ├─ GND ── common ground
                 │   OLED VCC     │
        GPIO 16 ─┤ ● HX711 DT     ├─ GPIO 22 ─ OLED SCL
        GPIO 17 ─┤ ● HX711 SCK    ├─ GPIO 21 ─ OLED SDA
        GPIO 25 ─┤ ● Feed button  ├─ ...
        GPIO 26 ─┤ ● Tare button  ├─ ...
                 │   ESP32 DevKit │
             5V ─┤ ● USB power    ├─
                 └──────┬────────┘
                     USB micro
```
