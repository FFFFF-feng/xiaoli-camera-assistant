"""One bounded local retry, with seeds selected from observed colour contrast.

No semantic colour, circle, eye or ear template is used. The deadline is checked
at native stage boundaries; OpenCV itself cannot be interrupted mid-call.
"""
import time

import cv2
import numpy as np

RETRY_BUDGET_SECONDS = .35
MAX_PATCH_EDGE = 160


def _background_palette(lab, mask):
    samples = lab[mask]
    if len(samples) < 12:
        return np.empty((0, 3), dtype=np.float32)
    samples = samples[::max(1, len(samples)//1024)].astype(np.float32)
    bins = (samples//16).astype(np.int16)
    _, inverse, counts = np.unique(bins, axis=0, return_inverse=True, return_counts=True)
    common = [i for i in np.argsort(counts)[::-1][:8] if counts[i] >= max(3, len(samples)*.025)]
    return np.array([samples[inverse == i].mean(axis=0) for i in common], dtype=np.float32)


def small_roi_mask(rgb, bbox, *, budget=RETRY_BUDGET_SECONDS):
    start = time.perf_counter()
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = [round(v*(w if i % 2 == 0 else h)) for i, v in enumerate(bbox)]
    pad = 6
    ox, oy, ex, ey = max(0, x1-pad), max(0, y1-pad), min(w, x2+pad), min(h, y2+pad)
    patch = np.ascontiguousarray(rgb[oy:ey, ox:ex])
    diag = {"code": "small_roi_ineligible", "seconds": 0., "candidates": 0}
    def done(mask, code):
        diag.update(code=code, seconds=time.perf_counter()-start)
        return mask, diag
    if min(x2-x1, y2-y1) < 8 or max(patch.shape[:2]) > MAX_PATCH_EDGE or (x2-x1)*(y2-y1) > h*w*.02:
        return done(None, 'small_roi_ineligible')
    inside = np.zeros(patch.shape[:2], dtype=bool)
    inside[y1-oy:y2-oy, x1-ox:x2-ox] = True
    support = cv2.dilate(inside.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    lab = cv2.cvtColor(patch, cv2.COLOR_RGB2LAB)
    palette = _background_palette(lab, ~support)
    if not len(palette):
        return done(None, 'small_roi_background_unknown')
    distances = np.linalg.norm(lab.astype(np.float32)[:, :, None]-palette, axis=3).min(axis=2)
    values = distances[inside]
    if not len(values) or float(values.max()) < 24:
        return done(None, 'small_roi_low_contrast')
    seeds = ((distances >= max(24, float(np.quantile(values, .85)))) & inside).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(seeds, connectivity=8)
    candidates = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= 3]
    if not candidates:
        return done(None, 'small_roi_seed_unavailable')
    chosen = max(candidates, key=lambda i: stats[i, cv2.CC_STAT_AREA])
    seed = labels == chosen
    # Follow connected chroma actually present in the seed, allowing brightness
    # variation across a shaded small item, within at most 2 uncertain work pixels.
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    if float(np.median(hsv[:, :, 1][seed])) >= 70:
        hue = float(np.median(hsv[:, :, 0][seed]))
        delta = np.abs(hsv[:, :, 0].astype(np.float32)-hue)
        delta = np.minimum(delta, 180-delta)
        chromatic = (support & (delta <= 16) & (hsv[:, :, 1] >= 45) & (hsv[:, :, 2] >= 15)).astype(np.uint8)
        _, regions = cv2.connectedComponents(chromatic, connectivity=8)
        matching = [int(i) for i in np.unique(regions[seed]) if i != 0]
        if matching:
            region = max(matching, key=lambda i: int(np.count_nonzero(regions == i)))
            seed = regions == region
    mask = np.where(inside, cv2.GC_PR_FGD, cv2.GC_BGD).astype(np.uint8)
    mask[support & ~inside] = cv2.GC_PR_BGD  # At most 2 work pixels of uncertain rim, not a larger object ROI.
    mask[seed] = cv2.GC_FGD
    if time.perf_counter()-start >= budget:
        return done(None, 'small_roi_budget_exceeded')
    diag['candidates'] = 1
    cv2.grabCut(patch, mask, None, np.zeros((1, 65)), np.zeros((1, 65)), 2, cv2.GC_INIT_WITH_MASK)
    if time.perf_counter()-start >= budget:
        return done(None, 'small_roi_budget_exceeded')
    foreground = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
    if foreground.sum() < 8:
        return done(None, 'small_roi_foreground_empty')
    full = np.zeros((h, w), dtype=bool)
    full[oy:ey, ox:ex] = foreground
    return done(full, 'small_roi_contrast_seeded')


def hole_matches_exterior(rgb, filled_silhouette, hole):
    """Require a second pixel cue before treating a mask cavity as transparent.

    A rejected cavity remains an observed detail stroke. This does not establish
    anatomy or guarantee that a light marking matching the background is a gap.
    """
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    palette = _background_palette(lab, filled_silhouette == 0)
    if not len(palette):
        return False
    hole_mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
    cv2.drawContours(hole_mask, [hole], -1, 255, cv2.FILLED)
    hole_mask = cv2.erode(hole_mask, np.ones((3, 3), np.uint8))
    samples = lab[hole_mask > 0].astype(np.float32)
    if len(samples) < 8:
        return False
    distances = np.linalg.norm(samples[:, None]-palette, axis=2).min(axis=1)
    return float(np.mean(distances < 24)) >= .75
