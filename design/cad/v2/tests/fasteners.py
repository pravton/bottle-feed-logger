#!/usr/bin/env python3
"""Fastener list, derived from the parameter table.

Every screw length here comes from the geometry: how much plastic sits between
the head seat and whatever the thread bites into, and how far the tip can go
before it breaks a surface or touches something it must not. Picking lengths by
eye is how a BOM drifts out of step with the model, so the BOM is written from
this report instead.

    python3 tests/fasteners.py              # markdown table for the BOM
    python3 tests/fasteners.py --check      # exit 1 if any screw has no stock length
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from check_v1_fit import evaluate  # noqa: E402
from test_resolve import load_bundled  # noqa: E402

# ISO metric stock lengths, the ones any hardware shop carries.
STOCK_LENGTHS = (6, 8, 10, 12, 14, 16, 20, 25, 30, 35, 40)


def stock_length(minimum, maximum):
    """Shortest stock length inside [minimum, maximum], or None if none fits."""
    for length in STOCK_LENGTHS:
        if minimum - 1e-6 <= length <= maximum + 1e-6:
            return length
    return None


def resolved_values():
    ns = load_bundled()
    meta = ns["META"]
    table, _ = ns["resolve_table"](
        ns["PARAMS"], ns["PROFILES"], ns["COMPONENT_SETS"],
        meta.get("process_profile", "fdm_prototype"),
        meta.get("component_set", "v1_measured"))
    values, unresolved = evaluate(table)
    if unresolved:
        raise SystemExit("parameters did not resolve: %s" % ", ".join(sorted(unresolved)))
    return meta, values


def fasteners(v):
    """(qty, description, thread, min, max, where) for every screw in the build."""
    return [
        (4, "button head, ISO 7380", "M%g" % v["screw_dia"],
         v["screw_length_min"], v["screw_length_max"],
         "Lid to base, from underneath. Self-taps into the printed pilot in each standoff"),
        (2, "socket head, ISO 4762", "M%g" % v["load_cell_screw_dia"],
         v["cell_fixed_screw_len_min"], v["cell_fixed_screw_len_max"],
         "Load cell fixed end into the base boss, from underneath"),
        (1, "button head, ISO 7380", "M%g" % v["load_cell_free_thread"],
         v["pan_screw_len_min"], v["pan_screw_len_max"],
         "Pan onto the load cell free end, through the spacer"),
    ]


def main(argv):
    meta, v = resolved_values()
    rows = fasteners(v)
    missing = []

    print("Fasteners for %s %s (%s, %s)\n" % (
        meta.get("name"), meta.get("version"),
        meta.get("process_profile"), meta.get("component_set")))
    print("| Qty | Screw | Length | Fits | Where |")
    print("|---|---|---|---|---|")
    for qty, kind, thread, lo, hi, where in rows:
        length = stock_length(lo, hi)
        if length is None:
            missing.append(thread)
        print("| %d | %s %s | %s | %.1f to %.1f | %s |" % (
            qty, thread, kind, ("%d mm" % length) if length else "**none**",
            lo, hi, where))
    print("| 1 | Washer, %.1f OD x %.1f | | | Spacer between the cell and the pan |"
          % (v["pan_spacer_dia"], v["pan_spacer_h"]))

    if missing and "--check" in argv:
        print("\nno stock length fits: %s" % ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
