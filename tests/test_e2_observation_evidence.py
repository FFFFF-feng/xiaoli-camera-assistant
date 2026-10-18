import base64
import json
from types import SimpleNamespace

import pytest
from test_observed_composition import advice, observed

from camera_assistant.composition_models import ObservedScene
from camera_assistant.services import composition_replay as replay
from camera_assistant.services.composition_trace import current_trace_id, observe_diagnostics
from camera_assistant.services.observation_evidence import category_adaptation, observation_summary
from camera_assistant.services.observed_composition import prepare_observation


@pytest.mark.parametrize("label,original,target", [("咖啡杯", "building", "cup"),
    ("white coffee cup", "architecture", "cup"), ("水瓶", "object", "bottle"),
    ("手持相机", "building", "camera"), ("蓝色小球", "object", "ball")])
def test_specific_names_have_traceable_generic_category_consistency(label, original, target):
    data = observed()
    data["objects"][0].update(label=label, kind=original)
    normalized = prepare_observation(data)["objects"][0]
    assert data["objects"][0]["kind"] == original
    assert normalized["kind"] == target
    assert normalized["category_adaptation"] == {"original_kind": original,
        "normalized_kind": target, "reason": "specific_label_category_consistency"}


@pytest.mark.parametrize("raw", [
    {"label": "咖啡店建筑", "kind": "building", "role": "main"},
    {"label": "杯形建筑", "kind": "building", "role": "main"},
    {"label": "细长塔楼", "kind": "building", "role": "main"},
    {"label": "咖啡杯", "kind": "background", "role": "background"},
    {"label": "cup bottle", "kind": "object", "role": "main"},
])
def test_architecture_background_and_ambiguous_names_are_not_rewritten(raw):
    assert category_adaptation(raw) is None


def test_remote_category_provenance_and_boundary_claims_are_discarded():
    data = observed()
    data["objects"][0].update(category_adaptation={"original_kind": "forged"}, photo_boundary={"version": 900})
    normalized = prepare_observation(data)["objects"][0]
    assert normalized["photo_boundary"] is None and normalized["category_adaptation"] is None


def test_observations_do_not_claim_missing_prop_is_drawn_or_segmentation_is_truth():
    data = observed()
    data["objects"][0].update(label="狗", kind="pet", mobility="unknown")
    data["unrendered_objects"] = [{"object_id": "object2", "label": "球", "reason_code": "foreground_empty"}]
    scene = ObservedScene.model_validate(data)
    result = observation_summary(advice(), scene)
    assert any("已识别到“球”，但未可靠绘出" in row for row in result.observations)
    assert any("名称和细节仍需" in row for row in result.observations)
    assert result.uncertainties == ["已识别到“球”，但未可靠绘出；请对照原图核对。"]
    assert observation_summary(result, scene) == result


def inspection():
    return SimpleNamespace(model_image_data_url='data:image/png;base64,' + base64.b64encode(b'local pixels').decode(),
                           metrics=SimpleNamespace(width=100, height=80))


def test_replay_opt_in_trace_association_bounded_retention_and_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv('CAMERA_AI_COMPOSITION_REPLAY', '1')
    monkeypatch.setattr(replay, 'REPLAY_ROOT', tmp_path)
    monkeypatch.setattr(replay, 'MAX_RECORDS', 2)
    trace = 'a' * 32
    with observe_diagnostics(lambda event: None, trace_id=trace):
        for _ in range(3):
            record = replay.ReplayRecord(inspection())
            record.metadata(ObservedScene.model_validate(observed()))
            record.update(code='contours_extracted', api_key='SECRET', raw_thinking='PRIVATE')
    assert current_trace_id() is None
    files = list(tmp_path.glob('*.json'))
    assert len(files) == 2
    for file in files:
        raw = file.read_text(encoding='utf-8')
        value = json.loads(raw)
        assert value['version'] == 'composition-replay-v3' and value['trace_id'] == trace
        assert value['metadata']['objects'][0]['bbox'] == [.4, .1, .5, .9]
        assert 'SECRET' not in raw and 'PRIVATE' not in raw and 'data:image' not in raw


def test_oversized_extracted_geometry_is_omitted_with_a_reason(tmp_path, monkeypatch):
    monkeypatch.setenv('CAMERA_AI_COMPOSITION_REPLAY', '1')
    monkeypatch.setattr(replay, 'REPLAY_ROOT', tmp_path)
    monkeypatch.setattr(replay, 'MAX_RECORD_BYTES', 600)
    record = replay.ReplayRecord(inspection())
    record.update(extracted={'large': 'x' * 2000}, code='contours_extracted')
    value = json.loads(record.path.read_text(encoding='utf-8'))
    assert value['extracted_omitted'] == 'record_size_limit' and 'extracted' not in value
    assert record.path.stat().st_size <= 600


def test_replay_write_failure_cannot_change_business_success(tmp_path, monkeypatch):
    monkeypatch.setenv('CAMERA_AI_COMPOSITION_REPLAY', '1')
    monkeypatch.setattr(replay, 'REPLAY_ROOT', tmp_path)
    record = replay.ReplayRecord(inspection())
    monkeypatch.setattr(type(record.path), 'write_bytes', lambda *args: (_ for _ in ()).throw(OSError('denied')))
    record.update(code='contours_extracted')
