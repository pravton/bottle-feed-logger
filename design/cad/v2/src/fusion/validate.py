# Validation: proves the model actually is parametric, rather than merely
# having parameters.
#
# CONCATENATION CONTRACT: see the note at the top of parameters.py.

HEALTH_OK = 0  # adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState


def timeline_health(design):
    """Every timeline feature that is erroring or warning.

    A parametric model is only worth having if it survives a parameter change.
    The usual failure is a fillet or shell keyed to an auto-numbered face that
    stops existing when a dimension moves: the feature goes red, and if nobody
    is checking, a broken model gets exported and quoted.
    """
    bad = []
    timeline = design.timeline
    for i in range(timeline.count):
        item = timeline.item(i)
        try:
            state = item.healthState
        except Exception:
            continue
        if state != HEALTH_OK:
            bad.append({
                "index": i,
                "name": item.name,
                "state": int(state),
                "message": item.errorOrWarningMessage or "",
            })
    return bad


def find_literal_dimensions(design):
    """Sketch dimensions that are bare numbers instead of parameter formulas.

    This is the check that actually enforces "no magic numbers". A single
    hardcoded 58 in a sketch is invisible in the Fusion UI but silently breaks
    the promise of the model: resize bottle_body_dia and that one dimension
    stays put, and the part quietly stops fitting.
    """
    literals = []
    for i in range(design.rootComponent.sketches.count):
        sketch = design.rootComponent.sketches.item(i)
        for j in range(sketch.sketchDimensions.count):
            dimension = sketch.sketchDimensions.item(j)
            param = dimension.parameter
            if param is None:
                continue
            expression = (param.expression or "").strip()
            # A formula references at least one parameter, so it contains a
            # letter that is not a unit suffix.
            stripped = expression
            for unit in (" mm", " cm", " in", " deg", " rad", "mm", "cm", "in", "deg", "rad"):
                if stripped.endswith(unit):
                    stripped = stripped[: -len(unit)]
                    break
            try:
                float(stripped.strip())
            except ValueError:
                continue  # contains a reference, so it is fine
            literals.append({
                "sketch": sketch.name,
                "dimension": param.name,
                "expression": expression,
            })
    return literals


def sweep(design, table, log, params_to_sweep=None):
    """Rebuild at each driving parameter's range extremes.

    This is the regression test. Nominal always works: that is the value the
    model was built at. Breakage shows up at the edges of the declared range,
    which is exactly where someone resizing the design will end up.

    Each parameter is swept independently and restored afterwards, so a failure
    names one parameter rather than a combination.
    """
    failures = []
    swept = 0

    for name, spec in sorted(table.items()):
        if spec.get("role") not in ("driving",):
            continue
        if spec.get("min") is None or spec.get("max") is None:
            continue
        if params_to_sweep and name not in params_to_sweep:
            continue

        param = design.userParameters.itemByName(name)
        if param is None:
            failures.append({"parameter": name, "at": "-", "error": "not in document"})
            continue

        original = param.expression
        units = spec.get("units", "")

        for bound in ("min", "max"):
            value = spec[bound]
            expression = ("%s %s" % (value, units)) if units else str(value)
            try:
                param.expression = expression
                design.computeAll()
            except Exception as exc:
                failures.append({
                    "parameter": name, "at": bound,
                    "expression": expression, "error": str(exc),
                })
                continue

            broken = timeline_health(design)
            if broken:
                failures.append({
                    "parameter": name, "at": bound, "expression": expression,
                    "error": "%d timeline feature(s) unhealthy: %s"
                             % (len(broken), ", ".join(b["name"] for b in broken)),
                })

        param.expression = original
        swept += 1

    design.computeAll()
    log("sweep: %d driving parameters exercised at min and max, %d failure(s)"
        % (swept, len(failures)))
    for f in failures:
        log("  FAIL %s @ %s: %s" % (f["parameter"], f["at"], f["error"]))
    return failures


