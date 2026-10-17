"""Small, deterministic checks for closed object silhouettes (not open detail lines)."""

from __future__ import annotations


def contained_outline(outer: list[list[float]], inner: list[list[float]]) -> bool:
    """A hole must lie strictly inside its outer polygon without crossing it."""
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def on(a, b, p):
        return abs(cross(a, b, p)) < 1e-10 and all(
            min(a[k], b[k])-1e-10 <= p[k] <= max(a[k], b[k])+1e-10 for k in (0, 1))
    def edges(path):
        ring = path[:-1] if path[0] == path[-1] else path
        return list(zip(ring, ring[1:]+ring[:1]))
    outer_edges, inner_edges = edges(outer), edges(inner)
    for a, b in inner_edges:
        inside = False
        for c, d in outer_edges:
            if on(c, d, a):
                return False
            if (c[1] > a[1]) != (d[1] > a[1]) and a[0] < (d[0]-c[0])*(a[1]-c[1])/(d[1]-c[1])+c[0]:
                inside = not inside
            if (on(c, d, b) or on(a, b, c) or on(a, b, d)
                    or (cross(a, b, c)*cross(a, b, d) < 0 and cross(c, d, a)*cross(c, d, b) < 0)):
                return False
        if not inside:
            return False
    return True


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
