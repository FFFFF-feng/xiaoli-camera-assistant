"""Service ownership of optional segmentation; no Torch import, download or cloud I/O.

The B runtime owns native inference and its cooperative stage deadlines.  This
wrapper owns configuration, public diagnostics and opt-in, bounded local evidence.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, RLock
from uuid import uuid4

import numpy as np
from PIL import Image

from camera_assistant.services.segmentation import (
    BackendError,
    SegmentationRegion,
    SegmentationRuntime,
)
from camera_assistant.services.segmentation.mobile_sam import MobileSAMBackend

_VERSION = "segmentation-provider-v1"
_MAX_WEIGHT_BYTES = 128 * 1024 * 1024
_HASH_CACHE: OrderedDict[tuple, str] = OrderedDict()
_HASH_LOCK = Lock()
_REGISTRY_LOCK = Lock()
_EVIDENCE_LOCK = Lock()
_EVIDENCE_ROOT = Path(__file__).resolve().parents[3] / ".tmp" / "segmentation-evidence"
_MAX_EVIDENCE_RECORDS = 32
_MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
_ID = re.compile(r"object[1-6]\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
_OWNED = re.compile(
    r"([0-9a-f]{32})-(?:object[1-6]\.mask\.png|contours\.json|drawing\.svg|manifest\.json)\Z"
)


@dataclass(frozen=True)
class _Config:
    backend: str = "grabcut"
    weights: Path | None = None
    expected_sha256: str = ""
    device: str = "cpu"
    fallback: bool = True
    timeout: float = 10.0
    evidence: bool = False

    @classmethod
    def read(cls, settings):
        if settings is None:
            return cls()
        path = getattr(settings, "segmentation_weights_path", None)
        return cls(
            backend=getattr(settings, "segmentation_backend", "grabcut"),
            weights=Path(path).expanduser().absolute() if path else None,
            expected_sha256=getattr(settings, "segmentation_weights_sha256", "").lower(),
            device=getattr(settings, "segmentation_device", "cpu"),
            fallback=getattr(settings, "segmentation_fallback", True),
            timeout=getattr(settings, "segmentation_timeout_seconds", 10.0),
            evidence=getattr(settings, "segmentation_evidence", False),
        )


def _weight_identity(path):
    """Bound both hashing work and the stat-keyed cache; never expose paths."""
    if path is None:
        return None, None, "weights_missing"
    try:
        info = path.stat()
        if not path.is_file():
            return None, None, "weights_missing"
        fingerprint = (str(path), info.st_dev, info.st_ino, info.st_size,
                       info.st_mtime_ns, info.st_ctime_ns)
        if not 0 < info.st_size <= _MAX_WEIGHT_BYTES:
            return None, fingerprint, "weights_invalid"
        with _HASH_LOCK:
            if fingerprint in _HASH_CACHE:
                _HASH_CACHE.move_to_end(fingerprint)
                return _HASH_CACHE[fingerprint], fingerprint, None
        digest_builder = hashlib.sha256()
        remaining = _MAX_WEIGHT_BYTES
        with path.open("rb") as stream:
            while chunk := stream.read(min(1024 * 1024, remaining + 1)):
                if len(chunk) > remaining:
                    return None, fingerprint, "weights_invalid"
                digest_builder.update(chunk)
                remaining -= len(chunk)
        digest = digest_builder.hexdigest()
        after = path.stat()
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns):
            return None, fingerprint, "weights_invalid"
        with _HASH_LOCK:
            _HASH_CACHE[fingerprint] = digest
            _HASH_CACHE.move_to_end(fingerprint)
            while len(_HASH_CACHE) > 32:
                _HASH_CACHE.popitem(last=False)
        return digest, fingerprint, None
    except OSError:
        return None, None, "weights_missing"


class _RejectedWeightsBackend(MobileSAMBackend):
    """Use B's normal input validation without reading a rejected weight file."""

    def load(self):
        raise BackendError("weights_invalid")


