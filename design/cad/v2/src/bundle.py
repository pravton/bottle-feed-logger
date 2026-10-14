#!/usr/bin/env python3
"""Compose the standalone Fusion script from the parameter tables and modules.

Fusion runs a single script file with a `run(context)` entry point, and has no
sensible way to import project modules from an arbitrary folder. So the repo
keeps the code split into readable modules and this bundler concatenates them,
embedding the parameter tables as literals.

The output, build/fusion_script.py, is self-contained: it can be sent through
the Fusion MCP or added under Utilities > Scripts and Add-Ins.

    python3 src/bundle.py --out build/fusion_script.py
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Concatenation order matters: main calls into all of them, and export.py's
# manifest writer consumes validate.py's output shape.
MODULES = [
    "src/fusion/parameters.py",
    "src/fusion/geometry.py",
    "src/fusion/validate.py",
    "src/fusion/export.py",
]

HEADER = '''# GENERATED FILE: DO NOT EDIT.
# Produced by src/bundle.py from the modules under src/fusion/ and the tables
# under params/. Edit those and re-bundle; edits here are overwritten.
#
# Entry point: run(context), at the bottom of this file.

import json
import traceback

import adsk.core
import adsk.fusion

# Tables are embedded as JSON text and parsed at load, rather than pasted in as
# Python literals. JSON null/true/false are not Python, so a literal paste
# breaks the moment any table grows a null.
PARAMS = json.loads({params})

PROFILES = json.loads({profiles})

COMPONENT_SETS = json.loads({standards})

META = json.loads({meta})

BUILD_CONFIG = json.loads({config})

_LOG_LINES = []


def log(message):
    _LOG_LINES.append(str(message))
    print(message)

'''

MAIN = '''

def run(_context: str):
    try:
        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)
        if design is None:
            raise RuntimeError(
                "No active Fusion design. Open or create a design document "
                "first, and make sure it is in Design workspace, not CAM."
            )

        # A parametric model is meaningless in direct-modelling mode: features
        # are not kept, so changing a parameter changes nothing downstream.
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            raise RuntimeError(
                "Design is in Direct Modelling mode. Switch to Parametric "
                "(right-click the document name in the browser > Do not "
                "capture Design History > uncheck) before building."
            )

        profile_name = BUILD_CONFIG["process_profile"]
        standard_name = BUILD_CONFIG["component_set"]
        log("build: profile=%s standard=%s" % (profile_name, standard_name))

        table, warnings = resolve_table(
            PARAMS, PROFILES, COMPONENT_SETS, profile_name, standard_name
        )
        for warning in warnings:
            log("  WARN " + warning)

        push(design, table, log)

        try:
            build(design, log, skeleton_only=BUILD_CONFIG.get("skeleton_only", False),
                  table=table)
        except NotImplementedError as exc:
            log("form: NOT BUILT (%s)" % exc)

        validation = report(
            design, table, log, run_sweep=BUILD_CONFIG.get("sweep", True)
        )

        if BUILD_CONFIG.get("export"):
            out_dir = BUILD_CONFIG.get("export_dir") or "."
            meta = dict(META)
            meta["process_profile"] = profile_name
            meta["component_set"] = standard_name
            export_all(design, meta, out_dir, log)
            log("manifest: " + export_manifest(table, meta, validation, out_dir))
        else:
            log("export: skipped")

    except Exception:
        # Never swallow this. Fusion shows nothing useful on an uncaught script
        # error, and without the traceback there is no way to tell which
        # feature or parameter rejected what.
        print("BUILD FAILED\\n" + traceback.format_exc())
        raise
'''


def read(relative_path):
    with open(os.path.join(ROOT, relative_path)) as handle:
        return handle.read()


def load_json(relative_path):
    return json.loads(read(relative_path))


def strip_comment_keys(obj):
    """Drop the _comment / _design_note documentation keys from the tables.

    They are there for whoever edits the JSON, and only bloat the generated
    script. Parameter entries whose own name starts with _ are kept, because
    parameters.py filters those deliberately and reports on them.
    """
    if isinstance(obj, dict):
        return {
            key: strip_comment_keys(value)
            for key, value in obj.items()
            if key not in ("_comment", "_design_note")
        }
    if isinstance(obj, list):
        return [strip_comment_keys(item) for item in obj]
    return obj


def provenance(params_doc, profiles_doc, standards_doc):
    """Version stamp carried into every export manifest.

    params_digest fingerprints only what changes the geometry: every parameter
    expression plus every profile and component-set override. Editing a comment
    leaves it alone; changing a value does not. git_sha says which commit the
    model came from, marked -dirty if the parameters or the source had
    uncommitted edits at bundle time, because a release built from those cannot
    be reproduced from the repo.
    """
    geometry_inputs = {
        "parameters": {name: spec.get("expression")
                       for name, spec in params_doc["parameters"].items()},
        "profiles": {name: prof.get("overrides", {})
                     for name, prof in profiles_doc["profiles"].items()},
        "sets": {name: comp.get("overrides", {})
                 for name, comp in standards_doc["sets"].items()},
    }
    digest = hashlib.sha256(
        json.dumps(geometry_inputs, sort_keys=True).encode("utf-8")).hexdigest()[:12]

    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            stderr=subprocess.DEVNULL).decode().strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--", "params", "src"], cwd=ROOT,
            stderr=subprocess.DEVNULL).decode().strip()
        if dirty:
            sha += "-dirty"
    except (OSError, subprocess.CalledProcessError):
        sha = "unknown"
    return {"git_sha": sha, "params_digest": digest}


def build_script(config):
    params_doc = load_json(config["params_file"])
    profiles_doc = load_json("params/process-profiles.json")
    standards_doc = load_json("params/component-sets.json")

    meta = dict(params_doc.get("meta", {}))
    meta.update(provenance(params_doc, profiles_doc, standards_doc))
    config = dict(config)
    config.setdefault("process_profile", meta.get("process_profile", "fdm_prototype"))
    config.setdefault("component_set", meta.get("component_set", "TO_CONFIRM"))

    def dump(obj):
        # repr of a Python str is always a valid Python string literal, so this
        # round-trips any content safely, quotes and backslashes included.
        return repr(json.dumps(strip_comment_keys(obj), sort_keys=True))

    parts = [
        HEADER.format(
            params=dump(params_doc["parameters"]),
            profiles=dump(profiles_doc["profiles"]),
            standards=dump(standards_doc["sets"]),
            meta=dump(meta),
            config=dump(config),
        )
    ]
    for module in MODULES:
        parts.append("\n# %s %s\n# %s\n\n%s" % ("=" * 8, module, "=" * 70, read(module)))
    parts.append(MAIN)
    return "\n".join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", dest="params_file", default="params/default.json")
    parser.add_argument("--out", default="build/fusion_script.py")
    parser.add_argument("--profile", dest="process_profile",
                        help="Override the process profile from the params meta block")
    parser.add_argument("--set", dest="component_set",
                        help="Override the component set from the params meta block")
    parser.add_argument("--skeleton-only", action="store_true",
                        help="Build datum geometry only, skip form features")
    parser.add_argument("--no-sweep", dest="sweep", action="store_false",
                        help="Skip the min/max rebuild regression test")
    parser.add_argument("--export", action="store_true",
                        help="Write STEP/STL/3MF and a build manifest")
    parser.add_argument("--export-dir", default=os.path.join(ROOT, "build", "export"))
    args = parser.parse_args(argv)

    config = {
        "params_file": args.params_file,
        "skeleton_only": args.skeleton_only,
        "sweep": args.sweep,
        "export": args.export,
        "export_dir": args.export_dir,
    }
    if args.process_profile:
        config["process_profile"] = args.process_profile
    if args.component_set:
        config["component_set"] = args.component_set

    script = build_script(config)

    out_path = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as handle:
        handle.write(script)

    # Catch syntax errors here rather than inside Fusion, where the only
    # feedback is a modal dialog with a truncated message.
    compile(script, out_path, "exec")
    print("wrote %s (%d lines)" % (out_path, script.count("\n") + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
