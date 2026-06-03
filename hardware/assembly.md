# Assembly

Physical assembly. The **load cell mounting** is the one part that determines whether this works at all, so it gets the most detail.

> **If your kit is a 5 kg load-cell kit:** it typically ships with the cantilever mounting hardware — the bar cell, 2 discs, 5 nylon guide columns, and 2 × M3×10 screws. Those parts *are* the mount: they sandwich the bar between two discs with the columns as spacers, which creates the correct cantilever + air gap. So most of the "hard" mechanical part below is already solved in the box — you mainly need a base to sit it on and a flat surface for the bottle.

## Tools

- Soldering iron + solder (for load cell → HX711)
- Small Phillips screwdriver
- The hardware that came with your kit: 2 discs, nylon guide columns, M3×10 screws
- (Optional) 3D printed base + bottle platform (see `design/cad/README.md`) — or improvise with what you have

## The load cell mounting principle (read first)

A bar load cell measures weight by **bending slightly**. For it to bend, it must be mounted as a **cantilever**:

```
   PLATFORM (weight goes here)
   ════════════════════╗
                       ║  ← screws fix this END to the platform
   ┌───────────────────╨───┐
   │   load cell (the bar) │   ← air gap underneath so it can flex
   └───╥───────────────────┘
       ║  ← screws fix THIS end to the base
   ════╩═══════════════════
   BASE (sits on the table)
```

- **One end** bolts to the fixed base.
- **The other end** bolts to the platform that receives the weight.
- There must be an **air gap** between the two ends so the bar can actually bend. If the bar is fully supported underneath, it can't flex and you get garbage.
- The load cell has an **arrow** indicating the direction of force — it should point **down** (the direction the weight pushes).
- **Do not press the white latex/sealed part** of the cell directly (per your kit's instructions) — it protects the strain gauge.

**With your kit, you don't build this from scratch.** The 2 discs + nylon columns + M3 screws assemble the bar in exactly this cantilever arrangement: one end of the bar screws to the bottom disc, the other end to the top disc, with the columns holding the gap. That sub-assembly *is* the cantilever. Then you just need to (a) sit the bottom disc on a stable base and (b) put a flat surface on the top disc for the bottle. A MakerWorld "load cell scale" print also works if you'd rather, but the kit hardware alone gets you there.

## Assembly order

### Step 1: Solder load cell to HX711

1. Tin the four HX711 pads (E+ E− A+ A−)
2. Solder the load cell wires per `hardware/wiring.md` (red→E+, black→E−, white→A−, green→A+; verify against your datasheet)
3. Keep the joints clean; no bridges

### Step 2: Assemble the load cell (using the kit hardware)

1. Note the **arrow** on the bar — it points in the direction force is applied (down in use).
2. Screw **one end** of the bar to one disc, and the **other end** to the second disc, using the nylon columns as spacers and the M3×10 screws — so the bar is sandwiched between the two discs with a clear gap. (This is the standard 5 kg-kit assembly; if a printed paper guide came with it, follow that.)
3. The result is a little "scale": bottom disc = base side, top disc = where weight goes.
4. Confirm the **air gap** — the two discs must not touch each other anywhere except through the bar. Press gently on the top disc; it should deflect a fraction of a millimeter and spring back.
5. Sit the bottom disc on your base (or printed base); put a flat surface / printed platform on the top disc for the bottle to rest on.
6. **Don't press or pinch the white sealed section** of the bar.

### Step 3: Place the electronics

1. Mount the HX711 to the base (double-sided tape) near the load cell, wires strain-relieved
2. Place the ESP32 on a small breadboard or perfboard in the base
3. Mount the OLED where you can read it (front face of the base, or a small riser)
4. Mount the button(s) where a thumb can reach while holding a baby

### Step 4: Wire it up

Follow `hardware/wiring.md`. Power on via USB.

### Step 5: Calibrate

Hold the tare button while pressing reset to enter calibration mode (see `firmware/README.md`). Use your known weight.

## Fit checks before final assembly

- [ ] Platform floats on the load cell with a clear air gap
- [ ] Pressing the platform shows a reading change in the serial monitor
- [ ] Nothing rubs or binds the platform against the base
- [ ] OLED readable from your normal standing position
- [ ] Button reachable one-handed
- [ ] USB cable strain-relieved where it exits

## Mounting / placement

- Put the stand where you **prep and give bottles** — kitchen counter, bottle station, or nightstand
- A flat, stable, non-vibrating surface gives the cleanest readings
- Keep it away from the edge so it can't get knocked
- Near a power outlet (it's mains-powered) and within Wi-Fi range

## Hygiene note

The platform may get milk drips. Make the platform wipeable (smooth PLA, or a silicone coaster on top) and clean it like any kitchen surface. Don't let liquid run into the electronics — a slightly raised lip or a coaster on the platform helps. See `docs/safety-notes.md`.

## Irreversible steps (check twice)

- **Gluing the load cell** — use screws, not glue, so you can re-level/replace it
- **Cutting wires to length** — only after confirming layout
- **Soldering to perfboard** (permanent build) — confirm everything works on breadboard first
