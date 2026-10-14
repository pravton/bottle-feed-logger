# Geometry: the feature tree.
#
# CONCATENATION CONTRACT: see the note at the top of parameters.py.
#
# STRUCTURE
# Geometry is built in two layers, and the split is the whole reason this model
# survives being resized:
#
#   1. SKELETON: named construction planes, positioned by parameter
#      expressions. Nothing but parameters drives the skeleton.
#   2. FORM: sketches and features that reference the SKELETON by name.
#
# Features never reference each other's faces or edges. That is the discipline.
# Fusion numbers faces and edges internally, and those numbers are not stable
# across a rebuild: change a diameter enough that a face splits or merges and
# every downstream fillet, shell and joint keyed to it goes red. Referencing a
# named datum plane instead means the reference survives any parameter value,
# because the plane is defined by a formula rather than by whatever the solid
# happened to look like when the feature was created.
#
# EVERY sketch dimension is set from a parameter expression, never left as the
# number it was drawn at. Geometry is drawn at the parameters' current values
# only so that Fusion has something to constrain; the dimensions applied
# immediately afterwards are what actually hold the shape. That is what makes
# Modify > Change Parameters work interactively after a scripted build.

SKELETON_PREFIX = "SK_"

# Fusion works in centimetres internally. Every parameter in the tables is in
# millimetres, so values read back from the API need scaling for use as
# coordinates.
CM = 0.1


# ---------------------------------------------------------------- utilities

def _values(design):
    """Current value of every user parameter, in Fusion's internal units."""
    values = {}
    for i in range(design.userParameters.count):
        param = design.userParameters.item(i)
        values[param.name] = param.value
    return values


def _point(x, y, z=0.0):
    return adsk.core.Point3D.create(x, y, z)


def _vi(expression):
    return adsk.core.ValueInput.createByString(expression)


def _find_plane(component, name):
    for i in range(component.constructionPlanes.count):
        plane = component.constructionPlanes.item(i)
        if plane.name == name:
            return plane
    return None


def _offset_plane(component, name, base_plane, expression, log=None):
    """Create or re-drive a named datum plane at a parametric offset."""
    existing = _find_plane(component, name)
    if existing is not None:
        # Re-drive rather than recreate. Recreating would orphan every feature
        # that already references this plane.
        existing.definition.offset.expression = expression
        return existing

    plane_input = component.constructionPlanes.createInput()
    plane_input.setByOffset(base_plane, _vi(expression))
    plane = component.constructionPlanes.add(plane_input)
    plane.name = name
    if log:
        log("  plane %-22s = %s" % (name, expression))
    return plane


HORIZONTAL = None  # resolved lazily; the enum lives on adsk.fusion
VERTICAL = None


def _orientations():
    global HORIZONTAL, VERTICAL
    if HORIZONTAL is None:
        HORIZONTAL = adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation
        VERTICAL = adsk.fusion.DimensionOrientations.VerticalDimensionOrientation
    return HORIZONTAL, VERTICAL


def _rect(sketch, cx, cy, length, width, l_expr, w_expr, x_expr=None, y_expr=None):
    """A rectangle centred at (cx, cy), dimensioned by expression.

    addCenterPointRectangle keeps the rectangle centred on its centre point by
    construction, so only the two side lengths and the centre position need
    dimensioning: four dimensions instead of the eight a corner-drawn
    rectangle would need, and no chance of it drifting off-centre on a rebuild.
    """
    horizontal, vertical = _orientations()
    centre = _point(cx, cy)
    lines = sketch.sketchCurves.sketchLines
    rect = lines.addCenterPointRectangle(centre, _point(cx + length / 2.0, cy + width / 2.0))

    horizontals, verticals = [], []
    # Indexed access rather than iteration: Fusion's returned line lists are
    # COM collections and item()/count is the interface they are guaranteed to
    # expose.
    for index in range(rect.count):
        line = rect.item(index)
        start = line.startSketchPoint.geometry
        end = line.endSketchPoint.geometry
        if abs(start.y - end.y) < 1e-7:
            horizontals.append(line)
        elif abs(start.x - end.x) < 1e-7:
            verticals.append(line)

    # addCenterPointRectangle adds NO geometric constraints, so the four lines
    # are free to rotate and skew. Without these the sketch is underconstrained
    # by four degrees of freedom and the shape is held only by where it was
    # drawn: exactly the "floating geometry" this model is supposed to forbid.
    constraints = sketch.geometricConstraints
    for line in horizontals:
        constraints.addHorizontal(line)
    for line in verticals:
        constraints.addVertical(line)

    dims = sketch.sketchDimensions
    text = _point(cx + length, cy + width)
    dim = dims.addDistanceDimension(
        horizontals[0].startSketchPoint, horizontals[0].endSketchPoint, horizontal, text)
    dim.parameter.expression = l_expr
    dim = dims.addDistanceDimension(
        verticals[0].startSketchPoint, verticals[0].endSketchPoint, vertical, text)
    dim.parameter.expression = w_expr

    # addCenterPointRectangle does NOT leave a sketch point at the centre, so
    # there is nothing to grab hold of. Build one: a construction diagonal
    # between opposite corners, with an explicit point constrained to its
    # midpoint. Guessing at "the new point nearest the centre" instead picks one
    # of the four equidistant corners and pins that to the origin, which puts
    # the whole rectangle a half-width off.
    corner_a = horizontals[0].startSketchPoint
    corner_b = None
    for index in range(rect.count):
        line = rect.item(index)
        for point in (line.startSketchPoint, line.endSketchPoint):
            geometry = point.geometry
            if (abs(geometry.x - corner_a.geometry.x) > 1e-7
                    and abs(geometry.y - corner_a.geometry.y) > 1e-7):
                corner_b = point
                break
        if corner_b:
            break

    diagonal = lines.addByTwoPoints(corner_a, corner_b)
    diagonal.isConstruction = True
    middle = sketch.sketchPoints.add(centre)
    sketch.geometricConstraints.addMidPoint(middle, diagonal)

    _locate(sketch, middle, cx, cy, x_expr, y_expr, text)
    return rect


