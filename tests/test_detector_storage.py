import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest
from test_detector_evaluation import annotate, experiment
from test_vision_lab_core import image_bytes
from test_vision_lab_records import run as legacy_run

from vision_lab_tool.detector_models import DetectorError
from vision_lab_tool.detector_storage import (
    DetectorStore,
    export_csv,
    export_json,
    filter_experiments,
)
from vision_lab_tool.images import prepare_image
from vision_lab_tool.storage import Store


def test_versioned_detector_namespace_does_not_touch_legacy_v1(tmp_path):
    original = legacy_run()
    legacy = Store(tmp_path)
    legacy.save_run(original)
    legacy_bytes = (tmp_path / "runs" / f"{original.run_id}.json").read_bytes()
    run = experiment()
    detector = DetectorStore(tmp_path)
    detector.save_run(run)
    reopened = detector.load_run(run.run_id)
    assert reopened.schema_version == "detector-1"
    assert detector.root == tmp_path / "detector_experiments"
    assert len(detector.list_runs()) == 1 and len(legacy.list_runs()) == 1
    assert legacy.load_run(original.run_id).schema_version == "1"
    assert (tmp_path / "runs" / f"{original.run_id}.json").read_bytes() == legacy_bytes


def test_review_version_uses_new_identity_and_keeps_source_history_and_image(tmp_path):
    run = experiment()
    store = DetectorStore(tmp_path)
    store.save_sample(run, prepare_image(image_bytes()))
    store.save_run(run)
    source_path = store.root / "runs" / f"{run.run_id}.json"
    original = source_path.read_bytes()
    run.reference.notes = "human draft, waiting confirmation"
    derived = store.save_review_version(run)
    assert derived.run_id != run.run_id and derived.attempt_id == run.attempt_id
    assert derived.provenance["annotation_parent_run_id"] == run.run_id
    assert source_path.read_bytes() == original
    assert store.load_run(derived.run_id).reference.notes == "human draft, waiting confirmation"
    assert store.load_sample(derived).size == store.load_sample(run).size
    assert len(store.list_runs()) == 2


def test_atomic_stage_update_retains_old_record_on_interruption(tmp_path, monkeypatch):
    run = experiment()
    store = DetectorStore(tmp_path)
    run.stages = {"vlm": "ok", "detector": "pending"}
    store.save_run(run)
    run.stages["detector"] = "timeout"

    def fail_replace(*args):
        raise OSError("simulated interruption")

    with monkeypatch.context() as patch:
        patch.setattr("vision_lab_tool.detector_storage.os.replace", fail_replace)
        with pytest.raises(OSError):
            store.save_run(run)
    assert store.load_run(run.run_id).stages["detector"] == "pending"
    assert not list(store.root.rglob("*.tmp"))
    store.save_run(run)
    assert store.load_run(run.run_id).stages == {"vlm": "ok", "detector": "timeout"}


def test_atomic_stage_replace_retries_transient_windows_handles(tmp_path, monkeypatch):
    import os

    run = experiment()
    store = DetectorStore(tmp_path)
    store.save_run(run)
    run.stages = {"detector": "completed"}
    replace = os.replace
    calls, delays = [], []

    def temporarily_locked(source, target):
        calls.append((source, target))
        if len(calls) <= 2:
            raise PermissionError("simulated Windows indexer handle")
        return replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr("vision_lab_tool.detector_storage.os.replace", temporarily_locked)
        patch.setattr("vision_lab_tool.detector_storage.time.sleep", delays.append)
        store.save_run(run)
    assert len(calls) == 3 and delays == [0.05, 0.1]
    assert store.load_run(run.run_id).stages["detector"] == "completed"
    assert not list(store.root.rglob("*.tmp"))


def test_atomic_stage_replace_persistent_lock_is_bounded_and_retains_old_file(
    tmp_path, monkeypatch
):
    run = experiment()
    store = DetectorStore(tmp_path)
    store.save_run(run)
    previous = (store.root / "runs" / f"{run.run_id}.json").read_bytes()
    run.stages = {"detector": "completed"}
    calls, delays = [], []

    def always_locked(source, target):
        calls.append((source, target))
        raise PermissionError("persistent access denial")

    with monkeypatch.context() as patch:
        patch.setattr("vision_lab_tool.detector_storage.os.replace", always_locked)
        patch.setattr("vision_lab_tool.detector_storage.time.sleep", delays.append)
        with pytest.raises(PermissionError):
            store.save_run(run)
    assert len(calls) == 5 and delays == [0.05, 0.1, 0.2, 0.4]
    assert (store.root / "runs" / f"{run.run_id}.json").read_bytes() == previous
    assert not list(store.root.rglob("*.tmp"))


def test_corrupt_history_visible_and_id_paths_rejected(tmp_path):
    store = DetectorStore(tmp_path)
    run = experiment()
    store.save_run(run)
    (store.root / "runs" / f"{'a' * 32}.json").write_text("{bad", "utf-8")
    assert len(store.list_runs()) == 1 and len(store.load_errors) == 1
    with pytest.raises(ValueError, match="run_id"):
        store.load_run("../escape")
    run.sample_file = "../escape.png"
    with pytest.raises(ValueError, match="路径"):
        store.load_sample(run)


