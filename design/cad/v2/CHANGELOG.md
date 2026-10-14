# Changelog

Versions of the printed stand. The firmware is versioned separately.

## 2.0.0-beta.1 (unreleased)

The first parametric version. It rebuilds V1, the hand-modelled prototype that
was printed and used, as a Fusion model generated from a parameter table.
Verified in CAD, not yet printed.

### Changed from V1

- **Four parts instead of three.** The collar is new: it hides the load cell,
  keeps spills out of the opening around it, and its top is an overload stop
  that catches the pan before the cell can yield. It is a separate part so that
  every part prints flat without supports.
- **Bottle locating recess in the pan**, so the bottle goes back in the same
  place between the before and after weighings. Corner loading does not cancel
  out of a before-minus-after reading, so this matters more than it looks.
- **Pan outline** reproduced from V1 as two overlapping circles, which keeps it
  clear of the buttons.
- **Lid** skin is 2.4 mm instead of V1's 1.0 mm, then hollowed from underneath
  to 0.9 mm between ribs, so it is stiff without being heavy.
- **Lid fastened with four M3 screws from underneath** into standoffs that stop
  short of the floor, so the rebate ledge alone seats the lid.
- **Load cell screwed in from underneath**, heads buried in counterbores.
- **Uniform 2.4 mm wall.** V1's was 4.75 mm on two sides and 5.00 mm on the
  other two.
- **Every cutout chamfered**, with a lead-in on the collar so its press fit
  goes in instead of jamming.
- Display aperture, buttons, load-cell holes and cable notch at V1's measured
  positions. The OLED recess under the lid is gone: the module had no way in.

### Added

- Screw lengths derived from the geometry (`tests/fasteners.py`).
- Export writes one STL and 3MF per part plus an assembly STEP, with a manifest
  recording the version, the git commit and a digest of every parameter value.
- Offline checks that run in CI, including a sweep of all 72 driving parameters
  to both ends of their range.

### Known gaps

- Not yet printed or assembled.
- Six dimensions are estimates: bottle footprint, breadboard height, component
  height, load cell deflection, length and hole-to-hole span.
- Load cell free-end thread (M4) is inferred from V1, not measured.