def _signed(expression, offset):
    """Make an expression evaluate positive, matching the drawn side.

    Fusion distance dimensions are magnitudes and reject a negative value, so a
    feature at a negative coordinate needs its expression negated. The parameter
    still drives it; only the sign is normalised.
    """
    if expression is None or offset >= 0:
        return expression
    # The caller passes the signed coordinate. At a negative coordinate the
    # magnitude is its negation: strip a leading minus if there is one, rather
    # than wrapping it into a double negative.
    stripped = expression.strip()
    if stripped.startswith("-"):
        return stripped[1:].strip()
    return "-(%s)" % stripped


def _locate(sketch, point, cx, cy, x_expr, y_expr, text):
    """Fix a sketch point relative to the sketch origin.

    None means "aligned with the origin on this axis" and is pinned with a
    geometric constraint rather than a dimension of zero, which is degenerate.

    Any guide line used to carry a constraint is marked as construction
    geometry. A normal line from the origin to the centre of a rectangle would
    cut its profile in two, and the extrude would then pick up half the shape.
    """
    horizontal, vertical = _orientations()
    dims = sketch.sketchDimensions
    origin = sketch.originPoint

    if x_expr is None and y_expr is None:
        sketch.geometricConstraints.addCoincident(point, origin)
        return

    guide = None
    if x_expr is None or y_expr is None:
        guide = sketch.sketchCurves.sketchLines.addByTwoPoints(origin, point)
        guide.isConstruction = True

    if x_expr is None:
        # Equal x means the guide line runs parallel to the Y axis.
        sketch.geometricConstraints.addVertical(guide)
    else:
        dims.addDistanceDimension(
            origin, point, horizontal, text).parameter.expression = _signed(x_expr, cx)

    if y_expr is None:
        sketch.geometricConstraints.addHorizontal(guide)
    else:
        dims.addDistanceDimension(
            origin, point, vertical, text).parameter.expression = _signed(y_expr, cy)



def _flip(expression, direction):
    """Negate an expression when the local axis runs against the world axis."""
    return expression if direction >= 0 else "-(%s)" % expression


def _plane_rect(sketch, spec_a, spec_b):
    """Place a rectangle on a vertical sketch plane using world coordinates.

    Each spec is (world_axis, coord_cm, size_cm, coord_expr, size_expr) where
    world_axis is 0/1/2 for X/Y/Z.

    Fusion's local sketch axes on a vertical plane do not map to world axes the
    obvious way: measured on a YZ plane here, local X runs along world -Z and
    local Y along world +Y. Assuming otherwise puts an opening on its side, which
    can still cut material at the nominal value and so looks correct until the
    parameter is swept. So the mapping is probed and each dimension assigned to
    whichever local axis actually carries it.
    """
    origin = sketch.sketchToModelSpace(_point(0, 0))
    unit_x = sketch.sketchToModelSpace(_point(1, 0))
    unit_y = sketch.sketchToModelSpace(_point(0, 1))
    base = (origin.x, origin.y, origin.z)
    dir_x = (unit_x.x - base[0], unit_x.y - base[1], unit_x.z - base[2])
    dir_y = (unit_y.x - base[0], unit_y.y - base[1], unit_y.z - base[2])

    target = [0.0, 0.0, 0.0]
    for axis, coord, _size, _cexpr, _sexpr in (spec_a, spec_b):
        target[axis] = coord - base[axis]
    local_x = sum(target[i] * dir_x[i] for i in range(3))
    local_y = sum(target[i] * dir_y[i] for i in range(3))

    # Whichever spec local X actually carries becomes the local-X dimension.
    if abs(dir_x[spec_a[0]]) > abs(dir_y[spec_a[0]]):
        first, second = spec_a, spec_b
    else:
        first, second = spec_b, spec_a

    return _rect(sketch, local_x, local_y, first[2], second[2],
                 first[4], second[4],
                 _flip(first[3], dir_x[first[0]]),
                 _flip(second[3], dir_y[second[0]]))


def _circle(sketch, cx, cy, diameter, dia_expr, x_expr=None, y_expr=None):
    """A circle at (cx, cy), diameter and position driven by expression."""
    circles = sketch.sketchCurves.sketchCircles
    circle = circles.addByCenterRadius(_point(cx, cy), diameter / 2.0)
    text = _point(cx + diameter, cy + diameter)
    sketch.sketchDimensions.addDiameterDimension(
        circle, text).parameter.expression = dia_expr
    _locate(sketch, circle.centerSketchPoint, cx, cy, x_expr, y_expr, text)
    return circle


