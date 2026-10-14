#!/usr/bin/env python3
"""Run the whole geometry build against a mock Fusion API.

Fusion cannot always be reached (it has to be running, with the MCP bridge
enabled), and shipping a large untested build script is how you find out in the
worst way that a parameter name was misspelled. This stubs enough of the Fusion
API to execute every line of geometry.py for real.

What this DOES prove:
  - the build runs start to finish with no Python error
  - every expression handed to Fusion references only parameters that exist
  - every expression is arithmetically valid and produces a sane number
  - features are created in a dependency-correct order
  - profile-splitting guide lines are marked as construction geometry

What this does NOT prove:
  - that the Fusion API signatures are correct
  - that the resulting solid is the shape intended

Those need Fusion. This closes the gap that can be closed offline.

    python3 tests/test_geometry_mock.py
"""

import math
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import bundle  # noqa: E402
from check_v1_fit import evaluate, strip_units  # noqa: E402
from fasteners import stock_length  # noqa: E402

RECORDED = {"expressions": [], "features": [], "sketches": [], "bodies": [],
            "negative_dims": []}


# ------------------------------------------------------------------ mocks

class Obj(object):
    """Permissive stand-in: any attribute access returns another Obj."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __getattr__(self, name):
        child = Obj()
        setattr(self, name, child)
        return child

    def __call__(self, *args, **kwargs):
        return Obj()


class Point(object):
    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)


class Collection(object):
    def __init__(self, items=None):
        self._items = list(items or [])

    def add(self, item):
        self._items.append(item)
        return item

    def item(self, i):
        return self._items[i]

    @property
    def count(self):
        return len(self._items)


class Parameter(object):
    """A dimension's parameter. Setting .expression is what we came to record."""

    def __init__(self, name, negative_ok=True):
        self.name = name
        self.negative_ok = negative_ok
        self._expression = ""
        self.comment = ""
        self.value = 1.0

    @property
    def expression(self):
        return self._expression

    @expression.setter
    def expression(self, value):
        self._expression = value
        RECORDED["expressions"].append((self.name, value))
        if not self.negative_ok:
            RECORDED["negative_dims"].append((self.name, value))


class Dimension(object):
    def __init__(self, name, negative_ok=True):
        self.parameter = Parameter(name, negative_ok)


class SketchPoint(object):
    # Unhashable, matching Fusion. A hashable mock hid a real TypeError.
    __hash__ = None

    def __init__(self, x, y):
        self.geometry = Point(x, y)


class SketchLine(object):
    def __init__(self, start, end):
        self.startSketchPoint = start
        self.endSketchPoint = end
        self._construction = False

    @property
    def isConstruction(self):
        return self._construction

    @isConstruction.setter
    def isConstruction(self, value):
        self._construction = bool(value)


class SketchCircle(object):
    def __init__(self, centre, radius):
        self.centerSketchPoint = centre
        self.radius = radius


class Lines(object):
    def __init__(self, sketch):
        self.sketch = sketch

    def addCenterPointRectangle(self, centre, corner):
        cx, cy = centre.x, centre.y
        hx, hy = corner.x - cx, corner.y - cy
        corners = [SketchPoint(cx - hx, cy - hy), SketchPoint(cx + hx, cy - hy),
                   SketchPoint(cx + hx, cy + hy), SketchPoint(cx - hx, cy + hy)]
        for point in corners:
            self.sketch.sketchPoints.add(point)
        self.sketch._rects += 1
        lines = [SketchLine(corners[i], corners[(i + 1) % 4]) for i in range(4)]
        return Collection(lines)

    def addByTwoPoints(self, start, end):
        line = SketchLine(start, end)
        self.sketch._guides.append(line)
        return line


class Dimensions(object):
    def __init__(self, sketch):
        self.sketch = sketch
        self._n = 0

    def _name(self, kind):
        self._n += 1
        return "%s_d%d_%s" % (self.sketch.name, self._n, kind)

    def addDistanceDimension(self, p1, p2, orientation, text):
        return Dimension(self._name("dist"), negative_ok=False)

    def addDiameterDimension(self, circle, text):
        return Dimension(self._name("dia"))


class Constraints(object):
    def __init__(self, sketch):
        self.sketch = sketch

    def addMidPoint(self, point, curve):
        self.sketch._constrained_guides.append(curve)
        return Obj()

    def addCoincident(self, a, b):
        return Obj()

    def addVertical(self, line):
        self.sketch._constrained_guides.append(line)
        self.sketch._axis_constraints += 1
        return Obj()

    def addHorizontal(self, line):
        self.sketch._constrained_guides.append(line)
        self.sketch._axis_constraints += 1
        return Obj()


