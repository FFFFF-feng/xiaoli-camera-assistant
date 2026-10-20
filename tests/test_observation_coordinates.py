"""Explicit model-coordinate contracts, including the real forest failure boxes."""
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
import test_observed_composition as fixtures

from camera_assistant.config import Settings
from camera_assistant.services import observed_composition as service
from camera_assistant.services.composition_replay import validation_fields
from camera_assistant.services.composition_trace import observe_diagnostics
from camera_assistant.services.observation_coordinates import (
    ObservationCoordinateError,
    ObservationCoordinates,
    observation_coordinates,
)

observed = fixtures.observed
inspection = fixtures.inspection


def settings(model='glm-4.6v', unit='model_default'):
    return Settings(demo_mode=False, api_key='test', base_url='https://example.invalid/v1',
                    vision_model=model, text_model='text', timeout_seconds=5,
                    max_image_mb=15, knowledge_dir=Path('knowledge'), observation_coordinate_unit=unit)


def wire_scene():
    data = observed()
    data['coordinate_unit'] = 'normalized_0_1000'
    for obj in data['objects']:
        obj['bbox'] = [round(n*1000) for n in obj['bbox']]
    return data


@pytest.mark.parametrize('model', ['glm-4.6v', 'GLM-4.6V-Flash', 'glm-4.5v',
                                 'zai-org/GLM-4.1V-9B-Thinking'])
def test_documented_glm_models_use_explicit_thousand_units(model):
    assert observation_coordinates(settings(model)).unit == 'normalized_0_1000'


@pytest.mark.parametrize('model', ['manual', 'vision', 'glm-5v-turbo', 'not-glm-4.6v'])
def test_unknown_models_keep_legacy_contract_even_with_glm_preset(model):
    value = replace(settings(model), preset='glm-dino')
    assert observation_coordinates(value).unit == 'normalized_0_1'
    with pytest.raises(ObservationCoordinateError):
        observation_coordinates(value).normalize_box([0, 440, 920, 999], 'objects.0.bbox')


def test_override_and_config_validation(monkeypatch):
    assert observation_coordinates(settings(unit='normalized_0_1')).scale == 1
    assert observation_coordinates(settings('manual', 'normalized_0_1000')).scale == 1000
    with pytest.raises(ValueError, match='COORDINATE_UNIT'):
        settings(unit='pixels')
    with pytest.raises(ValueError):
        ObservationCoordinates('auto')
    # No key vault, cloud call, private config or .env mutation for this test.
    from camera_assistant import config
    monkeypatch.setattr(config, 'load_dotenv', lambda *_: None)
    monkeypatch.setenv('APP_DEMO_MODE', 'true')
    monkeypatch.setenv('CAMERA_AI_PRESET', 'custom')
    monkeypatch.setenv('CAMERA_AI_OBSERVATION_COORDINATE_UNIT', 'normalized_0_1000')
    assert Settings.from_env().observation_coordinate_unit == 'normalized_0_1000'


@pytest.mark.parametrize('box,expected', [
    ([0, 440, 920, 999], [0, .44, .92, .999]),
    ([0, 0, 999, 470], [0, 0, .999, .47]),
    ([440, 730, 999, 999], [.44, .73, .999, .999]),
    ([0, 0, 1000, 1000], [0, 0, 1, 1]),
])
def test_real_failure_boxes_and_full_frame_convert_once_without_pixel_dimensions(box, expected):
    # These are the actual numeric bboxes from the authorized single call.
    # No fake recognition text or invented segmentation is used for this test.
    assert ObservationCoordinates('normalized_0_1000').normalize_box(box, 'objects.0.bbox') == expected


@pytest.mark.parametrize('box', [[False, 0, 900, 999], ['0', 0, 900, 999],
    [0, float('nan'), 900, 999], [0, 0, float('inf'), 999], [0, 0, 1001, 999],
    [0, 0, 10**400, 999],
    [-1, 0, 900, 999], [900, 0, 100, 999], [0, 800, 900, 20], [0, 0, 4, 999],
    [0, .44, .92, .999], [0, 440, .92, 999], [0, 0, 1, 1], [[0, 0], [900, 999]],
    [0, 0, 1280, 1920]])
def test_grid_contract_rejects_bad_mixed_normalized_or_pixel_boxes_without_guessing(box):
    before = deepcopy(box)
    with pytest.raises(ObservationCoordinateError) as failure:
        ObservationCoordinates('normalized_0_1000').normalize_box(box, 'objects.0.bbox')
    assert failure.value.code == 'recognition_bbox_invalid'
    assert validation_fields(failure.value) == [{'field_path': 'objects.0.bbox', 'type': 'value_error'}]
    # Compare representation so NaN still verifies that the input wasn't rewritten.
    assert repr(box) == repr(before)


def test_minimum_extent_is_numerically_stable_but_not_relaxed():
    data = wire_scene()
    data['objects'][0]['bbox'] = [100, 100, 105, 500]
    data['objects'] = data['objects'][:1]
    normalized = ObservationCoordinates('normalized_0_1000').normalize_answer(data)
    obj = service.observed_metadata(service.prepare_observation(normalized)).objects[0]
    assert obj.bbox == [.1, .1, .105, .5]
    assert ObservationCoordinates().normalize_box(obj.bbox, 'objects.0.bbox') == obj.bbox
    for box in ([.1, .1, .104999, .5], [100, 100, 104, 500]):
        profile = ObservationCoordinates() if box[0] == .1 else ObservationCoordinates('normalized_0_1000')
        with pytest.raises(ObservationCoordinateError):
            profile.normalize_box(box, 'objects.0.bbox')


