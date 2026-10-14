#!/usr/bin/env python3
"""Measure the V1 prototype meshes so V2 parameters start from real numbers.

Reverse-engineering a parametric model from a mesh means recovering the few
dimensions that actually drove the original. Bounding boxes give overall size;
the radial histogram is what finds cylindrical features, which is most of what
matters here: bores, bosses, and the cradle that grips the bottle.

    python3 tests/analyze_stl.py bottle_feeder_v1/*.stl
"""

import math
import os
import struct
import sys
from collections import Counter


def load_stl(path):
    """Return a list of (v0, v1, v2) triangles. Handles binary and ASCII."""
    with open(path, "rb") as handle:
        head = handle.read(5)
        handle.seek(0)
        if head == b"solid":
            # Could still be binary with a misleading header, so verify the
            # ASCII body actually parses before trusting it.
            text = handle.read()
            try:
                return _parse_ascii(text.decode("utf-8", "strict"))
            except (UnicodeDecodeError, ValueError):
                handle.seek(0)
        return _parse_binary(handle)


def _parse_binary(handle):
    handle.seek(80)
    (count,) = struct.unpack("<I", handle.read(4))
    data = handle.read(count * 50)
    triangles = []
    for i in range(count):
        chunk = data[i * 50 : i * 50 + 50]
        values = struct.unpack("<12f", chunk[:48])
        triangles.append((values[3:6], values[6:9], values[9:12]))
    return triangles


def _parse_ascii(text):
    vertices, triangles = [], []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("vertex "):
            vertices.append(tuple(float(x) for x in line.split()[1:4]))
            if len(vertices) == 3:
                triangles.append(tuple(vertices))
                vertices = []
    if not triangles:
        raise ValueError("no triangles")
    return triangles


def bounds(triangles):
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for tri in triangles:
        for vertex in tri:
            for axis in range(3):
                lo[axis] = min(lo[axis], vertex[axis])
                hi[axis] = max(hi[axis], vertex[axis])
    return lo, hi


def volume_and_area(triangles):
    """Signed volume via the divergence theorem, plus total surface area."""
    volume = area = 0.0
    for a, b, c in triangles:
        volume += (
            a[0] * (b[1] * c[2] - c[1] * b[2])
            - a[1] * (b[0] * c[2] - c[0] * b[2])
            + a[2] * (b[0] * c[1] - c[0] * b[1])
        ) / 6.0
        ab = [b[i] - a[i] for i in range(3)]
        ac = [c[i] - a[i] for i in range(3)]
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        area += 0.5 * math.sqrt(sum(v * v for v in cross))
    return abs(volume), area


def radial_peaks(triangles, centre, axis=2, bin_mm=0.25, top=8):
    """Find radii where lots of surface area sits, i.e. cylindrical features.

    Area-weighted rather than vertex-counted, because meshers put far more
    vertices on tightly curved features than on large ones, and a vertex count
    would rank a tiny fillet above the main bore.
    """
    plane = [i for i in range(3) if i != axis]
    histogram = Counter()
    for a, b, c in triangles:
        ab = [b[i] - a[i] for i in range(3)]
        ac = [c[i] - a[i] for i in range(3)]
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        tri_area = 0.5 * math.sqrt(sum(v * v for v in cross))
        # Skip faces normal to the axis: flat tops and bottoms are not
        # cylindrical features and would smear across every radius bin.
        if tri_area < 1e-9 or abs(cross[axis]) / (2 * tri_area) > 0.7:
            continue
        for vertex in (a, b, c):
            radius = math.hypot(
                vertex[plane[0]] - centre[0], vertex[plane[1]] - centre[1]
            )
            histogram[round(radius / bin_mm) * bin_mm] += tri_area / 3.0
    return histogram.most_common(top)


def axis_centre(triangles, lo, hi, axis=2):
    plane = [i for i in range(3) if i != axis]
    return [(lo[plane[0]] + hi[plane[0]]) / 2, (lo[plane[1]] + hi[plane[1]]) / 2]


def describe(path):
    triangles = load_stl(path)
    lo, hi = bounds(triangles)
    size = [hi[i] - lo[i] for i in range(3)]
    volume, area = volume_and_area(triangles)
    centre = axis_centre(triangles, lo, hi)

    print("\n%s" % os.path.basename(path))
    print("  triangles   %d" % len(triangles))
    print("  bbox        X %.2f  Y %.2f  Z %.2f mm" % tuple(size))
    print("  origin      X %.2f  Y %.2f  Z %.2f" % tuple(lo))
    print("  volume      %.2f cm3   (%.1f g in PLA, %.1f g in PP)"
          % (volume / 1000.0, volume / 1000.0 * 1.24, volume / 1000.0 * 0.905))
    print("  surface     %.1f cm2" % (area / 100.0))
    print("  bbox fill   %.1f%%  (low = open/shell-like, high = solid blocky)"
          % (100.0 * volume / (size[0] * size[1] * size[2])))

    print("  radial features about Z, area-weighted:")
    for radius, weight in radial_peaks(triangles, centre):
        print("    r %6.2f mm   dia %6.2f mm   area %8.1f mm2" % (radius, radius * 2, weight))


def main(paths):
    if not paths:
        print(__doc__)
        return 1
    for path in paths:
        try:
            describe(path)
        except Exception as exc:
            print("\n%s\n  FAILED: %s" % (os.path.basename(path), exc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