class SegmentationProvider:
    """One service-owned B runtime, with no implicit GrabCut fallback."""

    def __init__(self, config):
        self._config = config
        self._lock = RLock()
        self._runtime = None
        self._weight_state = None
        self._actual_digest = None
        self._weight_code = None
        self._closed = False
        self._last_actual = None
        self._last_weights = None
        self._last_code = None
        self._proven = False

    @property
    def evidence_enabled(self):
        return self._config.evidence

    def _refresh_weights(self):
        if self._config.backend != "mobile_sam":
            return
        digest, fingerprint, code = _weight_identity(self._config.weights)
        if self._config.expected_sha256 and (not _DIGEST.fullmatch(self._config.expected_sha256)
                                             or digest != self._config.expected_sha256):
            # A missing file retains the more useful frozen missing code.
            code = code or "weights_invalid"
        state = (digest, fingerprint, code)
        if state != self._weight_state:
            if self._runtime is not None:
                # B close waits for native completion before any replacement.
                self._runtime.close()
                self._runtime = None
            self._weight_state = state
            self._actual_digest, self._weight_code = digest, code
            self._last_actual = self._last_weights = self._last_code = None
            self._proven = False

    def identity(self):
        with self._lock:
            self._refresh_weights()
            config = self._config
            return {
                "provider_version": _VERSION,
                "backend": config.backend,
                "model": MobileSAMBackend.model_version if config.backend == "mobile_sam"
                else "opencv-GrabCut",
                "weights_sha256": self._actual_digest,
                "expected_weights_sha256": config.expected_sha256 or None,
                "weights_status": self._weight_code,
                "device": config.device if config.backend == "mobile_sam" else "cpu",
                "preprocess": MobileSAMBackend.preprocessing_version
                if config.backend == "mobile_sam" else "caller-normalized-RGB-grabcut-v1",
                "timeout_seconds": config.timeout,
                "timeout_semantics": "native-stage-boundary-not-hard-cancellation",
                "fallback": config.fallback,
            }

    def segment_many(self, rgb, eligible):
        regions = [SegmentationRegion(obj.object_id, tuple(obj.bbox)) for obj in eligible]
        if not regions:
            return {}
        with self._lock:
            self._refresh_weights()
            if self._runtime is None:
                # Hash the local file independently of B; also pin that observed
                # content during B's real load to reject a time-of-check race.
                if self._weight_code == "weights_invalid":
                    self._runtime = SegmentationRuntime(backend_factory=lambda:
                        _RejectedWeightsBackend(self._config.weights, device=self._config.device))
                else:
                    self._runtime = SegmentationRuntime(
                        self._config.weights, device=self._config.device,
                        expected_sha256=self._config.expected_sha256 or self._actual_digest,
                    )
                if self._closed or self._config.backend != "mobile_sam":
                    self._runtime.close()
            runtime = self._runtime
        # Do not hold the provider lock over native inference: B's .5-second
        # compute-slot queue remains the authority for concurrent requests.
        results = runtime.segment_many(rgb, regions, timeout_seconds=self._config.timeout)
        with self._lock:
            if runtime is self._runtime and not self._closed:
                for result in results:
                    if result.status == "success" and result.mask is not None:
                        self.record_actual(result.backend, weights_sha256=result.weights_sha256,
                                           code=result.code)
        return {result.object_id: result for result in results}

    def record_actual(self, backend, *, weights_sha256=None, code="mask_extracted"):
        """Call only after a real local attempt; configuration is not proof."""
        if backend not in {"grabcut", "mobile_sam"}:
            return
        with self._lock:
            self._last_actual = backend
            self._last_weights = weights_sha256 if isinstance(weights_sha256, str) and (
                _DIGEST.fullmatch(weights_sha256)) else None
            self._last_code = code if isinstance(code, str) and _CODE.fullmatch(code) else None
            self._proven = True

    def diagnostics(self):
        with self._lock:
            identity = self.identity()
            return {
                "configured_backend": identity["backend"],
                "model_version": identity["model"],
                "device": identity["device"],
                "weights_sha256": identity["weights_sha256"],
                "preprocessing_version": identity["preprocess"],
                "last_actual_backend": self._last_actual,
                "last_weights_sha256": self._last_weights,
                "last_code": self._last_code,
                "inference_proven": self._proven,
                "timeout_semantics": identity["timeout_semantics"],
                "fallback_enabled": self._config.fallback,
            }

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                if self._runtime is not None:
                    self._runtime.close()

    def export_evidence(self, image_sha256, masks, objects, processing, *, failed_code=None):
        if not self._config.evidence:
            return None
        try:
            return _export(self, image_sha256, masks, objects, processing, failed_code)
        except (OSError, ValueError, TypeError, OverflowError):
            # Evidence cannot turn an otherwise usable analysis into a failure.
            return None


_CURRENT: ContextVar[SegmentationProvider | None] = ContextVar("segmentation_provider", default=None)
_ACTIVE: SegmentationProvider | None = None


def get_provider(settings=None):
    global _ACTIVE
    if settings is None and _CURRENT.get() is not None:
        return _CURRENT.get()
    config = _Config.read(settings)
    with _REGISTRY_LOCK:
        if _ACTIVE is None or _ACTIVE._config != config or _ACTIVE._closed:
            if _ACTIVE is not None:
                _ACTIVE.close()
            _ACTIVE = SegmentationProvider(config)
        return _ACTIVE


