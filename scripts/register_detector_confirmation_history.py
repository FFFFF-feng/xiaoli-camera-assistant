"""Register offline replay and editable AI-reference copies without overwriting history."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from replay_detector_preacceptance import (
    compare_manifests,
    csv_bytes,
    offline_guard,
    sha256,
    source_manifest,
    value_hash,
    write_json_new,
)

from vision_lab_tool.detector_models import DetectorExperiment, DetectorReference
from vision_lab_tool.detector_reference import initialize_reference_workflow, reference_ready
from vision_lab_tool.detector_storage import DetectorStore

PREACCEPTANCE = ROOT / "data/vision_lab/detector_experiments/preacceptance_20261013"


class AppendOnlyDetectorStore(DetectorStore):
    @staticmethod
    def _write(path, data):
        """Publish atomically, rejecting a collision without replacement."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name == "nt":
                # Windows rename rejects an existing destination. Hard links are
                # denied by the workspace sandbox even for two allowed paths.
                os.rename(temporary, path)
            else:
                os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def history_manifest(store):
    files = {p.relative_to(store.root).as_posix(): sha256(p.read_bytes())
             for folder in ("runs", "samples")
             for p in sorted((store.root / folder).glob("*")) if p.is_file()}
    return {"files": files, "file_count": len(files), "store_root": str(store.root)}


def verify_old_history(before, after):
    changed = [{"path": p, "before": digest, "after": after["files"].get(p)}
               for p, digest in before["files"].items() if after["files"].get(p) != digest]
    added = sorted(set(after["files"]) - set(before["files"]))
    return {"original_history_unchanged": not changed, "changed_original_files": changed,
            "old_file_count": before["file_count"], "new_file_count": after["file_count"],
            "new_history_files": added}


def same_inference(left, right):
    return all(getattr(left, key) == getattr(right, key)
               for key in ("image", "task_prompt", "task_prompt_sha256", "configs", "vlm", "results"))


def attach_reference(run, sample, rule_condition, source, reference_path, reference):
    if reference.complete or any(o.confirmed or o.annotation_source != "ai"
                                 for o in reference.objects):
        raise ValueError("Registration requires an entirely unconfirmed AI reference")
    run.reference = reference.model_copy(deep=True)
    run.evaluations = {}
    run.provenance.pop("reference_workflow", None)
    run.provenance.update({
        "sample_id": sample, "rule_condition": rule_condition, "source_run_id": source.run_id,
        "frozen_ai_reference_sha256": sha256(reference_path.read_bytes()),
        "frozen_ai_reference_file": str(reference_path),
        "frozen_ai_reference_content_sha256": value_hash(reference.model_dump(mode="json")),
        "evaluation_scope": "original_complete_task", "human_confirmation_received": False,
        "history_registration": {"mode": "offline_only", "new_api_requests": 0,
                                 "new_detector_inferences": 0,
                                 "source_sample_file": source.sample_file},
    })
    if rule_condition == "fixed":
        reused = run.provenance["offline_replay"]["reuse"]
        source_results = {r["derived_result_id"]: r["source_result_id"] for r in reused}
    else:
        source_results = {r.result_id: r.result_id for r in source.results}
    run.provenance["source_result_ids"] = source_results
    initialize_reference_workflow(run)
    return source_results


def load_reference(sample, package, source_experiment):
    path = package / sample / "reference.json"
    if path.is_file():
        value = json.loads(path.read_text("utf-8"))
    else:
        path = source_experiment / "ai_references" / f"{sample}.json"
        value = json.loads(path.read_text("utf-8"))["reference"]
    return path, DetectorReference.model_validate(value)


def verify_saved(store, saved, source, reference):
    reopened = store.load_run(saved.run_id)
    photo = store.load_sample(reopened)
    source_photo = store.load_sample(source)
    if photo is None or source_photo is None:
        raise AssertionError("History photo missing")
    if photo.size != source_photo.size or photo.tobytes() != source_photo.tobytes():
        raise AssertionError("Reopened history photo changed")
    if reopened.model_dump(mode="json") != saved.model_dump(mode="json"):
        raise AssertionError("Reopened history differs from registered run")
    if reopened.reference != reference or reopened.evaluations or reference_ready(reopened):
        raise AssertionError("AI draft or unevaluated state changed on reopening")
    if reopened.provenance["reference_workflow"]["evaluation_scope"] != "original_complete_task":
        raise AssertionError("Reference scope changed")
    return photo