def _collect(profiles):
    """Build an ObjectCollection from an explicit list of profiles.

    Callers always pass a list. Sniffing the argument with hasattr() to work out
    whether it was a single profile or a Fusion collection is unreliable in both
    directions, and a wrong guess here shows up as a confusing type error deep
    inside the API rather than at the call site.
    """
    collection = adsk.core.ObjectCollection.create()
    for profile in profiles:
        collection.add(profile)
    return collection


def _all_profiles(sketch):
    """Every closed profile in a sketch, as a plain list."""
    return [sketch.profiles.item(i) for i in range(sketch.profiles.count)]


def _extrude(component, profiles, expression, operation, symmetric=False, taper=None,
             bodies=None):
    """Extrude a list of profiles by a parametric distance.

    `bodies` scopes the feature. All three parts live in the root component, so
    an unscoped cut would carve through every body it passes rather than only
    the part it belongs to: the lid's display window would slot the base.
    """
    extrudes = component.features.extrudeFeatures
    extrude_input = extrudes.createInput(_collect(profiles), operation)
    extent = adsk.fusion.DistanceExtentDefinition.create(_vi(expression))
    if symmetric:
        extrude_input.setSymmetricExtent(_vi(expression), True)
    else:
        direction = adsk.fusion.ExtentDirections.PositiveExtentDirection
        extrude_input.setOneSideExtent(extent, direction)
    if taper is not None:
        extrude_input.taperAngle = _vi(taper)
    # Set participants last. Assigning them before the extent is defined leaves
    # Fusion with nothing to scope and the assignment is silently dropped.
    if bodies:
        extrude_input.participantBodies = list(bodies)
    return extrudes.add(extrude_input)


def _cut_all(component, profiles, log, label, bodies=None):
    """Cut through everything, in both directions.

    Through-all rather than a measured depth: the depth of a through feature is
    a consequence of other parameters, so dimensioning it would create a second
    source of truth that silently goes wrong when the wall or floor changes.
    """
    extrudes = component.features.extrudeFeatures
    extrude_input = extrudes.createInput(
        _collect(profiles), adsk.fusion.FeatureOperations.CutFeatureOperation)
    extrude_input.setAllExtent(adsk.fusion.ExtentDirections.SymmetricExtentDirection)
    if bodies:
        extrude_input.participantBodies = list(bodies)
    feature = extrudes.add(extrude_input)
    log("  cut %s" % label)
    return feature


def _name_body(feature, name):
    """Name the body a NewBody extrude just created, and hand it back.

    The three parts are separate bodies in the root component rather than
    separate components, because a Fusion Part Design document permits only one
    component. Bodies work in both document types, and every subsequent feature
    is scoped to its own body so the parts stay independent.
    """
    body = feature.bodies.item(0)
    body.name = name
    return body


CHAMFER_REFUSALS = []


def _edges_in_plane(body, z_cm, tolerance=1e-4):
    """Every edge lying wholly in the horizontal plane at z_cm."""
    found = []
    for i in range(body.edges.count):
        edge = body.edges.item(i)
        try:
            box = edge.boundingBox
        except Exception:
            continue
        if (abs(box.minPoint.z - z_cm) < tolerance
                and abs(box.maxPoint.z - z_cm) < tolerance):
            found.append(edge)
    return found


def _chamfer_openings(component, body, z_cm, expression, log, label, interior=True):
    """Chamfer edges in a face: either its openings, or its outer perimeter.

    Perimeter is decided against the BODY's own bounding box at that height, not
    against the case outline. Using the case meant the collar (which is small
    and sits well off centre) had every edge classified as interior, so its
    spigot lead-in was silently skipped.

    Edges are picked geometrically every build rather than stored, and these run
    last in the timeline, so a broken reference costs only the chamfer.
    """
    candidates = _edges_in_plane(body, z_cm)
    if not candidates:
        log("  %s: no edges at that height, skipped" % label)
        return None

    lo_x = min(e.boundingBox.minPoint.x for e in candidates)
    hi_x = max(e.boundingBox.maxPoint.x for e in candidates)
    lo_y = min(e.boundingBox.minPoint.y for e in candidates)
    hi_y = max(e.boundingBox.maxPoint.y for e in candidates)
    margin = 0.02  # cm

    edges = adsk.core.ObjectCollection.create()
    for edge in candidates:
        box = edge.boundingBox
        touches_outline = (box.minPoint.x <= lo_x + margin
                           or box.maxPoint.x >= hi_x - margin
                           or box.minPoint.y <= lo_y + margin
                           or box.maxPoint.y >= hi_y - margin)
        if touches_outline != interior:
            edges.add(edge)
    if edges.count == 0:
        log("  %s: no %s edges matched, skipped"
            % (label, "opening" if interior else "perimeter"))
        return None

    chamfers = component.features.chamferFeatures
    chamfer_input = chamfers.createInput2()
    chamfer_input.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
        edges, _vi(expression), True)
    try:
        feature = chamfers.add(chamfer_input)
    except Exception as exc:
        # A chamfer wider than the material beside an opening cannot be cut.
        # Carry on rather than losing the whole build, but record it: swallowing
        # this quietly is how a chamfer appears to "stop growing" when the value
        # is raised, with nothing to say why.
        CHAMFER_REFUSALS.append("%s at %s (%s)" % (label, expression, exc))
        log("  %s: REFUSED, not enough material (%s)" % (label, expression))
        return None
    log("  %s: chamfered %d edge(s)" % (label, edges.count))
    return feature


