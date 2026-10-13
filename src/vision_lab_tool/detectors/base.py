"""Lightweight provenance and coordinate helpers shared by the isolated adapters."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from vision_lab_tool.detector_models import DetectionObject, DetectionResult, DetectorConfig

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_CACHE = PROJECT_ROOT / "data" / "vision_lab" / "model_cache"
DEFAULT_PATHS = {
    "grounding_dino": MODEL_CACHE / "grounding-dino-tiny",
    "yolo26": MODEL_CACHE / "yolo26n.pt",
}


def weights_path(config: DetectorConfig, root: Path = PROJECT_ROOT) -> Path:
    path = (Path(config.weights_path) if config.weights_path else
            root / "data/vision_lab/model_cache" / DEFAULT_PATHS[config.detector].name)
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def manifest_path(path: Path) -> Path:
    return path / "detector-manifest.json" if path.is_dir() else path.with_suffix(".manifest.json")


def read_manifest(path: Path) -> dict:
    try:
        return json.loads(manifest_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=64)
def _sha256(path: str, size: int, mtime_ns: int) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_provenance(path: Path) -> dict:
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size,
            "sha256": _sha256(str(path), stat.st_size, stat.st_mtime_ns)}


def versions() -> dict:
    result = {}
    for name in ("torch", "torchvision", "transformers", "ultralytics", "numpy", "Pillow"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "missing"
    return result


def provenance(config: DetectorConfig) -> dict:
    path = weights_path(config)
    files = sorted(path.glob("*.safetensors")) if path.is_dir() else [path]
    manifest = read_manifest(path)
    actual = [file_provenance(p) for p in files if p.is_file()]
    frozen = {item.get("path", "").replace("\\", "/").split("/")[-1]: item.get("sha256")
              for item in manifest.get("files", [])}
    for item in actual:
        expected = frozen.get(Path(item["path"]).name)
        if expected and expected != item["sha256"]:
            raise ValueError("权重 SHA256 与准备清单不一致；请重新准备或显式使用新实验版本。")
    revision = manifest.get("revision", "local-unversioned")
    if config.revision and config.revision not in (revision, "main"):
        raise ValueError("配置 revision 与本地权重清单不一致。")
    return {"weights": actual, "weights_path": str(path), "model_revision": revision,
            "model_id": manifest.get("model_id", config.model_id),
            "library_versions": versions(), "device": config.device,
            "precision": config.precision, "preparation_manifest": manifest,
            "batch_size": 1, "inference_network": "disabled"}


def pixel_xyxy(box: Iterable[float], width: int, height: int) -> list[float]:
    """Normalize original sent-image pixels. Never guess units or clip invalid boxes."""
    values = list(box)
    if len(values) != 4 or any(not math.isfinite(v) for v in values):
        raise ValueError("框必须包含四个有限像素坐标")
    x1, y1, x2, y2 = values
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("框越界、倒序或零面积；没有静默裁切")
    return [x1 / width, y1 / height, x2 / width, y2 / height]


def box_iou(a: list[float], b: list[float]) -> float:
    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    union = ((a[2] - a[0]) * (a[3] - a[1]) +
             (b[2] - b[0]) * (b[3] - b[1]) - intersection)
    return intersection / union if union > 0 else 0.0


def finish_result(config: DetectorConfig, result_id: str, raw: list[dict],
                  processed: list[dict], size: tuple[int, int], metadata: dict,
                  timings: dict) -> DetectionResult:
    candidates, diagnostics = [], []
    for item in processed:
        try:
            if item.get("raw_coordinates_valid") is False:
                raise ValueError("模型坐标在官方裁切前越界；保留官方裁切结果供检查，不计原始合法框。")
            normalized = pixel_xyxy(item["bbox_postprocessed"], *size)
            candidates.append(DetectionObject(
                object_id=f"{result_id}_{item['raw_index']}",
                label_original=item["label_original"],
                label_display=item["label_original"], class_id=item.get("class_id"),
                score=item["score"], score_kind=item["score_kind"],
                bbox_native=item["bbox_native"],
                bbox_postprocessed=item["bbox_postprocessed"], bbox=normalized,
                coordinate_basis=item["coordinate_basis"],
                semantic_source=config.detector,
            ))
        except (ValueError, KeyError, TypeError) as exc:
            diagnostics.append(f"raw_index={item.get('raw_index')}: {exc}")
    filtered, removed = [], []
    # Opt-in same-label, same-level suppression only; all original candidates survive.
    for candidate in sorted(candidates, key=lambda value: -(value.score or 0)):
        duplicate = next((old for old in filtered if
                          config.dedup_iou is not None and
                          old.label_original == candidate.label_original and
                          old.target_level == candidate.target_level and
                          box_iou(old.bbox, candidate.bbox) >= config.dedup_iou), None)
        if duplicate:
            removed.append({"object_id": candidate.object_id, "kept_id": duplicate.object_id})
        else:
            filtered.append(candidate)
    if config.dedup_iou is None:
        filtered = list(candidates)
    metadata.update({"source_image_size": list(size), "dedup_iou": config.dedup_iou,
                     "dedup_removed": removed, "invalid_coordinate_count": len(diagnostics)})
    status = ("partial_coordinates" if candidates and diagnostics else "success" if candidates
              else "coordinate_error" if diagnostics else "empty")
    return DetectionResult(result_id=result_id, config=config, status=status,
                           raw_candidates=raw, candidates=candidates,
                           filtered_candidates=filtered, diagnostics=diagnostics,
                           metadata=metadata, timings=timings, real=True)
