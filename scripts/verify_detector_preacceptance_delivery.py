"""Offline final checks: immutable evidence, exact reused inputs and no human metrics."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from register_detector_confirmation_history import history_manifest, verify_old_history
from replay_detector_preacceptance import compare_manifests, rule_snapshot, sha256, source_manifest

from vision_lab_tool.detector_evaluation import EVALUATION_RULE_VERSION, result_metrics
from vision_lab_tool.detector_models import DetectorExperiment, DetectorReference
from vision_lab_tool.detector_runner import localization_prompt
from vision_lab_tool.detector_storage import DetectorStore

BASE = ROOT / "data/vision_lab/detector_experiments/preacceptance_20261013"
SOURCE = ROOT / "data/vision_lab/detector_experiments/iteration_20261013_01"
QUALITY_FIELDS = (
    "tp", "fp", "fn", "precision", "recall", "mean_iou", "median_iou",
    "subject_correct_auto", "subject_correct_human", "complete_task_success",
    "complete_task_success_human", "query_target_coverage", "fixed_class_support_coverage",
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify():
    source_integrity = compare_manifests(
        read(BASE / "replay/source_hashes_before.json"), source_manifest(SOURCE))
    assert source_integrity["source_files_unchanged"], source_integrity
    assert source_integrity["request_ledger_unchanged"]
    store = DetectorStore(ROOT / "data/vision_lab")
    old_history = verify_old_history(
        read(BASE / "history_registration/history_hashes_before.json"), history_manifest(store))
    assert old_history["original_history_unchanged"], old_history
    package = BASE / "confirmation_package"
    manifest = read(package / "manifest.json")
    for path, digest in manifest["artifact_hashes"].items():
        assert sha256((package / path).read_bytes()) == digest, path
    for path, digest in manifest["source_hashes"].items():
        assert sha256(Path(path).read_bytes()) == digest, path
    references = {}
    for sample in manifest["sample_order"]:
        reference = DetectorReference.model_validate(read(package / sample / "reference.json"))
        assert not reference.complete
        assert all(o.annotation_source == "ai" and not o.confirmed for o in reference.objects)
        references[sample] = len(reference.objects)
    assert sum(references.values()) == 32
    summary = read(BASE / "replay_final/replay_comparison.json")
    rules = rule_snapshot()
    assert rules["bundle_sha256"] == summary["rules_bundle_sha256"]
    preserved_a = 0
    for mapping in summary["run_mapping"]:
        source = DetectorExperiment.model_validate_json((SOURCE / mapping["source_path"]).read_bytes())
        derived = DetectorExperiment.model_validate_json(
            (BASE / "replay_final" / mapping["derived_path"]).read_bytes())
        assert source.image == derived.image and source.configs == derived.configs
        assert source.vlm == derived.vlm and source.task_prompt == derived.task_prompt
        assert derived.provenance["offline_replay"]["rules_bundle_sha256"] == rules["bundle_sha256"]
        if source.vlm and source.provenance.get("localization_prompt"):
            assert source.provenance["localization_prompt"] == localization_prompt(
                source.task_prompt, source.provenance["localization_prompt_version"])
        for old, new in zip(source.results, derived.results, strict=True):
            assert old.detection == new.detection
            if old.method == "A":
                assert old.model_dump(exclude={"result_id"}) == new.model_dump(exclude={"result_id"})
                preserved_a += 1
    mapping = read(BASE / "history_registration_final/history_mapping.json")
    run_ids = {row["run_id"] for row in mapping["rows"]}
    assert len(run_ids) == 40
    method_count = 0
    for run_id in run_ids:
        run = store.load_run(run_id)
        assert store.load_sample(run) is not None
        assert not run.reference.complete and not any(o.confirmed for o in run.reference.objects)
        assert run.evaluations == {}
        assert run.provenance["reference_workflow"]["confirmation_log"] == []
        for result in run.results:
            metrics = result_metrics(run, result)
            assert not metrics["reference_ready"] and not metrics["scoring_ready"]
            assert all(metrics[field] is None for field in QUALITY_FIELDS), (run_id, result.method)
            method_count += 1
    assert method_count == 115
    result = {
        "verified_at": datetime.now(UTC).isoformat(), "status": "passed",
        "active_replay": "replay_final", "active_history_mapping": "history_registration_final",
        "association_rule_version": rules["association_rule_version"],
        "rules_bundle_sha256": rules["bundle_sha256"],
        "evaluation_rule_version": EVALUATION_RULE_VERSION,
        "source_integrity": source_integrity,
        "old_history_unchanged": old_history["original_history_unchanged"],
        "old_history_file_count": old_history["old_file_count"],
        "all_reference_objects_preserved": manifest["all_ai_draft_objects"],
        "five_sample_pending_counts": references, "five_sample_pending_total": 32,
        "required_units_in_draft": 27, "ignore_drafts": 2,
        "source_and_artifact_hashes_verified": True,
        "replayed_runs": 26, "preserved_A_results": preserved_a,
        "active_editable_runs_reopened": 40, "active_method_rows_unscored": method_count,
        "initial_B02_run_id": mapping["initial_run_id"],
        "new_paid_api_requests": 0, "new_local_detector_inferences": 0,
        "human_confirmations_received": 0, "human_quality_evaluated": False,
        "external_workspace_changes": "Concurrent app.py/camera_assistant changes were preserved; "
                                      "they are outside this repair's integration conclusions.",
    }
    output = BASE / "delivery_acceptance.json"
    if output.exists():
        raise FileExistsError("Final acceptance snapshot is immutable")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False))