@contextmanager
def use_segmentation(settings):
    provider = get_provider(settings)
    token = _CURRENT.set(provider)
    try:
        yield provider
    finally:
        _CURRENT.reset(token)


def close_providers():
    global _ACTIVE
    with _REGISTRY_LOCK:
        if _ACTIVE is not None:
            _ACTIVE.close()
            _ACTIVE = None


def _path_points(value, limit=64):
    if not isinstance(value, (list, tuple)):
        return []
    points = []
    for point in value[:limit]:
        if (not isinstance(point, (list, tuple)) or len(point) != 2
                or any(not isinstance(n, (int, float)) or isinstance(n, bool)
                       or not math.isfinite(n) or not 0 <= n <= 1 for n in point)):
            return []
        points.append([float(n) for n in point])
    return points


def _geometry(objects):
    records = []
    for obj in objects[:6]:
        identifier = getattr(obj, "object_id", "")
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            continue
        box = getattr(obj, "bbox", ())
        if len(box) != 4 or not _path_points([box[:2], box[2:]]):
            continue
        records.append({
            "object_id": identifier,
            "bbox": list(box),
            "outline": _path_points(getattr(obj, "outline", [])),
            **{key: [_path_points(path) for path in (getattr(obj, key, None) or [])[:limit]]
               for key, limit in (("contours", 12), ("holes", 12), ("details", 96),
                                  ("source_details", 96))},
        })
    return records


def _processing(records):
    safe = []
    numeric = {"component_count", "hole_count", "contour_count", "coverage", "area",
               "foreground_pixels", "discarded_components", "discarded_pixels", "discarded_noise_pixels", "total_seconds",
               "queue_seconds", "load_seconds", "encode_seconds", "decode_seconds",
               "postprocess_seconds", "candidate_count", "cache_hit", "fallback"}
    for record in records[:32]:
        if not isinstance(record, dict):
            continue
        item = {}
        for key, value in record.items():
            allowed_text = isinstance(value, str) and (
                (key == "object_id" and _ID.fullmatch(value))
                or (key in {"backend", "requested_backend", "actual_backend", "mask_backend"}
                    and value in {
                    "grabcut", "mobile_sam", "scene_structure", "scene_context"})
                or (key in {"code", "fallback_code"} and _CODE.fullmatch(value))
                or (key in {"weights_sha256", "weights_version"} and _DIGEST.fullmatch(value))
                or (key == "status" and value in {"success", "failed", "skipped", "fallback"})
            )
            allowed_number = (key in numeric and isinstance(value, (int, float, bool))
                              and math.isfinite(value))
            if allowed_text or allowed_number:
                item[key] = value
            if key == "timings" and isinstance(value, dict):
                item[key] = {stage: seconds for stage, seconds in value.items()
                             if stage in {"queue", "load", "encode", "decode", "postprocess", "total"}
                             and isinstance(seconds, (int, float)) and math.isfinite(seconds)
                             and seconds >= 0}
        safe.append(item)
    return safe


def _svg(records, width, height):
    paths = []
    for record in records:
        x1, y1, x2, y2 = record["bbox"]
        local_paths = [(path, True) for path in [record["outline"], *record["contours"],
                                               *record["holes"]]]
        local_paths.extend((path, False) for path in record["details"])
        for path, closed in local_paths:
            if len(path) < 2:
                continue
            points = " ".join(f"{(x1+x*(x2-x1))*width:.3f},{(y1+y*(y2-y1))*height:.3f}"
                              for x, y in path)
            element = "polygon" if closed else "polyline"
            paths.append(f'<{element} points="{points}"/>')
        for path in record["source_details"]:
            if len(path) >= 2:
                points = " ".join(f"{x*width:.3f},{y*height:.3f}" for x, y in path)
                paths.append(f'<polyline points="{points}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
            '<g fill="none" stroke="black" stroke-width="1">' + "".join(paths) + '</g></svg>')


def _owned_groups(root):
    groups = {}
    for path in root.iterdir():
        match = _OWNED.fullmatch(path.name)
        if (match and not path.is_symlink() and path.is_file()
                and path.resolve().parent == root):
            groups.setdefault(match[1], []).append(path)
    return sorted(groups.values(), key=lambda group: min(p.stat().st_mtime_ns for p in group))


