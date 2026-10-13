"""Replay saved association inputs only; never infer, reparse VLMs, or alter sources.

Original query arrays are the actual detector inputs. Only task_text is supplied
to the new association rules. Proposed query changes remain a separate plan.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import inspect
import io
import json
import socket
import subprocess
import sys
import time
from collections import Counter
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx

from vision_lab_tool import detector_queries, detector_runner
from vision_lab_tool.detector_models import DetectorExperiment
from vision_lab_tool.detectors.client import DetectorClient

REPLAY_VERSION = "saved-input-association-replay-v1"
DEFAULT_SOURCE = ROOT / "data/vision_lab/detector_experiments/iteration_20261013_01"
DEFAULT_OUTPUT = ROOT / "data/vision_lab/detector_experiments/preacceptance_20261013/replay"
QUERY_ARRAYS = ("from_task", "from_vlm", "manual", "merged", "fallback")
FOCUS_SAMPLES = ("B02", "D03", "D07", "C03", "P06")
HUMAN_METRICS = {
    name: None for name in (
        "localization_iou", "tp", "fp", "fn", "recall", "accuracy",
        "subject_correct_auto", "subject_correct_human", "complete_task_success",
        "query_support_coverage", "fixed_class_support_coverage", "candidate_usefulness",
    )
}


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def value_hash(value):
    return sha256(json_bytes(value))


def write_json_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2,
                                allow_nan=False).encode("utf-8"))


def source_manifest(source):
    files = {p.relative_to(source).as_posix(): sha256(p.read_bytes())
             for p in sorted(source.rglob("*")) if p.is_file()}
    return {"schema_version": "immutable-source-hashes/1",
            "source_experiment": str(source), "file_count": len(files), "files": files,
            "request_ledger_sha256": files.get("request_ledger.json")}


def compare_manifests(before, after):
    left, right = before["files"], after["files"]
    changes = [{"path": p, "before": left.get(p), "after": right.get(p)}
               for p in sorted(set(left) | set(right)) if left.get(p) != right.get(p)]
    return {"source_files_unchanged": not changes, "changed_files": changes,
            "source_file_count_before": len(left), "source_file_count_after": len(right),
            "request_ledger_sha256_before": before.get("request_ledger_sha256"),
            "request_ledger_sha256_after": after.get("request_ledger_sha256"),
            "request_ledger_unchanged": before.get("request_ledger_sha256") ==
                                        after.get("request_ledger_sha256")}


def forbidden_inference(*args, **kwargs):
    raise RuntimeError("Offline replay prohibits HTTP, model inference, downloads and workers")


@contextmanager
def offline_guard():
    """Fail closed if replay accidentally reaches a transport or inference entrypoint."""
    entries = (
        (httpx.Client, "request"), (httpx.Client, "send"),
        (httpx.AsyncClient, "request"), (httpx.AsyncClient, "send"),
        (socket.socket, "connect"), (socket.socket, "connect_ex"),
        (socket, "create_connection"), (subprocess, "Popen"),
        (DetectorClient, "detect"), (DetectorClient, "_start"),
        (detector_runner, "invoke_localization"), (detector_runner, "run_experiment"),
        (detector_runner, "detect_mock"), (detector_runner, "parse_snapshot"),
        (detector_runner, "localization_provenance"),
        (detector_queries, "compose_queries"),
    )
    with ExitStack() as stack:
        for target, name in entries:
            stack.enter_context(patch.object(target, name, forbidden_inference))
        yield


def rule_snapshot():
    """Whole executable modules include helper implementations and constants."""
    from vision_lab_tool import detector_scope

    modules = (detector_runner, detector_queries, detector_scope)
    files = {}
    for module in modules:
        path = Path(module.__file__).resolve()
        content = path.read_bytes()
        files[path.relative_to(ROOT).as_posix()] = {
            "sha256": sha256(content), "source": content.decode("utf-8")}
    bundle = {"association_rule_version": detector_runner.ASSOCIATION_RULE_VERSION,
              "dictionary_version": detector_queries.DICTIONARY_VERSION,
              "scope_versions": {name: value for name, value in vars(detector_scope).items()
                                 if name.endswith("VERSION") and isinstance(value, str)},
              "files": files}
    return {**bundle, "bundle_sha256": value_hash(bundle),
            "association_function_source": inspect.getsource(detector_runner._associate),
            "replay_version": REPLAY_VERSION,
            "replay_script_sha256": sha256(Path(__file__).read_bytes()),
            "hash_policy": "SHA256 of exact executable module bytes; bundle uses canonical JSON. "
                           "All helper code is included; no prompt/schema regeneration."}


def method_state(result):
    return {"result_id": result.result_id, "method_status": result.status,
            "detector_status": result.detection.status if result.detection else None,
            "selection_status": result.selection.status,
            "selected_ids": result.selection.selected_ids,
            "candidate_ids": [o.object_id for o in result.candidates],
            "candidate_count": len(result.candidates),
            "unsupported_targets": result.unsupported_targets,
            "reason": result.selection.reason, "stages": result.stages}


def candidate_changes(old, new):
    """Geometry and semantic decoration are reported separately."""
    left = {o.object_id: o.model_dump(mode="json") for o in old.candidates}
    right = {o.object_id: o.model_dump(mode="json") for o in new.candidates}
    geometry, labels, semantics = [], [], []
    for object_id in sorted(set(left) | set(right)):
        a, b = left.get(object_id), right.get(object_id)
        if a is None or b is None:
            geometry.append({"object_id": object_id, "before": a, "after": b})
            continue
        for fields, rows in (
            (("bbox", "bbox_native", "bbox_postprocessed", "coordinate_basis"), geometry),
            (("label_original", "label_display"), labels),
            (("target_level", "entity_kind", "parent_object_id", "semantic_source"), semantics),
        ):
            changed = {key: {"before": a[key], "after": b[key]}
                       for key in fields if a[key] != b[key]}
            if changed:
                rows.append({"object_id": object_id, "fields": changed})
    return {"candidate_coordinates_changed": bool(geometry), "coordinate_changes": geometry,
            "candidate_labels_changed": bool(labels), "label_field_changes": labels,
            "candidate_semantics_changed": bool(semantics), "semantic_field_changes": semantics}


def proposed_query_plan(queries):
    original = queries.get("merged", [])
    normalized = list(dict.fromkeys(detector_queries.canonical(q) for q in original))
    return {"actual_saved_queries": original,
            "proposed_new_queries": normalized if normalized != original else None,
            "requires_new_detection": normalized != original,
            "executed": False, "new_inference_count": 0,
            "status": "plan_only_not_validated" if normalized != original else "no_alias_query_change",
            "limitation": "This replay keeps exact saved queries and candidates; a new query "
                          "requires separately authorized new inference and cannot be scored here."}


def replay_run(source, source_path, rules, identity):
    """Read no reference annotations when choosing task scope or associations."""
    started = time.perf_counter()
    source_value = source.model_dump(mode="json")
    source_hash = value_hash(source_value)
    derived = source.model_copy(deep=True)
    derived.run_id, derived.attempt_id = uuid4().hex, uuid4().hex
    derived.experiment_id = "preacceptance_20261013"
    derived.experiment_version = (f"preacceptance_20261013:offline:{identity['version']}:"
                                  f"{identity['sample']}:{identity['condition']}")
    derived.created_at = datetime.now(UTC).isoformat()
    derived.results = []
    derived.evaluations = {}
    rows, reuse = [], []
    for old in source.results:
        query_input = copy.deepcopy(old.queries)
        if old.detection is not None:
            query_input["task_text"] = source.task_prompt
        query_input_hash = value_hash(query_input)
        if old.detection is None:
            new = old.model_copy(deep=True)
            new.result_id = uuid4().hex
            action = "A_preserved_without_reparse"
        else:
            detection_input = old.detection.model_copy(deep=True)
            snapshot_input = source.vlm.model_copy(deep=True) if source.vlm else None
            before_inputs = value_hash({"detection": detection_input.model_dump(mode="json"),
                                       "vlm": snapshot_input.model_dump(mode="json")
                                       if snapshot_input else None})
            new = detector_runner._associate(detection_input, snapshot_input,
                                              query_input, old.method)
            after_inputs = value_hash({"detection": detection_input.model_dump(mode="json"),
                                      "vlm": snapshot_input.model_dump(mode="json")
                                      if snapshot_input else None})
            if before_inputs != after_inputs:
                raise AssertionError("Association mutated reused VLM/detection input")
            for key in QUERY_ARRAYS:
                if new.queries.get(key) != old.queries.get(key):
                    raise AssertionError(f"Actual saved query array changed: {key}")
            action = "saved_detection_association_replayed"
        derived.results.append(new)
        normalization = copy.deepcopy(new.queries.get("label_normalization", {}))
        normalization_entries = list(normalization.values()) if isinstance(normalization, dict) else []
        semantic_normalization = [
            {"object_id": sem.object_id, "query_original": sem.query,
             "query_normalized": detector_queries.canonical(sem.query),
             "changed": sem.query != detector_queries.canonical(sem.query),
             "rule_source": "detector_queries.canonical; complete frozen aliases"}
            for sem in (source.vlm.semantics if source.vlm and old.detection else [])
        ]
        record = {
            **identity, "source_path": source_path, "source_run_id": source.run_id,
            "derived_run_id": derived.run_id, "source_result_id": old.result_id,
            "derived_result_id": new.result_id, "method": old.method, "detector": old.detector,
            "source_detection_id": old.detection.result_id if old.detection else None,
            "source_vlm_id": source.vlm.result_id if source.vlm else None,
            "input_hashes": {
                "source_run_canonical_sha256": source_hash,
                "source_method_sha256": value_hash(old.model_dump(mode="json")),
                "vlm_sha256": value_hash(source.vlm.model_dump(mode="json")) if source.vlm else None,
                "detection_sha256": value_hash(old.detection.model_dump(mode="json"))
                if old.detection else None, "saved_queries_sha256": value_hash(old.queries),
                "association_queries_sha256": query_input_hash,
                "association_output_queries_sha256": value_hash(new.queries),
                "task_prompt_sha256": sha256(source.task_prompt.encode("utf-8")),
                "image_sha256": source.image.get("sent_sha256"),
                "config_sha256": value_hash(old.detection.config.model_dump(mode="json"))
                if old.detection else None,
            }, "action": action, "old": method_state(old), "new": method_state(new),
            "method_status_changed": old.status != new.status,
            "selection_status_changed": old.selection.status != new.selection.status,
            "subject_selection_changed": old.selection.selected_ids != new.selection.selected_ids,
            **candidate_changes(old, new),
            "label_normalization": normalization,
            "candidate_label_normalized_count": sum(
                entry.get("normalized") != entry.get("original") for entry in normalization_entries),
            "compound_label_decoded_count": sum(
                len(entry.get("components", [])) > 1 for entry in normalization_entries),
            "semantic_query_normalization": semantic_normalization,
            "semantic_query_normalized_count": sum(entry["changed"] for entry in semantic_normalization),
            "task_scope": copy.deepcopy(new.queries.get("task_scope", {})),
            "query_plan": proposed_query_plan(old.queries),
            "queries_preserved": {key: old.queries.get(key) for key in QUERY_ARRAYS},
            "human_metrics": HUMAN_METRICS.copy(), "new_inference_count": 0,
        }
        rows.append(record)
        reuse.append({key: record[key] for key in (
            "source_result_id", "derived_result_id", "source_detection_id", "source_vlm_id",
            "input_hashes", "action")})
    if source_hash != value_hash(source.model_dump(mode="json")):
        raise AssertionError("Source model mutated")
    elapsed = time.perf_counter() - started
    derived.provenance = {
        **copy.deepcopy(source.provenance),
        "offline_replay": {
            "version": REPLAY_VERSION, "source_run_id": source.run_id,
            "source_attempt_id": source.attempt_id, "source_path": source_path,
            "source_run_sha256": source_hash, "source_provenance": source.provenance,
            "actual_sent_prompt_and_schema": "Original source provenance retained verbatim",
            "association_rule_version": rules["association_rule_version"],
            "dictionary_version": rules["dictionary_version"],
            "rules_bundle_sha256": rules["bundle_sha256"],
            "rules_source_files": {key: value["sha256"] for key, value in rules["files"].items()},
            "rule_snapshot_file": "rule_snapshot.json", "reuse": reuse,
            "new_vlm_requests": 0, "new_local_detector_inferences": 0,
            "source_timings": source.timings, "offline_replay_seconds": elapsed,
        },
    }
    derived.timings = {"offline_replay_seconds": elapsed}
    derived.costs = {"execution_mode": "offline_saved_input_replay", "new_vlm_requests": 0,
                     "new_local_detector_inferences": 0, "new_paid_requests": 0,
                     "source_recorded_costs": source.costs, "source_reuse_count": len(reuse)}
    derived.stages = {"offline_replay": "completed", "human_quality": "unevaluated"}
    DetectorExperiment.model_validate(derived.model_dump(mode="json"))
    return derived, rows


def csv_bytes(rows):
    output = io.StringIO(newline="")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        values = {}
        for key, value in row.items():
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False, allow_nan=False)
            value = "" if value is None else str(value)
            values[key] = "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        writer.writerow(values)
    return output.getvalue().encode("utf-8-sig")


def run_replay(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Replay destination must be separate from the immutable source")
    if (output / "replay_comparison.json").exists() or (output / "runs").exists():
        raise FileExistsError("Replay snapshot exists; choose a new destination")
    baseline_path = output / "source_hashes_before.json"
    if baseline_path.exists():
        before = json.loads(baseline_path.read_text("utf-8"))
        if not compare_manifests(before, source_manifest(source))["source_files_unchanged"]:
            raise ValueError("Source differs from pre-saved immutable hash manifest")
    else:
        before = source_manifest(source)
        write_json_new(baseline_path, before)
    rules = rule_snapshot()
    write_json_new(output / "rule_snapshot.json", rules)
    rows, mappings = [], []
    with offline_guard():
        for source_file in sorted((source / "outputs").glob("*/*/*/run.json")):
            version, sample, condition = source_file.parent.relative_to(source / "outputs").parts
            identity = {"version": version, "sample": sample, "condition": condition}
            old = DetectorExperiment.model_validate_json(source_file.read_bytes())
            new, changes = replay_run(old, source_file.relative_to(source).as_posix(), rules, identity)
            file_hash = sha256(source_file.read_bytes())
            new.provenance["offline_replay"]["source_file_sha256"] = file_hash
            for row in changes:
                row["input_hashes"]["source_run_file_sha256"] = file_hash
            derived_file = output / "runs" / version / sample / condition / "run.json"
            write_json_new(derived_file, new.model_dump(mode="json"))
            rows.extend(changes)
            mappings.append({**identity, "source_run_id": old.run_id,
                             "derived_run_id": new.run_id,
                             "source_path": source_file.relative_to(source).as_posix(),
                             "derived_path": derived_file.relative_to(output).as_posix(),
                             "source_file_sha256": sha256(source_file.read_bytes()),
                             "derived_file_sha256": sha256(derived_file.read_bytes()),
                             "task_prompt": old.task_prompt, "sample_file": old.sample_file,
                             "source_vlm_status": old.vlm.status if old.vlm else None,
                             "reference_complete": old.reference.complete,
                             "confirmed_reference_objects": sum(o.confirmed for o in old.reference.objects)})
    after = source_manifest(source)
    integrity = compare_manifests(before, after)
    write_json_new(output / "source_hashes_after.json", after)
    write_json_new(output / "integrity.json", integrity)
    if not integrity["source_files_unchanged"]:
        raise AssertionError("Immutable source changed during replay; see integrity.json")
    totals = {"run_count": len(mappings), "method_count": len(rows),
              "association_replay_count": sum(r["source_detection_id"] is not None for r in rows),
              "A_preserved_count": sum(r["method"] == "A" for r in rows),
              "candidate_label_normalized_count": sum(r["candidate_label_normalized_count"]
                                                       for r in rows),
              "compound_label_decoded_count": sum(r["compound_label_decoded_count"] for r in rows),
              "semantic_query_normalized_count": sum(r["semantic_query_normalized_count"]
                                                     for r in rows),
              **{key + "_count": sum(r[key] for r in rows) for key in (
                  "method_status_changed", "selection_status_changed", "subject_selection_changed",
                  "candidate_coordinates_changed", "candidate_labels_changed",
                  "candidate_semantics_changed")},
              "new_vlm_requests": 0, "new_local_detector_inferences": 0, "new_paid_requests": 0,
              "human_metrics": HUMAN_METRICS.copy()}
    transitions = Counter((r["method"], r["detector"], r["old"]["selection_status"],
                           r["new"]["selection_status"]) for r in rows)
    summary = {"schema_version": "detector-offline-replay/1", "replay_version": REPLAY_VERSION,
               "created_at": datetime.now(UTC).isoformat(), "source_experiment": str(source),
               "rules_bundle_sha256": rules["bundle_sha256"], "totals": totals,
               "integrity": integrity, "run_mapping": mappings,
               "selection_transitions": [{"method": a, "detector": b, "old": c, "new": d,
                                          "count": count}
                                         for (a, b, c, d), count in sorted(transitions.items())],
               "methods": rows, "quality_note": "No human truth; all quality metrics are null. "
               "State changes and semantic decorations are program diagnostics, not accuracy."}
    write_json_new(output / "replay_comparison.json", summary)
    focus = [r for r in rows if r["sample"] in FOCUS_SAMPLES]
    write_json_new(output / "five_sample_comparison.json", focus)
    write_json_new(output / "run_mapping.json", mappings)
    for name, records in (("replay_comparison.csv", rows), ("five_sample_comparison.csv", focus),
                          ("run_mapping.csv", mappings)):
        with (output / name).open("xb") as handle:
            handle.write(csv_bytes(records))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    summary = run_replay(args.source, args.output)
    print(json.dumps({"output": str(args.output), **summary["totals"],
                      "integrity": summary["integrity"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