def _round_outer_corners(component, body, half_l, half_w, radius_expr, log, label):
    """Round the four outer vertical corners of a box-like body.

    Edges are re-selected geometrically on every build rather than stored, and
    the feature is added last, so if a reference ever does break it takes
    nothing else with it. This is the one place the model touches topology
    instead of named datums, which is why it is quarantined at the end.
    """
    edges = adsk.core.ObjectCollection.create()
    for i in range(body.edges.count):
        edge = body.edges.item(i)
        try:
            start = edge.startVertex.geometry
            end = edge.endVertex.geometry
        except Exception:
            continue
        if abs(start.x - end.x) > 1e-6 or abs(start.y - end.y) > 1e-6:
            continue  # not a vertical edge
        if (abs(abs(start.x) - half_l) < 1e-3) and (abs(abs(start.y) - half_w) < 1e-3):
            edges.add(edge)
    if edges.count == 0:
        log("  %s: no outer corner edges found, skipped" % label)
        return None
    fillets = component.features.filletFeatures
    fillet_input = fillets.createInput()
    fillet_input.addConstantRadiusEdgeSet(edges, _vi(radius_expr), True)
    feature = fillets.add(fillet_input)
    log("  %s: rounded %d outer corner edge(s)" % (label, edges.count))
    return feature


def _sketch(component, plane, name):
    sketch = component.sketches.add(plane)
    sketch.name = name
    return sketch


def _largest_profile(sketch):
    best, best_area = None, -1.0
    for i in range(sketch.profiles.count):
        profile = sketch.profiles.item(i)
        area = profile.areaProperties().area
        if area > best_area:
            best, best_area = profile, area
    return best


# ---------------------------------------------------------------- skeleton


# The four screw positions. Each gets its own sketch: two circles sharing an X
# or a Y in one sketch make Fusion infer an alignment between their centres, and
# the second position dimension is then rejected as over-constraining.
SCREW_CORNERS = (("pp", 1.0, 1.0), ("pn", 1.0, -1.0), ("np", -1.0, 1.0), ("nn", -1.0, -1.0))


def _corner_expr(name, sign):
    return name if sign > 0 else "-" + name


def _screw_holes(component, root, v, plane, label, dia_expr, depth_expr, operation,
                 bodies=None):
    """One circle per corner, each in its own sketch, extruded together."""
    features = adsk.fusion.FeatureOperations
    diameter = v[dia_expr]
    for suffix, sign_x, sign_y in SCREW_CORNERS:
        sketch = _sketch(component, plane, "%s_%s" % (label, suffix))
        _circle(sketch, sign_x * v["screw_offset_x"], sign_y * v["screw_offset_y"],
                diameter, dia_expr,
                _corner_expr("screw_offset_x", sign_x),
                _corner_expr("screw_offset_y", sign_y))
        _extrude(component, [_largest_profile(sketch)], depth_expr, operation,
                 bodies=bodies)


GENERATED_SKETCH_PREFIXES = ("base_", "lid_", "pan_", "collar_")
GENERATED_BODIES = ("base", "lid", "pan", "collar")
# Every feature type this script creates. Anything else in the timeline was
# added by hand.
GENERATED_FEATURE_TYPES = ("Sketch", "ExtrudeFeature", "ConstructionPlane",
                           "FilletFeature", "ChamferFeature")


def reset_document(design, log):
    """Clear previously generated geometry so a rebuild replaces it.

    Refuses if the document contains anything this script did not create. That
    guard matters: this deletes the whole timeline, and running it against a
    hand-modelled document would destroy the work in it.
    """
    root = design.rootComponent
    foreign = []
    for i in range(root.sketches.count):
        name = root.sketches.item(i).name
        if not name.startswith(GENERATED_SKETCH_PREFIXES):
            foreign.append("sketch %r" % name)
    for i in range(root.bRepBodies.count):
        name = root.bRepBodies.item(i).name
        if name not in GENERATED_BODIES:
            foreign.append("body %r" % name)

    # Also check the timeline itself. Checking only sketch and body names misses
    # hand-added FEATURES: a chamfer or fillet applied to a generated body
    # leaves no trace in either list, and would be deleted without warning.
    for i in range(design.timeline.count):
        item = design.timeline.item(i)
        try:
            kind = item.entity.objectType.split(":")[-1]
        except Exception:
            continue
        if kind not in GENERATED_FEATURE_TYPES:
            foreign.append("%s %r" % (kind, item.name))
    if foreign:
        raise RuntimeError(
            "Refusing to clear this document: it holds geometry this script did "
            "not create (%s). Rebuilding would delete it. Build into an empty "
            "document instead." % ", ".join(foreign[:6]))

    timeline = design.timeline
    cleared = timeline.count
    if cleared:
        timeline.markerPosition = 0
        timeline.deleteAllAfterMarker()
    log("reset: cleared %d previously generated timeline feature(s)" % cleared)


