# V1 teardown: measured from the prototype meshes

Every figure here was recovered from the V1 STLs by contour slicing and
vertical ray probing (`tests/slice_features.py`, `tests/probe_z.py`), not
estimated. Reproduce any of it with the commands at the bottom.

Coordinates are in each file's own space. The base and lid share a frame:
X -5..145, Y -5..99, origin at the front-left outside corner offset by 5 mm.

## What the product actually is

An **electronics enclosure with a load-cell weighing platform**: a bottle
feeding scale. Three printed parts:

| Part | Role | Size (mm) |
|---|---|---|
| `base_bottle_feeder_v1` | Enclosure tray, holds electronics and the load cell | 150 x 104 x 23 |
| `top_bottle_feeder_v3` | Lid with display window and two buttons | 150 x 104 x 4.45 |
| `top_scale_v1` | Weighing pan the bottle sits on | 90 x 110 x 11 |

The 3MF is a Bambu Studio project with five plates, one object each. The file
naming records the iteration history: `top_bottle_feeder` -> `_v1` -> `_v3`,
`base_bottle_feeder_v1`, `top_scale_v1`. `base_cover_bottle_feeder.stl` and
`top_bottle_feeder_v3.stl` are byte-level the same geometry (both 5524
triangles), so the loose STL folder and the 3MF agree on the current lid.

`top_bottle_feeder_v2.stl` (6048 triangles) and `top_scale.stl` (45 x 87 pan)
are superseded iterations, kept for history.

## Base

| Feature | Measured | Notes |
|---|---|---|
| Outer footprint | 150.00 x 104.00 | Corner filleted; area 15594 mm2 |
| Overall height | 23.00 | Set by the load-cell boss, not the walls |
| Floor thickness | 3.00 | Solid Z 0.00..3.00 across the cavity |
| Internal cavity | 140.50 x 94.00 | |
| Wall, X sides | 4.75 | (150 - 140.5) / 2 |
| Wall, Y sides | 5.00 | (104 - 94) / 2 |
| Wall top | 15.50 | Lid seats here |
| Rebate lip top | 17.00 | Outer and inner lip either side of the lid seat |
| Divider wall | at X = 110, top Z 22.16 | Splits off a 30 mm bay at the right end |
| Load-cell boss | 28 x 17 footprint, Z 3.00..23.00 | 20 mm tall, centred near (126, 47) |
| Load-cell holes | 2 x dia 5.00 at (120, 47) and (135, 47) | **15.00 mm spacing**, on the Y centreline |
| Counterbore | dia 11.00 at BOTH (120, 47) and (135, 47) | 8 mm deep from the underside |

## Lid

| Feature | Measured | Notes |
|---|---|---|
| Outer footprint | 150.00 x 104.00 | Sits Z 15.55..20.00 |
| Overall depth | 4.45 | |
| **Top skin** | **1.00** | Z 19.00..20.00. See concerns below |
| Perimeter skirt | 4.44 deep | Drops to Z 15.56 |
| Display window | 19.00 x 31.00 at (17, 47) | Through the top skin |
| Display recess | dia 36.04 outer / 29.01 inner at (17, 47) | Annular, on the underside |
| Button holes | 2 x dia 18.00 at (29, 15.96) and (29, 78.04) | **62.08 mm apart**, symmetric about Y 47 |
| Button recess | dia 21.00, bore dia 13.00 | Shoulder for a cap flange |

## Scale pan

| Feature | Measured | Notes |
|---|---|---|
| Plate | 89.98 x 109.94 x **5.00** | Rounded paddle outline with a tab |
| Overall height | 11.00 | |
| Central boss | dia 20.0 tapering to dia 15.0, Z 5.00..11.00 | |
| Mount bore | dia 5.00 through | M5 |
| Counterbore | dia 8.00 on the underside | Screw head |

## What this tells us about the hardware

The load-cell screws enter from **underneath**: a dia 11 counterbore 8 mm deep in
the underside buries the head, and a dia 5 shank runs up through the boss to
thread into the cell's own tapped holes. That is the only way to reach them once
the case is closed, and it is why the boss has to be sized around the
counterbore rather than the screw.

The 2 x M5 holes at 15.00 mm centres on the base boss, paired with a single M5
on the pan, is the mounting pattern of a **straight-bar load cell**: the
common TAL220 / half-bridge family. One end bolts to the boss inside the case;
the free end carries the pan through the case opening. That needs confirming
against the actual part, but the pattern is distinctive.

Everything else could not be identified from the meshes, since the cavity has no
mounting features. It came from the build log instead: a half-size breadboard
carrying an ESP32 DevKit V1, an HX711 and an SSD1306 OLED, with two 12 mm
capped buttons. USB powered, no battery.

## Issues worth fixing in V2

Found while measuring, in rough priority order.

1. **The lid top skin is 1.00 mm over a 150 x 104 span.** Unsupported except at
   the rim. It will bow under a thumb press on the buttons, and the display
   window and two 18 mm holes remove material from the middle of the span where
   it is already weakest. This is the clearest structural weakness in V1.
2. **Wall thickness is not uniform**: 4.75 mm on the X sides, 5.00 mm on the Y
   sides. Almost certainly unintended: it comes from picking round numbers for
   both the 150 x 104 outside and the 140.5 x 94 cavity, which over-constrains
   the wall. In V2 the wall is the input and the outside is derived, so this
   cannot happen.
3. **The pan mounts on a single central M5.** One bolt is a poor moment
   connection: the pan can rotate about the screw, and an off-centre bottle
   applies a torque the joint resists only by friction. Worth reviewing against
   how the load cell's free end is actually meant to be attached.