class Sketch(object):
    def __init__(self, name, plane):
        self.name = name
        self.plane = plane
        self.sketchPoints = Collection()
        self._guides = []
        self._constrained_guides = []
        self._axis_constraints = 0
        self._rects = 0
        self.sketchCurves = Obj()
        self.sketchCurves.sketchLines = Lines(self)
        self.sketchCurves.sketchCircles = Obj()
        self.sketchCurves.sketchCircles.addByCenterRadius = self._circle
        self.sketchDimensions = Dimensions(self)
        self.geometricConstraints = Constraints(self)
        self.originPoint = SketchPoint(0.0, 0.0)
        self.profiles = Collection([Obj(areaProperties=lambda: Obj(area=1.0))])
        RECORDED["sketches"].append(name)

    def sketchToModelSpace(self, point):
        # Mirrors the mapping measured in Fusion: on a YZ plane local X runs
        # along world -Z and local Y along world +Y. The back wall is an XZ
        # plane, where local X runs along world X and local Y along world Z.
        if "back" in str(getattr(self.plane, "name", "")):
            return Point(point.x, 5.2, point.y)
        return Point(-7.5, point.y, -point.x)

    def _circle(self, centre, radius):
        point = SketchPoint(centre.x, centre.y)
        self.sketchPoints.add(point)
        circle = SketchCircle(point, radius)
        self.profiles.add(Obj(areaProperties=lambda: Obj(area=radius * radius)))
        return circle


class Sketches(object):
    def __init__(self):
        self._items = []

    def add(self, plane):
        sketch = Sketch("unnamed", plane)
        self._items.append(sketch)
        return sketch

    def item(self, i):
        return self._items[i]

    @property
    def count(self):
        return len(self._items)


class ExtrudeInput(object):
    def __init__(self, operation):
        self.operation = operation
        self.taperAngle = None
        self.detail = "?"

    def setOneSideExtent(self, extent, direction):
        self.detail = "one-side"

    def setSymmetricExtent(self, value, full):
        self.detail = "symmetric"

    def setAllExtent(self, direction):
        self.detail = "all"


class Extrudes(object):
    def createInput(self, profiles, operation):
        return ExtrudeInput(operation)

    def add(self, extrude_input):
        RECORDED["features"].append((extrude_input.operation, extrude_input.detail))
        feature = Obj()
        feature.bodies = Collection([_NamedBody()])
        feature.edges = Collection()
        return feature


class _NamedBody(object):
    def __init__(self):
        self._name = ""
        self.edges = Collection()

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value
        RECORDED["bodies"].append(value)


class _MockEdge(object):
    """A vertical edge at an outer corner, so the selection logic is exercised."""

    def __init__(self, x, y):
        self.startVertex = Obj(geometry=Point(x, y, 0.0))
        self.endVertex = Obj(geometry=Point(x, y, 1.0))


class Chamfers(object):
    def createInput2(self):
        return Obj(chamferEdgeSets=Obj(
            addEqualDistanceChamferEdgeSet=lambda e, v, t: None))

    def add(self, chamfer_input):
        RECORDED["features"].append(("chamfer", "openings"))
        return Obj()


class Fillets(object):
    def createInput(self):
        return Obj(addConstantRadiusEdgeSet=lambda e, v, t: None)

    def add(self, fillet_input):
        RECORDED["features"].append(("fillet", "corners"))
        return Obj()


class Component(object):
    def __init__(self, name):
        self.name = name
        self.sketches = Sketches()
        self.occurrences = Collection()
        self.constructionPlanes = PlaneCollection()
        self.bRepBodies = Collection()  # starts empty, like a fresh document
        self.features = Obj()
        self.features.extrudeFeatures = Extrudes()
        self.features.filletFeatures = Fillets()
        self.features.chamferFeatures = Chamfers()
        self.xYConstructionPlane = Obj(name="XY")
        self.xZConstructionPlane = Obj(name="XZ")
        self.yZConstructionPlane = Obj(name="YZ")


class PlaneCollection(Collection):
    def createInput(self):
        return Obj(setByOffset=lambda plane, value: None)

    def add(self, plane_input):
        plane = Obj(name="")
        plane.definition = Obj(offset=Parameter("plane_offset"))
        self._items.append(plane)
        return plane


class Occurrence(object):
    def __init__(self, name):
        self.component = Component(name)


class Timeline(object):
    def __init__(self):
        self.markerPosition = 0
        self.count = 0

    def deleteAllAfterMarker(self):
        return None


class RootComponent(Component):
    def __init__(self):
        Component.__init__(self, "root")
        self._children = []

    def _add_component(self):
        occurrence = Occurrence("unnamed")
        self._children.append(occurrence)
        self.occurrences._items.append(occurrence)
        return occurrence


def install_mocks():
    core = types.ModuleType("adsk.core")
    core.Point3D = Obj(create=lambda x, y, z=0.0: Point(x, y, z))
    core.ValueInput = Obj(createByString=_record_value_input)
    core.ObjectCollection = Obj(create=lambda: Collection())
    core.Matrix3D = Obj(create=lambda: Obj())

    fusion = types.ModuleType("adsk.fusion")
    fusion.DimensionOrientations = Obj(
        HorizontalDimensionOrientation="H", VerticalDimensionOrientation="V")
    fusion.FeatureOperations = Obj(
        NewBodyFeatureOperation="new", JoinFeatureOperation="join",
        CutFeatureOperation="cut")
    fusion.ExtentDirections = Obj(
        PositiveExtentDirection="+", NegativeExtentDirection="-",
        SymmetricExtentDirection="sym")
    fusion.DistanceExtentDefinition = Obj(create=lambda value: Obj())

    adsk = types.ModuleType("adsk")
    adsk.core, adsk.fusion = core, fusion
    sys.modules["adsk"] = adsk
    sys.modules["adsk.core"] = core
    sys.modules["adsk.fusion"] = fusion
    return adsk