def audit_provenance(table):
    """Which numbers are still guesses.

    A model full of placeholders can look finished. This makes the unmeasured
    ones impossible to miss before anyone commits money to tooling.
    """
    return sorted(
        name for name, spec in table.items()
        if spec.get("source") == "placeholder" and spec.get("role") != "note"
    )


def check_safety_limits(design, table, log):
    """Static checks against the safety parameters.

    Geometric checks (minimum achieved wall, edge radii, pinch gaps) need the
    solid body and are added with the geometry. What is checkable now is that
    the limits themselves are self-consistent: a model cannot satisfy limits
    that contradict each other.
    """
    problems = []

    def value_of(name):
        param = design.userParameters.itemByName(name)
        return param.value if param is not None else None

    wall = value_of("wall")
    min_wall = value_of("min_wall")
    if wall is not None and min_wall is not None and wall < min_wall:
        problems.append(
            "wall (%.2f) is below min_wall (%.2f): the nominal wall violates "
            "the process minimum" % (wall * 10, min_wall * 10)
        )

    fillet = value_of("fillet_external")
    min_radius = value_of("min_edge_radius")
    if fillet is not None and min_radius is not None and fillet < min_radius:
        problems.append(
            "fillet_external (%.2f) is below min_edge_radius (%.2f): external "
            "edges would be sharper than the infant-contact limit"
            % (fillet * 10, min_radius * 10)
        )

    for name, spec in table.items():
        if spec.get("min") is None or spec.get("max") is None:
            continue
        if spec["min"] > spec["max"]:
            problems.append("%s has min > max in the parameter table" % name)

    log("safety limits: %d problem(s)" % len(problems))
    for p in problems:
        log("  FAIL " + p)
    return problems


def report(design, table, log, run_sweep=True):
    """Full validation pass. Returns a dict; non-empty lists mean not shippable."""
    log("--- validation ---")

    result = {
        "chamfer_refusals": list(CHAMFER_REFUSALS),
        "timeline": timeline_health(design),
        "orphan_parameters": orphans(design, table),
        "literal_dimensions": find_literal_dimensions(design),
        "placeholders": audit_provenance(table),
        "safety": check_safety_limits(design, table, log),
        "sweep": sweep(design, table, log) if run_sweep else [],
    }

    if result["literal_dimensions"]:
        log("magic numbers: %d sketch dimension(s) hardcoded instead of driven "
            "by a parameter" % len(result["literal_dimensions"]))
        for d in result["literal_dimensions"]:
            log("  FAIL %s / %s = %s" % (d["sketch"], d["dimension"], d["expression"]))
    else:
        log("magic numbers: none")

    if result["timeline"]:
        log("timeline: %d unhealthy feature(s) at nominal" % len(result["timeline"]))
        for b in result["timeline"]:
            log("  FAIL [%d] %s: %s" % (b["index"], b["name"], b["message"]))
    else:
        log("timeline: healthy at nominal")

    if result["orphan_parameters"]:
        log("orphans: %d parameter(s) in the document but not in the repo: "
            "these will be lost on the next machine that builds this model"
            % len(result["orphan_parameters"]))
        for name in result["orphan_parameters"]:
            log("  WARN " + name)

    if result["placeholders"]:
        log("provenance: %d parameter(s) NOT MEASURED: prototype only, "
            "not releasable" % len(result["placeholders"]))
        log("  " + ", ".join(result["placeholders"]))

    if result["chamfer_refusals"]:
        log("chamfers: %d refused for lack of material. Raise whichever of "
            "lid_skin, screw_head_h or boss_wall is smallest, or lower chamfer_cutout"
            % len(result["chamfer_refusals"]))
        for line in result["chamfer_refusals"]:
            log("  FAIL " + line)

    blocking = (result["timeline"] + result["sweep"] + result["safety"]
                + result["literal_dimensions"] + result["chamfer_refusals"])
    log("--- %s ---" % ("PASS" if not blocking else "FAIL (%d)" % len(blocking)))
    return result
