# Assembly

Physical assembly. The **load cell mounting** is the one part that determines whether this works at all, so it gets the most detail.

> **Many bar load-cell kits include the mount.** Especially 5 kg kits, which often ship with the cantilever hardware: 2 discs, nylon guide columns, and 2 × M3×10 screws. Those parts *are* the mount: they sandwich the bar between two discs with the columns as spacers, which creates the correct cantilever + air gap. If yours does, most of the mechanical work below is already solved in the box, and you mainly need a base to sit it on and a flat surface for the bottle.

## Tools

- Soldering iron + solder (for load cell → HX711)
- Small Phillips screwdriver
- If your kit includes mounting hardware: 2 discs, nylon guide columns, M3×10 screws
- A stand: the printed V2 stand (see `design/cad/README.md`), a remix, or improvise with what you have
- For the V2 stand: 2 mm, 2.5 mm and 4 mm hex keys

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
- **Do not press the white latex/sealed part** of the cell directly: it protects the strain gauge.

**If your kit came with the disc-and-column hardware, you don't build this from scratch.** The 2 discs + nylon columns + M3 screws assemble the bar in exactly this cantilever arrangement: one end of the bar screws to the bottom disc, the other end to the top disc, with the columns holding the gap. That sub-assembly *is* the cantilever. Then you just need to (a) sit the bottom disc on a stable base and (b) put a flat surface on the top disc for the bottle. A MakerWorld "load cell scale" print works too. If your kit has **no** mounting hardware, skip the disc-and-column steps below and use a printed stand: for the V2 stand, follow [Assembling the V2 stand](#assembling-the-v2-stand).

## Assembly order

### Step 1: Solder load cell to HX711

1. Tin the four HX711 pads (E+ E− A+ A−)
2. Solder the load cell wires per `hardware/wiring.md` (red→E+, black→E−, white→A−, green→A+; verify against your datasheet)
3. Keep the joints clean; no bridges

### Step 2: Assemble the load cell (using the kit hardware)

1. Note the **arrow** on the bar — it points in the direction force is applied (down in use).
2. Screw **one end** of the bar to one disc, and the **other end** to the second disc, using the nylon columns as spacers and the M3×10 screws — so the bar is sandwiched between the two discs with a clear gap. (This is the standard bar-cell-kit assembly; if a printed paper guide came with it, follow that.)
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

## Assembling the V2 stand

If you printed the V2 stand from [`design/cad/`](../design/cad/README.md), it replaces steps 2 and 3 above: the cantilever is built into the parts. Solder and wire everything on the bench first (steps 1 and 4) and confirm a reading before anything goes in the case.

Screws are listed in [`design/cad/v2/README.md`](../design/cad/v2/README.md#hardware): four M3x14 and one M4x10 button heads, two M5x25 socket heads, and a 20 mm x 1.5 mm washer. Check your load cell's threads before buying: the stand assumes M5 at the fixed end and M4 at the free end.

1. **Load cell into the base.** Arrow pointing down. Sit the fixed end on the boss at the end of the base opposite the display, with the free end pointing toward the display end. Fit the two M5 screws up through the underside into the cell. The free end must not touch anything.
2. **Electronics into the base.** Place the breadboard so the OLED and both buttons will sit under their openings in the lid, and dry-fit the lid to check. Run the USB cable out through the notch in the back wall, so the lid traps it.
3. **Collar into the lid.** Press it in from the top; the chamfer on its spigot leads it in. Add a dab of glue so it cannot work loose. It carries no load, but if it moves it can lean on the pan.
4. **Lid onto the base.** Seat it on the ledge inside the walls, then fit the four M3 screws up through the underside into the lid's standoffs. They cut their own thread in the plastic, so stop at snug or they strip.
5. **Pan onto the load cell.** Put the washer on the free end, the pan on the washer, and fit the M4 screw down through the pan into the cell. Its head sits below the floor of the bottle recess.
6. **Check nothing touches.** Look all round the collar and under the pan's edge: the pan and the free end must touch nothing but each other. Press the pan. It should give a fraction of a millimetre and spring back. Rubbing anywhere is a second load path, and the scale will read low rather than fail.

Calibrate (step 5 above) with the stand fully assembled, since closing the case can shift the zero.

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
