"""Environmental geometry must come from pixels and one scene transform."""
from copy import deepcopy

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from camera_assistant.composition_models import ObservedObject, TargetLayer
from camera_assistant.services.scene_context import (
    CONTEXT_PATHS,
    _tone_strokes,
    clip_path,
    context_mask,
    project_context,
    scene_remainder,
    trace_context,
)


def object_data():
    return {"object_id": "object2", "label": "远处环境", "kind": "building", "role": "background",
            "depth": 0, "bbox": [0, 0, 1, 1], "outline": [[0, 0], [1, 0], [1, 1], [0, 1]],
            "identity_features": ["可见边界"], "evidence_photo_ids": ["photo1"], "mobility": "fixed"}


def context_object():
    return ObservedObject.model_validate({**object_data(), "representation": "context_lines",
        "outline": [], "details": [[[0, .25], [.5, .25], [1, .25]], [[.1, .6], [.8, .8]]]})


@pytest.mark.parametrize("change", [
    {"role": "main"}, {"outline": [[0, 0], [1, 0], [1, 1]]},
    {"details": []}, {"details": [[[False, 0], [1, 1]]]},
    {"contours": [[[0, 0], [1, 0], [1, 1]]]},
])
def test_context_cannot_replace_subject_or_create_filled_placeholder(change):
    with pytest.raises(ValidationError):
        TargetLayer.model_validate({**context_object().model_dump(), **change})


def test_uniform_background_is_not_an_invented_rectangle():
    assert trace_context(np.full((120, 160, 3), 200, np.uint8),
                         ObservedObject.model_validate(object_data())) is None


def test_blurred_structure_keeps_open_boundaries_without_closed_segmentation():
    rgb = np.full((160, 240, 3), 210, np.uint8)
    cv2.rectangle(rgb, (20, 25), (210, 130), (70, 80, 90), 3)
    cv2.line(rgb, (100, 25), (100, 130), (70, 80, 90), 3)
    rgb = cv2.GaussianBlur(rgb, (15, 15), 3)
    obj = trace_context(rgb, ObservedObject.model_validate(object_data()))
    assert obj and obj.representation == "context_lines"
    assert obj.outline == obj.contours == []
    assert 1 <= len(obj.details) <= CONTEXT_PATHS
    assert all(2 <= len(line) <= 64 for line in obj.details)


def test_unlabelled_environment_is_retained_but_not_claimed_as_identified_building():
    rgb = np.full((160, 240, 3), 230, np.uint8)
    cv2.line(rgb, (10, 140), (230, 140), (70, 80, 90), 3)
    obj = scene_remainder(rgb, [], "object3")
    assert obj and obj.object_id == "object3" and obj.kind == "scene_context"
    assert obj.details and obj.outline == []
    assert "未单独命名" in obj.identity_features[0]


def test_background_does_not_repeat_main_silhouette_or_blank_its_whole_box():
    obj = ObservedObject.model_validate({**object_data(), "role": "main", "depth": 2,
        "outline": [[.4, 0], [.6, 0], [.6, 1], [.4, 1]]})
    rgb = np.full((100, 100, 3), 230, np.uint8)
    mask = context_mask(rgb, [obj])
    assert mask[50, 50] == 0 and mask[50, 10] == 255
    cv2.line(rgb, (10, 10), (10, 90), (10, 10, 10), 2)
    cv2.line(rgb, (50, 10), (50, 90), (10, 10, 10), 2)
    context = scene_remainder(rgb, [obj], "object3")
    assert context and context.details
    assert all(x < .4 for path in context.details for x, _ in path)


def test_projection_uses_scene_transform_and_preserves_original_source_paths():
    obj = context_object()
    frozen = deepcopy(obj.model_dump())
    projected = project_context(obj, (.5, .5, .25, .1))
    assert projected and projected.bbox == pytest.approx([.25, .225, .75, .5])
    assert projected.source_bbox == obj.bbox
    assert projected.source_details == obj.details
    assert obj.model_dump() == frozen
    x1, y1, x2, y2 = projected.bbox
    first = projected.details[0][0]
    assert [x1+first[0]*(x2-x1), y1+first[1]*(y2-y1)] == pytest.approx([.25, .225])


def test_partial_environment_is_clipped_not_shrunk_or_dropped():
    obj = context_object()
    layer = project_context(obj, (2, 1, -.5, 0))
    assert layer and layer.bbox[0] == 0 and layer.bbox[2] == 1
    assert all(0 <= n <= 1 for path in layer.details for point in path for n in point)
    assert project_context(obj, (1, 1, 2, 0)) is None


def test_clipping_never_connects_separated_visible_parts_or_exceeds_point_budget():
    paths = clip_path([[.2, .2], [2, .2], [2, .8], [.2, .8]])
    assert len(paths) == 2
    assert paths[0][-1] == [1, .2] and paths[1][0] == [1, .8]
    assert all(len(p) <= 64 for p in clip_path([[i/200, .5] for i in range(201)]))
    assert clip_path([[-1, .5], [2, .5]]) == [[[0, .5], [1, .5]]]


def test_dense_environment_has_bounded_paths_and_points():
    rng = np.random.default_rng(14)
    obj = trace_context(rng.integers(0, 256, (400, 600, 3), dtype=np.uint8),
                        ObservedObject.model_validate(object_data()))
    if obj:
        assert len(obj.details) <= CONTEXT_PATHS
        assert sum(map(len, obj.details)) <= CONTEXT_PATHS*64


def test_tonal_boundary_does_not_close_a_trunk_along_the_crop_rim():
    gray = np.full((180, 240), 220, np.uint8)
    gray[:, :80] = 30  # A dark vertical structure continues beyond the photo.
    paths = _tone_strokes(gray, np.full_like(gray, 255))
    assert paths
    assert all(0 < x < 239 and 0 < y < 179 for path in paths for x, y in path)
    assert all(abs(int(x)-79) <= 1 for path in paths for x, _ in path)
