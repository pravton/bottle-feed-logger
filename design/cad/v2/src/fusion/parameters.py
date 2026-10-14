# Parameter push: resolves the parameter table and writes it into the active
# Fusion design as real User Parameters, with live formulas.
#
# CONCATENATION CONTRACT
# This file is bundled into a single standalone Fusion script by src/bundle.py.
# It must not import sibling modules. It may assume the bundle header has
# already done `import adsk.core, adsk.fusion` and defined PARAMS, PROFILES and
# COMPONENT_SETS as dicts. Define functions only; do no work at import time.

# Fusion rejects names that are not identifiers, and silently does odd things
# with names that shadow its own functions.
RESERVED_NAMES = {
    "abs", "acos", "asin", "atan", "cos", "sin", "tan", "exp", "log", "ln",
    "sqrt", "pi", "e", "min", "max", "pow", "round", "ceil", "floor",
}


def resolve_table(params, profiles, standards, profile_name, standard_name):
    """Apply component-set then process-profile overrides onto the base table.

    Order matters. The component set describes the thing we must fit, so it
    goes on first. The process profile describes how we make it, and its
    clearances are allowed to override anything the component set implied.

    Returns (resolved_table, list_of_warnings).
    """
    warnings = []
    table = {name: dict(spec) for name, spec in params.items()}

    std = standards.get(standard_name)
    if std is None:
        raise ValueError(
            "Unknown component set %r. Available: %s"
            % (standard_name, sorted(standards))
        )
    if std.get("source") == "placeholder" and std.get("overrides"):
        warnings.append(
            "Component set %r is PLACEHOLDER: dimensions are not measured. "
            "Do not release tooling from this build." % standard_name
        )
    for name, expr in std.get("overrides", {}).items():
        # Check the name before checking for TO_CONFIRM. The other order lets a
        # set keep listing a parameter that has since been renamed or deleted:
        # it gets skipped as "unconfirmed" and never validated, so the set looks
        # healthy while silently overriding nothing.
        if name not in table:
            raise ValueError(
                "Component set %r overrides unknown parameter %r"
                % (standard_name, name)
            )
        if table[name].get("role") == "derived":
            raise ValueError(
                "Component set %r overrides %r, which is a derived parameter. "
                "A set supplies component dimensions; it must not overwrite a "
                "formula, because doing so silently breaks the relationship the "
                "formula exists to guarantee." % (standard_name, name)
            )
        if expr == "TO_CONFIRM":
            warnings.append(
                "Component set %r leaves %s unconfirmed; falling back to the "
                "placeholder in default.json." % (standard_name, name)
            )
            continue
        table[name]["expression"] = expr
        table[name]["source"] = "measured"

    prof = profiles.get(profile_name)
    if prof is None:
        raise ValueError(
            "Unknown process profile %r. Available: %s"
            % (profile_name, sorted(profiles))
        )
    for name, expr in prof.get("overrides", {}).items():
        if name not in table:
            raise ValueError(
                "Process profile %r overrides unknown parameter %r"
                % (profile_name, name)
            )
        table[name]["expression"] = expr

    return table, warnings


def _modelled(table):
    """Parameters that become real Fusion User Parameters."""
    return {
        name: spec
        for name, spec in table.items()
        if spec.get("role") != "note" and not name.startswith("_")
    }


def check_names(table):
    """Reject names Fusion will mangle, before we touch the document."""
    problems = []
    for name in _modelled(table):
        if not name.isidentifier():
            problems.append("%r is not a valid identifier" % name)
        elif name in RESERVED_NAMES:
            problems.append("%r shadows a Fusion expression function" % name)
    return problems


def _seed_for(spec):
    """A safe placeholder value used during pass 1.

    Non-zero so that a formula dividing by this parameter does not blow up in
    the window between creation and getting its real expression.
    """
    units = spec.get("units", "")
    return "1 %s" % units if units else "1"


