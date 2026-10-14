#!/usr/bin/env python3
"""Recover exact feature dimensions from the V1 meshes by contour slicing.

Bounding boxes only give overall size. What a parametric rebuild needs is the
features: bore diameters, hole positions, wall thickness, cavity size, lid
rebate. Slicing the mesh at a Z height and linking the intersection segments
into closed loops recovers those exactly, because every loop is a real edge of
the solid rather than an inferred one.

    python3 tests/slice_features.py <file.stl> --z 5 10 15
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_stl import bounds, load_stl  # noqa: E402

WELD = 1e-4  # mm; endpoints closer than this are the same point


def slice_z(triangles, z):
    """Intersect the mesh with the plane Z=z, returning 2D segments.

    A vertex sitting exactly on the plane is a degenerate case that produces
    either a duplicate or a missing crossing, so the plane is nudged off any
    vertex it lands on. The nudge is far below print and CAD resolution, so it
    cannot move a measured dimension.
    """
    for _ in range(64):
        if not any(abs(v[2] - z) < WELD for tri in triangles for v in tri):
            break
        z += WELD * 7
    else:
        raise ValueError("could not find a clean slice height near Z=%.4f" % z)

    segments = []
    for tri in triangles:
        below = [v for v in tri if v[2] < z]
        above = [v for v in tri if v[2] > z]
        if len(below) != 3 - len(above) or not below or not above:
            continue
        # The odd vertex out is the one alone on its side of the plane.
        lone, pair = (below[0], above) if len(below) == 1 else (above[0], below)
        points = []
        for other in pair:
            t = (z - lone[2]) / (other[2] - lone[2])
            points.append((lone[0] + t * (other[0] - lone[0]),
                           lone[1] + t * (other[1] - lone[1])))
        if math.dist(points[0], points[1]) > WELD:
            segments.append(tuple(points))
    return segments


def link_loops(segments):
    """Chain segments end-to-end into closed loops.

    Each segment is consumed exactly once. The previous version walked the
    adjacency map without marking segments used, so every loop was rediscovered
    from each of its own segments and the same contour came back dozens of
    times with slightly different vertex ordering.
    """
    def key(point):
        return (round(point[0] / WELD), round(point[1] / WELD))

    adjacency = {}
    for index, (a, b) in enumerate(segments):
        adjacency.setdefault(key(a), []).append(index)
        adjacency.setdefault(key(b), []).append(index)

    used = [False] * len(segments)
    loops = []

    for start_index in range(len(segments)):
        if used[start_index]:
            continue
        used[start_index] = True
        start, current = segments[start_index]
        loop = [start, current]

        while True:
            nxt = None
            for index in adjacency.get(key(current), []):
                if used[index]:
                    continue
                a, b = segments[index]
                if math.dist(a, current) < WELD:
                    nxt, used[index] = b, True
                    break
                if math.dist(b, current) < WELD:
                    nxt, used[index] = a, True
                    break
            if nxt is None:
                break
            if math.dist(nxt, start) < WELD:
                break  # closed
            loop.append(nxt)
            current = nxt

        if len(loop) >= 3:
            loops.append(loop)
    return loops


def loop_stats(loop):
    """Area, centroid, bbox and circularity for one closed loop."""
    area2 = cx = cy = 0.0
    n = len(loop)
    for i in range(n):
        x0, y0 = loop[i]
        x1, y1 = loop[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        area2 += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area = area2 / 2.0
    if abs(area) < 1e-9:
        return None
    centroid = (cx / (3 * area2), cy / (3 * area2))

    xs = [p[0] for p in loop]
    ys = [p[1] for p in loop]
    radii = [math.dist(p, centroid) for p in loop]
    mean_r = sum(radii) / len(radii)
    spread = max(radii) - min(radii)

    return {
        "area": abs(area),
        "signed_area": area,
        "centroid": centroid,
        "width": max(xs) - min(xs),
        "height": max(ys) - min(ys),
        "min": (min(xs), min(ys)),
        "mean_radius": mean_r,
        # A true circle has near-zero radius spread about its centroid.
        "is_circle": spread < 0.12 * mean_r and mean_r > 0.3,
        "points": len(loop),
    }


def describe_slice(triangles, z, min_area=1.0):
    segments = slice_z(triangles, z)
    if not segments:
        print("  Z=%-7.2f  (no material)" % z)
        return
    loops = link_loops(segments)
    stats = [s for s in (loop_stats(loop) for loop in loops) if s and s["area"] >= min_area]
    stats.sort(key=lambda s: -s["area"])

    print("  Z=%-7.2f  %d loop(s), %d segment(s)" % (z, len(stats), len(segments)))
    for s in stats:
        if s["is_circle"]:
            shape = "circle  dia %6.2f" % (s["mean_radius"] * 2)
        else:
            shape = "profile %6.2f x %6.2f" % (s["width"], s["height"])
        print("      %-22s  area %8.2f mm2  centre (%7.2f, %7.2f)"
              % (shape, s["area"], s["centroid"][0], s["centroid"][1]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--z", type=float, nargs="*", help="Explicit Z heights")
    parser.add_argument("--steps", type=int, default=9,
                        help="If --z is omitted, slice this many times through the part")
    parser.add_argument("--min-area", type=float, default=1.0)
    args = parser.parse_args(argv)

    triangles = load_stl(args.path)
    lo, hi = bounds(triangles)
    print("\n%s   Z range %.2f .. %.2f mm" % (os.path.basename(args.path), lo[2], hi[2]))

    if args.z:
        heights = args.z
    else:
        span = hi[2] - lo[2]
        heights = [lo[2] + span * (i + 0.5) / args.steps for i in range(args.steps)]

    for z in heights:
        describe_slice(triangles, z, args.min_area)
    return 0


if __name__ == "__main__":
    sys.exit(main())
