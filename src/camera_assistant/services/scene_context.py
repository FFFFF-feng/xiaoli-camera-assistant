"""Bounded environmental strokes from visible pixels, without invented boxes."""
from __future__ import annotations

from itertools import pairwise

import cv2
import numpy as np

from camera_assistant.composition_models import ObservedObject, TargetLayer
from camera_assistant.services.pixel_strokes import edge_chains

CONTEXT_PATHS = 40
CONTEXT_PIXELS = 12_000


def _tone_strokes(gray, mask):
    """Coarse observed dark-region boundaries retain broad trunks and branches.

    Canny chains fragment at textured junctions; these tonal boundaries are a
    complementary pixel cue, not an assertion of semantic object segmentation.
    Trace before exclusion so the subject mask cannot create fake hole edges.
    """
    if int(gray.max())-int(gray.min()) < 15:
        return []
    threshold = min(max(float(np.quantile(gray, .22)), float(gray.min())+8), float(gray.max())-8)
    dark = np.uint8(gray < threshold)*255
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    h, w = gray.shape
    significant = [path for path in contours
                   if cv2.arcLength(path, True) > (w+h)*.12
                   and max(cv2.boundingRect(path)[2:]) > min(w, h)*.12]
    lines = []
    for contour in sorted(significant, key=lambda p: cv2.arcLength(p, True), reverse=True)[:8]:
        # Split masked runs *before* simplification, keeping each real endpoint.
        points = contour.reshape(-1, 2)
        points = np.vstack((points, points[0]))
        active = []
        for x, y in points:
            # A contour closed along the ROI rim is a crop boundary, not an
            # observed object edge. Split it rather than drawing a false cap.
            if 0 < x < w-1 and 0 < y < h-1 and mask[y, x]:
                active.append((x, y))
            elif active:
                if len(active) > 6:
                    lines.append(np.array(active, np.int32).reshape(-1, 1, 2))
                active = []
        if len(active) > 6:
            lines.append(np.array(active, np.int32).reshape(-1, 1, 2))
    result = []
    for line in sorted(lines, key=lambda p: cv2.arcLength(p, False), reverse=True):
        points = cv2.approxPolyDP(line, 1, False).reshape(-1, 2)
        # Do not over-simplify a complex connected branch to fit 64 points.
        for start in range(0, len(points)-1, 63):
            result.append(points[start:start+64])
            if len(result) == 16:
                return result
    return result