def push(design, table, log):
    """Create or update User Parameters from the resolved table.

    Two passes, deliberately. Formulas reference other parameters, and Fusion
    cannot create a parameter whose expression names one that does not exist
    yet. Pass 1 creates every parameter with a harmless literal so the whole
    namespace exists; pass 2 applies the real expressions, which can then
    reference each other in any order. This removes the need to declare
    parameters in dependency order in the JSON.
    """
    problems = check_names(table)
    if problems:
        raise ValueError("Invalid parameter names: " + "; ".join(problems))

    modelled = _modelled(table)
    user_params = design.userParameters
    created, updated = [], []

    # Pass 1: ensure the namespace exists.
    for name, spec in modelled.items():
        if user_params.itemByName(name) is not None:
            continue
        value = adsk.core.ValueInput.createByString(_seed_for(spec))
        user_params.add(name, value, spec.get("units", ""), spec.get("comment", ""))
        created.append(name)

    # Pass 2: apply real expressions, retrying until nothing more will take.
    #
    # Order matters here in a way pass 1 hides. A derived length whose inputs
    # still hold their seed value can evaluate negative in the intermediate
    # state, and Fusion rejects a negative length outright. Rather than sort the
    # table topologically, just keep sweeping: each round some parameters get
    # their real value, which unblocks the ones that depend on them.
    pending = dict(modelled)
    last_error = {}
    while pending:
        progressed = []
        for name, spec in list(pending.items()):
            param = user_params.itemByName(name)
            expression = spec["expression"]
            if param.expression == expression:
                progressed.append(name)
                continue
            try:
                param.expression = expression
            except Exception as exc:
                last_error[name] = exc
                continue
            if name not in created:
                updated.append(name)
            progressed.append(name)
        for name in progressed:
            del pending[name]
        if not progressed:
            stuck = sorted(pending)
            raise ValueError(
                "These parameters would not accept their expressions: %s. First "
                "failure: %r -> %r (%s). Check for a typo in a referenced name, "
                "a circular reference, or a formula that is negative for every "
                "possible ordering."
                % (", ".join(stuck), stuck[0], pending[stuck[0]]["expression"],
                   last_error.get(stuck[0], "unknown")))

    for name, spec in modelled.items():
        param = user_params.itemByName(name)
        comment = _comment_for(name, spec)
        if param.comment != comment:
            param.comment = comment

    log("parameters: %d created, %d updated, %d unchanged"
        % (len(created), len(updated), len(modelled) - len(created) - len(updated)))
    if created:
        log("  created: " + ", ".join(sorted(created)))
    if updated:
        log("  updated: " + ", ".join(sorted(updated)))

    return {"created": created, "updated": updated}


def _comment_for(name, spec):
    """Stamp role and provenance into the Fusion comment.

    This is what stops the model rotting. Anyone opening Change Parameters in
    Fusion can see at a glance which values are inputs they may edit, which are
    formulas they must not, and which are still unmeasured guesses.
    """
    role = spec.get("role", "driving")
    bits = ["[%s]" % role.upper()]
    if spec.get("source") == "placeholder":
        bits.append("[PLACEHOLDER: NOT MEASURED]")
    if role == "derived":
        bits.append("[DO NOT EDIT: edit the source parameters instead]")
    if spec.get("comment"):
        bits.append(spec["comment"])
    if spec.get("min") is not None and spec.get("max") is not None:
        bits.append("(valid %s..%s)" % (spec["min"], spec["max"]))
    return " ".join(bits)


def orphans(design, table):
    """User Parameters in the document that the table does not know about.

    These are how a scripted model drifts: someone adds a parameter by hand in
    Fusion, geometry starts depending on it, and it is invisible to the repo.
    Reported, never auto-deleted: deleting one that geometry references would
    break the timeline.
    """
    known = set(_modelled(table))
    found = []
    for i in range(design.userParameters.count):
        param = design.userParameters.item(i)
        if param.name not in known:
            found.append(param.name)
    return found
