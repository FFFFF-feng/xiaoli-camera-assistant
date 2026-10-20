"""Shared presentation policy for actual, normalized source-to-target geometry."""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from camera_assistant.composition_models import ObservedScene

SCALE_CHANGE_THRESHOLD = .06
FRAME_SHIFT_THRESHOLD = .04
SUBJECT_SHIFT_THRESHOLD = .04
SUBJECT_SIZE_THRESHOLD = .05
ASPECT_EPSILON = 1e-6
EDGE_MARGIN_THRESHOLD = .01


@dataclass(frozen=True)
class LayoutDelta:
    scale_change: float
    frame_center_shift: float
    subject_center_shift: float
    subject_size_change: float
    aspect_changed: bool

    @property
    def near_identity(self) -> bool:
        return (not self.aspect_changed
                and self.scale_change < SCALE_CHANGE_THRESHOLD
                and self.frame_center_shift < FRAME_SHIFT_THRESHOLD
                and self.subject_center_shift < SUBJECT_SHIFT_THRESHOLD
                and self.subject_size_change < SUBJECT_SIZE_THRESHOLD)


def measure_layout(transform: tuple[float, float, float, float], boxes: list[list[float]],
                   photo_aspect: float, target_aspect: float) -> LayoutDelta:
    sx, sy, tx, ty = transform
    return LayoutDelta(
        scale_change=max(abs(sx-1), abs(sy-1)),
        # Position of the target frame's centre in source-photo coordinates.
        frame_center_shift=hypot((.5-tx)/sx-.5, (.5-ty)/sy-.5),
        subject_center_shift=max(hypot((b[0]+b[2])/2*(sx-1)+tx,
                                       (b[1]+b[3])/2*(sy-1)+ty) for b in boxes),
        # Percentage-point change in width/height occupancy, for every main.
        subject_size_change=max(max(abs((b[2]-b[0])*(sx-1)),
                                    abs((b[3]-b[1])*(sy-1))) for b in boxes),
        aspect_changed=abs(target_aspect/photo_aspect-1) > ASPECT_EPSILON,
    )


def needs_source_frame(scene: ObservedScene) -> bool:
    return scene.scene_mode == "continuous" or any(
        o.role == "main" and ((o.photo_boundary and o.photo_boundary.clipped_edges)
            or min(o.bbox[0], o.bbox[1], 1-o.bbox[2], 1-o.bbox[3]) <= EDGE_MARGIN_THRESHOLD)
        for o in scene.objects)


def layout_mode(scene: ObservedScene, delta: LayoutDelta, *, crop: bool = False) -> str:
    if scene.scene_mode == "continuous":
        return "source_preserving"
    # A validated crop with a genuine aspect change can still be shown directly.
    if crop and delta.aspect_changed:
        return "crop_projection"
    if needs_source_frame(scene) or delta.near_identity:
        return "source_preserving"
    return "crop_projection" if crop else "schematic"