def build_skeleton(design, log):
    """Named datum geometry, driven entirely by parameters."""
    log("--- skeleton ---")
    root = design.rootComponent

    planes = {
        "SK_floor_top": (root.xYConstructionPlane, "floor_t"),
        "SK_wall_top": (root.xYConstructionPlane, "wall_top_z"),
        "SK_lid_underside": (root.xYConstructionPlane, "wall_top_z - lid_rebate_depth"),
        "SK_lid_top": (root.xYConstructionPlane, "wall_top_z + lid_skin"),
        "SK_boss_top": (root.xYConstructionPlane, "floor_t + boss_h"),
        "SK_case_back": (root.xZConstructionPlane, "case_w / 2"),
        "SK_pan_base": (root.xYConstructionPlane, "pan_assembly_z"),
        "SK_pan_face": (root.xYConstructionPlane, "pan_assembly_z + pan_plate"),
    }

    built = {}
    for name, (base, expression) in sorted(planes.items()):
        built[name] = _offset_plane(root, name, base, expression, log)

    log("skeleton: %d named plane(s)" % len(built))
    return built


# ---------------------------------------------------------------- base

def _build_base(design, root, planes, v, log):
    log("--- base ---")
    component = root
    features = adsk.fusion.FeatureOperations

    sketch = _sketch(component, root.xYConstructionPlane, "base_outer")
    _rect(sketch, 0, 0, v["case_l"], v["case_w"], "case_l", "case_w", None, None)
    # The base's own features are deliberately NOT scoped with
    # participantBodies. When they run (on the first build and on every
    # recompute, since the timeline replays in order) the base is the only body
    # that exists, so there is nothing else to protect. Scoping them anyway
    # stores a body reference that goes stale on rebuild and the feature fails
    # with "No target body". The lid and pan DO need scoping, because by then
    # the base is in the way.
    body = _name_body(_extrude(component, [_largest_profile(sketch)], "wall_top_z",
                               features.NewBodyFeatureOperation), "base")
    log("  outer block, case_l x case_w x wall_top_z")

    sketch = _sketch(component, planes["SK_floor_top"], "base_cavity")
    _rect(sketch, 0, 0, v["cavity_l"], v["cavity_w"], "cavity_l", "cavity_w", None, None)
    _extrude(component, [_largest_profile(sketch)], "cavity_h",
             features.CutFeatureOperation)
    log("  cavity, cavity_l x cavity_w x cavity_h")

    sketch = _sketch(component, planes["SK_wall_top"], "base_lid_rebate")
    _rect(sketch, 0, 0, v["lid_rebate_l"] + 2 * v["fit_lid"], v["lid_rebate_w"] + 2 * v["fit_lid"],
          "lid_rebate_l + 2 * fit_lid", "lid_rebate_w + 2 * fit_lid", None, None)
    _extrude(component, [_largest_profile(sketch)], "-lid_rebate_depth",
             features.CutFeatureOperation)
    log("  lid rebate, ledge lid_ledge_w wide")

    sketch = _sketch(component, root.xYConstructionPlane, "base_boss")
    _rect(sketch, v["boss_offset_x"], 0, v["boss_l"], v["boss_w"],
          "boss_l", "boss_w", "boss_offset_x", None)
    # From Z=0 rather than the floor top, so the boss overlaps the floor instead
    # of merely touching it. A coincident-face join is fragile.
    _extrude(component, [_largest_profile(sketch)], "floor_t + boss_h",
             features.JoinFeatureOperation)
    log("  load-cell boss, boss_l x boss_w x boss_h")

    # The load cell has its own threaded holes, so its screws enter from
    # UNDERNEATH: head buried in a counterbore in the underside, shank running
    # clear all the way up through the floor and boss, threads engaging only in
    # the cell itself. Cutting these from the floor top instead left no way to
    # reach them once the case was assembled.
    half = v["load_cell_hole_spacing"] / 2.0
    sketch = _sketch(component, root.xYConstructionPlane, "base_boss_holes")
    _circle(sketch, v["boss_offset_x"] - half, 0, v["load_cell_bore_dia"],
            "load_cell_bore_dia", "boss_offset_x - load_cell_hole_spacing / 2", None)
    _circle(sketch, v["boss_offset_x"] + half, 0, v["load_cell_bore_dia"],
            "load_cell_bore_dia", "boss_offset_x + load_cell_hole_spacing / 2", None)
    _extrude(component, _all_profiles(sketch), "floor_t + boss_h + cut_overshoot",
             features.CutFeatureOperation)
    log("  cut 2 x load-cell screw holes, right through from the underside")

    sketch = _sketch(component, root.xYConstructionPlane, "base_boss_cbore")
    _circle(sketch, v["boss_offset_x"] - half, 0, v["load_cell_head_dia"],
            "load_cell_head_dia", "boss_offset_x - load_cell_hole_spacing / 2", None)
    _circle(sketch, v["boss_offset_x"] + half, 0, v["load_cell_head_dia"],
            "load_cell_head_dia", "boss_offset_x + load_cell_hole_spacing / 2", None)
    _extrude(component, _all_profiles(sketch), "load_cell_cbore_depth",
             features.CutFeatureOperation)
    log("  cut 2 x load-cell head counterbores in the underside")

    sketch = _sketch(component, planes["SK_case_back"], "base_cable_notch")
    _plane_rect(sketch,
                (0, v["cable_notch_offset_x"], v["cable_notch_w"],
                 "cable_notch_offset_x", "cable_notch_w"),
                (2, v["cable_notch_z"], v["cable_notch_h"],
                 "cable_notch_z", "cable_notch_h"))
    # Symmetric about the wall plane and two walls deep, so it clears the wall
    # whichever way the sketch normal points. The notch runs past the wall top,
    # leaving it open so the cable lays in and the lid traps it.
    _extrude(component, [_largest_profile(sketch)], "(wall + cut_overshoot) * 2",
             features.CutFeatureOperation, symmetric=True)
    log("  cut cable exit notch in the back wall, open at the top")

    # Screws enter from underneath, so both features are cut from the Z=0 face.
    # The clearance hole must be a free fit: if the screw grips the base as well
    # as the lid boss it jacks the two parts apart instead of pulling them shut.
    _screw_holes(component, root, v, root.xYConstructionPlane, "base_screw_clear",
                 "screw_clearance_dia", "floor_t", features.CutFeatureOperation)
    log("  cut 4 x screw clearance holes through the floor")

    _screw_holes(component, root, v, root.xYConstructionPlane, "base_screw_cbore",
                 "screw_head_dia", "screw_head_h", features.CutFeatureOperation)
    log("  cut 4 x head counterbores, heads flush with the underside")

    log("base: done")
    return body


