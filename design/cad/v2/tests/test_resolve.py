#!/usr/bin/env python3
"""Smoke tests for the parts of the build that do not need Fusion.

Parameter resolution, name validation and provenance auditing are pure
functions over the JSON tables, so they can be tested on any machine without
Fusion running. This catches the common breakages (a profile overriding a
parameter that was renamed, a formula referencing a parameter that no longer
exists) before anyone opens the CAD.

    python3 tests/test_resolve.py
"""

import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import bundle  # noqa: E402


def load_bundled():
    """Exec the generated script with adsk stubbed out, and hand back its namespace."""
    script = bundle.build_script({"params_file": "params/default.json"})
    fake_adsk = types.ModuleType("adsk")
    fake_adsk.core = types.ModuleType("adsk.core")
    fake_adsk.fusion = types.ModuleType("adsk.fusion")
    sys.modules["adsk"] = fake_adsk
    sys.modules["adsk.core"] = fake_adsk.core
    sys.modules["adsk.fusion"] = fake_adsk.fusion
    namespace = {"__name__": "bundled"}
    exec(compile(script, "fusion_script.py", "exec"), namespace)
    return namespace


FAILURES = []


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        FAILURES.append(message)


def main():
    ns = load_bundled()
    params, profiles, standards = ns["PARAMS"], ns["PROFILES"], ns["COMPONENT_SETS"]
    resolve_table, check_names = ns["resolve_table"], ns["check_names"]
    audit = ns["audit_provenance"]

    print("parameter names")
    check(check_names(params) == [], "all names are valid Fusion identifiers")

    print("formula references resolve")
    known = set(params)
    dangling = []
    for name, spec in params.items():
        # Pull identifiers out of the expression, ignoring unit suffixes.
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(spec["expression"])):
            if token in ("mm", "cm", "in", "deg", "rad"):
                continue
            if token not in known and token not in ns["RESERVED_NAMES"]:
                dangling.append("%s -> %s" % (name, token))
    check(not dangling, "no formula references an unknown parameter %s" % (dangling or ""))

    print("every process profile resolves")
    for profile_name in profiles:
        try:
            table, _ = resolve_table(params, profiles, standards, profile_name, "TO_CONFIRM")
            check(len(table) == len(params), "profile %r resolves" % profile_name)
        except Exception as exc:
            check(False, "profile %r: %s" % (profile_name, exc))

    print("every component set resolves")
    for set_name in standards:
        try:
            resolve_table(params, profiles, standards, "fdm_prototype", set_name)
            check(True, "set %r resolves" % set_name)
        except Exception as exc:
            check(False, "set %r: %s" % (set_name, exc))

    print("profiles actually change the fits")
    fdm, _ = resolve_table(params, profiles, standards, "fdm_prototype", "TO_CONFIRM")
    ipp, _ = resolve_table(params, profiles, standards, "injection_pp", "TO_CONFIRM")
    check(fdm["fit_lid"]["expression"] != ipp["fit_lid"]["expression"],
          "switching process profile re-tunes fit_lid")
    check(ipp["draft_angle"]["expression"] != "0 deg",
          "injection profile carries real draft, FDM does not")

    print("unknown names are rejected, not silently ignored")
    for bad in (
        lambda: resolve_table(params, profiles, standards, "nope", "TO_CONFIRM"),
        lambda: resolve_table(params, profiles, standards, "fdm_prototype", "nope"),
    ):
        try:
            bad()
            check(False, "expected a rejection")
        except ValueError:
            check(True, "unknown profile/set raises")

    print("ranges are sane")
    bad_ranges = [n for n, s in params.items()
                  if s.get("min") is not None and s.get("max") is not None
                  and s["min"] > s["max"]]
    check(not bad_ranges, "no parameter has min > max %s" % (bad_ranges or ""))

    print("provenance")
    placeholders = audit(fdm)
    check(bool(placeholders), "placeholder parameters are detected (%d)" % len(placeholders))
    print("       unmeasured: %s" % ", ".join(placeholders))

    print("\n%s (%d failure(s))" % ("PASS" if not FAILURES else "FAIL", len(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
