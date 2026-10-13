import hashlib
import io
import json
import threading

import httpx
import pytest
from PIL import Image

from vision_lab_tool import detector_runner as runner
from vision_lab_tool.detector_mock import detect_mock, vlm_payload
from vision_lab_tool.detector_models import DetectorConfig, DetectorExperiment, VLMSnapshot
from vision_lab_tool.detector_queries import compose_queries
from vision_lab_tool.images import prepare_image
from vision_lab_tool.models import ModelConfig


@pytest.fixture
def image():
    value = Image.new("RGB", (2400, 800), "white")
    value.putpixel((500, 300), (0, 0, 0))
    data = io.BytesIO()
    value.save(data, "JPEG")
    return prepare_image(data.getvalue())


@pytest.fixture
def configs():
    return [DetectorConfig(detector="grounding_dino"), DetectorConfig(detector="yolo26")]


@pytest.fixture
def vlm():
    return ModelConfig(name="mock localization", provider="fixture", protocol="mock")


def test_pure_never_calls_vlm(monkeypatch, image, configs):
    monkeypatch.setattr(runner, "invoke_localization", lambda *a, **k: pytest.fail("VLM called"))
    record = runner.run_experiment(image, configs[:1], "pure_detection", "人物", simulated=True)
    assert record.vlm is None and len(record.results) == 1
    assert record.costs["shared_vlm_call_count"] == 0
    assert record.image["sent_size"] == [1600, 533]


def test_shared_one_vlm_exact_same_jpeg_and_sequential_failure_isolation(monkeypatch, image, configs):
    calls, sent_hashes, stages = [], [], []
    config = ModelConfig(name="local test", provider="fixture", protocol="chat",
                         base_url="https://example.invalid/v1", model_id="test")

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        url = body["messages"][0]["content"][1]["image_url"]["url"]
        assert url == image.data_url
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps(vlm_payload())}}]})

    def detect(prepared, queries, cfg):
        assert prepared.sent_bytes == image.sent_bytes
        sent_hashes.append(prepared.metadata()["sent_sha256"])
        if cfg.detector == "grounding_dino":
            raise RuntimeError("isolated failure")
        return detect_mock(prepared, queries, cfg)

    record = runner.run_experiment(image, configs, "localization", "人物", config,
                key="private-secret", transport=httpx.MockTransport(handler), detect_fn=detect,
                on_stage=lambda r: stages.append(r))
    assert len(calls) == 1 and len(sent_hashes) == 2
    assert [r.method for r in record.results] == ["A", "B1", "B2"]
    assert record.results[0].status == "success"
    assert record.results[1].status == "runtime_error"
    assert record.results[2].detection.candidates
    assert all(r.run_id == record.run_id for r in stages)
    assert len(stages) >= 6


@pytest.mark.parametrize("case", ["valid", "empty", "duplicate_id", "invalid_box", "ambiguous",
                                  "overlap", "unsupported", "vlm_network", "vlm_json",
                                  "vlm_semantic", "vlm_invalid_box"])
def test_offline_fixtures(image, configs, vlm, case):
    record = runner.run_experiment(image, configs, "localization", "person instrument hand",
                                   vlm, simulated=True, mock_case=case)
    assert record.simulated and not any(r.real for r in record.results)
    assert len(record.results) == 3
    if case in {"vlm_network", "vlm_json", "vlm_semantic"}:
        assert all(r.selection.status == "detection_only" for r in record.results[1:])
        assert record.results[1].detection.candidates
    if case == "vlm_invalid_box":
        assert record.vlm.box_status == "box_format_error"
        assert record.vlm.semantic_status == "success"
        assert not record.results[0].candidates
        assert record.results[1].queries["from_vlm"] == ["person"]
    if case == "ambiguous":
        assert not record.results[1].selection.selected_ids
    if case in {"duplicate_id", "invalid_box"}:
        assert record.results[1].status == "schema_error"
        assert record.results[1].detection.raw_candidates


