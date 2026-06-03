# Safety Notes

A low-risk project, but a few things worth being deliberate about since it lives around an infant's food.

## What this device is / isn't

- **It is** a convenience logger: it records how much was in the bottle before and after a feed, and the times.
- **It is not** a medical device, a nutrition authority, or a feeding recommender. It logs numbers; you and your pediatrician interpret them.
- Don't make feeding decisions purely on its readings — it's a tracking aid, not a clinical instrument. If a number looks alarming, trust your own observation and your pediatrician over the gadget.

## Food hygiene (the most relevant one here)

- The platform will catch milk/formula drips. **Make it wipeable** — smooth PLA, sealed with a food-safe finish, or simply put a silicone coaster on top that you can wash.
- Standard PLA is porous and not formally food-safe, and 3D prints have crevices that harbor bacteria. **Don't let the bottle's feeding surfaces (nipple, rim) touch the printed platform.** The bottle sits upright; only its base contacts the stand. Keep it that way.
- Clean the platform regularly like any kitchen surface.
- Keep liquid out of the electronics — a raised lip or a coaster prevents drips running into the HX711/ESP32.

## Electrical

- Low voltage throughout (5V USB in, 3.3V logic). No mains wiring you build yourself.
- Use a name-brand 5V USB adapter.
- Power off before changing wiring.
- HX711 on 3.3V (protects the ESP32's non-5V-tolerant GPIO).
- Keep the device away from sinks and wet areas; it's not water-resistant.

## Physical

- Keep cords out of reach — infants become grabby fast. Route and strain-relieve the USB cable.
- Place the stand where it won't be pulled down onto anyone.
- No small loose parts left where a baby could reach.

## Privacy / data

- Feed data is mildly personal and lives in **your private Notion workspace**.
- The **Notion integration token** is a secret — anyone with it can write to (and depending on capabilities, read) the connected database. Keep `config.h` out of public repos (it's gitignored).
- The device only makes **outbound** HTTPS calls (Notion, NTP, optional Telegram). It isn't a server and accepts no inbound connections in v1.
- v1 skips TLS certificate validation (`setInsecure()`) for simplicity — fine on a home network; harden with a pinned cert if you care.

## A gentle note on tracking

Feed logging is genuinely useful, but it can also become a source of anxiety if every number feels like a test you're passing or failing. The goal here is to *reduce* mental load — to stop doing math at 3am — not to add pressure. If you ever notice the log making feeds more stressful rather than less, that's a sign to lean on it loosely (or pause it), not to chase perfect data. Babies and parents both do fine without complete spreadsheets.
