"""Frozen segmentation-v1 records; importing this package never imports Torch."""
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np

FAILURE_CODES = frozenset({
    "invalid_image", "invalid_bbox", "region_too_small", "duplicate_object_id",
    "object_limit_exceeded", "backend_unavailable", "weights_missing", "weights_invalid",
    "device_unavailable", "compute_slot_busy", "inference_timeout", "inference_failed",
    "mask_empty", "mask_full_frame", "mask_invalid",
})


@dataclass(frozen=True)
class SegmentationRegion:
    object_id: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class SegmentationResult:
    object_id: str
    status: Literal["success", "failed"]
    code: str
    mask: np.ndarray | None
    backend: str
    model_version: str
    weights_sha256: str | None
    device: str
    timings: dict[str, float]
    candidate_count: int
    selection_basis: str


@dataclass(frozen=True)
class MaskCandidates:
    masks: np.ndarray
    scores: np.ndarray


class BackendError(Exception):
    """Fixed public failure only; never expose a provider's exception text."""

    def __init__(self, code):
        self.code = code if code in FAILURE_CODES else "inference_failed"
        super().__init__(self.code)


class SegmentationBackend(Protocol):
    backend: str
    model_version: str
    weights_sha256: str | None
    device: str
    preprocessing_version: str

    def load(self) -> None: ...
    def encode(self, rgb: np.ndarray) -> None: ...
    def predict(self, box: np.ndarray) -> MaskCandidates: ...
    def reset_image(self) -> None: ...
    def close(self) -> None: ...