def test_cache_new_attempt_same_result_source_and_invalidates(monkeypatch, image, configs, vlm):
    counters = {"vlm": 0, "detector": 0}
    invoke, detect = runner.invoke_localization, runner.detect_mock

    def counted_vlm(*a, **k):
        counters["vlm"] += 1
        return invoke(*a, **k)

    def counted_detect(*a, **k):
        counters["detector"] += 1
        return detect(*a, **k)

    monkeypatch.setattr(runner, "invoke_localization", counted_vlm)
    monkeypatch.setattr(runner, "detect_mock", counted_detect)
    cache = {}
    first = runner.run_experiment(image, configs, "localization", "人物", vlm,
                                   simulated=True, cache=cache)
    second = runner.run_experiment(image, configs, "localization", "人物", vlm,
                                    simulated=True, cache=cache)
    assert counters == {"vlm": 1, "detector": 2}
    assert first.run_id != second.run_id and first.attempt_id != second.attempt_id
    assert second.vlm.cache_hit and second.costs["shared_vlm_call_count"] == 0
    assert second.vlm.cache_source == first.vlm.result_id
    configs[0].box_threshold = .45
    runner.run_experiment(image, configs, "localization", "人物", vlm,
                          simulated=True, cache=cache)
    assert counters == {"vlm": 1, "detector": 3}
    runner.run_experiment(image, configs, "localization", "狗", vlm,
                          simulated=True, cache=cache)
    assert counters == {"vlm": 2, "detector": 5}


def test_query_inputs_have_no_truth_channel_and_no_eval(image, configs, vlm):
    assert "reference" not in runner.run_experiment.__code__.co_varnames
    sources = compose_queries("请保留器具和长杆", manual=[])
    assert "instrument" in sources["from_task"] and "rod" in sources["from_task"]
    assert compose_queries("hot dog")["merged"] == ["hot dog"]
    assert compose_queries("水杯 彩铅 喷溅区域 两只手")["merged"] == [
        "cup", "colored pencil", "water splash", "hand"]
    payload = vlm_payload()
    payload["objects"][0]["bbox"] = ["1/1000", 0, .7, .8]
    snapshot = runner.parse_snapshot(VLMSnapshot(config=vlm, raw_answer=json.dumps(payload)))
    assert snapshot.box_status == "box_format_error" and snapshot.semantic_status == "success"
    with pytest.raises(ValueError, match="人工补词"):
        runner.run_experiment(image, configs, "localization", "人物", vlm,
                              manual_queries=["person"], simulated=True)


def test_id_binding_invalidates_a(image, vlm):
    payload = vlm_payload()
    payload["main_subject_ids"] = ["missing"]
    snapshot = runner.parse_snapshot(VLMSnapshot(config=vlm, raw_answer=json.dumps(payload)))
    assert snapshot.box_status == "box_format_error"
    assert snapshot.semantic_status == "success"
    assert not runner._a_method(snapshot).selection.selected_ids


def test_semantic_ids_cannot_reuse_single_box_or_repair_selection(image, configs, vlm):
    payload = vlm_payload()
    second = dict(payload["objects"][0], object_id="v2")
    payload["objects"].append(second)
    payload["main_subject_ids"] = ["v1", "v2"]
    snap = runner.parse_snapshot(VLMSnapshot(config=vlm, raw_answer=json.dumps(payload)))
    detection = detect_mock(image, ["person"], configs[0])
    derived = runner._associate(detection, snap, compose_queries("person", snap.semantics), "B1")
    assert derived.selection.status == "ambiguous"
    assert not derived.selection.selected_ids
    payload["main_subject_ids"] = ["v1"]
    payload["objects"][1]["target_level"] = "whole"
    snap = runner.parse_snapshot(VLMSnapshot(config=vlm, raw_answer=json.dumps(payload)))
    derived = runner._associate(detection, snap, compose_queries("person", snap.semantics), "B1")
    assert derived.selection.status == "ambiguous" and not derived.selection.selected_ids
    assert derived.candidates[0].target_level == "instance"
    payload["subject_status"] = "ambiguous"
    snap = runner.parse_snapshot(VLMSnapshot(config=vlm, raw_answer=json.dumps(payload)))
    assert snap.selection_status == "selection_format_error" and not snap.main_subject_ids
    assert snap.semantic_status == "success"
    payload = vlm_payload()
    payload.update(subject_status="abstained", main_subject_ids=[])
    snap = runner.parse_snapshot(VLMSnapshot(config=vlm, raw_answer=json.dumps(payload)))
    assert runner._a_method(snap).selection.status == "abstained"


