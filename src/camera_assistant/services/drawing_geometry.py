"""Small, deterministic checks for closed object silhouettes (not open detail lines)."""

from __future__ import annotations


def simple_outline(points: list[list[float]]) -> bool:
    """Reject crossings, overlapping edges and repeated vertices; allow explicit closure."""
    ring = points[:-1] if points[0] == points[-1] else points
    if len(ring) < 3 or len({tuple(p) for p in ring}) != len(ring):
        return False

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on(a, b, p):
        return abs(cross(a, b, p)) < 1e-10 and all(
            min(a[k], b[k]) - 1e-10 <= p[k] <= max(a[k], b[k]) + 1e-10 for k in (0, 1)
        )

    edges = list(zip(ring, ring[1:] + ring[:1]))
    for i, (a, b) in enumerate(edges):
        # Even adjacent collinear edges must not double back over each other.
        c = ring[(i + 2) % len(ring)]
        if on(a, b, c) or on(b, c, a):
            return False
        for j in range(i + 1, len(edges)):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            c, d = edges[j]
            if (on(a, b, c) or on(a, b, d) or on(c, d, a) or on(c, d, b)
                    or (cross(a, b, c) * cross(a, b, d) < 0
                        and cross(c, d, a) * cross(c, d, b) < 0)):
                return False
    return True