def write_mapping(output, rows, integrity):
    initial = next(r for r in rows if r["recommended_initial"])
    payload = {"schema_version": "confirmation-history-mapping/1",
               "initial_sample": "B02", "initial_version": "v1",
               "initial_rule_condition": "original", "initial_run_id": initial["run_id"],
               "new_run_count": len({r["run_id"] for r in rows}), "method_rows": len(rows),
               "new_api_requests": 0, "new_detector_inferences": 0,
               "human_quality_evaluated": False, "integrity": integrity, "rows": rows}
    write_json_new(output / "history_mapping.json", payload)
    with (output / "history_mapping.csv").open("xb") as handle:
        handle.write(csv_bytes(rows))
    lines = ["# 可编辑确认历史映射", "",
             f"第一张：B02 / v1 / 原规则确认副本，run_id `{initial['run_id']}`。",
             "在8502“检测与联合定位”的历史下拉按样例/版本/规则或run ID定位。",
             "全部参考仍为AI草稿，未收到人工确认；重开、编辑、导出不执行推理。", "",
             "共40条新历史（26修复回放+14五图原规则副本）；115个方法行。", "",
             "| 样例 | 版本/条件 | 规则 | 可重开run ID | 方法 | 照片 |",
             "|---|---|---|---|---|---|"]
    groups = {}
    for row in rows:
        groups.setdefault(row["run_id"], []).append(row)
    for group in groups.values():
        row = group[0]
        methods = ", ".join(r["method"] + ("/" + r["detector"] if r["detector"] else "")
                            for r in group)
        lines.append(f"| {row['sample_id']} | {row['version']}/{row['condition']} | "
                     f"{row['rule_condition']} | `{row['run_id']}` | {methods} | "
                     f"[照片]({row['sample_path']}) |")
    with (output / "history_mapping.md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return payload


def register_histories(store_root, source_experiment, replay, package, output):
    store = AppendOnlyDetectorStore(Path(store_root))
    source_experiment, replay, package, output = (
        Path(p).resolve() for p in (source_experiment, replay, package, output))
    if (output / "history_mapping.json").exists() or output.exists():
        raise FileExistsError("History registration snapshot already exists")
    sources = json.loads((package / "source_runs.json").read_text("utf-8"))["rows"]
    replay_mapping = json.loads((replay / "run_mapping.json").read_text("utf-8"))
    original_sources = {row["run_id"]: row for row in sources}
    if len(replay_mapping) != 26 or len(original_sources) != 14:
        raise ValueError("Expected exactly 26 replay runs and 14 original confirmation sources")
    plan = [("fixed", row) for row in replay_mapping]
    originals = sorted(original_sources.values(), key=lambda row: (
        row["sample_id"] == "B02" and row["version"] == "v1" and row["condition"] == "paired",
        row["sample_id"], row["version"], row["condition"]))
    plan.extend(("original", row) for row in originals)
    before = history_manifest(store)
    frozen_sources = source_manifest(source_experiment)
    frozen_package = source_manifest(package)
    # Validate every source and collision before writing any history.
    prepared = []
    for condition, row in plan:
        sample = row["sample"] if condition == "fixed" else row["sample_id"]
        source_id = row["source_run_id"] if condition == "fixed" else row["run_id"]
        source = store.load_run(source_id)
        source_path = (source_experiment / row["source_path"] if condition == "fixed"
                       else Path(row["source_run_path"]))
        archived = DetectorExperiment.model_validate_json(source_path.read_bytes())
        if not same_inference(source, archived):
            raise ValueError("Historical store source differs from immutable experiment")
        if condition == "original" and sha256(source_path.read_bytes()) != row["source_run_sha256"]:
            raise ValueError("Confirmation package source hash mismatch")
        if store.load_sample(source) is None:
            raise ValueError("Source history photo missing")
        reference_path, reference = load_reference(sample, package, source_experiment)
        if sample in {r["sample_id"] for r in sources}:
            manifest = json.loads((package / sample / "manifest.json").read_text("utf-8"))
            if manifest["task_prompt"] != source.task_prompt or \
                    manifest["input"]["sent_sha256"] != source.image["sent_sha256"]:
                raise ValueError("Confirmation package image/task mismatch")
            file_key = f"{sample}/reference.json"
            artifact_hash = json.loads((package / "manifest.json").read_text("utf-8"))[
                "artifact_hashes"].get(file_key)
            if artifact_hash and sha256(reference_path.read_bytes()) != artifact_hash:
                raise ValueError("Frozen confirmation reference hash mismatch")
        run = (DetectorExperiment.model_validate_json((replay / row["derived_path"]).read_bytes())
               if condition == "fixed" else source.model_copy(deep=True))
        if condition == "fixed":
            for folder, suffix in (("runs", ".json"), ("samples", ".png")):
                if (store.root / folder / (run.run_id + suffix)).exists():
                    raise FileExistsError("Replay run ID already exists in history")
        prepared.append((condition, row, sample, source, reference_path, reference, run))
    write_json_new(output / "history_hashes_before.json", before)
    write_json_new(output / "frozen_source_hashes_before.json", frozen_sources)
    write_json_new(output / "frozen_package_hashes_before.json", frozen_package)
    rows = []
    with offline_guard():
        for condition, row, sample, source, reference_path, reference, run in prepared:
            source_results = attach_reference(run, sample, condition, source, reference_path, reference)
            run.experiment_id = "preacceptance_20261013"
            run.experiment_version = (f"确认:{sample}:{row['version']}:{condition}:"
                                      f"{row['condition']}:preacceptance_20261013")
            if condition == "original":
                run = store.save_review_version(run)
                if not same_inference(run, source):
                    raise AssertionError("Original confirmation copy changed inference results")
            else:
                photo = store.load_sample(source)
                run.sample_file = None
                store.save_sample(run, SimpleNamespace(corrected=photo))
                store.save_run(run)
            verify_saved(store, run, source, reference)
            for result in run.results:
                rows.append({"sample_id": sample, "version": row["version"],
                             "condition": row["condition"], "rule_condition": condition,
                             "run_id": run.run_id, "source_run_id": source.run_id,
                             "result_id": result.result_id,
                             "source_result_id": source_results[result.result_id],
                             "method": result.method, "detector": result.detector,
                             "status": result.status, "selection_status": result.selection.status,
                             "created_at": run.created_at, "experiment_version": run.experiment_version,
                             "history_run_path": str(store.root / "runs" / f"{run.run_id}.json"),
                             "sample_path": str(store.root / "samples" / run.sample_file),
                             "source_sample_path": str(store.root / "samples" / source.sample_file),
                             "original_image_sha256": run.image.get("original_sha256"),
                             "sent_image_sha256": run.image.get("sent_sha256"),
                             "reference_json_path": str(reference_path),
                             "frozen_ai_reference_sha256": sha256(reference_path.read_bytes()),
                             "reference_id": run.provenance["reference_workflow"]["reference_id"],
                             "evaluation_scope": "original_complete_task", "complete": False,
                             "confirmed_objects": 0, "reopen_verified": True,
                             "new_inference_count": 0,
                             "recommended_initial": sample == "B02" and row["version"] == "v1"
                             and row["condition"] == "paired" and condition == "original"})
    after = history_manifest(store)
    integrity = verify_old_history(before, after)
    integrity["source_experiment_unchanged"] = compare_manifests(
        frozen_sources, source_manifest(source_experiment))["source_files_unchanged"]
    integrity["confirmation_package_unchanged"] = compare_manifests(
        frozen_package, source_manifest(package))["source_files_unchanged"]
    integrity["all_40_runs_and_photos_reopen"] = len({r["run_id"] for r in rows}) == 40
    integrity["all_reference_fields_unconfirmed"] = True
    write_json_new(output / "history_hashes_after.json", after)
    write_json_new(output / "history_integrity.json", integrity)
    if not all(integrity[key] for key in (
        "original_history_unchanged", "source_experiment_unchanged", "confirmation_package_unchanged",
        "all_40_runs_and_photos_reopen")):
        raise AssertionError("History registration integrity check failed")
    rows.sort(key=lambda r: (not r["recommended_initial"], r["sample_id"], r["version"] != "v1",
                             r["version"], r["condition"], r["rule_condition"], r["method"], r["detector"]))
    return write_mapping(output, rows, integrity)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, default=ROOT / "data/vision_lab")
    parser.add_argument("--source", type=Path,
                        default=ROOT / "data/vision_lab/detector_experiments/iteration_20261013_01")
    parser.add_argument("--replay", type=Path, default=PREACCEPTANCE / "replay")
    parser.add_argument("--package", type=Path, default=PREACCEPTANCE / "confirmation_package")
    parser.add_argument("--output", type=Path, default=PREACCEPTANCE / "history_registration")
    args = parser.parse_args()
    result = register_histories(args.store_root, args.source, args.replay, args.package, args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}))


if __name__ == "__main__":
    main()