# ---------------------------------------------------------------- lid

def _build_lid(design, root, planes, v, log):
    log("--- lid ---")
    component = root
    features = adsk.fusion.FeatureOperations

    sketch = _sketch(component, planes["SK_wall_top"], "lid_skin")
    _rect(sketch, 0, 0, v["case_l"], v["case_w"], "case_l", "case_w", None, None)
    body = _name_body(_extrude(component, [_largest_profile(sketch)], "lid_skin",
                               features.NewBodyFeatureOperation), "lid")
    log("  top skin, lid_skin thick (V1 was 1.00 mm and bowed)")

    sketch = _sketch(component, planes["SK_wall_top"], "lid_spigot")
    _rect(sketch, 0, 0, v["lid_rebate_l"], v["lid_rebate_w"],
          "lid_rebate_l", "lid_rebate_w", None, None)
    _extrude(component, [_largest_profile(sketch)], "-lid_rebate_depth",
             features.JoinFeatureOperation, bodies=[body])
    log("  spigot into the rebate, fit_lid clearance")

    sketch = _sketch(component, planes["SK_lid_top"], "lid_display_window")
    _rect(sketch, v["display_offset_x"], v["display_offset_y"],
          v["display_window_l"], v["display_window_w"],
          "display_window_l", "display_window_w", "display_offset_x", "display_offset_y")
    _extrude(component, [_largest_profile(sketch)], "-(lid_skin + lid_rebate_depth + cut_overshoot)",
             features.CutFeatureOperation, bodies=[body])
    log("  cut display window")

    # No recess for the OLED module. A blind pocket on the underside gives it
    # nowhere to enter from, so the aperture is a plain through window and the
    # module is retained some other way. Removing it also doubles the material
    # at the window edge, which is what limits chamfer_cutout.

    # One sketch per button. Two aligned circles in a single sketch make Fusion
    # infer a constraint between their centres, and the second position
    # dimension is then rejected as over-constraining.
    half = v["button_spacing"] / 2.0
    button_profiles = []
    for suffix, sign, y_expr in (("a", -1.0, "-button_spacing / 2"),
                                 ("b", 1.0, "button_spacing / 2")):
        sketch = _sketch(component, planes["SK_lid_top"], "lid_button_%s" % suffix)
        _circle(sketch, v["button_offset_x"], sign * half, v["button_dia"],
                "button_dia", "button_offset_x", y_expr)
        button_profiles.append(_largest_profile(sketch))
    _extrude(component, button_profiles, "-(lid_skin + lid_rebate_depth + cut_overshoot)",
             features.CutFeatureOperation, bodies=[body])
    log("  cut 2 x button holes")

    # Opening for the collar's press-fit spigot. The collar itself is a separate
    # printed part: with it joined to the lid, the lid had 18.6 mm of collar
    # above its skin and 12.5 mm of standoffs below, so whichever way up it was
    # printed one of them held a 150 x 92 skin off the bed and the whole thing
    # needed support.
    sketch = _sketch(component, planes["SK_lid_top"], "lid_collar_opening")
    _rect(sketch, v["collar_offset_x"], 0, v["lid_opening_l"], v["lid_opening_w"],
          "lid_opening_l", "lid_opening_w", "collar_offset_x", None)
    _extrude(component, [_largest_profile(sketch)],
             "-(lid_skin + lid_rebate_depth + cut_overshoot)",
             features.CutFeatureOperation, bodies=[body])
    log("  opening for the collar spigot")

    # The pan deliberately does NOT cut the lid. It is screwed to the load cell,
    # so it needs a fastener path, not a large opening, and a large opening is
    # a direct spill path into the electronics.

    # Standoffs hang from the lid down to the base floor. screw_boss_h is
    # derived as wall_top_z - floor_t, so they always span the cavity exactly
    # however tall it becomes.
    _screw_holes(component, root, v, planes["SK_wall_top"], "lid_screw_boss",
                 "screw_boss_od", "-screw_boss_h", features.JoinFeatureOperation,
                 bodies=[body])
    log("  4 x screw standoffs down to the floor")

    _screw_holes(component, root, v, planes["SK_wall_top"], "lid_screw_pilot",
                 "screw_pilot_dia", "-screw_boss_h", features.CutFeatureOperation,
                 bodies=[body])
    log("  4 x pilot holes, stopping below the lid skin")

    # Hollow the underside, leaving ribs. One sketch holds the pocket boundary
    # and every island; Fusion works out the region between them and
    # _largest_profile picks it. The islands matter as much as the pocket: the
    # standoffs pass through this depth, so without one round each the cut would
    # sever them from the skin.
    sketch = _sketch(component, planes["SK_lid_underside"], "lid_pocket")
    _rect(sketch, 0, 0, v["lid_pocket_l"], v["lid_pocket_w"],
          "lid_pocket_l", "lid_pocket_w", None, None)
    _rect(sketch, v["collar_offset_x"], 0, v["collar_rib_l"], v["collar_rib_w"],
          "collar_rib_l", "collar_rib_w", "collar_offset_x", None)
    _rect(sketch, v["display_offset_x"], v["display_offset_y"],
          v["display_rib_l"], v["display_rib_w"],
          "display_rib_l", "display_rib_w", "display_offset_x", "display_offset_y")
    half = v["button_spacing"] / 2.0
    _circle(sketch, v["button_offset_x"], -half, v["button_boss_dia"],
            "button_boss_dia", "button_offset_x", "-button_spacing / 2")
    _circle(sketch, v["button_offset_x"], half, v["button_boss_dia"],
            "button_boss_dia", "button_offset_x", "button_spacing / 2")
    for suffix, sign_x, sign_y in SCREW_CORNERS:
        _circle(sketch, sign_x * v["screw_offset_x"], sign_y * v["screw_offset_y"],
                v["screw_boss_od"], "screw_boss_od",
                _corner_expr("screw_offset_x", sign_x),
                _corner_expr("screw_offset_y", sign_y))
    _extrude(component, [_largest_profile(sketch)], "lid_pocket_depth",
             features.CutFeatureOperation, bodies=[body])
    log("  underside hollowed %s deep, leaving %s ribs"
        % ("lid_pocket_depth", "lid_rib_w"))

    log("lid: done")
    return body


