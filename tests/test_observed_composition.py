"""Route tests use explicit fixtures, never spend model credits or claim fidelity."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from camera_assistant.composition_models import CompositionAdvice, ObservedScene
from camera_assistant.models import ExifInfo, ImageInspection, ImageMetrics
from camera_assistant.services import observed_composition as service
from camera_assistant.services.cloud import ModelServiceError


def observed():
    return {"objects": [{
        "object_id": "object1", "label": "细长塔楼", "kind": "building", "role": "main",
        "depth": 2, "bbox": [.4, .1, .5, .9], "mobility": "fixed",
        "outline": [[0, .15], [.5, 0], [1, .15], [1, 1], [0, 1]],
        "details": [[[.2, .3], [.8, .3]], [[.3, .3], [.3, .95]]],
        "identity_features": ["尖顶", "纵向立柱"], "evidence_photo_ids": ["photo1"],
    }], "limitations": ["遮挡部分未恢复"]}


def advice(ids=("object1",), action="reshoot", crop=None):
    return CompositionAdvice.model_validate({"status": "unverified", "proposals": [{
        "action_type": action, "goal": "突出塔楼", "actions": ["调整取景并检查主体占比"],
        "reasons": ["突出纵向结构"], "conditions": ["允许重新取景"],
        "tradeoffs": ["减少背景"], "limitations": ["需试拍"], "crop_bbox": crop,
        "storyboard": {"aspect": "portrait", "reference_photo_id": "photo1", "intent": "竖幅突出主体",
                       "distance_relation": "similar", "distance_instruction": "保持相近距离检查取景",
                       "layers": [{"source_object_id": obj, "label": "不应覆盖真实名称", "kind": "object",
                                   "role": "main" if i == 0 else "prop", "depth": 9,
                                   "bbox": [.1, .1, .9, .9], "outline": [[0, 0], [1, 0], [1, 1], [0, 1]],
                                   "evidence_photo_ids": ["photo1"]} for i, obj in enumerate(ids)],
                       "changes": [{"problem": "主体不突出", "adjustment": "竖幅取景", "benefit": "强调线条"}],
                       "limitations": ["目标布局需实拍核对"]},
    }]})


@pytest.fixture
def inspection():
    return ImageInspection(exif=ExifInfo(), model_image_data_url="data:image/jpeg;base64,TEST",
                           metrics=ImageMetrics(width=1200, height=800, mean_brightness=.5,
                                                contrast=.2, shadow_ratio=.1,
                                                highlight_ratio=.1, sharpness_score=5))


def test_shapes_are_frozen_and_physical_aspect_is_preserved(inspection):
    scene = ObservedScene.model_validate(observed())
    original = advice()
    before = original.model_dump()
    result = service.apply_observed_layout(original, scene, inspection)
    board = result.proposals[0].storyboard
    layer = board.layers[0]
    assert layer.label == "细长塔楼" and layer.kind == "building"
    assert layer.outline == scene.objects[0].outline
    assert layer.details == scene.objects[0].details
    assert layer.identity_features == scene.objects[0].identity_features
    assert layer.source_bbox == scene.objects[0].bbox
    assert layer.depth == 2 and layer.mobility == "fixed"
    assert layer.certainty == "approximate"
    x1, y1, x2, y2 = layer.bbox
    assert (x2-x1)*.75/(y2-y1) == pytest.approx(.1*1.5/.8)
    assert board.render_basis == "source_geometry"
    assert board.source_photo_aspect == 1.5
    assert original.model_dump() == before


@pytest.mark.parametrize("ids", [("object2",), ("object1", "object1"), (None,)])
def test_unknown_duplicate_or_missing_ids_never_publish_placeholder(ids, inspection):
    result = service.apply_observed_layout(advice(ids), ObservedScene.model_validate(observed()), inspection)
    assert result.proposals[0].storyboard is None
    assert result.proposals[0].actions and result.notes


def test_observation_failure_keeps_text_without_legacy_redrawing(inspection):
    result = service.apply_observed_layout(advice(), None, inspection)
    assert result.proposals[0].storyboard is None
    assert service.SOURCE_FAILURE in result.notes


def test_crop_uses_one_transform_not_independent_object_placement(inspection):
    crop = [.25, 0, .75, 1]  # 1200*.5 / 800 = portrait .75
    result = service.apply_observed_layout(advice(action="crop", crop=crop),
                                          ObservedScene.model_validate(observed()), inspection)
    board = result.proposals[0].storyboard
    assert board.layout_mode == "crop_projection"
    assert board.layers[0].bbox == pytest.approx([.3, .1, .5, .9])


@pytest.mark.parametrize("crop", [None, [.45, 0, .95, 1], [.2, .1, .8, .9]])
def test_missing_cut_subject_or_wrong_aspect_crop_is_not_drawn(crop, inspection):
    result = service.apply_observed_layout(advice(action="crop", crop=crop),
                                          ObservedScene.model_validate(observed()), inspection)
    assert result.proposals[0].storyboard is None


def test_missing_second_main_cannot_silently_disappear(inspection):
    data = observed()
    data["objects"].append({**data["objects"][0], "object_id": "object2", "bbox": [.6, .1, .7, .9]})
    result = service.apply_observed_layout(advice(), ObservedScene.model_validate(data), inspection)
    assert result.proposals[0].storyboard is None


def test_cannot_demote_main_to_a_prop(inspection):
    scene = ObservedScene.model_validate(observed())
    value = advice()
    value.proposals[0].storyboard.layers[0].role = "prop"
    assert service.apply_observed_layout(value, scene, inspection).proposals[0].storyboard is None


def test_cannot_reverse_fixed_buildings(inspection):
    data = observed()
    data["objects"][0]["bbox"] = [.1, .1, .2, .9]
    data["objects"].append({**data["objects"][0], "object_id": "object2", "role": "prop", "bbox": [.8, .1, .9, .9]})
    value = advice(("object1", "object2"))
    value.proposals[0].storyboard.layers[0].bbox = [.8, .1, .99, .9]
    value.proposals[0].storyboard.layers[1].bbox = [.01, .1, .2, .9]
    result = service.apply_observed_layout(value, ObservedScene.model_validate(data), inspection)
    assert result.proposals[0].storyboard is None


def test_source_reference_cannot_be_replaced_by_another_view(inspection):
    value = advice()
    value.proposals[0].storyboard.reference_photo_id = "photo2"
    result = service.apply_observed_layout(value, ObservedScene.model_validate(observed()), inspection)
    assert result.proposals[0].storyboard is None


def test_catalog_does_not_ask_planner_to_redraw_shapes():
    catalog = service.object_catalog(ObservedScene.model_validate(observed()))
    assert catalog[0]["object_id"] == "object1" and "bbox" in catalog[0]
    assert "outline" not in catalog[0] and "details" not in catalog[0]
    assert service.object_catalog(None) == []


@pytest.mark.parametrize("included", [False, True])
def test_environment_is_kept_even_when_planner_omits_it(included, inspection):
    data = observed()
    data["objects"].append({**data["objects"][0], "object_id": "object2", "label": "背景横梁",
        "role": "background", "depth": 0, "bbox": [.3, .2, .7, .7],
        "representation": "context_lines", "outline": [], "details": [[[0, .5], [1, .5]]]})
    scene = ObservedScene.model_validate(data)
    value = advice(("object1", "object2") if included else ("object1",))
    result = service.apply_observed_layout(value, scene, inspection)
    board = result.proposals[0].storyboard
    assert board and len(board.layers) == 2
    context = next(layer for layer in board.layers if layer.source_object_id == "object2")
    assert context.representation == "context_lines" and context.role == "background"
    assert context.source_details == scene.objects[1].details
    # Planner's proposed independent object2 box does not own the background.
    main = board.layers[0]
    sx = (main.bbox[2]-main.bbox[0])/.1
    expected_center = main.bbox[0]+(.5-.4)*sx
    assert (context.bbox[0]+context.bbox[2])/2 == pytest.approx(expected_center)


def test_unselected_companion_silhouette_is_not_silently_erased(inspection):
    data = observed()
    data["objects"].append({**data["objects"][0], "object_id": "object2", "role": "foreground",
                            "bbox": [.3, .2, .38, .7]})
    result = service.apply_observed_layout(advice(), ObservedScene.model_validate(data), inspection)
    board = result.proposals[0].storyboard
    assert board and len(board.layers) == 2
    assert board.layers[1].representation == "context_lines" and board.layers[1].details


def test_crop_clips_partial_background_without_rejecting_complete_main(inspection):
    data = observed()
    data["objects"].append({**data["objects"][0], "object_id": "object2", "role": "background",
        "bbox": [0, 0, 1, 1], "representation": "context_lines", "outline": [],
        "details": [[[0, .5], [1, .5]]]})
    result = service.apply_observed_layout(advice(action="crop", crop=[.25, 0, .75, 1]),
                                          ObservedScene.model_validate(data), inspection)
    board = result.proposals[0].storyboard
    assert board and len(board.layers) == 2
    context = board.layers[1]
    assert context.bbox[0] == 0 and context.bbox[2] == 1
    assert context.source_details == [[[0, .5], [1, .5]]]


@pytest.mark.parametrize("mutation", ["duplicate", "crossing", "bad_bbox", "wrong_photo"])
def test_source_scene_validates_evidence_and_geometry(mutation):
    data = observed()
    if mutation == "duplicate":
        data["objects"].append(deepcopy(data["objects"][0]))
    elif mutation == "crossing":
        data["objects"][0]["outline"] = [[0, 0], [1, 1], [0, 1], [1, .4], [.8, 0]]
    elif mutation == "bad_bbox":
        data["objects"][0]["bbox"] = [False, 0, 1, 1]
    else:
        data["objects"][0]["evidence_photo_ids"] = ["photo2"]
    with pytest.raises(ValidationError):
        ObservedScene.model_validate(data)


def test_source_observation_uses_vision_and_does_not_retry_transport(monkeypatch, inspection):
    from camera_assistant.config import Settings
    settings = Settings(demo_mode=False, api_key="test", base_url="https://example.invalid/v1",
                        vision_model="test-vision", text_model="text-only", timeout_seconds=5,
                        max_image_mb=15, knowledge_dir=Path("knowledge"), max_output_tokens=2048)
    calls = []
    def fake(config, payload):
        assert payload["model"] == "test-vision"
        assert config.format_retry_count == 0 and payload["max_tokens"] == 2048
        calls.append(payload)
        return observed()
    monkeypatch.setattr(service, "request_json", fake)
    monkeypatch.setattr(service, "trace_observed_scene", lambda answer, _: service.parse_observed_scene(answer))
    assert service.observe_objects(settings, inspection, {})
    assert len(calls) == 1
    def failure(*_):
        calls.append(None)
        raise ModelServiceError("请求失败")
    monkeypatch.setattr(service, "request_json", failure)
    assert service.observe_objects(settings, inspection, {}) is None
    assert len(calls) == 2


def test_integer_drawing_sheet_is_converted_before_schema_validation():
    data = observed()
    geometry = data["objects"][0]
    geometry["outline"] = [[round(x*1000), round(y*1000)] for x, y in geometry["outline"]]
    geometry["details"] = [[[round(x*1000), round(y*1000)] for x, y in path] for path in geometry["details"]]
    scene = service.parse_observed_scene(data)
    assert scene.objects[0].outline == observed()["objects"][0]["outline"]
    assert scene.objects[0].bbox == geometry["bbox"]
    geometry["outline"][0][0] = .5
    with pytest.raises(ValueError, match="混用"):
        service.parse_observed_scene(data)


@pytest.mark.parametrize("value", [True, "500", 1001, -1])
def test_invalid_source_sheet_cannot_be_silently_coerced(value):
    data = observed()
    data["objects"][0]["outline"][0][0] = value
    with pytest.raises((ValueError, TypeError)):
        service.parse_observed_scene(data)


def test_structural_repair_is_bounded_and_feedback_does_not_echo_raw_validation(monkeypatch, inspection):
    from camera_assistant.config import Settings
    settings = Settings(demo_mode=False, api_key="test", base_url="https://example.invalid/v1",
                        vision_model="vision", text_model="text", timeout_seconds=5,
                        max_image_mb=15, knowledge_dir=Path("knowledge"))
    calls = []
    def fake(config, payload):
        calls.append(len(payload["messages"]))
        if len(calls) == 1:
            data = observed()
            data["objects"][0]["bbox"] = [38, 11, 687, 254]
            return data
        message = payload["messages"][-1]["content"]
        assert "bbox" in message and "687" not in message
        return observed()
    monkeypatch.setattr(service, "request_json", fake)
    monkeypatch.setattr(service, "trace_observed_scene", lambda answer, _: service.parse_observed_scene(answer))
    assert service.observe_objects(settings, inspection, {}) is not None
    assert calls == [1, 3]
    calls.clear()
    monkeypatch.setattr(service, "request_json", lambda *args: calls.append(1) or {"objects": []})
    assert service.observe_objects(settings, inspection, {}) is None
    assert calls == [1, 1]


def test_chinese_subject_kind_cannot_bypass_complex_shape_guard():
    data = observed()
    data["objects"][0]["kind"] = "动物"
    with pytest.raises(ValueError, match="过度简化"):
        service.parse_observed_scene(data)


def test_observation_failure_reports_stage_without_exposing_remote_data(monkeypatch, inspection):
    from camera_assistant.config import Settings
    settings = Settings(demo_mode=False, api_key="test", base_url="https://example.invalid/v1",
                        vision_model="vision", text_model="text", timeout_seconds=5,
                        max_image_mb=15, knowledge_dir=Path("knowledge"))
    issues = []
    monkeypatch.setattr(service, "request_json", lambda *_: observed())
    def bad_contour(*_):
        raise ValueError("private-image-or-provider-content")
    monkeypatch.setattr(service, "trace_observed_scene", bad_contour)
    assert service.observe_objects(settings, inspection, {}, issues) is None
    assert len(issues) == 1 and "主要主体轮廓" in issues[0]
    assert "private" not in issues[0]