def _record_value_input(text):
    RECORDED["expressions"].append(("<extent>", text))
    return Obj(text=text)


# ------------------------------------------------------------------ checks

FAILURES = []


def check(condition, message):
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        FAILURES.append(message)


PLACEHOLDERS = set()

SAFE = {"abs": abs, "atan": math.atan, "sin": math.sin, "cos": math.cos,
        "tan": math.tan, "sqrt": math.sqrt, "pi": math.pi}


def main():
    adsk = install_mocks()

    script = bundle.build_script({"params_file": "params/default.json"})
    namespace = {"__name__": "bundled", "adsk": adsk}
    exec(compile(script, "fusion_script.py", "exec"), namespace)

    table, _ = namespace["resolve_table"](
        namespace["PARAMS"], namespace["PROFILES"], namespace["COMPONENT_SETS"],
        "fdm_prototype", "v1_measured")
    values_mm, unresolved = evaluate(table)
    check(not unresolved, "every parameter formula resolves to a number")

    # geometry.py reads design.userParameters and works in Fusion's internal
    # centimetres, so the mock has to present values the same way.
    root = RootComponent()
    params = Collection([_param(name, mm / 10.0) for name, mm in sorted(values_mm.items())])
    for _p in params._items:
        _p.deleteMe = lambda: None
    design = Obj(rootComponent=root, userParameters=params, timeline=Timeline())

    # Route addNewComponent through the root so named lookups work.
    root.occurrences.addNewComponent = lambda matrix: root._add_component()

    logged = []
    try:
        namespace["build"](design, logged.append)
    except Exception as exc:
        import traceback
        print("\nBUILD RAISED:\n" + traceback.format_exc())
        check(False, "build() completes without raising (%s)" % exc)
        return 1
    check(True, "build() completes without raising")

    print("\nbuild log")
    for line in logged:
        print("    " + line)

    print("\nexpressions handed to Fusion: %d" % len(RECORDED["expressions"]))
    known = set(values_mm)
    bad_names, bad_math = [], []
    for owner, expression in RECORDED["expressions"]:
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", strip_units(expression)))
        unknown = tokens - known - set(SAFE)
        if unknown:
            bad_names.append("%s: %s -> %s" % (owner, expression, sorted(unknown)))
            continue
        try:
            eval(strip_units(expression), {"__builtins__": {}}, dict(values_mm, **SAFE))
        except Exception as exc:
            bad_math.append("%s: %s (%s)" % (owner, expression, exc))

    check(not bad_names, "every expression references only real parameters")
    for line in bad_names:
        print("       " + line)
    check(not bad_math, "every expression evaluates")
    for line in bad_math:
        print("       " + line)

    # Sketches live on the root component now, not on child components.
    # Collecting only from children silently made these checks vacuous.
    all_sketches = list(root.sketches._items) + [
        s for occurrence in root._children for s in occurrence.component.sketches._items]
    check(len(all_sketches) > 10, "sketches were actually collected (%d)" % len(all_sketches))
    solid_guides = [line for s in all_sketches for line in s._guides
                    if not line.isConstruction]
    check(not solid_guides,
          "guide lines are construction geometry, so they cannot split a profile")

    orphan_guides = [line for s in all_sketches for line in s._guides
                     if line not in s._constrained_guides]
    check(not orphan_guides, "every guide line carries a constraint")
    # Fusion distance dimensions are magnitudes and reject a negative value, so
    # evaluate each one rather than eyeballing a leading minus.
    negative = []
    for owner, expression in RECORDED["negative_dims"]:
        try:
            if eval(strip_units(expression), {"__builtins__": {}},
                    dict(values_mm, **SAFE)) < 0:
                negative.append("%s = %s" % (owner, expression))
        except Exception:
            negative.append("%s = %s (did not evaluate)" % (owner, expression))
    check(not negative, "no distance dimension evaluates negative")

    # Every rectangle needs four axis constraints of its own, or the sketch is
    # underconstrained and the shape is held only by where it was drawn.
    short = [s.name for s in all_sketches if s._rects and s._axis_constraints < 4 * s._rects]
    check(not short, "every rectangle gets its four horizontal/vertical constraints %s"
          % (short or ""))
    for line in negative:
        print("       " + line)

    print("\ngeometric consistency at nominal")
    global PLACEHOLDERS
    PLACEHOLDERS = {n for n, spec in table.items() if spec.get("source") == "placeholder"}
    blocked = check_geometry(values_mm)
    if blocked:
        print("\n  blocked on measurement, not defects:")
        for line in blocked:
            print("    " + line)

    sweep_geometry(table, values_mm)

    print("\nfasteners at nominal (the release configuration)")
    for label, lo, hi in fastener_windows(values_mm):
        length = stock_length(lo, hi)
        check(length is not None, "%s: stock length %s fits %.1f to %.1f"
              % (label, ("%d mm" % length) if length else "NONE", lo, hi))

    print("\nexport layout")
    check_export(namespace)

    print("\nbodies:     %s" % ", ".join(sorted(RECORDED["bodies"])))
    print("sketches:   %d" % len(all_sketches))
    print("features:   %d (%s)" % (
        len(RECORDED["features"]),
        ", ".join("%s/%s" % f for f in RECORDED["features"][:6]) + " ..."))

    print("\n%s (%d failure(s))" % ("PASS" if not FAILURES else "FAIL", len(FAILURES)))
    return 1 if FAILURES else 0


