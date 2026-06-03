# 3D Design — Stand

The stand has two printed parts: a **base** (holds the electronics, sits on the counter) and a **platform** (the bottle sits on this). The load cell bridges them in a cantilever.

> **Heads-up for your 5 kg kit:** it already includes the cantilever hardware (2 discs + nylon columns + M3 screws). That assembly handles the load-cell mounting, so you may not need precise printed mounting bosses at all — you mainly need a stable base under the bottom disc and a flat bottle surface on the top disc. The printed parts below are then optional/cosmetic. If you do print, set `cell_hole_dia = 3.4` (M3) in the OpenSCAD file.

## Two ways to get the stand

### Option A — Remix a MakerWorld model (easiest)

The mounting geometry is the tricky part, and kitchen-scale models already solve it. Search MakerWorld / Printables / Thingiverse for:

- `load cell scale stand`
- `HX711 kitchen scale`
- `load cell platform 1kg`
- `bottle scale` / `coffee scale` (coffee-scale builds are basically this project)

Pick one sized for your **1 kg bar cell** and matching its screw holes. Coffee-scale enclosures are an especially good match — same sensor, same cantilever, similar size.

### Option B — Print the included OpenSCAD starter

[`bottle-feed-logger-stand.scad`](./bottle-feed-logger-stand.scad) is a parametric base + platform with the cantilever mounting bosses, air gap, a bottle lip, and a channel for the HX711 + wires. **Measure your load cell and set the parameters at the top**, then render and export STLs.

Key parameters to set:
- `cell_length`, `cell_width`, `cell_height` — your load cell's dimensions
- `cell_hole_spacing` — distance between the mounting holes on each end
- `cell_hole_dia` — screw clearance (e.g. M4 ≈ 4.5 mm, M5 ≈ 5.5 mm)
- `platform_size` — top platform footprint (default 90 mm; fit your bottle base)
- `air_gap` — clearance so the cell can flex (default 4 mm)

## The one rule

However you get the stand, the load cell **must be cantilever-mounted with an air gap** — one end to the base, the other to the platform, nothing supporting the middle. See `hardware/assembly.md` for the diagram. This is the difference between accurate readings and garbage.

## Print settings (guidance)

| Setting | Value | Why |
|---------|-------|-----|
| Material | PLA (or PETG) | PLA is fine indoors; PETG if it'll see warmth/moisture |
| Layer height | 0.2 mm | Standard |
| Infill | 30–40% | Rigidity matters — a flexy base adds noise |
| Walls | 3+ perimeters | Stiffness |
| Supports | Only for the wire channel/overhangs | Mostly support-free |
| Orientation | Flat faces down | Strength + clean top surface |

## Food-contact note

PLA isn't formally food-safe and prints have crevices. Only the **base of the bottle** touches the platform — keep nipples/rims off it. Make the top **wipeable** (smooth top layer, a food-safe sealant, or just set a **silicone coaster** on the platform). See `docs/safety-notes.md`.

## Files in this folder

- `README.md` — this file
- `bottle-feed-logger-stand.scad` — parametric OpenSCAD starter (base + platform)
- (export your STLs here once rendered)

## Status

Not yet printed. Decide Option A vs B, then print in parallel with the bench build.
