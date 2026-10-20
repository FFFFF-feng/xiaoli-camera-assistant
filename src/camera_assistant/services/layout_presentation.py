"""Shared, deterministic presentation policy; never synthesizes scene geometry."""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from math import hypot

from camera_assistant.composition_models import ObservedScene

SCALE_CHANGE_THRESHOLD = .06
FRAME_SHIFT_THRESHOLD = .04
SUBJECT_SHIFT_THRESHOLD = .04
SUBJECT_AREA_THRESHOLD = .05
ASPECT_CHANGE_THRESHOLD = .02
TARGET_EDGE_MARGIN = .08


def source_transform(photo_aspect: float, frame_aspect: float) -> tuple[float, float, float, float]:
    sy = min(1., frame_aspect / photo_aspect)
    sx = sy * photo_aspect / frame_aspect
    return sx, sy, (1-sx)/2, (1-sy)/2


@dataclass(frozen=True)
class LayoutChange:
    scale: float
    frame_center: float
    subject_center: float
    subject_area: float
    aspect_changed: bool

    @property
    def near_identity(self) -> bool:
        return (self.scale < SCALE_CHANGE_THRESHOLD
                and self.frame_center < FRAME_SHIFT_THRESHOLD
                and self.subject_center < SUBJECT_SHIFT_THRESHOLD
                and self.subject_area < SUBJECT_AREA_THRESHOLD
                and not self.aspect_changed)


def measure_layout(transform: tuple[float, float, float, float], photo_aspect: float,
                   frame_aspect: float, subject: list[float]) -> LayoutChange:
    """Compare against an unchanged source fitted to the canvas, excluding letterbox padding.

    Centers use normalized frame/source units. Subject area is a fraction of the
    frame (percentage points), not a relative percentage of a tiny subject.
    """
    sx, sy, tx, ty = transform
    bx, by, btx, bty = source_transform(photo_aspect, frame_aspect)
    cx, cy = (subject[0]+subject[2])/2, (subject[1]+subject[3])/2
    area = (subject[2]-subject[0]) * (subject[3]-subject[1])
    return LayoutChange(
        scale=max(abs(sx/bx-1), abs(sy/by-1)),
        frame_center=hypot((.5-tx)/sx-.5, (.5-ty)/sy-.5),
        subject_center=hypot(cx*sx+tx-(cx*bx+btx), cy*sy+ty-(cy*by+bty)),
        subject_area=abs(area*(sx*sy-bx*by)),
        aspect_changed=abs(frame_aspect/photo_aspect-1) >= ASPECT_CHANGE_THRESHOLD,
    )


def classify_layout(scene: ObservedScene, photo_aspect: float, frame_aspect: float,
                    transform: tuple[float, float, float, float], subject: list[float],
                    *, crop: list[float] | None = None,
                    aspect_changed: bool | None = None) -> tuple[str, LayoutChange]:
    change = measure_layout(transform, photo_aspect, frame_aspect, subject)
    if aspect_changed is not None:
        # The old three-value canvas enum approximates 3:2 etc. Fitting an
        # unchanged photo to that canvas is not a requested aspect-ratio change.
        change = replace(change, aspect_changed=aspect_changed)
    # A validated crop is observed-pixel projection, not an invented new viewpoint.
    if crop is not None and not change.near_identity:
        mode = "crop_projection"
    elif (scene.scene_mode == "continuous" or any(
        obj.role == "main" and obj.photo_boundary and obj.photo_boundary.clipped_edges
        for obj in scene.objects
    ) or change.near_identity):
        mode = "source_preserving"
    else:
        mode = "schematic"
    logging.getLogger(__name__).debug("composition_layout mode=%s change=%s", mode, change)
    return mode, change


def target_frame(scene: ObservedScene) -> list[float]:
    """A field instruction in source-photo coordinates; outside pixels stay unknown.

    Eight percent is an illustrative edge allowance, never a prediction of the
    unseen subject or of the distance needed to photograph it completely.
    """
    edges = {edge for obj in scene.objects if obj.role == "main" and obj.photo_boundary
             for edge in obj.photo_boundary.clipped_edges}
    return [-TARGET_EDGE_MARGIN if "left" in edges else 0.,
            -TARGET_EDGE_MARGIN if "top" in edges else 0.,
            1.+TARGET_EDGE_MARGIN if "right" in edges else 1.,
            1.+TARGET_EDGE_MARGIN if "bottom" in edges else 1.]
