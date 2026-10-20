"""Geometric invariants for real observed objects, not renderer implementation snapshots."""
from copy import deepcopy
from itertools import product

import pytest
from pydantic import ValidationError
from test_observed_composition import advice, observed

from camera_assistant.composition_models import CompositionIntent, ObservedScene
from camera_assistant.services.layout_solver import ASPECTS, solve_layout


@pytest.mark.parametrize("placement,scale,aspect", list(product(
    ["keep", "left", "center", "right"], ["keep", "larger", "smaller"], ["portrait", "landscape", "square"])))
def test_layout_is_deterministic_protects_subject_and_preserves_physical_proportions(placement, scale, aspect):
    scene = ObservedScene.model_validate(observed())
    plan = CompositionIntent(focus_object_id="object1", diagnosis="突出细长建筑", placement=placement,
                             subject_scale=scale, aspect=aspect)
    before = scene.model_dump()
    first, _ = solve_layout(plan, scene, 1.5, advice().proposals[0])
    second, _ = solve_layout(plan, scene, 1.5, advice().proposals[0])
    assert first == second and scene.model_dump() == before
    main = first.layers[0]
    x1, y1, x2, y2 = main.bbox
    assert .039999 < x1 < x2 < .960001 and .039999 < y1 < y2 < .960001
    assert (x2-x1)*ASPECTS[aspect]/(y2-y1) == pytest.approx(.1*1.5/.8)
    assert main.outline == scene.objects[0].outline
    assert main.details == scene.objects[0].details
    assert first.layout_engine == "local_v1"


def test_all_main_subjects_are_preserved_and_share_one_transform():
    data = observed()
    data["objects"][0]["bbox"] = [.05, .1, .25, .9]
    data["objects"].append({**deepcopy(data["objects"][0]), "object_id": "object2", "bbox": [.75, .1, .95, .9]})
    scene = ObservedScene.model_validate(data)
    board, _ = solve_layout(CompositionIntent(focus_object_id="object1", diagnosis="保留两座建筑",
        placement="right", subject_scale="larger"), scene, 1.5, advice().proposals[0])
    assert {l.source_object_id for l in board.layers if l.role == "main"} == {"object1", "object2"}
    a, b = board.layers
    assert a.bbox[2] < b.bbox[0]
    sx = (a.bbox[2]-a.bbox[0])/.2
    assert b.bbox[0]-a.bbox[0] == pytest.approx(.7*sx)
    assert any("限制放大或偏移" in note for note in board.limitations)


def test_background_is_clipped_as_open_lines_not_repositioned_or_given_new_fill():
    data = observed()
    data["objects"].append({**deepcopy(data["objects"][0]), "object_id": "object2",
                            "role": "background", "bbox": [0, 0, 1, 1]})
    scene = ObservedScene.model_validate(data)
    board, _ = solve_layout(CompositionIntent(focus_object_id="object1", diagnosis="突出主体",
        subject_scale="larger", placement="left"), scene, 1.5, advice().proposals[0])
    context = next(l for l in board.layers if l.source_object_id == "object2")
    assert context.representation == "context_lines" and context.outline == []
    assert all(0 <= n <= 1 for path in context.details for point in path for n in point)


def test_no_fabricated_target_without_a_real_main_reference():
    scene = ObservedScene.model_validate(observed())
    with pytest.raises(ValueError, match="unknown_focus"):
        solve_layout(CompositionIntent(focus_object_id="object2", diagnosis="主体突出"), scene, 1.5, advice().proposals[0])
    with pytest.raises(ValidationError):
        CompositionIntent(focus_object_id="object1", diagnosis="   ")
    with pytest.raises(ValidationError):
        CompositionIntent(focus_object_id="object1", diagnosis="主体突出", placement="invented")


def test_conservative_defaults_are_allowed_but_missing_focus_never_guessed():
    plan = CompositionIntent(focus_object_id="object1", diagnosis="保持主体完整")
    assert plan.placement == plan.subject_scale == plan.aspect == "keep"
    with pytest.raises(ValidationError):
        CompositionIntent(diagnosis="保持主体完整")


@pytest.mark.parametrize('direction,factor', [('larger', 1.7), ('smaller', .65)])
def test_explicit_scale_changes_are_visible_without_moving_objects_independently(direction, factor):
    data = observed()
    data['objects'][0]['bbox'] = [.4, .4, .6, .6]
    scene = ObservedScene.model_validate(data)
    plan = CompositionIntent(focus_object_id='object1', diagnosis='调整主体占比',
                             subject_scale=direction, aspect='square')
    board, _ = solve_layout(plan, scene, 1., advice().proposals[0])
    target = board.layers[0]
    assert target.bbox[2]-target.bbox[0] == pytest.approx(.2*factor)
    assert target.bbox[3]-target.bbox[1] == pytest.approx(.2*factor)
    assert target.outline == scene.objects[0].outline
    assert min(target.bbox[:2]) >= .04
    assert max(target.bbox[2:]) <= .96


