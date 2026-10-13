"""Editable review copies must preserve raw results, photos and frozen AI provenance."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_detector_preacceptance_replay as replay_tests
from PIL import Image

from vision_lab_tool.detector_models import DetectorReference, GroundTruth
from vision_lab_tool.detector_reference import reference_ready

spec = importlib.util.spec_from_file_location(
    "confirmation_history", Path(__file__).resolve().parents[1] /
    "scripts/register_detector_confirmation_history.py")
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


@pytest.fixture
def saved_run():
    return replay_tests.saved_run.__wrapped__()


def ai_reference():
    return DetectorReference(objects=[GroundTruth(
        gt_id="cup", label="cup", bbox=[.1, .1, .9, .9], target_level="whole",
        annotation_source="ai", confirmed=False)])


def test_append_only_store_cannot_overwrite_existing_snapshot(tmp_path):
    path = tmp_path / "runs" / "existing.json"
    history.AppendOnlyDetectorStore._write(path, b"original failure")
    with pytest.raises(FileExistsError):
        history.AppendOnlyDetectorStore._write(path, b"replacement success")
    assert path.read_bytes() == b"original failure"
    assert not list(path.parent.glob("*.tmp"))


def test_reference_attachment_copies_ai_without_confirming_or_changing_inference(
        saved_run, tmp_path):
    source = saved_run.model_copy(deep=True)
    source.image["original_sha256"] = "original-photo"
    reference = ai_reference()
    path = tmp_path / "reference.json"
    path.write_text(reference.model_dump_json(), encoding="utf-8")
    run = source.model_copy(deep=True)
    mapping = history.attach_reference(run, "B02", "original", source, path, reference)
    assert history.same_inference(run, source)
    assert run.reference == reference and not reference_ready(run)
    assert run.provenance["frozen_ai_reference_sha256"] == history.sha256(path.read_bytes())
    assert run.provenance["reference_workflow"]["evaluation_scope"] == "original_complete_task"
    assert run.provenance["reference_workflow"]["inventory_gt_ids"] == ["cup"]
    assert run.provenance["reference_workflow"]["confirmation_log"] == []
    assert mapping == {r.result_id: r.result_id for r in source.results}


def test_human_flags_cannot_be_registered_as_ai_draft(saved_run, tmp_path):
    reference = ai_reference()
    reference.objects[0].confirmed = True
    path = tmp_path / "reference.json"
    path.write_text(reference.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="unconfirmed"):
        history.attach_reference(saved_run, "B02", "original", saved_run, path, reference)


def test_review_copy_and_photo_reopen_without_touching_source(saved_run, tmp_path):
    store = history.AppendOnlyDetectorStore(tmp_path)
    source = saved_run.model_copy(deep=True)
    source.image["original_sha256"] = "original-photo"
    photo = Image.new("RGB", (83, 41), (11, 54, 120))
    store.save_sample(source, SimpleNamespace(corrected=photo))
    store.save_run(source)
    before = history.history_manifest(store)
    reference = ai_reference()
    path = tmp_path / "reference.json"
    path.write_text(reference.model_dump_json(), encoding="utf-8")
    edited = source.model_copy(deep=True)
    history.attach_reference(edited, "B02", "original", source, path, reference)
    with history.offline_guard():
        derived = store.save_review_version(edited)
        history.verify_saved(store, derived, source, reference)
    assert derived.run_id != source.run_id
    assert history.same_inference(derived, source)
    assert history.verify_old_history(before, history.history_manifest(store))[
        "original_history_unchanged"]


def test_legacy_ai_confirmed_flag_is_not_human_evidence(saved_run):
    reference = ai_reference()
    reference.objects[0].confirmed = True
    reference.complete = True
    saved_run.reference = reference
    assert not reference_ready(saved_run)
    reference.objects[0].annotation_source = "human"
    assert reference_ready(saved_run)