def test_exif_corrected_same_normalized_overlay(image, configs):
    source = Image.new("RGB", (120, 60), "white")
    exif = source.getexif()
    exif[274] = 6
    buffer = io.BytesIO()
    source.save(buffer, "JPEG", exif=exif)
    rotated = prepare_image(buffer.getvalue(), longest_edge=64)
    assert rotated.original_size == (120, 60)
    assert rotated.corrected.size == (60, 120) and rotated.sent_size == (32, 64)
    record = runner.run_experiment(rotated, configs[:1], "pure_detection", "人物", simulated=True)
    assert record.results[0].candidates[0].bbox == [.1, .1, .7, .8]


def test_cancel_keeps_a_and_no_detector_call(image, configs, vlm):
    event = threading.Event()
    event.set()
    record = runner.run_experiment(image, configs, "localization", "人物", vlm,
                                  simulated=True, cancel_event=event)
    assert record.results[0].status == "cancelled" and not record.vlm.attempts
    assert all(r.status == "cancelled" for r in record.results[1:])
    assert record.stages["run"] == "cancelled"


def test_planned_stages_and_mock_semantics_never_claim_full_real(image, configs, vlm):
    stages = []
    def local(image, queries, config):
        result = detect_mock(image, queries, config)
        result.real = True
        return result
    record = runner.run_experiment(image, configs, "localization", "person", vlm,
                                    detect_fn=local, on_stage=stages.append)
    assert stages[0].vlm.status == "pending" and not stages[0].vlm.attempts
    assert [r.method for r in stages[0].results] == ["A", "B1", "B2"]
    assert all(r.status == "pending" for r in stages[0].results)
    assert all(stages[0].results[i].result_id == record.results[i].result_id for i in range(3))
    assert record.simulated and not any(r.real for r in record.results)
    assert all(r.detection.real for r in record.results[1:])


def test_preparatory_provenance_preserves_exact_historical_prompt():
    task = "定位可见人物 {schema}，保留原文"
    # Golden digest computed from the source frozen before preparatory edits.
    expected_hash = "e643ddc66c5560714d1e90e468ac9b4c5f2cf618c58e145070d53292f726886a"
    prompt = runner.localization_prompt(task)
    assert hashlib.sha256(prompt.encode()).hexdigest() == expected_hash
    assert task in prompt
    provenance = runner.localization_provenance(task)
    assert provenance["localization_prompt"] == prompt
    assert provenance["localization_prompt_sha256"] == expected_hash
    assert provenance["dictionary"]["task_dictionary"] == runner.query_module.TASK_DICTIONARY
    assert "def _associate(" in provenance["association_rules"]


