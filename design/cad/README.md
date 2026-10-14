# 3D design: the stand

The stand holds the electronics and the load cell, and gives the bottle somewhere
to sit. There are three ways to get one, from least to most work.

## Option 1: the V2 stand (recommended)

[`v2/`](./v2/) is the stand from the build log photos, as a parametric Fusion
model: a base for the breadboard and load cell, a lid with the display window and
two buttons, a collar that hides the load cell, and the pan the bottle sits on.
Four parts, and all of them print without supports.

- **Printable files** (one STL per part, plus an assembly STEP) are attached to
  each [release](https://github.com/pravton/bottle-feed-logger/releases), not
  kept in the repo.
- **How to print each part, which screws to buy, and what has been tested:**
  [`v2/README.md`](./v2/README.md).
- **Assembly:** [Assembling the V2 stand](../../hardware/assembly.md#assembling-the-v2-stand).

> **2.0.0-beta.1 is verified in CAD but has not been printed yet.** It is
> derived from V1, which was printed and used daily. Treat the first print as a
> test fit.

It is sized for a 1 kg bar load cell (13 x 13 mm, M5 thread at one end and M4 at
the other), a half-size breadboard (55 x 84 mm) and two 12 mm capped buttons. If
your parts differ, change the parameters and rebuild it in Fusion: every size
comes from one table, and [`v2/README.md`](./v2/README.md#changing-the-design)
explains how.

## Option 2: remix a scale model

The mounting geometry is the tricky part, and kitchen-scale models already solve
it. Search MakerWorld, Printables or Thingiverse for `load cell scale stand`,
`HX711 kitchen scale`, `load cell platform 1kg`, or `coffee scale` (coffee-scale
builds are basically this project). Pick one sized for your **1 kg bar cell** and
matching its screw holes.

## Option 3: the OpenSCAD starter

[`bottle-feed-logger-stand.scad`](./bottle-feed-logger-stand.scad) is a simple
parametric base and platform with cantilever mounting bosses, an air gap and a
bottle lip. It is generic and is not maintained alongside V2, but it needs only
free software, and it is a quick way to fit a load cell with different holes.
Measure your load cell and set the parameters at the top:

- `cell_length`, `cell_width`, `cell_height`: your load cell's dimensions
- `cell_hole_spacing`: distance between the mounting holes at each end
- `cell_hole_dia`: screw clearance, e.g. 4.5 mm for M4, 5.5 mm for M5
- `platform_size`: top platform footprint (default 90 mm; fit your bottle base)
- `air_gap`: clearance so the cell can flex (default 4 mm)

> **If your kit includes the cantilever hardware** (common with 5 kg bar kits:
> two discs, nylon columns and M3 screws), that assembly already handles the
> load-cell mounting, and any printed parts are mainly a base and a flat top. If
> you print this starter for it, set `cell_hole_dia = 3.4` (M3).

## The one rule

However you get the stand, the load cell **must be mounted as a cantilever with
an air gap**: one end fixed to the base, the other carrying the platform, nothing
supporting the middle. And **nothing may touch both sides**: if a cover, a screw
or a stiff wire bridges the fixed part and the moving part, the scale does not
fail, it quietly reads low. See [`hardware/assembly.md`](../../hardware/assembly.md).

## Print settings for options 2 and 3

The V2 stand has its own per-part guidance in [`v2/README.md`](./v2/README.md#printing).

| Setting | Value | Why |
|---------|-------|-----|
| Material | PLA (or PETG) | PLA is fine indoors; PETG if it will see warmth or moisture |
| Layer height | 0.2 mm | Standard |
| Infill | 30 to 40% | Rigidity matters: a flexing base adds noise |
| Walls | 3+ perimeters | Stiffness |
| Supports | Only where the model needs them | |
| Orientation | Flat faces down | Strength and a clean top surface |

## Food-contact note

PLA isn't formally food-safe and prints have crevices. Only the **base of the
bottle** touches the platform; keep nipples and rims off it. Make the top
**wipeable** (a smooth top layer, ironing, a food-safe sealant, or just a silicone
coaster on the platform). See [`docs/safety-notes.md`](../../docs/safety-notes.md).

## Files in this folder

- `README.md`: this file
- `v2/`: the V2 stand, a parametric Fusion model with its own tests and docs
- `bottle-feed-logger-stand.scad`: the generic OpenSCAD starter