def test_parts_use_same_photo_units_and_bad_optional_hints_are_discarded_not_reinterpreted():
    data = wire_scene()
    data['objects'][0].update(kind='flower', bbox=[100, 100, 900, 900], parts=[
        {'label': 'first', 'kind': 'flower', 'bbox': [200, 200, 400, 400]},
        {'label': 'mixed', 'kind': 'leaf', 'bbox': [.2, .2, .4, .4]},
        {'label': 'outside', 'kind': 'flower', 'bbox': [0, 0, 200, 200]},
    ])
    data['objects'] = data['objects'][:1]
    before = deepcopy(data)
    clean = ObservationCoordinates('normalized_0_1000').normalize_answer(data)
    result = service.observed_metadata(service.prepare_observation(clean))
    assert result.objects[0].bbox == [.1, .1, .9, .9]
    assert [part.bbox for part in result.objects[0].parts] == [[.2, .2, .4, .4]]
    assert any('可选分部' in note for note in result.limitations)
    assert data == before


def test_explicit_response_declaration_cannot_change_request_contract_or_double_convert():
    profile = ObservationCoordinates('normalized_0_1000')
    data = wire_scene()
    data['coordinate_unit'] = 'normalized_0_1'
    with pytest.raises(ObservationCoordinateError, match='单位') as failure:
        profile.normalize_answer(data)
    assert service.observation_failure(failure.value)[0] == 'recognition_coordinate_unit_invalid'
    normalized = profile.normalize_answer(wire_scene())
    assert 'coordinate_unit' not in normalized
    with pytest.raises(ObservationCoordinateError):
        profile.normalize_answer(normalized)


def test_live_entry_schema_prompt_parts_and_tracer_all_share_the_same_contract(monkeypatch, inspection):
    calls, traces, diagnostics = [], [], []
    answer = wire_scene()
    before = deepcopy(answer)
    def request(config, payload):
        calls.append(deepcopy(payload))
        assert config.format_retry_count == 0
        text = payload['messages'][0]['content'][0]['text']
        assert 'coordinate_unit=normalized_0_1000' in text and '宽高各至少5' in text
        schema = json.loads(text.split('输出Schema：\n')[1])
        assert schema['$defs']['ObservedObject']['properties']['bbox']['items'] == {
            'type': 'integer', 'minimum': 0, 'maximum': 1000}
        assert schema['$defs']['ObservedPart']['properties']['bbox']['items']['maximum'] == 1000
        return answer
    def trace(value, _inspection):
        traces.append(deepcopy(value))
        return service.parse_observed_scene(value)
    monkeypatch.setattr(service, 'request_json', request)
    monkeypatch.setattr(service, 'trace_observed_scene', trace)
    with observe_diagnostics(diagnostics.append):
        result = service.observe_objects(settings(), inspection, {})
    assert result and len(calls) == 1 and len(traces) == 1
    assert result.objects[0].bbox == observed()['objects'][0]['bbox']
    assert all(0 <= n <= 1 for obj in result.objects for n in obj.bbox)
    assert answer == before
    assert [row.status for row in diagnostics] == ['complete', 'complete']


def test_repair_feedback_keeps_wire_units_and_does_not_send_normalized_intermediate(monkeypatch, inspection):
    calls = []
    def request(_config, payload):
        calls.append(deepcopy(payload))
        if len(calls) == 1:
            data = wire_scene()
            data['objects'][0]['evidence_photo_ids'] = ['photo6']
            return data
        assistant = json.loads(payload['messages'][-2]['content'])
        assert assistant['objects'][0]['bbox'] == wire_scene()['objects'][0]['bbox']
        return wire_scene()
    monkeypatch.setattr(service, 'request_json', request)
    monkeypatch.setattr(service, 'trace_observed_scene', lambda value, _: service.parse_observed_scene(value))
    assert service.observe_objects(settings(), inspection, {})
    assert len(calls) == 2


def test_invalid_contract_never_reaches_contours_and_retry_count_is_unchanged(monkeypatch, inspection):
    calls, diagnostics = [], []
    def request(_config, payload):
        calls.append(deepcopy(payload))
        return observed()  # 0..1 boxes violate this request's fixed 0..1000 contract.
    monkeypatch.setattr(service, 'request_json', request)
    monkeypatch.setattr(service, 'trace_observed_scene', lambda *_: pytest.fail('invalid coordinates reached tracer'))
    with observe_diagnostics(diagnostics.append):
        assert service.observe_objects(settings(), inspection, {}) is None
    assert len(calls) == 2
    repair = calls[-1]['messages'][-1]['content']
    assert '0到1000整数xyxy' in repair and '至少5' in repair and '不机械交换' in repair
    assert diagnostics[-1].code == 'recognition_bbox_invalid'


def test_strict_internal_models_still_reject_thousand_unit_boxes():
    with pytest.raises(ValueError):
        service.prepare_observation(wire_scene())
