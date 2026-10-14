# Export: the manufacturing outputs.
#
# CONCATENATION CONTRACT: see the note at the top of parameters.py.
#
# Filenames are deterministic and derived from the build configuration rather
# than from a timestamp, so re-running the same configuration overwrites the
# same file and git shows a real diff instead of an ever-growing pile of
# near-identical exports.

import os


def _slug(text):
    # Dots are kept: they are safe in filenames on every platform, and turning
    # 2.0.0-beta.1 into 2-0-0-beta-1 would destroy the version it is carrying.
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in str(text)).strip("-.")


def basename(meta):
    """name-version-profile, e.g. bottle-feeder-v2-2.0.0-beta.1-fdm_prototype.

    The version is what someone holding a loose STL needs to know. The process
    profile is in the name too because it changes the fits, so an FDM and an
    injection export of the same version must never overwrite each other. The
    component set and the full parameter values are in the manifest.
    """
    return "%s-%s-%s" % (
        _slug(meta.get("name", "model")),
        _slug(meta.get("version", "unversioned")),
        _slug(meta.get("process_profile", "unknown")),
    )


def export_all(design, meta, out_dir, log, formats=("step", "stl", "3mf")):
    """Write the manufacturing outputs: one assembly STEP, one mesh per part.

    STEP is the one that matters for production: a real solid with exact
    surfaces, which is what a toolmaker or a machinist needs. It is exported as
    the whole assembly, because STEP keeps each body a separate solid and the
    relationship between the parts is useful to anyone opening it in CAD.

    STL and 3MF are meshes for printing, so they are written one file per part.
    Exporting the root component as a single mesh, which this used to do, gives
    you every part fused into one file in its assembled position: the pan
    floating above the case and the lid overlapping the base. Nobody can print
    that. Each part file is still in assembly orientation; the README says how
    to lay each one on the bed.
    """
    os.makedirs(out_dir, exist_ok=True)
    manager = design.exportManager
    root = design.rootComponent
    stem = os.path.join(out_dir, basename(meta))
    written = []

    if "step" in formats:
        path = stem + "-assembly.step"
        manager.execute(manager.createSTEPExportOptions(path, root))
        written.append(path)

    bodies = [root.bRepBodies.item(i) for i in range(root.bRepBodies.count)]
    for body in bodies:
        part_stem = "%s-%s" % (stem, _slug(body.name))

        if "stl" in formats:
            path = part_stem + ".stl"
            options = manager.createSTLExportOptions(body, path)
            # Refinement drives chord tolerance. High is the right default for
            # a part with small fillets: Medium visibly facets a 2 mm radius.
            options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
            manager.execute(options)
            written.append(path)

        if "3mf" in formats:
            path = part_stem + ".3mf"
            try:
                manager.execute(manager.createC3MFExportOptions(body, path))
                written.append(path)
            except Exception as exc:
                # 3MF export of a single body is not available on every Fusion
                # build. The STL is the file that matters for printing.
                log("  3mf for %s unavailable: %s" % (body.name, exc))

    log("export: %d file(s)" % len(written))
    for path in written:
        log("  " + path)
    return written


def export_manifest(table, meta, validation, out_dir):
    """A record of exactly what produced these files.

    An exported STEP on its own carries no evidence of which parameter values,
    which component set or which process profile made it, and no record of
    whether it passed validation. Shipping the manifest alongside is what makes
    a build traceable after the fact.
    """
    manifest = {
        "meta": dict(meta),
        "parameters": {
            name: {
                "expression": spec.get("expression"),
                "role": spec.get("role"),
                "source": spec.get("source"),
            }
            for name, spec in sorted(table.items())
            if spec.get("role") != "note"
        },
        "validation": {
            "timeline_failures": len(validation.get("timeline", [])),
            "sweep_failures": len(validation.get("sweep", [])),
            "safety_failures": len(validation.get("safety", [])),
            "literal_dimensions": len(validation.get("literal_dimensions", [])),
            "unmeasured_parameters": validation.get("placeholders", []),
            "releasable": not (
                validation.get("timeline") or validation.get("sweep")
                or validation.get("safety") or validation.get("literal_dimensions")
                or validation.get("placeholders")
            ),
        },
    }
    path = os.path.join(out_dir, basename(meta) + ".manifest.json")
    with open(path, "w") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    return path
