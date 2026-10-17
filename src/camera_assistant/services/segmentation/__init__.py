"""Optional local segmentation-v1; no dependency installation or network I/O."""
from .contracts import (
    BackendError,
    MaskCandidates,
    SegmentationBackend,
    SegmentationRegion,
    SegmentationResult,
)
from .runtime import SegmentationRuntime

__all__ = ["BackendError", "MaskCandidates", "SegmentationBackend", "SegmentationRegion",
           "SegmentationResult", "SegmentationRuntime"]
