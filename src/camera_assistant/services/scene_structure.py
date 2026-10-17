"""Open, pixel-supported structure for continuous fixed scenery.

These lines are not semantic segmentation or a generated new viewpoint. Their
coverage is validated independently from closed object silhouettes.
"""
from __future__ import annotations

import cv2
import numpy as np

from camera_assistant.composition_models import ObservedObject
from camera_assistant.services.pixel_strokes import edge_chains

STRUCTURE_VERSION = "scene-structure-v1"


def trace_structure(rgb: np.ndarray, obj: ObservedObject) -> ObservedObject:
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = [round(v*(w if i % 2 == 0 else h)) for i, v in enumerate(obj.bbox)]
    patch = np.ascontiguousarray(rgb[y1:y2, x1:x2])
    ph, pw = patch.shape[:2]
    if min(ph, pw) < 24 or float(patch.std()) < 3:
        raise ValueError("structure_low_contrast")
    # Suppress fine stone/grass texture before tracing actual boundaries. Edge
    # chains stop at junctions; they never bridge a missing arch or ridge.
    gray = cv2.cvtColor(cv2.GaussianBlur(patch, (7, 7), 1.4), cv2.COLOR_RGB2GRAY)
    low, high = 18., 48.
    for _ in range(7):
        edges = cv2.Canny(gray, low, high, L2gradient=True)
        if np.count_nonzero(edges) <= 24000:
            break
        low, high = low*1.4, high*1.4
    else:
        raise ValueError("structure_density_exceeded")
    candidates = []
    for chain in edge_chains(edges):
        length = cv2.arcLength(chain, False)
        _, _, dx, dy = cv2.boundingRect(chain)
        if length < (pw+ph)*.025 or max(dx/pw, dy/ph) < .035:
            continue
        points = cv2.approxPolyDP(chain, .8, False).reshape(-1, 2)
        for start in range(0, len(points)-1, 63):
            part = points[start:start+64]
            if len(part) >= 2:
                candidates.append((length, part))
    # Reserve spatial coverage before allowing the strongest near structure to
    # use the budget. This retains both sides and upper/lower reflection regions.
    buckets = {}
    for length, path in candidates:
        x, y = np.mean(path, axis=0)
        cell = (min(3, int(x*4/pw)), min(3, int(y*4/ph)))
        buckets.setdefault(cell, []).append((length, path))
    for rows in buckets.values():
        rows.sort(key=lambda item: item[0], reverse=True)
    selected = []
    for depth in range(96):
        rows = sorted((rows[depth] for rows in buckets.values() if len(rows) > depth),
                      key=lambda item: item[0], reverse=True)
        if not rows:
            break
        selected.extend(path for _, path in rows[:96-len(selected)])
        if len(selected) == 96:
            break
    details = [[[round(float(x/pw), 6), round(float(y/ph), 6)] for x, y in p] for p in selected]
    if len(details) < 4:
        raise ValueError("structure_paths_insufficient")
    xs = [p[0] for path in details for p in path]
    ys = [p[1] for path in details for p in path]
    cells = {(min(3, int(x*4)), min(3, int(y*4))) for x, y in zip(xs, ys)}
    if max(xs)-min(xs) < .65 or max(ys)-min(ys) < .65 or len(cells) < 6:
        raise ValueError("structure_coverage_insufficient")
    return ObservedObject.model_validate({
        **obj.model_dump(), "bbox": [x1/w, y1/h, x2/w, y2/h], "parts": [],
        "representation": "scene_structure", "outline": [], "contours": [], "holes": [],
        "details": details, "outline_style": "angular", "certainty": "approximate",
        "mobility": "fixed",
    })