def test_independent_errors_same_category_export_separately_and_scrub(tmp_path):
    run = experiment()
    run.task_prompt = '=HYPERLINK("evil")'
    review = annotate(run)
    review.notes = "token-secret; Bearer private-token; data:image/jpeg;base64,AAAA"
    review.errors = [
        DetectorError(tag="检测漏检", evidence="=one", confirmed=True),
        DetectorError(tag="检测漏检", evidence="@two", confirmed=False),
    ]
    run.results[0].queries = {"headers": {"Authorization": "secret"}, "api_key": "token-secret"}
    store = DetectorStore(tmp_path)
    store.save_run(run, ["token-secret"])
    saved = store.load_run(run.run_id)
    assert saved.results[0].queries["headers"] == "[REDACTED]"
    serialized = export_json([saved], ["token-secret"]).decode("utf-8")
    assert (
        "private-token" not in serialized
        and "AAAA" not in serialized
        and "token-secret" not in serialized
    )
    rows = list(csv.DictReader(io.StringIO(export_csv([saved]).decode("utf-8-sig"))))
    assert len(rows) == 2 and rows[0]["error_id"] != rows[1]["error_id"]
    assert rows[0]["task_prompt"].startswith("'=")
    assert rows[0]["evidence"] == "'=one" and rows[1]["evidence"] == "'@two"
    assert rows[0]["simulated"] == "False" and rows[0]["method"] == "B1"


def test_invalid_pair_and_duplicate_error_reject_without_overwriting(tmp_path):
    run = experiment()
    review = annotate(run)
    store = DetectorStore(tmp_path)
    store.save_run(run)
    review.box_matches = {"missing": "gt1"}
    with pytest.raises(ValueError, match="配对引用不存在"):
        store.save_run(run)
    assert not store.load_run(run.run_id).evaluations[run.results[0].result_id].box_matches
    review.box_matches = {}
    error = DetectorError(tag="误检")
    review.errors = [error, error.model_copy()]
    with pytest.raises(ValueError, match="error_id 重复"):
        store.save_run(run)


def test_save_image_opt_in_exif_corrected_round_trip(tmp_path):
    store = DetectorStore(tmp_path)
    run = experiment()
    store.save_run(run)
    assert store.load_sample(run) is None
    assert not list(store.root.rglob("*.png"))
    prepared = prepare_image(image_bytes(orientation=6))
    store.save_sample(run, prepared)
    store.save_run(run)
    image = store.load_sample(store.load_run(run.run_id))
    assert image.size == prepared.corrected.size and not image.getexif()


def test_filter_uses_matching_error_confirmed_status_and_keeps_identity():
    run = experiment()
    review = annotate(run)
    review.errors = [
        DetectorError(tag="漏检", confirmed=False),
        DetectorError(tag="误检", confirmed=True),
    ]
    assert filter_experiments([run], error_type="漏检", confirmed=True) == []
    assert filter_experiments([run], error_type="漏检", confirmed=False) == [run]
    run.stages = {"vlm": "ok"}
    assert filter_experiments(
        [run], stage="vlm", model="grounding", task="person", image="image-hash", simulated=False
    ) == [run]
    assert filter_experiments([run], dataset_split="验证") == []


def test_pilot_whitelists_paths_and_never_copies_checkpoint_or_title(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "prepare_detector_pilot.py"
    spec = importlib.util.spec_from_file_location("prepare_detector_pilot", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    grouped = {}
    for dataset_id, sample_id, _, _ in module.PILOT_TASKS:
        dataset = tmp_path / "data" / "vision_lab" / "test_sets" / dataset_id
        (dataset / "images").mkdir(parents=True, exist_ok=True)
        image = dataset / "images" / f"{sample_id}.jpg"
        image.write_bytes(sample_id.encode())
        grouped.setdefault(dataset, []).append(
            {
                "sample_id": sample_id,
                "file": f"images/{sample_id}.jpg",
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "title": "DO_NOT_USE_TITLE",
                "evaluation_checks": "DO_NOT_USE_CHECKPOINT",
                "bbox": [0, 0, 1, 1],
                "reference_confirmed": True,
                "license": "fixture license",
                "author": "fixture author",
            }
        )
    before = {}
    for dataset, samples in grouped.items():
        path = dataset / "manifest.json"
        path.write_text(json.dumps({"samples": samples}), "utf-8")
        before[path] = path.read_bytes()
    manifest = module.prepare_pilot(tmp_path)
    serialized = json.dumps(manifest)
    assert "DO_NOT_USE_TITLE" not in serialized and "DO_NOT_USE_CHECKPOINT" not in serialized
    assert manifest["development_count"] == 3 and manifest["validation_count"] == 7
    assert manifest["blind_test"] is False and manifest["quality_experiment_started"] is False
    assert all(not s["reference"]["complete"] for s in manifest["samples"])
    assert all(path.read_bytes() == data for path, data in before.items())
    with pytest.raises(FileExistsError):
        module.prepare_pilot(tmp_path)
