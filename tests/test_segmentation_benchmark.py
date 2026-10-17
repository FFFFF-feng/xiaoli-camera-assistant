"""Benchmark uses real GrabCut, plus synthetic masks to test evidence rendering."""
import importlib.util
from pathlib import Path

import numpy as np


def module():
    path = Path(__file__).resolve().parents[1] / "scripts/segmentation_benchmark/benchmark.py"
    spec = importlib.util.spec_from_file_location("segmentation_benchmark", path)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_source_extraction_runs_frozen_grabcut_without_downstream_geometry():
    bench = module()
    source = '''def _trace_single(rgb, obj, *, seeded=False):
    mask = np.zeros(rgb.shape[:2], np.uint8)
    ox, oy, ex, ey = 0, 0, rgb.shape[1], rgb.shape[0]
    cv2.grabCut(rgb, mask, (8, 8, 24, 24), np.zeros((1,65)), np.zeros((1,65)), 2, cv2.GC_INIT_WITH_RECT)
    foreground = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    raise RuntimeError("downstream geometry must not run")
'''
    rgb = np.zeros((40, 40, 3), np.uint8)
    rgb[12:28, 12:28] = 240
    result = bench.grabcut_mask(source, rgb, (.2, .2, .8, .8), "cup")
    assert result.dtype == np.bool_ and result.shape == (40, 40)
    assert result[20, 20] and not result[0, 0]


def test_topology_and_visible_comparison_keep_hole_and_disconnected_region(tmp_path):
    bench = module()
    mask = np.zeros((40, 40), bool)
    mask[3:20, 3:20] = True
    mask[7:11, 7:11] = False
    mask[30:35, 30:35] = True
    metrics = bench.topology(mask)
    assert metrics["components"] == 2 and metrics["holes"] == 1
    assert metrics["foreground_pixels"] == int(mask.sum())
    bench.save_visuals(tmp_path / "sample", np.zeros((40, 40, 3), np.uint8), mask)
    assert (tmp_path / "sample-mask.png").is_file()
    assert (tmp_path / "sample-overlay.png").is_file()
    assert (tmp_path / "sample-contours.png").is_file()
