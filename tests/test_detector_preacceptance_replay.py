"""Saved inputs remain immutable and replay cannot cross an inference boundary."""
import importlib.util
import json
import socket
import subprocess
from contextlib import nullcontext
from pathlib import Path

import httpx
import pytest

from vision_lab_tool import detector_runner
from vision_lab_tool.detector_models import (
    DetectionObject,
    DetectionResult,
    DetectorConfig,
    DetectorExperiment,
    GroundTruth,
    MethodResult,
    SemanticObject,
    SubjectSelection,
    VLMSnapshot,
)
from vision_lab_tool.detectors.client import DetectorClient
from vision_lab_tool.models import ModelConfig

spec = importlib.util.spec_from_file_location(
    "preacceptance_replay", Path(__file__).resolve().parents[1] /
    "scripts/replay_detector_preacceptance.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


@pytest.fixture
def saved_run():
    obj = DetectionObject(object_id="det-cup", label_original="cup", label_display="cup",
                          bbox_native=[10., 10., 90., 90.], bbox_postprocessed=[10., 10., 90., 90.],
                          bbox=[.1, .1, .9, .9], coordinate_basis="saved")
    detection = DetectionResult(config=DetectorConfig(detector="yolo26"), status="success",
                                candidates=[obj], filtered_candidates=[obj],
                                raw_candidates=[{"saved_unmodified": True}])
    vlm = VLMSnapshot(config=ModelConfig(name="saved", provider="fixture", protocol="mock"),
                      status="box_format_error", raw_answer="original failure; never reparse",
                      semantic_status="success", box_status="box_format_error",
                      subject_status="selected", selection_status="success",
                      main_subject_ids=["sem-cup"],
                      semantics=[SemanticObject(object_id="sem-cup", label="杯子", query="cup",
                                                target_level="whole", entity_kind="unknown")],
                      provenance={"localization_prompt": "原实际发送全文\n{schema}",
                                  "result_schema": {"frozen": "old"},
                                  "localization_prompt_sha256": "old-prompt-hash"})
    queries = {"from_task": ["cup"], "from_vlm": ["cup"], "merged": ["cup"],
               "fallback": [], "manual": [], "dictionary_version": "task-english-v1"}
    a = MethodResult(method="A", status="box_format_error", diagnostics=["original failure"],
                     selection=SubjectSelection(status="abstained"))
    b = MethodResult(method="B2", detector="yolo26", status="success", detection=detection,
                     candidates=[obj], queries=queries,
                     selection=SubjectSelection(status="ambiguous", candidate_ids=[obj.object_id]))
    return DetectorExperiment(mode="localization", experiment_version="source:v1:B02:paired",
                              task_prompt="定位水杯", task_prompt_sha256="source-task-hash",
                              image={"sent_sha256": "saved-image"}, configs=[detection.config],
                              results=[a, b], vlm=vlm, provenance=vlm.provenance.copy(),
                              timings={"historical": 30.}, costs={"unknown_cost": None})


@pytest.fixture
def rules():
    return {"association_rule_version": "new-rule", "dictionary_version": "new-dictionary",
            "bundle_sha256": "new-bundle", "files": {"helpers.py": {"sha256": "helper-sha"}}}


def test_replay_preserves_source_and_real_inputs(saved_run, rules):
    before = saved_run.model_dump(mode="json")
    with replay.offline_guard():
        derived, rows = replay.replay_run(saved_run, "outputs/v1/B02/paired/run.json", rules,
                                          {"version": "v1", "sample": "B02", "condition": "paired"})
    assert saved_run.model_dump(mode="json") == before
    assert derived.run_id != saved_run.run_id and derived.attempt_id != saved_run.attempt_id
    assert {r.result_id for r in derived.results}.isdisjoint(r.result_id for r in saved_run.results)
    assert derived.vlm.model_dump(mode="json") == before["vlm"]
    assert derived.results[1].detection.model_dump(mode="json") == before["results"][1]["detection"]
    assert derived.results[0].model_dump(exclude={"result_id"}) == saved_run.results[0].model_dump(
        exclude={"result_id"})
    assert derived.results[1].queries["task_text"] == saved_run.task_prompt
    for key in replay.QUERY_ARRAYS:
        assert derived.results[1].queries[key] == saved_run.results[1].queries[key]
    assert derived.provenance["localization_prompt"] == saved_run.provenance["localization_prompt"]
    assert derived.provenance["result_schema"] == saved_run.provenance["result_schema"]
    assert derived.provenance["offline_replay"]["rules_bundle_sha256"] == "new-bundle"
    assert not any(r["candidate_coordinates_changed"] for r in rows)
    assert all(v is None for r in rows for v in r["human_metrics"].values())
    assert derived.evaluations == {}
    assert derived.timings.keys() == {"offline_replay_seconds"}


def test_complete_replay_never_calls_http_models_queries_or_prompt_regeneration(
        monkeypatch, tmp_path, saved_run, rules):
    def sentinel(*args, **kwargs):
        pytest.fail("Replay reached a network/model/prompt/query entry point")

    for target, name in ((httpx.Client, "send"), (httpx.Client, "request"),
                         (DetectorClient, "detect"), (DetectorClient, "_start"),
                         (detector_runner, "invoke_localization"),
                         (detector_runner, "run_experiment"),
                         (detector_runner, "parse_snapshot"),
                         (detector_runner, "localization_provenance"),
                         (replay.detector_queries, "compose_queries"),
                         (subprocess, "Popen"), (socket, "create_connection")):
        monkeypatch.setattr(target, name, sentinel)
    # Exercise the whole exporter under independent sentinels, without its guard
    # replacing them; the other test checks fail-closed guard behavior directly.
    monkeypatch.setattr(replay, "offline_guard", nullcontext)
    monkeypatch.setattr(replay, "rule_snapshot", lambda: rules)
    source, output = tmp_path / "source", tmp_path / "output"
    path = source / "outputs/v1/B02/paired/run.json"
    path.parent.mkdir(parents=True)
    path.write_text(saved_run.model_dump_json(), encoding="utf-8")
    (source / "request_ledger.json").write_text('[{"request_sent":true}]', encoding="utf-8")
    summary = replay.run_replay(source, output)
    assert summary["totals"]["run_count"] == 1
    assert summary["totals"]["method_count"] == 2
    assert summary["integrity"]["source_files_unchanged"]
    assert summary["integrity"]["request_ledger_unchanged"]
    derived = DetectorExperiment.model_validate_json(
        (output / "runs/v1/B02/paired/run.json").read_bytes())
    assert derived.vlm.result_id == saved_run.vlm.result_id
    assert derived.results[1].detection.result_id == saved_run.results[1].detection.result_id
    assert json.loads((output / "run_mapping.json").read_text("utf-8"))[0]["source_run_id"] == \
        saved_run.run_id
    with pytest.raises(FileExistsError, match="snapshot exists"):
        replay.run_replay(source, output)


@pytest.mark.parametrize("target,name", [
    (httpx.Client, "request"), (httpx.AsyncClient, "send"),
    (DetectorClient, "detect"), (DetectorClient, "_start"),
    (detector_runner, "invoke_localization"), (detector_runner, "parse_snapshot"),
    (detector_runner, "localization_provenance"),
    (replay.detector_queries, "compose_queries"), (socket, "create_connection"),
    (subprocess, "Popen"),
])
def test_offline_guard_blocks_all_entrypoints(target, name):
    with replay.offline_guard(), pytest.raises(RuntimeError, match="Offline replay prohibits"):
        getattr(target, name)()


def test_existing_baseline_detects_any_source_change(tmp_path, monkeypatch, rules):
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    (source / "request_ledger.json").write_text("[]", encoding="utf-8")
    replay.write_json_new(output / "source_hashes_before.json", replay.source_manifest(source))
    (source / "new-evidence.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(replay, "rule_snapshot", lambda: rules)
    with pytest.raises(ValueError, match="Source differs"):
        replay.run_replay(source, output)
    assert not (output / "rule_snapshot.json").exists()


def test_replay_destination_cannot_overlap_source(tmp_path):
    source = tmp_path / "source"
    for output in (source, source / "replay", tmp_path):
        with pytest.raises(ValueError, match="separate"):
            replay.run_replay(source, output)


def test_actual_query_arrays_never_rewritten_for_alias_plan():
    saved = {"merged": ["cup", "water cup", "cup inside region"]}
    original = json.dumps(saved)
    plan = replay.proposed_query_plan(saved)
    assert json.dumps(saved) == original
    assert plan["actual_saved_queries"] == saved["merged"]
    assert plan["executed"] is False
    assert plan["new_inference_count"] == 0
    assert "cup inside region" in (plan["proposed_new_queries"] or saved["merged"])


def test_rule_hash_includes_full_helper_modules():
    pytest.importorskip("vision_lab_tool.detector_scope")
    snapshot = replay.rule_snapshot()
    scope_file = snapshot["files"]["src/vision_lab_tool/detector_scope.py"]
    assert "def resolve_task_scope(" in scope_file["source"]
    assert scope_file["sha256"] == replay.sha256(
        (replay.ROOT / "src/vision_lab_tool/detector_scope.py").read_bytes())
    assert "def label_components(" in snapshot["files"][
        "src/vision_lab_tool/detector_queries.py"]["source"]


def test_reference_cannot_supply_task_scope_or_association(saved_run, rules):
    identity = {"version": "v1", "sample": "B02", "condition": "paired"}
    _, first = replay.replay_run(saved_run, "run.json", rules, identity)
    changed = saved_run.model_copy(deep=True)
    changed.reference.objects = [GroundTruth(gt_id="human-rock", label="rock",
                                             bbox=[.2, .2, .4, .4], confirmed=True,
                                             annotation_source="human", required=True)]
    changed.reference.complete = True
    _, second = replay.replay_run(changed, "run.json", rules, identity)
    assert first[1]["task_scope"] == second[1]["task_scope"]
    assert first[1]["new"]["selection_status"] == second[1]["new"]["selection_status"]
    assert first[1]["new"]["selected_ids"] == second[1]["new"]["selected_ids"]
    assert first[1]["new"]["unsupported_targets"] == second[1]["new"]["unsupported_targets"]
