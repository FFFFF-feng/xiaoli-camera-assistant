"""Bounded vector strokes from observed edges, without closing open features."""
from __future__ import annotations

import cv2
import numpy as np

MAX_STROKES = 96
MAX_EDGE_PIXELS = 30_000


def edge_chains(edges: np.ndarray) -> list[np.ndarray]:
    """Walk each pixel edge once; terminate at junctions instead of bridging them."""
    if np.count_nonzero(edges) > MAX_EDGE_PIXELS:
        raise ValueError("结构线密度过高，无法可靠区分细节")
    pixels = set(zip(*np.nonzero(edges)))
    graph = {}
    for y, x in sorted(pixels):
        neighbours = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                neighbour = (y+dy, x+dx)
                if (dy == dx == 0 or neighbour not in pixels
                        or (dy and dx and ((y, x+dx) in pixels or (y+dy, x) in pixels))):
                    continue
                neighbours.append(neighbour)
        graph[y, x] = neighbours
    visited = set()
    paths = []

    def walk(start, following):
        path = [start]
        previous, current = start, following
        while True:
            edge = tuple(sorted((previous, current)))
            if edge in visited:
                break
            visited.add(edge)
            path.append(current)
            if current == start or len(graph[current]) != 2:
                break
            next_pixel = next(p for p in graph[current] if p != previous)
            previous, current = current, next_pixel
        if len(path) >= 3:
            paths.append(np.array([(x, y) for y, x in path], dtype=np.int32).reshape(-1, 1, 2))

    for pixel, neighbours in graph.items():
        if len(neighbours) != 2:
            for neighbour in neighbours:
                walk(pixel, neighbour)
    # The remaining edges belong to loops with no endpoints or junctions.
    for pixel, neighbours in graph.items():
        for neighbour in neighbours:
            if tuple(sorted((pixel, neighbour))) not in visited:
                walk(pixel, neighbour)
    return paths


def structural_strokes(rgb: np.ndarray, mask: np.ndarray, *, kind: str = "") -> list[np.ndarray]:
    """Keep petal seams and fine structures, distributed across the object."""
    smooth = cv2.bilateralFilter(rgb, 5, 25, 3)
    gray = cv2.cvtColor(smooth, cv2.COLOR_RGB2GRAY)
    contrast = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(gray)
    luminance_edges = cv2.Canny(contrast, 18, 55, L2gradient=True)
    # Yellow stamens and green veins can share the petals' luminance; preserve
    # their observed chroma boundaries as well as gray-level transitions.
    hsv = cv2.cvtColor(smooth, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1]
    chroma_edges = cv2.Canny(saturation, 25, 65, L2gradient=True)
    edges = cv2.bitwise_and(cv2.bitwise_or(luminance_edges, chroma_edges), mask)
    height, width = mask.shape
    minimum = max(4, (width+height)*.007)
    buckets = {}
    for line in edge_chains(edges):
        closed = bool(np.array_equal(line[0], line[-1]))
        length = cv2.arcLength(line, closed)
        x, y, w, h = cv2.boundingRect(line)
        if length < minimum or max(w, h) < 3:
            continue
        epsilon = max(.55, length*.001)
        for _ in range(16):
            points = cv2.approxPolyDP(line, epsilon, closed).reshape(-1, 2)
            if len(points) <= (63 if closed else 64):
                break
            epsilon *= 1.4
        if len(points) < 2:
            continue
        if closed and len(points) > 2:
            points = np.vstack((points, points[0]))
        key = (min(5, int((x+w/2)*6/width)), min(3, int((y+h/2)*4/height)))
        score = max(w, h) * length**.5
        buckets.setdefault(key, []).append((score, points))
    for rows in buckets.values():
        rows.sort(key=lambda row: row[0], reverse=True)
    # Give each populated area a turn. One long leaf edge cannot exhaust the
    # budget before smaller stamens or facial details in other regions appear.
    selected = []
    if kind == "flower":
        # Small observed yellow marks often disappear from grayscale edges.
        # Preserve their actual boundaries; do not draw synthetic radial stamens.
        yellow = cv2.inRange(hsv, np.array([15, 80, 80]), np.array([42, 255, 255]))
        accents, _ = cv2.findContours(cv2.bitwise_and(yellow, mask), cv2.RETR_EXTERNAL,
                                     cv2.CHAIN_APPROX_SIMPLE)
        for accent in sorted(accents, key=cv2.contourArea, reverse=True):
            if not 1 <= cv2.contourArea(accent) <= max(24, width*height*.003):
                continue
            points = cv2.approxPolyDP(accent, .3, True).reshape(-1, 2)
            if 3 <= len(points) < 64:
                selected.append(np.vstack((points, points[0])))
            if len(selected) == 8:
                break
    depth = 0
    while len(selected) < MAX_STROKES:
        candidates = sorted((rows[depth] for rows in buckets.values() if len(rows) > depth),
                            key=lambda row: row[0], reverse=True)
        if not candidates:
            break
        selected.extend(points for _, points in candidates[:MAX_STROKES-len(selected)])
        depth += 1
    return selected
