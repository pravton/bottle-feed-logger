# Bottle Feeder V2: design specification

An infant bottle feeding **scale**: an electronics enclosure with a load-cell
weighing platform, a display and two buttons. See `docs/v1-teardown.md` for what
V1 actually is, measured.

The parametric model is the easy half of "production ready". This is the other
half: the requirements the geometry has to satisfy, and the evidence needed
before anyone spends money on tooling.

Status: **draft, for 2.0.0-beta.1.** V2 is verified in CAD and has not yet been
printed. Sections marked TBD are still open.

---

## 1. Scope and intended use

Confirmed from the build log at
`buildlog.pravton.com/projects/bottle-feed-logger`:

- **What it does.** Weighs the bottle before and after a feed, computes the
  volume consumed from the difference, and logs volume, duration and timestamps
  to Notion, with optional Telegram notification.
- **How it is used.** "Set it down full, feed, set it back down." The parent taps
  a button at the start and end. The bottle is **removed from the pan and
  replaced** between the two weighings.
- **Accuracy target.** Readings within **±5 mL** are considered acceptable.
- **Calibration.** One-time, against a known weight (250 mL water = 250 g). The
  factor is stored in flash. No per-bottle calibration.
- **Power.** USB adapter, no battery.
- **Problem solved.** Removes manual note-taking during night feeds.

This is a domestic logging device, not a medical or trade instrument. That keeps
it clear of legal metrology (OIML R76 / NAWI), which applies to trade use.
Worth confirming before making any accuracy claim on packaging.

Still TBD: whether the bottle sits on it unattended during a feed.

## 2. Accuracy and metrology

This is a measuring instrument, and it is the part most likely to be got wrong.

| Requirement | Target | Status |
|---|---|---|
| Accuracy | ±5 mL on a feed | Stated; not yet verified against corner error |
| Range | 0 to `load_capacity` (1.2 kg) | Under the 1 kg cell's rating: **see below** |
| Repeatability | TBD | Same bottle, removed and replaced |
| Corner load error | TBD | **The dominant risk: see below** |
| Drift over a feed | negligible | Cancelled by per-feed subtraction |

### Corner loading does not cancel here

This is the single most important mechanical finding, and it follows directly
from how the device is used.

Differential weighing cancels **drift**, because drift is slow relative to a
feed. It does **not** cancel **corner error**, because the bottle is lifted off
and put back down between the two weighings. If it comes back 20 mm from where
it started, the position-dependent error enters the result at full value, and
it enters a subtraction, so it lands directly on the reported volume.

Scale that against the target. A 250 mL feed at ±5 mL is a **±2%** budget, and
that budget has to cover everything. Corner error on an inexpensive bar cell
across a 110 mm pan can plausibly consume the whole of it on its own.

Mitigations, most effective first:

1. **A moulded locating recess on the pan**, so the bottle can only sit in one
   place. This is the highest-value change in V2 and it is nearly free.
2. Move the cell so the pan's centre of load sits over its measuring axis.
3. Keep the pan no larger than the bottle needs.
4. Calibrate the error out: only works if it is repeatable.

**Measure this before trusting the accuracy claim.** Put a known weight at the pan
centre, then at each edge, and record the spread, on V1 or on the first V2 print.
That number decides whether the recess is enough or the layout has to change. It
is an hour of work.

### Capacity

`load_capacity` is set to 1.2 kg but the cell is rated **1 kg**. Confirm the real
worst case: a full bottle plus the 90 x 110 x 5 mm pan is likely well under 1 kg,
but a 1 kg cell has no headroom for someone leaning on the pan.

**Overload protection.** A hard stop that limits travel before the cell yields.
Without one, a single overload silently ruins the calibration and the device goes
on reporting confident wrong numbers. In V2 the top of the collar is that stop:
it sits `overload_gap` (twice `load_cell_deflection`) below the pan, so the cell
reaches full scale first and an overload then lands on the collar. The stop is
only as good as `load_cell_deflection`, which is still a placeholder.

## 3. Load cases