def _strokes(rgb, mask):
    if min(rgb.shape[:2]) < 4:
        return []
    # Context needs large connected structure, not bark/leaf texture. Extract at
    # a coarser scale than the main object's details, without extending lines
    # across missing evidence or generating a semantic shape from an icon.
    smooth = cv2.GaussianBlur(rgb, (11, 11), 2.2)
    gray = cv2.cvtColor(smooth, cv2.COLOR_RGB2GRAY)
    large_shapes = _tone_strokes(gray, mask)
    low, high = 8, 22
    for _ in range(7):
        edges = cv2.bitwise_and(cv2.Canny(gray, low, high, L2gradient=True), mask)
        if np.count_nonzero(edges) <= CONTEXT_PIXELS:
            break
        low, high = low*1.65, high*1.65
    else:
        return large_shapes
    h, w = gray.shape
    buckets = {}
    for line in edge_chains(edges):
        closed = bool(np.array_equal(line[0], line[-1]))
        length = cv2.arcLength(line, closed)
        x, y, dx, dy = cv2.boundingRect(line)
        if length < max(8, (w+h)*.025) or max(dx, dy) < max(4, min(w, h)*.035):
            continue
        epsilon = max(1, length*.003)
        for _ in range(16):
            points = cv2.approxPolyDP(line, epsilon, closed).reshape(-1, 2)
            if len(points) <= (63 if closed else 64):
                break
            epsilon *= 1.4
        if len(points) < 2:
            continue
        if closed:
            points = np.vstack((points, points[0]))
        cell = (min(3, int((x+dx/2)*4/w)), min(2, int((y+dy/2)*3/h)))
        buckets.setdefault(cell, []).append((max(dx, dy)*length**.5, points))
    for rows in buckets.values():
        rows.sort(key=lambda row: row[0], reverse=True)
    # Preserve dominant connected boundaries before spending the rest of the
    # budget on spatial coverage; equal cell quotas can otherwise erase a trunk.
    strongest = sorted((row for rows in buckets.values() for row in rows),
                       key=lambda row: row[0], reverse=True)[:(CONTEXT_PATHS-len(large_shapes))*2//3]
    chosen = {id(points) for _, points in strongest}
    selected, depth = [*large_shapes, *(points for _, points in strongest)], 0
    buckets = {key: [row for row in rows if id(row[1]) not in chosen] for key, rows in buckets.items()}
    while len(selected) < CONTEXT_PATHS:
        rows = sorted((r[depth] for r in buckets.values() if len(r) > depth),
                      key=lambda row: row[0], reverse=True)
        if not rows:
            break
        selected.extend(points for _, points in rows[:CONTEXT_PATHS-len(selected)])
        depth += 1
    return selected


def trace_context(rgb, obj: ObservedObject, *, mask=None) -> ObservedObject | None:
    """Trace a branch, blurred structure or scene remainder as open strokes."""
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = [round(n*(w if i % 2 == 0 else h)) for i, n in enumerate(obj.bbox)]
    patch = np.ascontiguousarray(rgb[y1:y2, x1:x2])
    if min(patch.shape[:2]) < 4:
        return None
    region_mask = np.full(patch.shape[:2], 255, dtype=np.uint8) if mask is None else mask[y1:y2, x1:x2]
    lines = _strokes(patch, region_mask)
    if not lines:
        return None
    details = [[[round(float(x/(x2-x1)), 5), round(float(y/(y2-y1)), 5)]
                for x, y in path] for path in lines]
    return ObservedObject.model_validate({
        **obj.model_dump(), "bbox": [x1/w, y1/h, x2/w, y2/h], "parts": [],
        "representation": "context_lines", "outline": [], "contours": [],
        "details": details, "outline_style": "angular", "certainty": "approximate",
    })


def context_mask(rgb, objects: list[ObservedObject]):
    """Exclude already represented pixels, without blanking whole object boxes."""
    h, w = rgb.shape[:2]
    mask = np.full((h, w), 255, dtype=np.uint8)
    for obj in objects:
        x1, y1, x2, y2 = obj.bbox
        def project(path, x1=x1, y1=y1, x2=x2, y2=y2):
            return np.array([[(x1+x*(x2-x1))*w, (y1+y*(y2-y1))*h] for x, y in path],
                            dtype=np.int32).reshape(-1, 1, 2)
        if obj.representation == "context_lines":
            for path in obj.details:
                cv2.polylines(mask, [project(path)], False, 0, 5)
        else:
            for path in obj.contours or [obj.outline]:
                cv2.fillPoly(mask, [project(path)], 0)
    # Avoid drawing a duplicate halo just outside the foreground silhouette.
    mask = cv2.erode(mask, np.ones((5, 5), dtype=np.uint8))
    return mask


def scene_remainder(rgb, objects: list[ObservedObject], identifier: str) -> ObservedObject | None:
    """Keep unlabelled context too; exclude pixels already represented by objects."""
    obj = ObservedObject.model_validate({
        "object_id": identifier, "label": "其余环境线索", "kind": "scene_context", "role": "background",
        "depth": 0, "bbox": [0, 0, 1, 1], "outline": [[0, 0], [1, 0], [1, 1], [0, 1]],
        "identity_features": ["原图中未单独命名的环境边界", "不推测物体类别或画外内容"],
        "evidence_photo_ids": ["photo1"], "mobility": "fixed",
    })
    return trace_context(rgb, obj, mask=context_mask(rgb, objects))


def clip_path(path):
    """Liang–Barsky segment clipping; never bridge disconnected visible pieces."""
    result, active = [], []
    for a, b in pairwise(path):
        dx, dy = b[0]-a[0], b[1]-a[1]
        lo, hi = 0., 1.
        visible = True
        for p, q in ((-dx, a[0]), (dx, 1-a[0]), (-dy, a[1]), (dy, 1-a[1])):
            if p == 0:
                if q < 0:
                    visible = False
                    break
            elif p < 0:
                lo = max(lo, q/p)
            else:
                hi = min(hi, q/p)
        if not visible or lo > hi:
            if len(active) > 1:
                result.append(active)
            active = []
            continue
        start, end = [[min(1, max(0, a[k]+t*(b[k]-a[k]))) for k in (0, 1)] for t in (lo, hi)]
        if start == end:
            continue
        if active and any(abs(active[-1][k]-start[k]) > 1e-8 for k in (0, 1)):
            result.append(active)
            active = []
        if not active:
            active = [start]
        active.append(end)
        if len(active) == 64:
            result.append(active)
            active = [end]
    if len(active) > 1:
        result.append(active)
    return result


def project_context(obj: ObservedObject, transform: tuple[float, float, float, float]) -> TargetLayer | None:
    """Place environment with the same camera-frame transform as the main object."""
    paths = list(obj.details)
    if obj.representation != "context_lines":
        paths = [*(p+[p[0]] if p[-1] != p[0] else p for p in obj.contours or [obj.outline]), *paths]
    paths = paths[:96]
    sx, sy, tx, ty = transform
    x1, y1, x2, y2 = obj.bbox
    projected = []
    for path in paths:
        projected.extend(clip_path([[(x1+x*(x2-x1))*sx+tx, (y1+y*(y2-y1))*sy+ty] for x, y in path]))
    projected = projected[:96]
    if not projected:
        return None
    xs = [p[0] for line in projected for p in line]
    ys = [p[1] for line in projected for p in line]
    def extent(values):
        low, high = min(values), max(values)
        if high-low < .006:
            low = max(0, min((low+high)/2-.003, 1-.006))
            high = low+.006
        return low, high
    ax, bx = extent(xs)
    ay, by = extent(ys)
    return TargetLayer.model_validate({
        **obj.model_dump(exclude={"object_id", "parts"}), "representation": "context_lines",
        "bbox": [ax, ay, bx, by], "outline": [], "contours": [], "outline_style": "angular",
        "details": [[[round((x-ax)/(bx-ax), 6), round((y-ay)/(by-ay), 6)] for x, y in line] for line in projected],
        "source_bbox": obj.bbox, "source_details": paths, "source_object_id": obj.object_id,
        "certainty": "approximate",
    })
