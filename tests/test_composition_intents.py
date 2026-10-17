"""Exercise the new live contract through the advisor with controlled upstream failures."""
from copy import deepcopy

import pytest
import test_composition_advisor as fixtures
from test_composition_advisor import proposal, response
from test_observed_composition import observed

from camera_assistant.services import composition, observed_composition
from camera_assistant.services.cloud import ModelServiceError

inputs = fixtures.inputs


def setup_source(monkeypatch):
    source = observed_composition.parse_observed_scene(observed())
    monkeypatch.setattr(composition, "observe_objects", lambda *_: source)
    return source


def run(inputs):
    inspection, request, scene, camera, settings = inputs
    return composition.OpenAICompatibleCompositionAdvisor(settings).recommend(inspection, request, scene, None, [], camera)


def test_minimal_intent_without_provider_geometry_produces_a_grounded_target(inputs, monkeypatch):
    setup_source(monkeypatch)
    value = {"proposals": [{**proposal(), "composition_intent": {
        "focus_object_id": "object1", "diagnosis": "突出细长建筑", "placement": "left", "subject_scale": "larger"}}]}
    monkeypatch.setattr(composition, "request_json", lambda *_: deepcopy(value))
    result = run(inputs)
    assert result.proposals[0].storyboard.layout_engine == "local_v1"
    assert result.proposals[0].framing_plan.diagnosis == "突出细长建筑"
    assert [d.status for d in result.diagnostics] == ["complete"]*4
    assert len(result.trace_id) == 32
    assert "unknown" == result.proposals[0].storyboard.distance_relation


@pytest.mark.parametrize("plan", [None, {"diagnosis": "缺少主体"},
    {"focus_object_id": "object1", "diagnosis": "主体突出", "placement": "bad"},
    {"focus_object_id": "object2", "diagnosis": "引用了未观察主体"}])
def test_bad_or_absent_intent_preserves_text_and_never_generates_a_placeholder(inputs, monkeypatch, plan):
    setup_source(monkeypatch)
    monkeypatch.setattr(composition, "request_json", lambda *_: response([{**proposal(), "composition_intent": plan}]))
    result = run(inputs)
    assert result.proposals[0].actions and result.proposals[0].storyboard is None
    assert any(d.status != "complete" for d in result.diagnostics if d.stage == "layout")


def test_intent_timeout_has_one_call_and_a_fixed_diagnostic(inputs, monkeypatch):
    setup_source(monkeypatch)
    calls = []
    def timeout(*_):
        calls.append(True)
        raise ModelServiceError("模型服务超时")
    monkeypatch.setattr(composition, "request_json", timeout)
    result = run(inputs)
    assert len(calls) == 1 and result.status == "unavailable"
    assert any(d.code == "intent_service_failed" for d in result.diagnostics)


def test_observation_service_and_pixel_failures_have_distinct_diagnostics(inputs, monkeypatch):
    monkeypatch.setattr(composition, "request_json", lambda *_: response([proposal()]))
    monkeypatch.setattr(observed_composition, "request_json", lambda *_: (_ for _ in ()).throw(ModelServiceError("模型服务超时")))
    first = run(inputs)
    assert any(d.stage == "recognition" and d.status == "failed" for d in first.diagnostics)
    monkeypatch.setattr(observed_composition, "request_json", lambda *_: observed())
    monkeypatch.setattr(observed_composition, "trace_observed_scene", lambda *_: (_ for _ in ()).throw(ValueError("private failure")))
    second = run(inputs)
    assert any(d.stage == "recognition" and d.status == "complete" for d in second.diagnostics)
    assert any(d.stage == "contours" and d.status == "failed" for d in second.diagnostics)
    assert "private failure" not in second.model_dump_json()


def test_invalid_optional_parts_are_omitted_without_changing_the_parent_or_leaking_values():
    metadata = observed()
    metadata["objects"][0]["kind"] = "flower"
    metadata["objects"][0]["parts"] = [{"label": "private-flower", "kind": "flower", "bbox": [.01, .01, .2, .2]}]
    prepared = observed_composition.prepare_observation(metadata)
    result = observed_composition.observed_metadata(prepared)
    assert result.objects[0].bbox == metadata["objects"][0]["bbox"]
    assert result.objects[0].parts == []
    assert any("可选分部的位置无效" in note for note in result.limitations)
    assert "private-flower" not in result.model_dump_json()
    assert metadata["objects"][0]["parts"]  # Input is not mutated.


def test_invalid_main_box_is_not_repaired_or_silently_accepted(inputs, monkeypatch):
    metadata = observed()
    metadata["objects"][0]["bbox"] = [.8, .2, .1, .9]
    monkeypatch.setattr(composition, "request_json", lambda *_: response([proposal()]))
    calls = []
    def source_reply(*_):
        calls.append(True)
        return metadata
    monkeypatch.setattr(observed_composition, "request_json", source_reply)
    result = run(inputs)
    assert len(calls) == 2
    assert any(d.code == "recognition_bbox_invalid" for d in result.diagnostics)
    assert any("物体位置字段不符合要求" in note for note in result.notes)


def test_observation_color_is_local_and_invalid_root_data_is_not_rewritten():
    metadata = observed()
    metadata["objects"][0]["color"] = "white"
    prepared = observed_composition.prepare_observation(metadata)
    assert observed_composition.observed_metadata(prepared).objects[0].color == "slate"
    metadata["limitations"] = "not-a-list"
    invalid = observed_composition.prepare_observation(metadata)
    assert invalid["limitations"] == "not-a-list"
    with pytest.raises(ValueError):
        observed_composition.observed_metadata(invalid)
