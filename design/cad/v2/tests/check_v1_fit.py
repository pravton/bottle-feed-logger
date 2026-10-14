#!/usr/bin/env python3
"""Evaluate the parameter formulas numerically and compare against V1.

A parametric model that cannot reproduce the prototype it was derived from is
not a rebuild, it is a new design wearing the old one's numbers. This evaluates
every formula and diffs the derived values against the measurements in
docs/v1-teardown.md.

Mismatches are expected while components are unconfirmed: that is the point.
Each one names a specific number that has to be measured before V2 geometry can
be trusted.

    python3 tests/check_v1_fit.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_resolve import load_bundled  # noqa: E402

# Measured from the V1 meshes. See docs/v1-teardown.md.
V1 = {
    "case_l": 150.00,
    "case_w": 104.00,
    "cavity_l": 140.50,
    "cavity_w": 94.00,
    "wall_top_z": 15.50,
    "boss_l": 28.00,
    "boss_w": 17.00,
    "boss_h": 20.00,
    "floor_t": 3.00,
    "pan_l": 110.00,
    "pan_w": 90.00,
    "pan_plate": 5.00,
    "lid_rebate_depth": 1.50,
}

# Places V2 deliberately departs from V1, with the reason. Without this they
# read as defects forever, and a permanently-failing check gets ignored.
EXPECTED_DIFFERENCES = {
    "boss_w": "V1 used 1.0 mm of boss wall along its length but 2.07 mm across, "
              "the same asymmetry as its 4.75/5.00 case wall. V2 uses one uniform "
              "boss_wall, so the width comes out 15.0 instead of 17.13",
}

TOLERANCE = 0.05  # mm


def strip_units(expression):
    """Drop unit suffixes so the expression is plain arithmetic."""
    return re.sub(r"\b(mm|cm|deg|rad|in)\b", "", str(expression))


def evaluate(table):
    """Resolve every parameter to a number, following formula dependencies.

    Iterates to a fixed point rather than topologically sorting, because the
    JSON deliberately does not require declaration order and the dependency
    graph is tiny.
    """
    values, unresolved = {}, {}
    for name, spec in table.items():
        if spec.get("role") == "note":
            continue
        unresolved[name] = strip_units(spec["expression"])

    for _ in range(len(unresolved) + 2):
        if not unresolved:
            break
        for name in list(unresolved):
            try:
                values[name] = float(eval(  # noqa: S307 - fixed, repo-controlled input
                    unresolved[name], {"__builtins__": {}, "abs": abs}, dict(values)
                ))
                del unresolved[name]
            except Exception:
                continue

    return values, unresolved


def placeholder_roots(table, name, seen=None):
    """Every unconfirmed parameter this one depends on, at any depth.

    Walking transitively matters: case_l references cavity_l, which references
    pcb_l. Checking only direct references would report case_l as an unexplained
    mismatch when the real cause is one unmeasured PCB dimension two hops away.
    """
    seen = seen if seen is not None else set()
    if name in seen or name not in table:
        return set()
    seen.add(name)

    if table[name].get("source") == "placeholder":
        return {name}

    roots = set()
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(table[name]["expression"])):
        if token in table:
            roots |= placeholder_roots(table, token, seen)
    return roots


def main():
    ns = load_bundled()
    table, warnings = ns["resolve_table"](
        ns["PARAMS"], ns["PROFILES"], ns["COMPONENT_SETS"], "fdm_prototype", "v1_measured"
    )
    for warning in warnings:
        print("WARN %s" % warning)

    values, unresolved = evaluate(table)
    if unresolved:
        print("\nUNRESOLVED formulas (circular or referencing a missing parameter):")
        for name, expression in sorted(unresolved.items()):
            print("  %-24s %s" % (name, expression))

    print("\n%-24s %10s %10s %9s  %s" % ("parameter", "V2 model", "V1 actual", "delta", "status"))
    print("-" * 74)

    blocking = []
    for name in sorted(V1):
        target = V1[name]
        actual = values.get(name)
        if actual is None:
            print("%-24s %10s %10.2f %9s  NOT IN MODEL" % (name, "-", target, "-"))
            blocking.append(name)
            continue
        delta = actual - target
        if abs(delta) <= TOLERANCE:
            status = "match"
        else:
            source = table[name].get("source", "")
            drivers = placeholder_roots(table, name)
            if name in EXPECTED_DIFFERENCES:
                status = "intentional: " + EXPECTED_DIFFERENCES[name][:52] + "..."
            elif drivers:
                status = "needs: " + ", ".join(sorted(drivers))
            elif source == "design":
                status = "intentional V2 change"
            else:
                status = "MISMATCH"
                blocking.append(name)
        print("%-24s %10.2f %10.2f %+9.2f  %s" % (name, actual, target, delta, status))

    print()
    if blocking:
        print("%d parameter(s) genuinely disagree with V1 and are not explained "
              "by an unconfirmed component: %s" % (len(blocking), ", ".join(blocking)))
    else:
        print("Every difference from V1 is either an intentional V2 change or "
              "traceable to a component dimension that is not confirmed yet.")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
