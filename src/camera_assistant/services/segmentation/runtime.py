"""One model, one slot, one embedding; stage-boundary (not hard) timeouts."""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import replace
from numbers import Real
from threading import Lock

import numpy as np

from .contracts import BackendError, SegmentationBackend, SegmentationRegion, SegmentationResult


def _bbox_error(region, shape):
    if region.object_id not in {f"object{i}" for i in range(1, 7)}:
        return "invalid_bbox"
    box = region.bbox
    if not isinstance(box, (tuple, list)) or len(box) != 4:
        return "invalid_bbox"
    if any(not isinstance(n, Real) or isinstance(n, bool) or not math.isfinite(n)
           or not 0 <= n <= 1 for n in box):
        return "invalid_bbox"
    x1, y1, x2, y2 = box
    if x1 >= x2 or y1 >= y2:
        return "invalid_bbox"
    if (x2-x1)*shape[1] < 4 or (y2-y1)*shape[0] < 4:
        return "region_too_small"
    return None


def _valid_image(rgb):
    return (isinstance(rgb, np.ndarray) and rgb.dtype == np.uint8 and rgb.ndim == 3
            and rgb.shape[2] == 3 and min(rgb.shape[:2]) >= 8
            and rgb.shape[0]*rgb.shape[1] <= 4_000_000)


def _select(candidates, shape):
    masks, scores = candidates.masks, candidates.scores
    if (not isinstance(masks, np.ndarray) or masks.dtype != np.bool_
            or masks.ndim != 3 or not 1 <= len(masks) <= 3
            or min(masks.shape[1:]) < 1 or np.prod(masks.shape[1:]) > 4_000_000
            or not isinstance(scores, np.ndarray) or scores.shape != (len(masks),)
            or not np.issubdtype(scores.dtype, np.number)):
        raise BackendError("mask_invalid")
    eligible = []
    failures = []
    for index, mask in enumerate(masks):
        if not np.isfinite(scores[index]):
            failures.append("mask_invalid")
        elif not mask.any():
            failures.append("mask_empty")
        elif mask.all():
            failures.append("mask_full_frame")
        else:
            eligible.append(index)
    if not eligible:
        raise BackendError(failures[0])
    index = max(eligible, key=lambda i: (scores[i], -i))
    mask = masks[index]
    if mask.shape != shape:
        # Binary masks are never bilinearly smoothed, morphologically closed,
        # filled, or reduced to the largest connected component.
        ys = np.arange(shape[0]) * mask.shape[0] // shape[0]
        xs = np.arange(shape[1]) * mask.shape[1] // shape[1]
        mask = mask[ys[:, None], xs[None, :]]
    if not mask.any():
        raise BackendError("mask_empty")
    if mask.all():
        raise BackendError("mask_full_frame")
    return mask.copy(), len(masks), (
        f"max_predicted_iou_among_valid_masks;ties=lowest_index;not_accuracy;index={index}"
    )