def test_keep_four_thirds_is_source_reference_not_a_new_recommendation():
    from camera_assistant.services.layout_presentation import measure_layout
    scene = ObservedScene.model_validate(observed())
    board, _ = solve_layout(CompositionIntent(focus_object_id='object1', diagnosis='检查主体边缘'),
                            scene, 4/3, advice().proposals[0])
    assert board.layout_mode == 'source_preserving'
    assert board.layers[0].bbox == pytest.approx(scene.objects[0].bbox)
    assert board.target_frame == board.observed_frame == [0, 0, 1, 1]
    metrics = measure_layout((1, 1, 0, 0), 4/3, 4/3, scene.objects[0].bbox)
    assert metrics.near_identity
    assert metrics.scale == metrics.frame_center == metrics.subject_center == metrics.subject_area == 0
    assert not metrics.aspect_changed


def test_keep_three_to_two_does_not_mistake_canvas_padding_for_an_aspect_change():
    scene = ObservedScene.model_validate(observed())
    board, _ = solve_layout(CompositionIntent(focus_object_id='object1', diagnosis='核对原取景'),
                            scene, 1.5, advice().proposals[0])
    assert board.layout_mode == 'source_preserving'
    assert board.target_frame == [0, 0, 1, 1]


def test_explicit_aspect_change_still_keeps_recommendation():
    scene = ObservedScene.model_validate(observed())
    board, _ = solve_layout(CompositionIntent(focus_object_id='object1', diagnosis='横向重取景',aspect='landscape'),
                            scene, 1.5, advice().proposals[0])
    assert board.layout_mode == 'schematic'


@pytest.mark.parametrize('transform,expected', [
    ((1.03, 1.03, -.015, -.015), 'source_preserving'),
    ((1, 1, .02, 0), 'source_preserving'),
    ((1, 1, -.12, 0), 'schematic'),
    ((1.25, 1.25, -.125, -.125), 'schematic'),
])
def test_shared_thresholds_measure_actual_changes(transform, expected):
    from camera_assistant.services.layout_presentation import classify_layout
    scene = ObservedScene.model_validate(observed())
    mode, metrics = classify_layout(scene, 4/3, 4/3, transform, scene.objects[0].bbox)
    assert mode == expected
    assert metrics.near_identity == (expected == 'source_preserving')


@pytest.mark.parametrize('placement,scale', [('left', 'keep'), ('keep', 'larger')])
def test_visible_changes_keep_schematic(placement, scale):
    scene = ObservedScene.model_validate(observed())
    board, _ = solve_layout(CompositionIntent(focus_object_id='object1', diagnosis='突出主体',
        placement=placement, subject_scale=scale), scene, 4/3, advice().proposals[0])
    assert board.layout_mode == 'schematic'
    assert board.target_frame is None


def test_clipped_subject_has_target_frame_but_no_outside_geometry():
    from camera_assistant.services.photo_boundary import boundary_evidence
    data = observed()
    obj = data['objects'][0]
    obj['bbox'] = [.3, .1, .9, 479/480]
    obj['photo_boundary'] = boundary_evidence(obj['outline'], obj['bbox'], 720, 480)
    scene = ObservedScene.model_validate(data)
    board, _ = solve_layout(CompositionIntent(focus_object_id='object1', diagnosis='拍完整主体',
        placement='left', subject_scale='larger'), scene, 4/3, advice().proposals[0])
    assert board.layout_mode == 'source_preserving'
    assert board.target_frame[3] == 1.08
    assert len(board.layers) == len(scene.objects)
    assert board.layers[0].bbox == pytest.approx(obj['bbox'])
    assert board.layers[0].outline == obj['outline']
    assert board.layers[0].photo_boundary == scene.objects[0].photo_boundary
    assert '后退' in board.distance_instruction and '未知' in board.distance_instruction


def test_real_crop_keeps_crop_projection_with_a_shared_transform():
    scene = ObservedScene.model_validate(observed())
    proposal = advice(action='crop', crop=[.25, 0, .75, 1]).proposals[0]
    board, _ = solve_layout(CompositionIntent(focus_object_id='object1', diagnosis='竖幅取景'),
                            scene, 1.5, proposal)
    assert board.layout_mode == 'crop_projection' and board.aspect == 'portrait'
    assert board.layers[0].bbox == pytest.approx([.3, .1, .5, .9])
    assert board.target_frame is None


def test_old_board_without_optional_frame_still_validates():
    from camera_assistant.composition_models import TargetBoard
    data = advice().proposals[0].storyboard.model_dump(exclude={'target_frame'})
    restored = TargetBoard.model_validate(data)
    assert restored.target_frame is None


@pytest.mark.parametrize('frame', [[0, 0, float('nan'), 1], [0, 0, 2, 1], [True, 0, 1, 1],
                                 [.8, 0, .2, 1], [0, 1], ['0', 0, 1, 1]])
def test_target_frame_rejects_invalid_coordinates(frame):
    from camera_assistant.composition_models import TargetBoard
    data = advice().proposals[0].storyboard.model_dump()
    with pytest.raises(ValidationError):
        TargetBoard.model_validate({**data, 'target_frame': frame})