def test_recorded_prompt_and_schema_are_exact_network_inputs_even_when_failed(image, configs):
    config = ModelConfig(name="local test", provider="fixture", protocol="chat",
                         base_url="https://example.invalid/v1", model_id="test",
                         structured="json_schema")
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(503, json={"error": "deliberate offline failure"})

    record = runner.run_experiment(image, configs[:1], "localization", "人物", config,
        transport=httpx.MockTransport(handler), detect_fn=detect_mock)
    prompt = sent[0]["messages"][0]["content"][0]["text"]
    schema = sent[0]["response_format"]["json_schema"]["schema"]
    assert record.vlm.status == "http_error"
    assert record.provenance == record.vlm.provenance
    assert record.provenance["localization_prompt"] == prompt
    assert record.provenance["result_schema"] == schema
    assert record.vlm.attempts[0]["request_sent"]
    assert record.vlm.attempts[0]["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
    assert record.provenance["result_schema_sha256"] == hashlib.sha256(
        json.dumps(schema, ensure_ascii=False).encode()).hexdigest()


def test_same_version_content_changes_invalidate_cache(image, configs, vlm, monkeypatch):
    cache = {}
    first = runner.run_experiment(image, configs[:1], "localization", "人物", vlm,
                                  simulated=True, cache=cache)
    reused = runner.run_experiment(image, configs[:1], "localization", "人物", vlm,
                                   simulated=True, cache=cache)
    assert reused.vlm.cache_hit and reused.results[1].detection.cache_hit
    monkeypatch.setitem(runner.LOCALIZATION_PROMPT_TEMPLATES, runner.PROMPT_VERSION,
        runner.LOCALIZATION_PROMPT_TEMPLATES[runner.PROMPT_VERSION] + "\n格式诊断")
    changed = runner.run_experiment(image, configs[:1], "localization", "人物", vlm,
                                    simulated=True, cache=cache)
    assert not changed.vlm.cache_hit and not changed.results[1].detection.cache_hit
    assert changed.provenance["localization_prompt_sha256"] != first.provenance[
        "localization_prompt_sha256"]
    monkeypatch.setitem(runner.query_module.TASK_DICTIONARY, "临时通用词", "person")
    dictionary_changed = runner.run_experiment(image, configs[:1], "localization", "人物", vlm,
                                               simulated=True, cache=cache)
    assert not dictionary_changed.vlm.cache_hit
    assert dictionary_changed.provenance["dictionary_version"] == first.dictionary_version
    assert dictionary_changed.provenance["dictionary_sha256"] != changed.provenance[
        "dictionary_sha256"]


def test_schema_and_rule_content_hashes_invalidate_without_version_change(image, vlm, monkeypatch):
    before = runner.localization_provenance("人物")
    cache_before = runner._cache_key("vlm", image, "人物", vlm, [True, "valid"], before)
    schema = runner.VLMPayload.model_json_schema()
    schema["description"] = "schema revision without a version bump"
    monkeypatch.setattr(runner.VLMPayload, "model_json_schema", lambda: schema)
    after_schema = runner.localization_provenance("人物")
    assert after_schema["result_schema_sha256"] != before["result_schema_sha256"]
    assert runner._cache_key("vlm", image, "人物", vlm, [True, "valid"], after_schema) != cache_before
    original_associate = runner._associate

    def same_behavior_changed_source(*args, **kwargs):
        return original_associate(*args, **kwargs)

    monkeypatch.setattr(runner, "_associate", same_behavior_changed_source)
    after_rules = runner.localization_provenance("人物")
    assert after_rules["association_rule_version"] == before["association_rule_version"]
    assert after_rules["association_rule_sha256"] != after_schema["association_rule_sha256"]
    assert runner._cache_key("vlm", image, "人物", vlm, [True, "valid"], after_rules) != runner._cache_key(
        "vlm", image, "人物", vlm, [True, "valid"], after_schema)


def test_version_selection_restore_and_old_record_compatibility(image, configs, vlm, monkeypatch):
    baseline = runner.LOCALIZATION_PROMPT_TEMPLATES[runner.PROMPT_VERSION]
    monkeypatch.setattr(runner, "LOCALIZATION_PROMPT_TEMPLATES",
                        dict(runner.LOCALIZATION_PROMPT_TEMPLATES))
    runner.register_localization_prompt("candidate-offline", baseline + "\n候选格式说明")
    cache = {}
    original = runner.run_experiment(image, configs[:1], "localization", "人物", vlm,
        simulated=True, cache=cache)
    candidate = runner.run_experiment(image, configs[:1], "localization", "人物", vlm,
        simulated=True, cache=cache, prompt_version="candidate-offline")
    restored = runner.run_experiment(image, configs[:1], "localization", "人物", vlm,
        simulated=True, cache=cache, prompt_version=runner.PROMPT_VERSION)
    assert candidate.provenance["localization_prompt_version"] == "candidate-offline"
    assert not candidate.vlm.cache_hit and restored.vlm.cache_hit
    assert restored.vlm.cache_source == original.vlm.result_id
    with pytest.raises(ValueError, match="版本已存在"):
        runner.register_localization_prompt(runner.PROMPT_VERSION, baseline + " changed")
    with pytest.raises(ValueError, match="未知定位提示词"):
        runner.localization_prompt("人物", "missing-version")
    with pytest.raises(ValueError, match="占位符"):
        runner.register_localization_prompt("unsafe-format", "{task.__class__} {schema}")
    old = original.model_dump(mode="json")
    old.pop("provenance")
    old["vlm"].pop("provenance")
    compatible = DetectorExperiment.model_validate(old)
    assert compatible.provenance == {} and compatible.vlm.provenance == {}
    assert compatible.results == original.results


def test_failed_http_attempt_retains_bounded_scrubbed_provider_error(image):
    config = ModelConfig(name="local test", provider="fixture", protocol="chat",
                         base_url="https://example.invalid/v1", model_id="test")
    error = "Bearer private-secret; provider_code=EXAMPLE_503; " + "可复核" * 6000
    snapshot = runner.invoke_localization(config, "人物", image, key="private-secret",
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text=error)))
    attempt = snapshot.attempts[0]
    assert snapshot.status == "http_error" and len(snapshot.attempts) == 1
    assert attempt["response_status"] == 503 and attempt["request_sent"]
    assert "EXAMPLE_503" in attempt["response_error_body"]
    assert "private-secret" not in attempt["response_error_body"]
    assert attempt["response_error_body_truncated"]
    assert attempt["response_error_body_limit_bytes"] == 16384