def fastener_windows(p):
    return (("lid screw", p["screw_length_min"], p["screw_length_max"]),
            ("load-cell screw", p["cell_fixed_screw_len_min"], p["cell_fixed_screw_len_max"]),
            ("pan screw", p["pan_screw_len_min"], p["pan_screw_len_max"]))


def check_export(namespace):
    """Export writes one mesh per part and one assembly STEP, all versioned.

    It used to export the root component as a single mesh: every part fused
    into one file in its assembled position, which nobody can print.
    """
    written = []

    class Manager(object):
        def createSTEPExportOptions(self, path, geometry):
            return ("step", path)

        def createSTLExportOptions(self, geometry, path):
            return Obj(path=path, meshRefinement=None, kind="stl")

        def createC3MFExportOptions(self, geometry, path):
            return ("3mf", path)

        def execute(self, options):
            path = options[1] if isinstance(options, tuple) else options.path
            written.append(os.path.basename(path))

    parts = ("base", "lid", "collar", "pan")
    bodies = Collection([Obj(name=name) for name in parts])
    design = Obj(exportManager=Manager(),
                 rootComponent=Obj(bRepBodies=bodies))
    meta = {"name": "bottle-feeder-v2", "version": "2.0.0-beta.1",
            "process_profile": "fdm_prototype"}
    namespace["adsk"].fusion.MeshRefinementSettings = Obj(MeshRefinementHigh="high")
    import tempfile
    namespace["export_all"](design, meta, tempfile.mkdtemp(), lambda m: None)

    stls = [f for f in written if f.endswith(".stl")]
    steps = [f for f in written if f.endswith(".step")]
    check(len(stls) == len(parts), "one STL per part (%d)" % len(stls))
    check(len(steps) == 1 and steps[0].endswith("-assembly.step"),
          "one assembly STEP")
    check(all("2.0.0-beta.1" in f for f in written), "every file carries the version")
    check(all(any(f.endswith("-%s.stl" % part) for f in stls) for part in parts),
          "STL files are named by part")


def sweep_geometry(table, nominal):
    """Re-check the geometry at each driving parameter's declared limits.

    Nominal always works: it is the value the design was drawn at. Breakage
    shows up at the edges of the declared range, which is exactly where someone
    resizing the design ends up. Anything reported here means either the
    geometry needs to cope, or the declared range is wrong; both are worth
    knowing before Fusion is involved.

    Reported rather than failed: a range being too generous is a documentation
    bug, not a broken model, and the useful output is the list.
    """
    global FAILURES
    print("\ngeometric consistency across declared ranges")

    broken = []
    swept = 0
    for name, spec in sorted(table.items()):
        if spec.get("role") != "driving" or spec.get("min") is None:
            continue
        swept += 1
        for bound in ("min", "max"):
            trial = {n: dict(s) for n, s in table.items()}
            units = spec.get("units", "")
            trial[name]["expression"] = ("%s %s" % (spec[bound], units)) if units else str(spec[bound])
            values, unresolved = evaluate(trial)
            if unresolved:
                broken.append((name, bound, ["formula did not resolve"]))
                continue

            saved, FAILURES = FAILURES, []
            devnull, sys.stdout = sys.stdout, open(os.devnull, "w")
            try:
                check_geometry(values)
            finally:
                sys.stdout.close()
                sys.stdout = devnull
            found, FAILURES = FAILURES, saved
            if found:
                broken.append((name, bound, found))

    print("  swept %d driving parameters at min and max" % swept)
    if not broken:
        print("  no geometric violations anywhere in the declared ranges")
        return

    print("  %d parameter/bound combination(s) produce invalid geometry:" % len(broken))
    for name, bound, problems in broken:
        value = table[name][bound]
        print("    %-24s @ %-3s = %-8s" % (name, bound, value))
        for problem in problems[:3]:
            print("        %s" % problem)


EPS = 1e-6