# ---------------------------------------------------------------- pan

def _build_collar(design, root, planes, v, log):
    """The shroud, as its own printed part.

    A rectangular tube, open at both ends, with a spigot at the base that
    presses into the lid. Printed standing on its rim it needs no support at
    all, which is the whole reason it is not part of the lid.
    """
    log("--- collar ---")
    component = root
    features = adsk.fusion.FeatureOperations

    sketch = _sketch(component, planes["SK_lid_top"], "collar_outer")
    _rect(sketch, v["collar_offset_x"], 0, v["collar_outer_l"], v["collar_outer_w"],
          "collar_outer_l", "collar_outer_w", "collar_offset_x", None)
    body = _name_body(_extrude(component, [_largest_profile(sketch)], "collar_h",
                               features.NewBodyFeatureOperation), "collar")
    log("  tube, %s tall" % "collar_h")

    sketch = _sketch(component, planes["SK_lid_top"], "collar_spigot")
    _rect(sketch, v["collar_offset_x"], 0, v["collar_spigot_l"], v["collar_spigot_w"],
          "collar_spigot_l", "collar_spigot_w", "collar_offset_x", None)
    _extrude(component, [_largest_profile(sketch)], "-collar_spigot_h",
             features.JoinFeatureOperation, bodies=[body])
    log("  press-fit spigot below, an interference fit in the lid opening")

    # One symmetric cut opens the tube above and the spigot below.
    sketch = _sketch(component, planes["SK_lid_top"], "collar_bore")
    _rect(sketch, v["collar_offset_x"], 0, v["collar_inner_l"], v["collar_inner_w"],
          "collar_inner_l", "collar_inner_w", "collar_offset_x", None)
    _extrude(component, [_largest_profile(sketch)], "(collar_h + cut_overshoot) * 2",
             features.CutFeatureOperation, symmetric=True, bodies=[body])
    log("  bore, clearing the boss and the cell")

    log("collar: built")
    return body


