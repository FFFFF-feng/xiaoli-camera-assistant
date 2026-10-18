"""A's minimal call site. This example intentionally does not change the pipeline."""
from camera_assistant.services.segmentation import SegmentationRegion, SegmentationRuntime


def segment_visible_objects(runtime, rgb, observed_objects):
    """RGB must already have EXIF orientation normalized by A.

    Call once for the 1–4 eligible silhouette objects on this image. Continuous
    scene structures keep A's existing path. Return failures to A's scheduler;
    B never silently substitutes GrabCut or a rectangle.
    """
    regions = [SegmentationRegion(obj.object_id, tuple(obj.bbox)) for obj in observed_objects]
    return runtime.segment_many(rgb, regions, timeout_seconds=10.0)


def example_service(weights_path, expected_sha256):
    # Own one instance for this service, not one instance per object/request.
    # A may select device="cuda" only after testing its chosen Torch install.
    return SegmentationRuntime(weights_path, device="cpu", expected_sha256=expected_sha256)


# At A's foreground-producing point, after success and local patch selection:
# foreground = result.mask[oy:ey, ox:ex].astype("uint8") * 255
# Keep CCOMP hierarchy/multiple components before simplification. A owns the
# coverage/self-intersection/source/aspect checks and the fallback diagnostics.
# On service shutdown, runtime.close(); it waits for in-progress native work.