def check_geometry(p):
    """Assertions about the shape the numbers describe.

    The mock proves the script runs. These prove the part it would build is
    physically coherent: nothing pokes outside the case, nothing is cut deeper
    than the material it is cut into, no wall ends up thinner than the process
    can make. Every one of these is a way a parameter sweep can silently produce
    a broken solid rather than a failed feature.
    """
    blocked = []

    def ok(condition, message, detail="", depends=()):
        if not condition:
            unconfirmed = sorted(d for d in depends if d in PLACEHOLDERS)
            if unconfirmed:
                blocked.append("%s  [%s]  needs: %s"
                               % (message, detail, ", ".join(unconfirmed)))
                return
        check(condition, message + (("  [%s]" % detail) if detail and not condition else ""))

    half_l, half_w = p["case_l"] / 2, p["case_w"] / 2

    ok(p["lid_ledge_w"] < p["wall"], "lid ledge is narrower than the wall",
       "ledge %.2f vs wall %.2f" % (p["lid_ledge_w"], p["wall"]))
    rim = p["wall"] - p["lid_ledge_w"]
    ok(rim >= p["min_wall"], "wall rim outside the lid rebate clears min_wall",
       "rim %.2f vs min %.2f" % (rim, p["min_wall"]))
    ok(p["lid_rebate_depth"] < p["cavity_h"], "lid rebate is shallower than the cavity")

    boss_edge = abs(p["boss_offset_x"]) + p["boss_l"] / 2
    ok(boss_edge <= half_l - p["wall"], "load-cell boss fits inside the cavity",
       "boss reaches %.1f, cavity ends at %.1f" % (boss_edge, half_l - p["wall"]))
    hole_edge = p["load_cell_hole_spacing"] / 2 + p["load_cell_head_dia"] / 2
    ok(hole_edge <= p["boss_l"] / 2, "screw holes fit within the boss footprint",
       "holes reach %.1f, boss half-length %.1f" % (hole_edge, p["boss_l"] / 2))

    ok(p["load_cell_head_dia"] > p["load_cell_bore_dia"],
       "load-cell counterbore is wider than its clearance hole")
    ok(p["load_cell_bore_dia"] > p["load_cell_screw_dia"],
       "load-cell hole is a clearance fit, so the screw grips only in the cell",
       "bore %.2f vs screw %.2f" % (p["load_cell_bore_dia"], p["load_cell_screw_dia"]))
    ok(p["load_cell_cbore_depth"] < p["floor_t"] + p["boss_h"] - p["min_wall"],
       "counterbore leaves material under the load cell seat",
       "%.1f deep of %.1f available"
       % (p["load_cell_cbore_depth"], p["floor_t"] + p["boss_h"]))
    ok(p["load_cell_head_dia"] / 2 + p["load_cell_hole_spacing"] / 2 <= p["boss_l"] / 2,
       "counterbores stay inside the boss",
       "reach %.1f, boss half-length %.1f"
       % (p["load_cell_head_dia"] / 2 + p["load_cell_hole_spacing"] / 2, p["boss_l"] / 2))

    disp_x = abs(p["display_offset_x"]) + p["display_window_l"] / 2
    ok(disp_x <= half_l - p["wall"], "display window is inside the lid",
       "window reaches %.1f, limit %.1f" % (disp_x, half_l - p["wall"]))

    # A recess smaller than the aperture sits wholly inside the hole, so the cut
    # has nothing to remove and Fusion fails the feature.

    ok(p["display_window_w"] > p["display_window_l"],
       "display aperture is portrait, matching how the OLED is mounted",
       "%.1f wide x %.1f tall" % (p["display_window_l"], p["display_window_w"]))

    btn_y = p["button_spacing"] / 2 + p["button_dia"] / 2
    ok(btn_y <= half_w - p["wall"], "buttons fit across the lid",
       "buttons reach %.1f, limit %.1f" % (btn_y, half_w - p["wall"]))
    # Only the flange matters. A cap narrower than the bore is a sliding fit
    # retained from below; a cap wider than it seats on the lid and is fitted
    # from above. Both are normal, so requiring one of them was wrong.
    ok(p["button_shoulder_dia"] > p["button_bore_dia"],
       "button flange is wider than the bore, so the cap is retained",
       "flange %.2f vs bore %.2f" % (p["button_shoulder_dia"], p["button_bore_dia"]))

    ok(p["cable_notch_bottom_z"] > p["floor_t"] - EPS,
       "cable notch floor sits above the case floor",
       "notch %.1f vs floor %.1f" % (p["cable_notch_bottom_z"], p["floor_t"]))
    ok(p["cable_notch_bottom_z"] < p["wall_top_z"],
       "cable notch is actually open, not above the wall")
    ok(abs(p["cable_notch_offset_x"]) + p["cable_notch_w"] / 2 <= half_l - p["wall"] + EPS,
       "cable notch stays within the back wall",
       "reaches %.1f, limit %.1f"
       % (abs(p["cable_notch_offset_x"]) + p["cable_notch_w"] / 2, half_l - p["wall"]))

    ok(p["pan_recess_dia"] < min(p["pan_l"], p["pan_w"]),
       "bottle locating recess fits on the pan",
       "recess %.1f vs pan %.1f" % (p["pan_recess_dia"], min(p["pan_l"], p["pan_w"])))
    ok(p["pan_recess_depth"] < p["pan_plate"], "locating recess is shallower than the plate")
    ok(p["pan_counterbore_dia"] < p["pan_recess_dia"],
       "screw counterbore sits inside the locating recess")
    ok(p["pan_bore_dia"] < p["pan_counterbore_dia"], "bore is smaller than its counterbore")
    ok(p["pan_bore_dia"] > p["load_cell_free_thread"],
       "pan bore is a clearance fit, so the screw pulls the pan down instead of gripping it",
       "bore %.2f vs thread %.2f" % (p["pan_bore_dia"], p["load_cell_free_thread"]))
    ok(p["pan_counterbore_dia"] > p["free_screw_head_dia"],
       "pan counterbore takes the screw head",
       "%.2f vs head %.2f" % (p["pan_counterbore_dia"], p["free_screw_head_dia"]))
    ok(p["pan_cbore_depth"] >= p["pan_recess_depth"] + p["free_screw_head_h"] - EPS,
       "pan screw head sits below the locating recess floor, so the bottle cannot rock on it",
       "head top %.2f below the face, recess floor %.2f"
       % (p["pan_cbore_depth"] - p["free_screw_head_h"], p["pan_recess_depth"]))
    ok(p["pan_under_head"] >= p["min_wall"] - EPS,
       "plastic under the pan screw head meets min_wall",
       "%.2f vs %.2f" % (p["pan_under_head"], p["min_wall"]))

        # An inverted window (shortest that holds > longest that fits) means the
    # geometry cannot hold the screw at all. Whether a STOCK length lands in the
    # window is a question for the release configuration only, checked at
    # nominal in main(), not across every parameter extreme.
    for label, lo, hi in fastener_windows(p):
        ok(lo <= hi + EPS, "%s window is not inverted" % label,
           "needs %.1f to %.1f" % (lo, hi))

    # Layout conflicts between the pan and the lid's controls. The pan outline is
    # two overlapping circles, so testing its bounding box would condemn the very
    # corners the curved shape exists to remove.
    def clears_circles(px, py, pad):
        """True if a feature at (px, py) with radius `pad` misses both circles."""
        for centre_x, radius in ((p["pan_offset_x"], p["pan_main_dia"] / 2),
                                 (p["pan_offset_x"] + p["pan_lobe_offset"],
                                  p["pan_lobe_dia"] / 2)):
            if ((px - centre_x) ** 2 + py ** 2) ** 0.5 <= radius + pad:
                return False
        return True

    pan_lo = p["pan_offset_x"] - p["pan_main_dia"] / 2
    pan_hi = p["pan_offset_x"] + p["pan_lobe_offset"] + p["pan_lobe_dia"] / 2
    ok(pan_lo >= -half_l and pan_hi <= half_l,
       "pan stays within the case footprint",
       "pan spans %.1f..%.1f, case %.1f..%.1f" % (pan_lo, pan_hi, -half_l, half_l),
       depends=("load_cell_span", "bottle_footprint_dia"))

    ok(clears_circles(p["display_offset_x"], p["display_offset_y"],
                      max(p["display_window_l"], p["display_window_w"]) / 2),
       "pan does not cover the display",
       "display at %.1f, pan reaches %.1f" % (p["display_offset_x"], pan_lo),
       depends=("load_cell_span", "bottle_footprint_dia"))

    ok(clears_circles(p["button_offset_x"], p["button_spacing"] / 2,
                      p["button_shoulder_dia"] / 2),
       "pan does not cover the buttons",
       "button at (%.1f, %.1f), main circle centre %.1f r %.1f"
       % (p["button_offset_x"], p["button_spacing"] / 2,
          p["pan_offset_x"], p["pan_main_dia"] / 2),
       depends=("load_cell_span", "bottle_footprint_dia"))

    ok(abs(p["pan_offset_x"]) > 1.0,
       "pan offset stays clear of zero, where its dimension cannot solve",
       "pan_offset_x = %.2f" % p["pan_offset_x"],
       depends=("load_cell_span", "bottle_footprint_dia"))
    ok(p["pan_gap"] > p["load_cell_deflection"],
       "pan clears the lid at full-scale deflection",
       "gap %.2f vs deflection %.2f" % (p["pan_gap"], p["load_cell_deflection"]),
       depends=("load_cell_deflection",))

    # Bottom-entry screws: head sunk into the floor, standoff spanning the cavity.
    # EPS because floor_t is a max() that can land exactly on this limit, and
    # binary floating point then reads 2.6 - 1.8 as 0.79999999999999982.
    ok(p["floor_t"] - p["screw_head_h"] >= p["min_wall"] - EPS,
       "floor still clears min_wall under the countersunk head",
       "%.2f left vs min %.2f" % (p["floor_t"] - p["screw_head_h"], p["min_wall"]))
    ok(p["screw_head_dia"] > p["screw_clearance_dia"],
       "head counterbore is wider than the clearance hole")
    ok(p["screw_boss_od"] >= p["screw_pilot_dia"] + 2 * p["min_wall"] - EPS,
       "standoff has real material around the pilot hole",
       "od %.2f vs pilot %.2f" % (p["screw_boss_od"], p["screw_pilot_dia"]))
    ok(p["screw_clearance_dia"] > p["screw_pilot_dia"],
       "base hole is a free fit and the lid boss is the only thing gripping",
       "clearance %.2f vs pilot %.2f" % (p["screw_clearance_dia"], p["screw_pilot_dia"]))
    # Lid ribbing.
    ok(p["lid_pocket_depth"] < p["lid_pocket_total"] + EPS,
       "hollow does not cut clean through the lid",
       "depth %.2f vs total %.2f" % (p["lid_pocket_depth"], p["lid_pocket_total"]))
    ok(p["lid_pocket_depth"] >= 0,
       "hollow depth is never negative", "%.2f" % p["lid_pocket_depth"])
    ok(p["lid_skin_remaining"] >= p["min_wall"] - EPS,
       "skin left over the hollow still meets min_wall",
       "%.2f left vs min %.2f" % (p["lid_skin_remaining"], p["min_wall"]))
    ok(p["lid_pocket_l"] > 0 and p["lid_pocket_w"] > 0,
       "ribs leave an actual hollow",
       "pocket %.1f x %.1f" % (p["lid_pocket_l"], p["lid_pocket_w"]))
    ok(p["button_boss_dia"] > p["button_bore_dia"],
       "button island is wider than its bore")
    ok(p["display_rib_l"] > p["display_window_l"]
       and p["display_rib_w"] > p["display_window_w"],
       "display island is wider than its aperture")

    ok(p["screw_boss_h"] > 0, "standoff has positive length",
       "%.2f" % p["screw_boss_h"])
    ok(p["screw_engagement"] < p["screw_boss_h"],
       "thread engagement fits inside the standoff",
       "%.2f in %.2f" % (p["screw_engagement"], p["screw_boss_h"]))
    ok(p["screw_boss_gap"] < p["cavity_h"],
       "standoff gap leaves an actual standoff",
       "gap %.1f vs cavity %.1f" % (p["screw_boss_gap"], p["cavity_h"]))

    sx, sy = p["screw_offset_x"], p["screw_offset_y"]
    boss_r = p["screw_boss_od"] / 2
    ok(sx + boss_r <= half_l - p["wall"] and sy + boss_r <= half_w - p["wall"],
       "screw standoffs fit inside the cavity",
       "reach %.1f, %.1f  limits %.1f, %.1f"
       % (sx + boss_r, sy + boss_r, half_l - p["wall"], half_w - p["wall"]))

    # Standoffs land in the cavity, so they must miss everything else in it.
    lc_x, lc_y = p["boss_offset_x"], 0.0
    clear_lc = (abs(sx - lc_x) > (boss_r + p["boss_l"] / 2)
                or abs(sy - lc_y) > (boss_r + p["boss_w"] / 2))
    ok(clear_lc, "screw standoffs clear the load-cell boss")
    notch_lo = p["cable_notch_offset_x"] - p["cable_notch_w"] / 2
    notch_hi = p["cable_notch_offset_x"] + p["cable_notch_w"] / 2
    ok(sx - boss_r > notch_hi or -sx + boss_r < notch_lo,
       "screw standoffs clear the cable notch",
       "standoffs at +/-%.1f, notch %.1f..%.1f" % (sx, notch_lo, notch_hi))
    btn_gap = ((sx - p["button_offset_x"]) ** 2
               + (sy - p["button_spacing"] / 2) ** 2) ** 0.5
    ok(btn_gap > boss_r + p["button_shoulder_dia"] / 2,
       "screw standoffs clear the buttons", "centres %.1f apart" % btn_gap)

    # Fixed collar, no skirt. Every one of these is a way it could touch
    # something it must not, and any contact is a second load path.
    ok(p["collar_top_z"] >= p["cell_top_z"] - EPS,
       "collar top covers the top of the cell, which is what hides it",
       "collar %.2f vs cell top %.2f" % (p["collar_top_z"], p["cell_top_z"]))
    ok(p["collar_top_z"] < p["pan_assembly_z"],
       "collar stays below the pan",
       "collar %.2f vs pan %.2f" % (p["collar_top_z"], p["pan_assembly_z"]))
    ok(p["overload_gap"] > p["load_cell_deflection"],
       "overload stop engages only after full scale, not before",
       "stop at %.2f, full scale %.2f" % (p["overload_gap"], p["load_cell_deflection"]))
    ok(p["pan_spacer_h"] >= p["overload_gap"] + EPS,
       "spacer lifts the pan enough for the collar to fit under it and still cover the cell",
       "spacer %.2f vs overload gap %.2f" % (p["pan_spacer_h"], p["overload_gap"]))
    ok(p["pan_spacer_dia"] > p["pan_bore_dia"],
       "spacer is wider than the bore it sits on")
    ok(p["collar_inner_w"] > p["boss_w"] and p["collar_inner_w"] > p["load_cell_width"],
       "collar bore clears the boss and the cell")
    ok(p["collar_h"] > 0, "collar has positive height", "%.2f" % p["collar_h"])
    ok(p["collar_offset_x"] + p["collar_outer_l"] / 2 <= half_l + EPS,
       "collar stays within the case footprint",
       "reaches %.1f, case ends at %.1f"
       % (p["collar_offset_x"] + p["collar_outer_l"] / 2, half_l))

    # Printability, now checked for every part rather than just the pan.
    ok(p["pan_recess_depth"] < p["pan_plate"],
       "locating recess stays inside the plate")
    ok(p["load_cell_head_dia"] <= p["bridge_max"],
       "load-cell counterbore ceiling is a bridgeable span",
       "%.1f vs limit %.1f" % (p["load_cell_head_dia"], p["bridge_max"]))
    ok(p["screw_head_dia"] <= p["bridge_max"],
       "lid-screw counterbore ceiling is a bridgeable span",
       "%.1f vs limit %.1f" % (p["screw_head_dia"], p["bridge_max"]))
    # A chamfer bigger than the material beside the opening cannot be cut.
    # Not lid_skin: the display recess is cut into the underside, so the window
    # edge only has what is left over. That difference is the real ceiling, and
    # checking against the full skin let an impossible chamfer through.
    ok(p["chamfer_applied"] <= p["chamfer_headroom"] + EPS,
       "applied chamfer fits the thinnest material it is cut into",
       "%.2f vs headroom %.2f (lid skin %.2f, counterbore %.2f)"
       % (p["chamfer_applied"], p["chamfer_headroom"], p["lid_skin"], p["screw_head_h"]))
    ok(p["chamfer_applied"] > 0, "applied chamfer is positive",
       "%.2f" % p["chamfer_applied"])

    ok(p["chamfer_applied"] < p["button_bore_dia"] / 4,
       "cutout chamfer leaves the button bore intact",
       "%.2f vs bore/4 %.2f" % (p["chamfer_applied"], p["button_bore_dia"] / 4))
    ok(p["chamfer_applied"] < p["pan_plate"],
       "cutout chamfer is shallower than the pan plate")
    ok(p["chamfer_applied"] >= p["min_edge_radius"] - EPS,
       "broken edges meet the infant-contact minimum after any clamping",
       "applied %.2f vs min_edge_radius %.2f"
       % (p["chamfer_applied"], p["min_edge_radius"]))
    ok(p["chamfer_leadin"] < p["collar_spigot_h"],
       "lead-in chamfer is shallower than the spigot it leads into",
       "%.2f vs spigot %.2f" % (p["chamfer_leadin"], p["collar_spigot_h"]))
    ok(p["chamfer_applied"] < p["floor_t"],
       "counterbore chamfer is shallower than the floor it is cut into",
       "%.2f vs floor %.2f" % (p["chamfer_applied"], p["floor_t"]))
    ok(p["chamfer_leadin"] < p["collar_spigot_wall"],
       "lead-in chamfer leaves the spigot wall intact",
       "%.2f vs spigot wall %.2f" % (p["chamfer_leadin"], p["collar_spigot_wall"]))

    ok(p["collar_spigot_h"] <= p["lid_skin"] + EPS,
       "collar spigot stops within the lid skin rather than poking through",
       "spigot %.2f vs skin %.2f" % (p["collar_spigot_h"], p["lid_skin"]))
    ok(p["collar_spigot_l"] > p["lid_opening_l"] and p["collar_spigot_w"] > p["lid_opening_w"],
       "collar spigot is an interference fit in the lid opening",
       "spigot %.2f x %.2f vs opening %.2f x %.2f"
       % (p["collar_spigot_l"], p["collar_spigot_w"], p["lid_opening_l"], p["lid_opening_w"]))
    ok(p["collar_outer_l"] > p["lid_opening_l"] and p["collar_outer_w"] > p["lid_opening_w"],
       "collar has a flange to seat on rather than dropping through the lid",
       "collar %.2f x %.2f vs opening %.2f x %.2f"
       % (p["collar_outer_l"], p["collar_outer_w"], p["lid_opening_l"], p["lid_opening_w"]))

    # The boss deliberately protrudes through the lid; the lid must have a hole.
    protrudes = p["floor_t"] + p["boss_h"] > p["wall_top_z"]
    if protrudes:
        ok(p["boss_opening_l"] > p["boss_l"] and p["boss_opening_w"] > p["boss_w"],
           "lid opening clears the protruding boss")
        ok(abs(p["boss_offset_x"]) + p["boss_opening_l"] / 2 <= half_l,
           "boss opening stays within the lid outline")

    return blocked


def _param(name, value):
    parameter = Parameter(name)
    parameter.value = value
    return parameter


if __name__ == "__main__":
    sys.exit(main())
