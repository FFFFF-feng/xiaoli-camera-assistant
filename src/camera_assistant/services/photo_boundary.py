"""Photo-edge evidence, independent of layout and of the unknown shape outside it.

Contours use pixel centres divided by work width/height (not width-1/height-1).
Thus the last sampled row is (height-1)/height, not 1. No geometry is stretched.
"""
from __future__ import annotations

from itertools import pairwise


def split_frame_edges(paths, bbox, width, height, edges):
    """Remove only segments on an evidenced frame edge; keep all other vertices."""
    def at(point, side):
        axis = 0 if side in {"left", "right"} else 1
        size = width if axis == 0 else height
        value = (bbox[axis] + point[axis] * (bbox[axis + 2] - bbox[axis])) * size
        return abs(value - (size - 1 if side in {"right", "bottom"} else 0)) <= .02
    result = []
    for path in paths:
        run = [path[0]]
        for a, b in pairwise(path):
            if any(at(a, side) and at(b, side) for side in edges):
                if len(run) >= 2:
                    result.append(run)
                run = [b]
            else:
                run.append(b)
        if len(run) >= 2:
            result.append(run)
    # Every input is already contract-bounded. Split without discarding vertices.
    return [run[start:start + 64] for run in result for start in range(0, len(run) - 1, 63)]


def boundary_evidence(outline, bbox, width, height, *, basis="pixel_mask_v1"):
    """Frame contact is evidence of an unknown continuation, not a completed object.

    saved_outline_v1 is explicitly reconstructed from stored post-segmentation
    geometry; it does not recover an original recognition bbox or raw mask.
    """
    ring = outline[:-1] if outline[0] == outline[-1] else outline
    edges = []
    for side, axis, size, target in (("left", 0, width, 0), ("top", 1, height, 0),
                                    ("right", 0, width, width - 1), ("bottom", 1, height, height - 1)):
        hits = [p for p in ring if abs((bbox[axis] + p[axis] * (bbox[axis + 2] - bbox[axis])) * size - target) <= .02]
        # A lone tangent sample does not establish an artificial closing segment.
        if len(hits) >= 2 and max(p[1-axis] for p in hits) - min(p[1-axis] for p in hits) > 1e-6:
            edges.append(side)
    closed = [*ring, ring[0]]
    visible = split_frame_edges([closed], bbox, width, height, edges) if edges else []
    # Join runs split solely by the arbitrary first ring vertex.
    if len(visible) > 1 and visible[-1][-1] == visible[0][0] and len(visible[-1]) + len(visible[0]) - 1 <= 64:
        visible = [[*visible[-1], *visible[0][1:]], *visible[1:-1]]
    return {"version": 1, "basis": basis, "work_width": width, "work_height": height,
            "clipped_edges": edges, "visible_paths": visible}
