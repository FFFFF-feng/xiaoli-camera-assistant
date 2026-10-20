"""Exercise the new live contract through the advisor with controlled upstream failures."""
from copy import deepcopy
from math import cos, pi, sin
from pathlib import Path

import pytest
import test_composition_advisor as fixtures
from test_composition_advisor import proposal, response
from test_observed_composition import observed

from camera_assistant.services import composition, observed_composition
from camera_assistant.services.cloud import ModelServiceError
from camera_assistant.composition_models import ObservedScene, TargetLayer
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase
from camera_assistant.services.phone_knowledge import PhoneKnowledgeBase

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
    metadata = observed()
    # This fixture uses GLM-4.6V: successful wire metadata uses its explicit
    # 0..1000 protocol before the independent contour failure is exercised.
    for obj in metadata['objects']:
        obj['bbox'] = [round(n*1000) for n in obj['bbox']]
    monkeypatch.setattr(observed_composition, "request_json", lambda *_: metadata)
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


@pytest.mark.parametrize('device', ['generic_phone', 'known_phone', 'canon_70d'])
def test_device_selection_keeps_valid_composition_with_maximum_environment_outline(inputs, monkeypatch, device):
    root = Path(__file__).resolve().parents[1]
    inspection, request, scene, camera, settings = inputs
    if device == 'canon_70d':
        camera = CameraKnowledgeBase(root/'knowledge/cameras/camera_profiles.yaml').resolve('Canon EOS 70D', 'APS-C')
        request = request.model_copy(update={'device_type': 'camera', 'camera_profile_id': camera.profile_id,
            'focal_length_mm': 60, 'max_aperture': 5.6})
    else:
        phones = PhoneKnowledgeBase(root/'knowledge/devices/phone_profiles.yaml')
        camera = (phones.resolve('generic_phone') if device == 'generic_phone' else
                  next(p for p in phones.list_profiles() if not p.profile_id.startswith('generic_')))
        request = request.model_copy(update={'device_type': 'phone', 'phone_profile_id': camera.profile_id})
    data = observed()
    data['objects'].append({**deepcopy(data['objects'][0]), 'object_id': 'object2', 'role': 'background',
        'bbox': [0, 0, 1, 1], 'outline': [[.5+.4*cos(i*pi/32), .5+.4*sin(i*pi/32)] for i in range(64)]})
    source = ObservedScene.model_validate(data)
    monkeypatch.setattr(composition, 'observe_objects', lambda *_: source)
    calls = []
    def provider(*_):
        calls.append(True)
        return {'proposals': [{**proposal(), 'composition_intent': {
            'focus_object_id': 'object1', 'diagnosis': '突出主体', 'placement': 'left', 'subject_scale': 'larger'}}]}
    monkeypatch.setattr(composition, 'request_json', provider)
    result = run((inspection, request, scene, camera, settings))
    board = result.proposals[0].storyboard
    assert board and len(board.layers) == 2 and board.layout_engine == 'local_v1'
    assert board.layers[0].source_object_id == 'object1'
    assert all(len(path) <= 64 for path in board.layers[1].source_details)
    assert not any(d.status == 'failed' for d in result.diagnostics)
    assert len(calls) == 1


@pytest.mark.parametrize('failure,code,field', [
    ('unknown_focus', 'layout_focus_unavailable', None),
    ('invalid_photo_aspect', 'layout_photo_invalid', None),
    ('main_subjects_too_small', 'layout_subjects_too_small', None),
    ('private-input-value', 'layout_invalid_data', None),
    ('geometry', 'layout_geometry_invalid', 'bbox'),
])
def test_layout_failure_retains_specific_bounded_diagnostic_without_retry(inputs, monkeypatch, failure, code, field):
    setup_source(monkeypatch)
    calls = []
    def provider(*_):
        calls.append(True)
        return {'proposals': [{**proposal(), 'composition_intent': {
            'focus_object_id': 'object1', 'diagnosis': '突出主体'}}]}
    def fail_layout(*_):
        if failure == 'geometry':
            TargetLayer.model_validate({**observed()['objects'][0], 'bbox': 'private-input-value'})
        raise ValueError(failure)
    monkeypatch.setattr(composition, 'request_json', provider)
    monkeypatch.setattr(composition, 'solve_layout', fail_layout)
    result = run(inputs)
    diagnostic = next(d for d in result.diagnostics if d.stage == 'layout' and d.status == 'failed')
    assert diagnostic.code == code and diagnostic.field_path == field
    assert result.proposals[0].actions and result.proposals[0].storyboard is None
    assert 'private-input-value' not in result.model_dump_json()
    assert len(calls) == 1