def _build_pan(design, root, planes, v, log):
    log("--- pan ---")
    component = root
    features = adsk.fusion.FeatureOperations

    # The outline is two overlapping circles, which is what V1 actually is: a
    # main circle the bottle stands on, plus a smaller lobe reaching back over
    # the load cell. Fitting circles to the V1 mesh matches its measured width
    # at every station to about 1 mm.
    #
    # The curve is not decoration. A rectangle of the same overall size sweeps
    # 45 mm of half-width straight across the button footprint; the circle has
    # zero width there, which is precisely why V1 was shaped this way.
    sketch = _sketch(component, planes["SK_pan_base"], "pan_main")
    _circle(sketch, v["pan_offset_x"], 0, v["pan_main_dia"], "pan_main_dia",
            "pan_offset_x", None)
    body = _name_body(_extrude(component, [_largest_profile(sketch)], "pan_plate",
                               features.NewBodyFeatureOperation), "pan")
    log("  main circle, pan_main_dia, centred on the load cell free end")

    # Separate sketch per circle: two circles sharing a centreline in one sketch
    # make Fusion infer an alignment and reject the second position dimension.
    sketch = _sketch(component, planes["SK_pan_base"], "pan_lobe")
    _circle(sketch, v["pan_offset_x"] + v["pan_lobe_offset"], 0, v["pan_lobe_dia"],
            "pan_lobe_dia", "pan_offset_x + pan_lobe_offset", None)
    _extrude(component, [_largest_profile(sketch)], "pan_plate",
             features.JoinFeatureOperation, bodies=[body])
    log("  lobe joined, giving the V1 paddle outline")

    # No pad and no skirt on the underside. Both would hold the plate off the
    # bed and force support right under the bottle-contact face. The pan is a
    # plain flat plate; a spacer washer on the screw does the pad's job, and the
    # collar alone already hides the cell.


    sketch = _sketch(component, planes["SK_pan_face"], "pan_locating_recess")
    _circle(sketch, v["pan_offset_x"], 0, v["pan_recess_dia"], "pan_recess_dia",
            "pan_offset_x", None)
    _extrude(component, [_largest_profile(sketch)], "-pan_recess_depth",
             features.CutFeatureOperation, bodies=[body])
    log("  bottle locating recess on the bottle side: the corner-load fix")

    sketch = _sketch(component, planes["SK_pan_face"], "pan_counterbore")
    _circle(sketch, v["pan_offset_x"], 0, v["pan_counterbore_dia"],
            "pan_counterbore_dia", "pan_offset_x", None)
    _extrude(component, [_largest_profile(sketch)], "-pan_cbore_depth",
             features.CutFeatureOperation, bodies=[body])
    log("  screw-head counterbore")

    sketch = _sketch(component, planes["SK_pan_face"], "pan_bore")
    _circle(sketch, v["pan_offset_x"], 0, v["pan_bore_dia"], "pan_bore_dia",
            "pan_offset_x", None)
    _extrude(component, [_largest_profile(sketch)], "-(pan_plate + cut_overshoot)",
             features.CutFeatureOperation, bodies=[body])
    log("  cut M5 mount bore")

    log("pan: built")
    return body


# ---------------------------------------------------------------- entry

def build_form(design, log):
    """The sketches and features that make the three parts."""
    root = design.rootComponent
    planes = {}
    for name in ("SK_floor_top", "SK_wall_top", "SK_lid_top",
                 "SK_boss_top", "SK_case_back", "SK_pan_base", "SK_pan_face",
                 "SK_lid_underside"):
        plane = _find_plane(root, name)
        if plane is None:
            raise RuntimeError("skeleton plane %s missing: build_skeleton did not run" % name)
        planes[name] = plane

    v = _values(design)
    base_body = _build_base(design, root, planes, v, log)
    lid_body = _build_lid(design, root, planes, v, log)
    collar_body = _build_collar(design, root, planes, v, log)
    pan_body = _build_pan(design, root, planes, v, log)

    log("--- edge breaking ---")
    half_l, half_w = v["case_l"] / 2.0, v["case_w"] / 2.0
    for body, label in ((base_body, "base"), (lid_body, "lid")):
        _round_outer_corners(root, body, half_l, half_w, "fillet_external", log, label)

    # Cutout mouths. Done last so that if an edge reference ever breaks it
    # costs a chamfer and nothing else.
    _chamfer_openings(root, lid_body, v["lid_top_z"], "chamfer_applied",
                      log, "lid cutouts", interior=True)
    _chamfer_openings(root, base_body, 0.0, "chamfer_applied",
                      log, "base underside counterbores", interior=True)
    _chamfer_openings(root, collar_body,
                      v["lid_top_z"] - v["collar_spigot_h"], "chamfer_leadin",
                      log, "collar spigot lead-in", interior=False)
    _chamfer_openings(root, pan_body, v["pan_assembly_z"] + v["pan_plate"],
                      "chamfer_applied", log, "pan cutouts", interior=True)
    # The pan's outer edge is the most handled edge on the whole device, so it
    # gets broken too. Classifying it as perimeter is correct, but perimeter is
    # not the same as "leave alone".
    _chamfer_openings(root, pan_body, v["pan_assembly_z"] + v["pan_plate"],
                      "chamfer_applied", log, "pan outer edge", interior=False)


def prune_orphan_parameters(design, table, log):
    """Delete user parameters left over from an earlier version of the table.

    Only safe immediately after the reset, when no geometry references anything.
    Without this, a document accumulates dead parameters every time a formula is
    renamed, and they look like real inputs to whoever opens it next.
    """
    known = {name for name, spec in table.items()
             if spec.get("role") != "note" and not name.startswith("_")}
    removed = []
    for i in range(design.userParameters.count - 1, -1, -1):
        param = design.userParameters.item(i)
        if param.name not in known:
            try:
                param.deleteMe()
                removed.append(param.name)
            except Exception:
                pass
    if removed:
        log("reset: pruned %d dead parameter(s): %s"
            % (len(removed), ", ".join(sorted(removed))))


def build(design, log, skeleton_only=False, reset=True, table=None):
    if reset:
        reset_document(design, log)
        if table:
            prune_orphan_parameters(design, table, log)
    build_skeleton(design, log)
    if skeleton_only:
        log("form: skipped (skeleton_only)")
        return
    build_form(design, log)