def test_error_body_redaction_precedes_byte_limit(image):
    config = ModelConfig(name="local test", provider="fixture", protocol="chat",
                         base_url="https://example.invalid/v1", model_id="test")
    error = "x" * 16380 + "private-secret" + " error details"
    snapshot = runner.invoke_localization(config, "人物", image, key="private-secret",
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text=error)))
    attempt = snapshot.attempts[0]
    assert attempt["response_error_body_truncated"]
    assert "priv" not in attempt["response_error_body"]


def test_candidate_format_prompt_changes_only_prompt_and_sends_selected_version(image):
    task = "定位可见目标，不指定主角"
    baseline = runner.localization_provenance(task, runner.PROMPT_VERSION)
    candidate = runner.localization_provenance(task, runner.CANDIDATE_PROMPT_VERSION)
    for key in ("result_schema", "result_schema_sha256", "dictionary", "dictionary_sha256",
                "association_rules", "association_rule_sha256", "association_rule_version"):
        assert candidate[key] == baseline[key]
    assert candidate["localization_prompt_sha256"] != baseline["localization_prompt_sha256"]
    prompt = candidate["localization_prompt"]
    assert "不输出JSON Schema" in prompt and "禁止0到1000坐标" in prompt
    assert "不要求一律unknown" in prompt
    assert "subject_status只允许selected、ambiguous、abstained" in prompt
    example_json = prompt.split("请根据图片和任务填值：\n", 1)[1].split("\n字段校验schema", 1)[0]
    example = runner.VLMPayload.model_validate_json(example_json)
    assert example.objects[0].bbox == [0.12, 0.23, 0.45, 0.67]
    config = ModelConfig(name="local test", provider="fixture", protocol="chat",
                         base_url="https://example.invalid/v1", model_id="test")
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["messages"][0]["content"][0]["text"])
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps(vlm_payload())}}]})

    snapshot = runner.invoke_localization(config, task, image,
        transport=httpx.MockTransport(handler), prompt_version=runner.CANDIDATE_PROMPT_VERSION)
    assert sent == [prompt]
    assert snapshot.provenance["localization_prompt_version"] == runner.CANDIDATE_PROMPT_VERSION
    assert snapshot.attempts[0]["prompt_version"] == runner.CANDIDATE_PROMPT_VERSION
    assert snapshot.box_status == "success"


def test_scope_candidate_retains_prior_prompt_and_changes_no_other_factor(image, configs, vlm):
    task = "定位可见整体和部件，保留各自范围"
    first = runner.localization_provenance(task, runner.CANDIDATE_PROMPT_VERSION)
    second = runner.localization_provenance(task, runner.SCOPE_PROMPT_VERSION)
    assert second["localization_prompt"].startswith(first["localization_prompt"])
    for key in ("result_schema", "result_schema_sha256", "dictionary", "dictionary_sha256",
                "association_rules", "association_rule_sha256", "association_rule_version"):
        assert second[key] == first[key]
    assert first["localization_prompt_sha256"] != second["localization_prompt_sha256"]
    cache = {}
    old = runner.run_experiment(image, configs[:1], "localization", task, vlm,
        simulated=True, cache=cache, prompt_version=runner.CANDIDATE_PROMPT_VERSION)
    scoped = runner.run_experiment(image, configs[:1], "localization", task, vlm,
        simulated=True, cache=cache, prompt_version=runner.SCOPE_PROMPT_VERSION)
    restored = runner.run_experiment(image, configs[:1], "localization", task, vlm,
        simulated=True, cache=cache, prompt_version=runner.CANDIDATE_PROMPT_VERSION)
    assert not scoped.vlm.cache_hit and scoped.configs == old.configs
    assert restored.vlm.cache_hit and restored.vlm.cache_source == old.vlm.result_id
    assert "main_subject_ids可并列引用" in second["localization_prompt"]
    assert "parent_object_id引用存在的整体ID" in second["localization_prompt"]
    assert "target_level=region" in second["localization_prompt"]
    assert "不要求一律unknown" in second["localization_prompt"]