| Case | Load | Notes |
|---|---|---|
| Working | up to `load_capacity` (1.2 kg) | Full bottle plus pan |
| Design | working x `load_safety_factor` (4.0) | Static, with margin |
| Overload stop | 2x full-scale deflection | Collar top; force set by `load_cell_deflection`, unmeasured |
| Abuse / lean | TBD | Adult hand pressing on the pan |
| Drop | TBD | Onto a hard floor, from counter height |
| Tipping | TBD | Bottle at the pan edge; the case must not lift |

Tipping deserves a real check. The pan overhangs the case in V1, so a full
bottle at the overhang applies a moment the case footprint has to resist.

## 4. Safety

An electronics device used one-handed, near an infant, around liquid.

- **Power.** USB powered, no battery. If one is ever added (the project BOM
  lists a LiPo and TP4056 as an optional later phase), it becomes the
  highest-severity item: an enclosure an infant cannot open without a tool,
  puncture protection, and a protected charge circuit.
- **Small parts.** Nothing that can detach (button caps especially) may be
  small enough to swallow. The caps are retained by a flange under the lid
  (`button_shoulder_dia`), which needs a pull test, not an assumption.
- **No sharp edges.** `min_edge_radius` (0.5 mm) on every reachable edge.
- **Stability.** It must not tip with a full bottle placed off-centre.
- **Liquid ingress.** Milk gets spilled at feeding time. See below.
- **Cable strangulation** if it is mains or USB powered near a cot.

### Candidate standards

Confirm applicability with a compliance specialist for the target markets. This
is a starting point for that conversation, not a determination:

- **EN 71-1 / ISO 8124-1**: mechanical and physical, small parts and sharp edges
- **16 CFR 1501**: US small-parts rule for children under 3
- **IEC 62368-1**: electrical safety for the electronics
- **IEC 62133**: lithium cell safety, only if a battery is added
- **EN 55032 / EN 55035** or **FCC Part 15**: EMC
- **CPSIA**: US, lead and phthalate content, tracking labels
- **EN 14350**: only if any part contacts milk

Note what is **not** here: this is a domestic scale, so it is very likely outside
legal metrology (OIML R76 / NAWI Directive), which applies to trade use. Confirm
that, because it changes what you may print on the box.

## 5. Ingress and cleaning

Milk will be spilled on this. Design for it rather than hoping.

- The load-cell boss passes through the lid, so there is an **opening straight
  into the electronics** around it. This was the main ingress path in V1. V2's
  answer is the raised collar (section 5c): spills on the lid run off it rather
  than into the opening.
- The lid should sit **proud with a drip lip**, so liquid runs off rather than
  into the seam.
- Buttons need sealing (a membrane or an over-moulded boot) or spills wick
  straight through the 13 mm bores.
- Every external surface wipeable with a cloth: no deep texture, no blind
  crevices, generous radii.
- **Nothing here should contact milk**, so food-contact certification is not
  needed for the case. Keep it that way: if a milk path ever gets designed in,
  the whole material and cleanability story changes.

## 5b. Assembly and fastening

Four M3 screws, entering from **underneath** and self-tapping into the lid.

- Standoffs hang from the lid and stop `screw_boss_gap` short of the floor, a
  fraction of the cavity depth (5 mm at present). They deliberately do not
  land on it: a standoff touching the floor fights the rebate ledge over which
  one seats the lid, and tolerance decides the winner. With the gap, the ledge
  is the only seat.
- The base floor has a **clearance** hole, not a threaded one. This matters: if
  the screw grips the base as well as the lid boss, it jacks the two parts apart
  instead of pulling them together.
- Heads are counterbored flush with the underside so the case sits flat.
  `floor_t` is derived as whichever is thicker: the structural floor, or enough
  material to bury the head and still leave `min_wall`. A taller screw therefore
  thickens the floor rather than breaking through it.
- Screw positions are derived inward from the walls, so they track the case size
  and are checked to clear the load-cell boss, the cable notch and the buttons.
- Every screw length is derived from the geometry, not chosen:
  `tests/fasteners.py` prints the list. At present: M3x14 button head (window
  12.2 to 15.3) for the lid, M5x25 socket head (22.5 to 28.0) for the load cell's
  fixed end, M4x10 button head (8.5 to 15.5) for the pan, and a 20 x 1.5 spacer.
  The load cell threads (M5 fixed, M4 free) are inferred from V1 and need
  confirming against the cell.

