"""Diagnostics never echo remote inputs, secrets or image base64."""

from test_observed_composition import observed

from camera_assistant.services.composition_replay import ReplayRecord, validation_fields
from camera_assistant.services.observed_composition import observation_failure
from camera_assistant.services.pixel_contours import observed_metadata
import pytest


def test_invalid_enum_and_missing_fields_have_safe_distinct_codes():
    for field, value, code in [('role', 'SECRET_remote_value', 'recognition_illegal_enum'),
                               ('evidence_photo_ids', None, 'recognition_missing_field')]:
        data = observed()
        if value is None:
            del data['objects'][0][field]
        else:
            data['objects'][0][field] = value
        try:
            observed_metadata(data)
        except ValueError as error:
            assert observation_failure(error)[0] == code
            rows = validation_fields(error)
            assert rows[0]['field_path'] == f'objects.0.{field}'
            assert 'SECRET_remote_value' not in str(rows)
            assert 'input' not in str(rows)
        else:
            raise AssertionError('invalid metadata accepted')


def test_replay_disabled_by_default_does_not_write(monkeypatch):
    monkeypatch.delenv('CAMERA_AI_COMPOSITION_REPLAY', raising=False)
    record = ReplayRecord(None)
    record.update(stage='recognition', code='recognition_invalid')
    assert record.path is None


@pytest.mark.parametrize('box', [[10, 20, 600, 800], [.8, .2, .1, .9],
    [0, 0, .001, .8], ['0', 0, 1, 1], [False, 0, 1, 1], [[0, 0], [1, 1]]])
def test_invalid_boxes_get_specific_safe_repair_without_weakening_validation(box):
    from camera_assistant.services.observed_composition import observation_repair_hint, prepare_observation
    data = observed()
    data['objects'][0]['bbox'] = box
    data['objects'][0]['label'] = 'SECRET_LABEL_MUST_NOT_LEAK'
    with pytest.raises(ValueError) as failure:
        prepare_observation(data)
    assert observation_failure(failure.value)[0] == 'recognition_bbox_invalid'
    hint = observation_repair_hint(failure.value)
    for rule in ('[x1,y1,x2,y2]', '0.005', '字符串', '像素', '不机械交换'):
        assert rule in hint
    assert 'SECRET_LABEL' not in hint
    assert data['objects'][0]['bbox'] == box


def test_invalid_continuous_relation_records_safe_inputs_and_specific_repair():
    from camera_assistant.services.observed_composition import observation_repair_hint
    data = observed()
    data['scene_mode'] = 'continuous'
    data['objects'][0].update(kind='mountain', mobility='unknown')
    data['api_key'] = 'SECRET_SHOULD_NOT_RECORD'
    record = ReplayRecord(None)
    record.observation(data, 1)
    snapshot = record.value['observations'][0]
    assert snapshot['objects'][0]['mobility'] == 'unknown'
    assert snapshot['objects'][0]['kind'] == 'mountain'
    assert 'SECRET_SHOULD_NOT_RECORD' not in str(record.value)
    del data['api_key']
    try:
        observed_metadata(data)
    except ValueError as error:
        hint = observation_repair_hint(error)
        assert 'mobility=fixed' in hint and 'mountain' in hint
        assert '不改变' in hint
    else:
        raise AssertionError('invalid relation accepted')
