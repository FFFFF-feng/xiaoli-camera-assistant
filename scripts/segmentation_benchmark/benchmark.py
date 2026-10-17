"""Offline masks only. Never starts the app, contacts cloud models, or writes source photos."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

BASELINE = "986fd0594150dce96b3255c8cc77ff54e8174620"
OLD = "9b9ad3b79f5f7311ff1a5a7ea4d0c41863b1d66e"
CASES = [
    ("02", "02_running_dog_sharp.jpg", (.18, .25, .81, .78), "pet", "frozen_manual_bbox"),
    ("06", "06_coffee_depth_white_balance.jpg", (.36, .065, .98, 1.), "cup", "frozen_manual_bbox"),
    ("07", "07_mountain_lake_reflection.jpg", (0., .12, 1., .98), "landscape",
     "B_manual_applicability_only"),
    ("08", "08_architecture_corridor_symmetry.jpg", (.02, .02, .98, .98), "building",
     "B_manual_applicability_only"),
]


class BenchmarkFailure(ValueError):
    def __init__(self, code, *args, **kwargs):
        self.code = code
        super().__init__(code)


def grabcut_mask(source, rgb, bbox, kind):
    """Execute exactly the source's mask-producing prefix, before contour selection.

    This deliberately excludes simplification/details/geometry validation, so a
    successful result here does not assert `_trace_single` or final line success.
    """
    fn = next(n for n in ast.parse(source).body
              if isinstance(n, ast.FunctionDef) and n.name == "_trace_single")
    prefix = []
    for node in fn.body:
        prefix.append(node)
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "foreground" for t in node.targets):
            break
    else:
        raise ValueError("Frozen source has no foreground assignment")
    fn.body = prefix + ast.parse("return foreground != 0, (ox, oy, ex, ey)").body
    fn.returns = None
    for arg in [*fn.args.args, *fn.args.kwonlyargs]:
        arg.annotation = None
    namespace = {"np": np, "cv2": cv2, "PET_ITERATIONS": 5,
                 "ContourFailure": BenchmarkFailure}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),  # noqa: S102
                 "<frozen-grabcut-mask-prefix>", "exec"), namespace)
    cv2.setRNGSeed(0)
    patch, (ox, oy, ex, ey) = namespace["_trace_single"](
        rgb, SimpleNamespace(bbox=bbox, kind=kind, object_id="object1"))
    full = np.zeros(rgb.shape[:2], bool)
    full[oy:ey, ox:ex] = patch
    return full


def topology(mask):
    binary = mask.astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    holes = [] if hierarchy is None else [i for i in range(len(contours))
                                         if hierarchy[0][i][3] != -1]
    return {"foreground_pixels": int(mask.sum()), "components": count-1,
            "component_areas": sorted(map(int, stats[1:, cv2.CC_STAT_AREA]), reverse=True),
            "holes": len(holes), "hole_contour_areas": sorted(
                [float(cv2.contourArea(contours[i])) for i in holes], reverse=True),
            "bottom_edge_foreground_pixels": int(mask[-1].sum()),
            "contour_points": sum(len(c) for c in contours)}


def save_visuals(prefix, rgb, mask):
    prefix = Path(prefix)
    Image.fromarray(mask.astype(np.uint8)*255).save(f"{prefix}-mask.png")
    overlay = rgb.copy()
    overlay[mask] = (overlay[mask]*.55 + np.array([0, 190, 255])*.45).astype(np.uint8)
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay, contours, -1, (255, 60, 35), 1)
    Image.fromarray(overlay).save(f"{prefix}-overlay.png")
    canvas = np.full_like(rgb, 255)
    cv2.drawContours(canvas, contours, -1, (15, 15, 15), 1)
    Image.fromarray(canvas).save(f"{prefix}-contours.png")


def memory():
    try:
        import psutil
        return {"process_rss_bytes": psutil.Process().memory_info().rss}
    except ImportError:
        return {"process_rss_bytes": None}


def gpu_memory():
    # Never allocate a GPU context for the GrabCut-only run.
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        return {"torch_allocated_bytes": torch.cuda.memory_allocated(),
                "torch_reserved_bytes": torch.cuda.memory_reserved(),
                "torch_peak_allocated_bytes": torch.cuda.max_memory_allocated()}
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photos", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--skip-model", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)  # retain failures, never overwrite a run
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "src"))
    import camera_assistant
    from camera_assistant.services.segmentation import SegmentationRegion, SegmentationRuntime

    cv2.setNumThreads(1)
    sources = {name: subprocess.check_output([
        "git", "-C", str(repo), "show", f"{sha}:src/camera_assistant/services/pixel_contours.py",
    ]).decode("utf-8") for name, sha in [("grabcut_old", OLD), ("grabcut_checkpoint", BASELINE)]}
    manifest = {"kind": "controlled_manual_boxes_mask_only", "cloud_gateway_calls": 0,
        "cloud_internal_requests": 0, "baseline": BASELINE,
        "source_module": camera_assistant.__file__, "python": sys.version,
        "platform": platform.platform(), "cv2": cv2.__version__, "numpy": np.__version__,
        "input_preprocessing": "PIL exif_transpose RGB thumbnail BICUBIC; max-edge 720/1280",
        "source_hashes": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sources.items()},
        "ground_truth": None, "IoU": None, "attempts": []}
    runtime = None if args.skip_model else SegmentationRuntime(args.weights, device=args.device)
    ledger = args.output / "manifest.json"

    def persist():
        ledger.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    persist()
    try:
        for case_id, filename, box, kind, provenance in CASES:
            path = args.photos / filename
            photo_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            for edge in (720, 1280):
                with Image.open(path) as image:
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    image.thumbnail((edge, edge), Image.Resampling.BICUBIC)
                    rgb = np.array(image)
                for backend in [*sources, *(["mobile_sam"] if runtime else [])]:
                    for repeat in (0, 1):
                        record = {"case": case_id, "backend": backend, "edge": edge,
                            "repeat": repeat, "bbox": box, "box_provenance": provenance,
                            "photo_sha256": photo_sha, "rgb_sha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
                            "shape": rgb.shape, "memory_before": memory(), "mask_metrics": None}
                        prefix = args.output / f"{case_id}-{edge}-{backend}-{repeat}"
                        start = time.perf_counter()
                        mask = None
                        try:
                            if backend in sources:
                                mask = grabcut_mask(sources[backend], rgb, box, kind)
                                record.update(status="success", code="mask_prefix_only",
                                              timings={"total": time.perf_counter()-start})
                            else:
                                result, = runtime.segment_many(rgb,
                                    [SegmentationRegion("object1", box)], timeout_seconds=120.)
                                mask = result.mask
                                record.update({k: getattr(result, k) for k in (
                                    "status", "code", "timings", "model_version", "weights_sha256",
                                    "device", "candidate_count", "selection_basis")})
                        except Exception as error:  # noqa: BLE001 -- ledger every attempt, no raw text
                            record.update(status="failed", code=getattr(error, "code", type(error).__name__),
                                          timings={"total": time.perf_counter()-start})
                        record["wall_seconds"] = time.perf_counter()-start
                        record["memory_after"] = {**memory(), **gpu_memory()}
                        if mask is not None:
                            record["mask_metrics"] = topology(mask)
                            record["mask_file"] = f"{prefix.name}-mask.png"
                            save_visuals(prefix, rgb, mask)
                        manifest["attempts"].append(record)
                        persist()
                        print(case_id, edge, backend, repeat, record["code"],
                              round(record["wall_seconds"], 4), flush=True)
    finally:
        if runtime:
            runtime.close()
        manifest["after_close_memory"] = {**memory(), **gpu_memory()}
        persist()
    # Each comparison keeps the same image aspect and includes raw contours,
    # not a simulated final composition. Photo overlays remain in ignored output.
    for case_id, _, _, _, _ in CASES:
        for edge in (720, 1280):
            records = [r for r in manifest["attempts"] if r["case"] == case_id
                       and r["edge"] == edge and r["repeat"] == 0 and r.get("mask_file")]
            panels = []
            for record in records:
                prefix = args.output / record["mask_file"].replace("-mask.png", "")
                with Image.open(f"{prefix}-overlay.png") as im:
                    overlay = im.copy()
                with Image.open(f"{prefix}-contours.png") as im:
                    contours = im.copy()
                panel = Image.new("RGB", (overlay.width, overlay.height*2+36), "white")
                ImageDraw.Draw(panel).text((8, 8), record["backend"]+" (mask only)", fill="black")
                panel.paste(overlay, (0, 36))
                panel.paste(contours, (0, 36+overlay.height))
                panels.append(panel)
            if panels:
                sheet = Image.new("RGB", (sum(p.width for p in panels), max(p.height for p in panels)), "white")
                x = 0
                for panel in panels:
                    sheet.paste(panel, (x, 0))
                    x += panel.width
                sheet.save(args.output / f"{case_id}-{edge}-comparison.png")


if __name__ == "__main__":
    main()