Open points:

- **Self-tapping into printed plastic has a limited number of cycles.** If the
  case will be opened repeatedly, use heat-set brass inserts instead. That is a
  parameter change (`screw_pilot_dia` becomes the insert's bore) plus a boss
  wall thick enough for the insert.
- Screws land in the cavity, so the final PCB positions must clear the four
  standoffs. Worth checking once the board outlines are confirmed.

## 5c. How the pan reaches the load cell

The load cell's fixed end bolts down onto the base boss, which rises through the
lid, so the bar sits above the lid. The pan sits on the cell's free end with a
spacer washer between them, and the stack is a chain of derived heights:

```
cell_seat_z    = floor_t + boss_h
cell_top_z     = cell_seat_z + load_cell_height
pan_assembly_z = cell_top_z + pan_spacer_h
```

so the pan always sits on the cell, whatever the cell's height. `boss_h` is the
taller of the measured 20 mm and whatever keeps the cell clear of the lid, so a
deeper cavity raises the cell rather than burying it.

A separate **collar** rises from the lid around the exposed run of the cell. It
hides the cell, keeps spills out of the opening, and its top is the overload
stop (section 2). It sits `overload_gap` below the pan and covers the top of the
cell, which is why `pan_spacer_h` is derived as `overload_gap + cell_hide_margin`
rather than chosen.

**Nothing may touch both the fixed and the moving side.** Any contact is a
second load path: the scale does not fail visibly, it reads low, goes non-linear
and shows hysteresis. `shroud_gap` (3 mm) separates the collar from the cell and
the pan all round, and the pan screw is limited in length so its tip cannot
reach the lid.

The pan screw head is sunk below the floor of the bottle locating recess
(`pan_cbore_depth`). If it stood proud, the bottle would rock on it.

## 5d. Print strategy

Four parts, each printed flat with **no support anywhere**. That constraint
drove the split, so it is worth recording why each part is shaped as it is.

| Part | Orientation | Why it works |
|---|---|---|
| Base | Floor down | Everything rises from the floor. Only two downward ceilings, both bridges over holes: dia 11 and dia 6, against a `bridge_max` of 15 |
| Lid | Top face down | Spigot and standoffs are the only features, both below the skin, so they point up. Bonus: the visible face gets the bed finish |
| Collar | Standing on its rim | An open-ended tube. Nothing overhangs |
| Pan | Bottom face down | A plain flat plate; recess and counterbore are pockets into the top. Iron the top face for the bottle-contact surface |

**The collar is a separate part for this reason and no other.** Joined to the
lid it put 18.6 mm of collar above the skin and 12.5 mm of standoffs below, so
whichever way up the lid was printed, one of them stood on the bed holding a
150 x 92 mm skin in the air and the whole part needed support.

It attaches by a press fit: a spigot one lid-skin deep, sized `fit_press`
oversize for an interference of about 0.10 mm. `fit_press` is bounded strictly
negative, because a collar that is a slip fit can work loose, lean on the pan
and short the load path.

Add a dab of glue on assembly. The collar carries no load, but it must not move.

## 5e. Edge breaking

Two parameters, applied last in the timeline so a broken edge reference costs a
chamfer and nothing else.

| Parameter | Value | Where | Why |
|---|---|---|---|
| `chamfer_cutout` | 0.6 | Lid cutouts, base counterbores, pan recess, pan outer edge | Breaks the sharp edges section 4 requires, and hides the FDM first-layer bulge that makes printed holes read as ragged |
| `chamfer_leadin` | derived, `collar_wall / 4` | Collar spigot | Functional. An interference fit with a square leading edge jams or shaves instead of entering |

`chamfer_cutout` cannot be set below `min_edge_radius`: these are precisely the
edges the safety section calls for, so the range is bounded by it rather than
left to judgement.

`chamfer_leadin` is derived from the wall it is cut into rather than chosen. A
fixed value big enough to be useful on a thick wall eats straight through a thin
one, which the range sweep demonstrated.

### The chamfer ceiling

`chamfer_cutout` is what you ask for; `chamfer_applied` is what the geometry
uses, clamped to `chamfer_headroom`. Ask for more than fits and you get the
largest that does, and the build says so. Previously the chamfer feature simply
failed and the chamfer disappeared, with nothing to explain why.

`chamfer_headroom` is the thinnest material at any chamfered edge:

| Constraint | Value | What it is |
|---|---|---|
| `lid_skin` | 2.40 | Material at the display window |
| `screw_head_h` | 1.80 | Depth of the base counterbores |
| `boss_wall` | **1.00** | Material beside the load-cell counterbore, in its boss |

The third was found by testing, not by reasoning. Reasoning from the lid and the
counterbore alone gave 1.80, and the geometry actually failed between 1.20 and
1.50: the dia 11 counterbore sits only `boss_wall` from the side of its boss, so
a wider chamfer breaks straight out. Worth remembering that the binding
constraint on a chamfer is rarely the face you are chamfering.

To raise the ceiling, raise whichever of the three is currently smallest.

Edges are selected geometrically on every build rather than stored, and openings
are told apart from the perimeter using **each body's own** bounding box. Using
the case outline instead meant the collar, being small and off centre, had every
edge classified as interior and its spigot lead-in was silently skipped.

## 6. Materials

Recommended production material: **ABS or PC/ABS**.

- Tough, dimensionally stable, good surface finish, easy to mould.
- Handles the drop case better than PLA or PETG.
- Not food contact, which is fine because nothing here touches milk.

The **pan** may deserve a different material or a soft over-mould: it needs to
be stiff (a flexing pan reads as noise) and grippy (the bottle must not slide).

For prototyping, keep printing. PLA is fine for form and fit. Note that PLA
softens around 60 C, so a prototype left in a car or near a steriliser will
distort: not a production concern, but a prototype-handling one.

## 7. Design for manufacture

Encoded in `params/process-profiles.json`, so switching profile re-tunes the
model.

- **Uniform wall.** `wall` is one parameter applied to all four sides. V1's
  4.75/5.00 split came from hardcoding both the outside and the cavity; here the
  outside is derived, so it cannot recur.
- **Draft.** `draft_angle` 1.5 deg on every mould-parallel face.
- **Ribs at 60% of nominal wall** (`rib_wall`) to stiffen without sink marks.
- **Shrinkage is the toolmaker's business.** CAD stays at nominal part size.
- **Gate and parting line** off cosmetic and user-contact surfaces.

## 8. Verification plan

| Stage | What it proves | Status |
|---|---|---|
| Parameter sweep rebuild | The model survives resizing across its range | automated, `validate.py` |
| Magic-number audit | No sketch dimension is hardcoded | automated, `validate.py` |
| V1 reconciliation | The model reproduces the working prototype | automated, `tests/check_v1_fit.py` |
| Geometry across ranges | Every part is coherent at every parameter's limits | automated, `tests/test_geometry_mock.py` |
| Fasteners | A stock screw length fits every hole | automated, `tests/fasteners.py --check` |
| First print and test fit | V2 prints support-free and assembles | **TBD, blocks 2.0.0 final** |
| Corner-load test | Reading does not change with bottle position | TBD, do this on V1 now |
| Calibration and linearity | The accuracy claim is real | TBD |
| Overload test | A hard stop protects the cell | TBD |
| Drop test | Survives the drop case | TBD |
| Spill test | Liquid on the lid does not reach the PCB | TBD |
| Sharp edge / small parts | Meets infant-contact requirements | TBD |

## 9. Open questions

1. Section 1, all of it: the intended use decides the accuracy claim.
2. Load cell: deflection at full scale, overall length and hole-to-hole span are
   still placeholders, and the threads (M5 fixed, M4 free) are inferred from V1.
3. Breadboard height and the height of what stands on it (`breadboard_h`,
   `component_stack_h`) are placeholders. Length and width are measured.
4. Volume and target cost, which decide printed versus moulded.
5. Target markets, which decide the standards list.
6. What the 0.5 mm slit in V1's left wall is for (teardown issue 6).
