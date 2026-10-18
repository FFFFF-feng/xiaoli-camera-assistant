from copy import deepcopy

import numpy as np
import pytest
from test_observed_composition import advice, observed

from camera_assistant.composition_models import CompositionIntent, ObservedScene, PhotoBoundary
from camera_assistant.services.layout_solver import ASPECTS, solve_layout
from camera_assistant.services.photo_boundary import boundary_evidence, split_frame_edges
from camera_assistant.services.pixel_contours import _trace_single, observed_metadata

RING = [[0, 0], [1, 0], [1, 1], [0, 1]]


@pytest.mark.parametrize("edge,box", [
    ("left", [0, .2, .8, .8]), ("top", [.2, 0, .8, .8]),
    ("right", [.2, .2, .99, .8]), ("bottom", [.2, .2, .8, .99]),
])
def test_four_edges_use_pixel_centres_and_only_remove_frame_segments(edge, box):
    evidence = boundary_evidence(RING, box, 100, 100)
    parsed = PhotoBoundary.model_validate(evidence)
    assert parsed.clipped_edges == [edge]
    assert sum(len(path) - 1 for path in parsed.visible_paths) == 3
    assert all(p in RING for path in parsed.visible_paths for p in path)


def test_near_edge_and_true_unclipped_flat_base_do_not_become_truncation():
    for box in ([.2, .2, .8, .98], [.2, .2, .8, .9]):
        evidence = boundary_evidence(RING, box, 100, 100)
        assert evidence["clipped_edges"] == [] and evidence["visible_paths"] == []


@pytest.mark.parametrize("photo_aspect", [.6, 1., 1.500586, 2.4])
def test_truncated_source_preserves_single_transform_and_marks_unknown_field(photo_aspect):
    data = observed()
    obj = data["objects"][0]
    obj["bbox"] = [.3, .1, .9, 479/480]
    obj["outline"] = deepcopy(RING)
    obj["details"] = [[[.2, .2], [.8, .7]]]
    obj["photo_boundary"] = boundary_evidence(RING, obj["bbox"], 720, 480)
    scene = ObservedScene.model_validate(data)
    for target_aspect in ASPECTS:
        board, _ = solve_layout(CompositionIntent(focus_object_id="object1", diagnosis="保留实际可见边界",
            subject_scale="larger", placement="right", aspect=target_aspect), scene, photo_aspect, advice().proposals[0])
        main = board.layers[0]
        assert board.layout_mode == "source_preserving" and board.observed_frame is not None
        assert main.source_bbox == scene.objects[0].bbox and main.outline == scene.objects[0].outline
        assert main.details == scene.objects[0].details
        x1, y1, x2, y2 = board.observed_frame
        assert main.bbox == pytest.approx([x1+.3*(x2-x1), y1+.1*(y2-y1), x1+.9*(x2-x1), y1+479/480*(y2-y1)])
        assert (x2-x1)*ASPECTS[board.aspect]/(y2-y1) == pytest.approx(photo_aspect)
        assert main.bbox[3] != 1  # No forced bottom completion.


def test_last_mask_row_supplies_evidence_without_inventing_a_bottom():
    rgb = np.indices((100, 100)).sum(axis=0).astype(np.uint8)
    rgb = np.repeat(rgb[:, :, None], 3, axis=2)
    mask = np.zeros((100, 100), dtype=bool)
    mask[20:, 20:80] = True
    obj = observed_metadata({"objects": [{**observed()["objects"][0], "bbox": [.2, .2, .8, 1]}],
                            "limitations": ["合成像素回归"]}).objects[0]
    traced = _trace_single(rgb, obj, foreground_mask=mask)
    assert traced.bbox[3] == .99
    assert traced.photo_boundary.clipped_edges == ["bottom"]
    assert traced.photo_boundary.basis == "pixel_mask_v1"


def test_texture_frame_runs_are_removed_but_other_details_remain_unchanged():
    detail = [[.3, .2], [.6, .8]]
    paths = split_frame_edges([RING + [RING[0]], detail], [.2, .2, .8, .99], 100, 100, ["bottom"])
    assert detail in paths
    assert sum(len(p)-1 for p in paths) == 4  # three real sides plus one texture line


def test_historical_geometry_does_not_silently_acquire_contact_evidence():
    scene = ObservedScene.model_validate(observed())
    assert scene.objects[0].photo_boundary is None
    reconstructed = boundary_evidence(RING, [.2, .2, .8, .99], 100, 100, basis="saved_outline_v1")
    assert reconstructed["basis"] == "saved_outline_v1"
