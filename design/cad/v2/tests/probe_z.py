#!/usr/bin/env python3
"""Probe a mesh with vertical rays to read off solid intervals along Z.

Contour slicing tells you the shape at a height. This answers the other
question (how thick is the floor, how tall is that boss, how deep is that
counterbore) by firing a ray straight up through a chosen XY point and
reporting where it is inside material.

Unlike summing loop areas, this needs no assumption about loop winding: a ray
crosses a closed surface an even number of times, so the crossings pair up into
solid intervals directly.

    python3 tests/probe_z.py <file.stl> --at 70,47 120,47
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_stl import bounds, load_stl  # noqa: E402

EPS = 1e-9


def ray_hits(triangles, x, y):
    """Z heights where a vertical ray at (x, y) crosses the surface."""
    hits = []
    for a, b, c in triangles:
        # Barycentric test in the XY plane.
        denominator = ((b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]))
        if abs(denominator) < EPS:
            continue  # triangle is vertical, contributes no crossing
        u = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / denominator
        v = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / denominator
        w = 1.0 - u - v
        if u < 0 or v < 0 or w < 0:
            continue
        hits.append(u * a[2] + v * b[2] + w * c[2])
    return sorted(hits)


def intervals(hits, weld=1e-4):
    """Pair sorted crossings into solid spans."""
    cleaned = []
    for z in hits:
        if not cleaned or abs(z - cleaned[-1]) > weld:
            cleaned.append(z)
        else:
            cleaned.pop()  # a grazing double-hit at an edge: not a real crossing
    return [(cleaned[i], cleaned[i + 1]) for i in range(0, len(cleaned) - 1, 2)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    # Points are given as [label=]x,y. The optional label is not just
    # documentation: a bare negative coordinate like -2.5,47 is parsed by
    # argparse as an option, so writing left-wall=-2.5,47 is what makes probing
    # the negative side of the origin possible at all.
    parser.add_argument("--at", nargs="+", required=True,
                        help="Probe points as [label=]x,y in the file's own coordinates")
    args = parser.parse_args(argv)

    triangles = load_stl(args.path)
    lo, hi = bounds(triangles)
    print("\n%s   X %.2f..%.2f  Y %.2f..%.2f  Z %.2f..%.2f"
          % (os.path.basename(args.path), lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]))

    for point in args.at:
        label, _, coordinates = point.rpartition("=")
        x, y = (float(v) for v in coordinates.split(","))
        spans = intervals(ray_hits(triangles, x, y))
        if not spans:
            print("  (%7.2f, %7.2f) %-22s  no material" % (x, y, label))
            continue
        parts = ["%.2f..%.2f (%.2f)" % (a, b, b - a) for a, b in spans]
        print("  (%7.2f, %7.2f) %-22s  %s" % (x, y, label, "   ".join(parts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