4. **The pan overhangs the case.** It is 90 x 110 mounted off a boss at X 126,
   near the right-hand end of a 150 mm case. A full bottle placed toward the
   overhang applies a large tipping moment. Check the case does not lift.
5. **No PCB mounting features anywhere in the cavity.** No bosses, no standoffs,
   no ribs. The electronics are presumably taped or floating, which is fine for
   a prototype and not for production.
6. **A 0.5 mm full-height slit** in the left wall near X -3.5, Y 47. Either a
   deliberate feature whose purpose is not obvious from geometry, or a mesh
   artifact. Flagged rather than reproduced, and still unexplained.
7. **CORRECTED: V1 does have a cable exit.** An earlier pass through the mesh
   concluded there was none, on the strength of horizontal slices at Z 6, 9 and
   13 showing an unbroken wall ring. That was wrong: the opening is a **notch in
   the back (+Y) wall**, and slicing missed it because the notch is open at the
   top rather than being a closed hole, so it does not read as a break in the
   ring at the heights sampled. Confirmed against the Fusion source and by point
   containment on the solid:

   | Feature | Measured |
   |---|---|
   | Position | X 52 .. 67, centre **59.5** (offset -10.5 from case centre) |
   | Width | 15.0 |
   | Floor | Z **10.0**, with a 2 mm radius bottom |
   | Top | open to the wall top at Z 17 |

   Open-topped is the better design and V2 keeps it: the cable lays into the
   notch during assembly and the lid traps it, instead of having to be threaded
   through a closed port.
8. **The case is roughly three times the footprint the electronics need.**
   An ESP32 DevKit V1 and an HX711 side by side need about 95 x 36 mm including
   walls. V1 is 150 x 104. That is not waste: the footprint is set by **tipping
   stability and the pan**, not by the boards, and the V2 model now says so
   explicitly (`case_l` takes whichever of the two governs). Worth knowing
   because it means shrinking the case is a stability question, not a packaging
   one.
9. **Overall height is set by the boss (23 mm), not the walls (15.5 mm).** The
   load cell boss protrudes 6 mm above the lid. Intentional, but it means the
   lid needs a clearance opening around it, and that opening is a dirt and
   spill path straight into the electronics.

## The Fusion source

`base_bottle_feeder`, the original hand-modelled Fusion document, is the source V1 was printed from.
Reading it directly confirmed the mesh measurements and settled the ones the mesh
could not. Its state is consistent with exploratory work: **0 user parameters**,
13 bodies named `Body1`, `Body2`, `iedge`, `i-edge (1)`, `thred-center`, and
several sketches not fully constrained. Nothing in it was edited.

Positions read from its sketches, in the file's own corner-origin frame
(case spans X -5..145, Y -5..99, so the centre is 70, 47):

| Cutout | V1 position | Offset from centre |
|---|---|---|
| Load-cell screw holes, dia 5.0 | (120.0, 47.0) and (135.0, 47.0) | X +50.0, +65.0 |
| Load-cell counterbores, dia 11.0 | same two centres | both, not just one |
| Load-cell boss body | X 111.98..140.00, Y 38.86..55.99 | centre X +55.99, **Y +0.425** |
| Display centre | (17.0, 47.0) | X -53.0, Y 0 |
| Button centres, bore dia 13.0 | (29.0, 15.958) and (29.0, 78.042) | X -41.0, Y +/-31.042 |
| Cable notch | X 52..67 at the +Y wall, floor Z 10.0 | X -10.5 |
| Corner screw posts, pilot dia 1.86 | (+/-72.5, +/-49.5) from centre | 2.5 in from the outer edge |

Two things worth noting from this. The **load-cell screws are not centred on
their own boss**: the boss centre is at X +55.99 but the screw midpoint is at
+57.5, a 1.5 mm discrepancy, and the boss is 0.425 mm off the Y centreline.
Both look like artefacts of unconstrained sketching rather than intent. V2
centres the screws on the boss and puts the boss on the centreline.

The **corner screw posts cannot be reproduced at V2's wall thickness.** V1 sits
them 2.5 mm in from the outer edge, which works because V1's wall is 5.0 mm:
the post is embedded in the wall. V2's wall is 2.4 mm, so the same absolute
position would put the post half outside the case. V2 therefore derives the
screw position inward from the cavity instead. Reproducing V1's exact corner
position requires setting `wall` back to 5.0.

## Reproducing these numbers

The V1 meshes are not kept in the repository. They are attached to the stand's
GitHub release as `bottle-feeder-v1-reference.zip`; unzip it here to get a
`bottle_feeder_v1/` folder and the commands below run as written.

```bash
python3 tests/analyze_stl.py bottle_feeder_v1/bottle-feeder-stl/*.stl
```

```bash
python3 tests/slice_features.py bottle_feeder_v1/bottle-feeder-stl/base_bottle_feeder.stl --z 0.5 5 10 16 20 22.5
```

```bash
python3 tests/probe_z.py bottle_feeder_v1/bottle-feeder-stl/base_bottle_feeder.stl --at floor=70,47 wall=-2.5,47 boss=126,52
```

### A caution on the slicer

`slice_features.py` links intersection segments into loops geometrically. Where
the mesh has coincident or internal faces it can emit partial chains, and a
partial chain's reported centroid and "circle" classification are meaningless.
Cross-check anything surprising with `probe_z.py`, which pairs ray crossings
and does not depend on loop winding. Every figure in the tables above was
confirmed by ray probing.