def _export(provider, image_sha256, masks, objects, processing, failed_code):
    if not isinstance(image_sha256, str) or not _DIGEST.fullmatch(image_sha256):
        return None
    prefix = uuid4().hex
    payloads = {}
    mask_records = {}
    safe_processing = _processing(processing)
    processing_by_id = {item["object_id"]: item for item in safe_processing if "object_id" in item}
    width = height = 720
    for identifier, mask in list(masks.items())[:4]:
        if (not isinstance(identifier, str) or not _ID.fullmatch(identifier)
                or not isinstance(mask, np.ndarray) or mask.dtype != np.bool_
                or mask.ndim != 2 or not 0 < mask.size <= 4_000_000):
            continue
        height, width = mask.shape
        name = f"{prefix}-{identifier}.mask.png"
        stream = io.BytesIO()
        Image.fromarray(mask.astype(np.uint8) * 255).save(stream, format="PNG")
        payloads[name] = stream.getvalue()
        source = processing_by_id.get(identifier, {})
        mask_records[identifier] = {
            "file": name, "shape": list(mask.shape),
            "sha256": hashlib.sha256(mask.tobytes()).hexdigest(),
            "source_backend": source.get("mask_backend", source.get("actual_backend",
                                                                        source.get("backend"))),
            "weights_sha256": source.get("weights_sha256", source.get("weights_version")),
        }
    geometries = _geometry(objects)
    contour_name = f"{prefix}-contours.json"
    svg_name = f"{prefix}-drawing.svg"
    manifest_name = f"{prefix}-manifest.json"
    payloads[contour_name] = json.dumps(geometries, separators=(",", ":")).encode()
    payloads[svg_name] = _svg(geometries, width, height).encode()
    diagnostics = provider.diagnostics()
    actual_backends = {identifier: row.get("actual_backend", row.get("backend"))
                       for identifier, row in processing_by_id.items()
                       if row.get("actual_backend", row.get("backend")) is not None}
    used_backends = set(actual_backends.values())
    actual_backend = next(iter(used_backends)) if len(used_backends) == 1 else (
        "mixed" if used_backends else None)
    used_weights = {row.get("weights_sha256", row.get("weights_version"))
                    for identifier, row in processing_by_id.items()
                    if actual_backends.get(identifier) == "mobile_sam"
                    and row.get("weights_sha256", row.get("weights_version"))}
    manifest = {
        "evidence_version": "segmentation-evidence-v1",
        "input_sha256": image_sha256,
        "created_at": datetime.now(UTC).isoformat(),
        "configured_backend": diagnostics["configured_backend"],
        "actual_backend": actual_backend,
        "actual_backends": actual_backends,
        "weights_sha256": next(iter(used_weights)) if len(used_weights) == 1 else None,
        "backend_evidence": "this_batch_processing_not_service_last_call",
        "source_ids": sorted(set(mask_records) | {obj["object_id"] for obj in geometries}),
        "masks": mask_records,
        "contours": contour_name,
        "drawing": svg_name,
        "drawing_stage": "supplied_source_geometry_preview_not_target_layout",
        "processing": safe_processing,
        "failed_code": failed_code if isinstance(failed_code, str)
        and _CODE.fullmatch(failed_code) else None,
    }
    payloads[manifest_name] = json.dumps(manifest, separators=(",", ":")).encode()
    required = sum(map(len, payloads.values()))
    if required > _MAX_EVIDENCE_BYTES:
        return None
    with _EVIDENCE_LOCK:
        root = _EVIDENCE_ROOT.absolute()
        # Refuse symlinks/junctions, including redirected ancestors. Cleanup is
        # flat and only touches our UUID filenames, never another directory.
        if root.resolve() != root:
            return None
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or root.resolve() != root:
            return None
        groups = _owned_groups(root)
        existing = sum(path.stat().st_size for group in groups for path in group)
        while groups and (len(groups) >= _MAX_EVIDENCE_RECORDS
                          or existing + required > _MAX_EVIDENCE_BYTES):
            group = groups.pop(0)
            for path in group:
                if (not path.is_symlink() and path.is_file() and path.resolve().parent == root
                        and _OWNED.fullmatch(path.name)):
                    size = path.stat().st_size
                    path.unlink()
                    existing -= size
        written = []
        try:
            # The association manifest is written last; failed exports remove
            # their own partial files and never erase another attempt's record.
            for name, payload in payloads.items():
                path = root / name
                with path.open("xb") as stream:
                    stream.write(payload)
                written.append(path)
        except OSError:
            for path in written:
                if not path.is_symlink() and path.resolve().parent == root:
                    path.unlink(missing_ok=True)
            raise
        return str(root / manifest_name)
