"""Synthetic scene geometry, not a claim of real-photo semantic quality."""

import cv2
import numpy as np
import pytest
from pydantic import ValidationError
from test_observed_composition import advice, observed

from camera_assistant.composition_models import CompositionIntent, ObservedScene
from camera_assistant.services.layout_solver import solve_layout


def scene():
    data = observed()
    data['scene_mode'] = 'continuous'
    obj = data['objects'][0]
    obj.update(bbox=[0, 0, 1, 1], representation='scene_structure', outline=[],
               details=[[[0, .1], [.5, .5], [1, .1]], [[0, .9], [.5, .5], [1, .9]],
                        [[.1, 0], [.4, 1]], [[.9, 0], [.6, 1]]])
    return ObservedScene.model_validate(data)


def test_open_main_requires_continuous_scene_and_real_structure():
    data = scene().model_dump()
    data['scene_mode'] = 'objects'
    with pytest.raises(ValidationError):
        ObservedScene.model_validate(data)
    data['scene_mode'] = 'continuous'
    data['objects'][0]['details'] = []
    with pytest.raises(ValidationError):
        ObservedScene.model_validate(data)


def test_continuous_mode_cannot_bypass_pet_segmentation():
    data = scene().model_dump()
    data['objects'][0]['kind'] = 'pet'
    with pytest.raises(ValidationError, match='连续场景主体'):
        ObservedScene.model_validate(data)


def test_continuous_keep_does_not_shrink_scene_and_invent_edge_margins():
    source = scene()
    plan = CompositionIntent(focus_object_id='object1', diagnosis='保留居中秩序与完整两侧结构')
    board, framing = solve_layout(plan, source, .75, advice().proposals[0])
    layer = board.layers[0]
    assert layer.representation == 'scene_structure' and layer.role == 'main'
    assert layer.bbox == [0, 0, 1, 1]
    assert layer.details == source.objects[0].details
    assert layer.source_details == source.objects[0].details
    assert board.layout_mode == 'source_preserving'
    assert '保留' in framing.edge_check


def test_structure_extractor_keeps_open_edges_and_rejects_blank_pixels():
    from camera_assistant.services.scene_structure import trace_structure
    obj = scene().objects[0]
    rgb = np.full((240, 180, 3), 220, np.uint8)
    for y in (15, 55, 95, 125):
        cv2.ellipse(rgb, (90, y+65), (80-y//3, 60), 0, 180, 360, (30, 30, 30), 3)
    cv2.line(rgb, (5, 235), (80, 130), (30, 30, 30), 3)
    cv2.line(rgb, (175, 235), (100, 130), (30, 30, 30), 3)
    traced = trace_structure(rgb, obj)
    assert traced.role == 'main' and traced.outline == [] and not traced.contours
    assert len(traced.details) >= 4
    assert all(2 <= len(p) <= 64 for p in traced.details)
    with pytest.raises(ValueError, match='structure'):
        trace_structure(np.full_like(rgb, 220), obj)