class SegmentationRuntime:
    """Synchronous local inference. Create one shared instance in A's service.

    Native load/encode/decode cannot be interrupted in this implementation.
    Deadlines are checked before/after each stage: an overrun returns failure
    only after the native call returns. The slot remains held throughout.
    `close` waits for that call before releasing the model. A hard service
    deadline requires a separately managed, recyclable process owned by A.
    """

    def __init__(self, weights_path=None, *, device="cpu", expected_sha256=None,
                 backend_factory: Callable[[], SegmentationBackend] | None = None):
        if backend_factory is None:
            from .mobile_sam import MobileSAMBackend
            backend_factory = lambda: MobileSAMBackend(
                weights_path, device=device, expected_sha256=expected_sha256)
        self._backend = backend_factory()
        self._slot = Lock()
        self._loaded = False
        self._closed = False
        self._unhealthy = False
        self._embedding_key = None

    def _result(self, region, timings, code, mask=None, count=0, basis="none"):
        backend = self._backend
        return SegmentationResult(
            region.object_id, "success" if mask is not None else "failed", code, mask,
            backend.backend, backend.model_version, backend.weights_sha256, backend.device,
            dict(timings), count, basis,
        )

    def _reset(self):
        self._embedding_key = None
        try:
            self._backend.reset_image()
        except Exception:  # noqa: BLE001 -- cleanup failures cannot expose native exception text
            self._unhealthy = True
            return False
        return True

    def segment_many(self, rgb: np.ndarray, regions: Sequence[SegmentationRegion], *,
                     timeout_seconds: float = 10.0) -> list[SegmentationResult]:
        started = time.perf_counter()
        timings = dict.fromkeys(("queue", "load", "encode", "decode", "postprocess", "total"), 0.)
        # Own all prompt parameters before queueing or invoking native code.
        regions = [SegmentationRegion(
            r.object_id if isinstance(r.object_id, str) else "",
            tuple(r.bbox) if isinstance(r.bbox, (tuple, list)) else r.bbox,
        ) for r in regions]
        if not regions:
            return []
        errors = [None] * len(regions)

        def finish(results):
            elapsed = time.perf_counter() - started
            return [replace(r, timings={**r.timings, "total": elapsed}) for r in results]

        def failed_all(code):
            return finish([self._result(r, timings, error or code)
                           for r, error in zip(regions, errors)])

        if not _valid_image(rgb):
            return failed_all("invalid_image")
        if len(regions) > 4:
            return failed_all("object_limit_exceeded")
        counts = Counter(r.object_id for r in regions if r.object_id in {
            f"object{i}" for i in range(1, 7)})
        errors = ["duplicate_object_id" if counts.get(r.object_id, 0) > 1
                  else _bbox_error(r, rgb.shape) for r in regions]
        if all(errors):
            return finish([self._result(r, timings, e) for r, e in zip(regions, errors)])
        if (not isinstance(timeout_seconds, Real) or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0):
            return failed_all("inference_timeout")
        deadline = started + timeout_seconds
        queue_start = time.perf_counter()
        acquired = self._slot.acquire(timeout=min(.5, max(0., deadline-queue_start)))
        timings["queue"] = time.perf_counter() - queue_start
        if not acquired:
            return failed_all("compute_slot_busy")

        def check_deadline():
            if time.perf_counter() >= deadline:
                raise BackendError("inference_timeout")

        def stage(name, operation):
            check_deadline()
            before = time.perf_counter()
            try:
                return operation()
            finally:
                timings[name] = time.perf_counter() - before

        try:
            if self._closed or self._unhealthy:
                return failed_all("backend_unavailable")
            check_deadline()
            # Snapshot only after owning the slot: at most one retained image.
            snapshot = np.array(rgb, copy=True, order="C")
            if not _valid_image(snapshot):
                return failed_all("invalid_image")
            shape = snapshot.shape[:2]
            # Shape may have changed while queued; validate against owned pixels.
            errors = [error or _bbox_error(r, shape) for r, error in zip(regions, errors)]
            if not self._loaded:
                stage("load", self._backend.load)
                self._loaded = True
            check_deadline()
            digest = hashlib.sha256(snapshot.tobytes())
            digest.update(json.dumps([
                snapshot.shape, self._backend.backend, self._backend.model_version,
                self._backend.weights_sha256, self._backend.device,
                self._backend.preprocessing_version, "segmentation-v1-selection-v1",
                [(r.object_id, list(map(float, r.bbox))) for r, e in zip(regions, errors) if not e],
            ], separators=(",", ":")).encode())
            key = digest.digest()
            if key != self._embedding_key:
                if not self._reset():
                    raise BackendError("inference_failed")
                stage("encode", lambda: self._backend.encode(snapshot))
                check_deadline()
                self._embedding_key = key
            results = []
            any_failed = False
            for region, error in zip(regions, errors):
                timings["decode"] = timings["postprocess"] = 0.
                count = 0
                if error:
                    results.append(self._result(region, timings, error))
                    any_failed = True
                    continue
                try:
                    box = np.array(region.bbox, dtype=np.float32) * (
                        [shape[1], shape[0]] * 2)
                    candidates = stage("decode", lambda box=box: self._backend.predict(box))
                    if isinstance(candidates.masks, np.ndarray) and candidates.masks.ndim == 3:
                        count = len(candidates.masks)
                    check_deadline()
                    mask, count, basis = stage("postprocess", lambda candidates=candidates: _select(
                        candidates, shape))
                    check_deadline()
                    results.append(self._result(region, timings, "mask_extracted", mask, count, basis))
                except Exception as error:  # noqa: BLE001 -- frozen failure boundary
                    code = error.code if isinstance(error, BackendError) else "inference_failed"
                    results.append(self._result(region, timings, code, count=count,
                                                basis="selection_failed" if count else "none"))
                    any_failed = True
            if any_failed:
                self._reset()
            return finish(results)
        except Exception as error:  # noqa: BLE001 -- frozen failure boundary
            self._reset()
            code = error.code if isinstance(error, BackendError) else "inference_failed"
            return failed_all(code)
        finally:
            self._slot.release()

    def close(self) -> None:
        with self._slot:
            if not self._closed:
                self._closed = True
                self._embedding_key = None
                try:
                    self._backend.close()
                except Exception:  # noqa: BLE001 -- close is idempotent and sanitized
                    self._unhealthy = True
                self._loaded = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
