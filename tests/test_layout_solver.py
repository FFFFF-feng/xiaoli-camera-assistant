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
