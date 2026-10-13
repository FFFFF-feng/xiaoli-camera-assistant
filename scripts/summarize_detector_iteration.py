"""Read-only engineering summary of an existing bounded detector experiment.

No image decoding, model loading, VLM requests or quality re-scoring occurs here.
Each invocation writes a new summary snapshot; existing evidence is never replaced.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision_lab_tool.detector_models import DetectorExperiment
from vision_lab_tool.detector_storage import export_csv, export_json

EXPERIMENTS = ROOT / "data/vision_lab/detector_experiments"
METHODS = ("A", "B1", "B2")
SUCCESS = {"success", "ok", "empty"}
TRANSPORT_FAILURES = {
    "authentication", "http_error", "network_error", "timeout", "response_error",
    "runtime_error", "refused", "truncated",
}


def _inside(path: Path, root: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path must remain within {root}")
    return path


def _read_json(path: Path, default=None):
    return json.loads(path.read_text("utf-8")) if path.exists() else default


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False)
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def _csv(rows):
    output = io.StringIO(newline="")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    if fields:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: _cell(row.get(key)) for key in fields} for row in rows)
    return output.getvalue().encode("utf-8-sig")


def _load_runs(experiment: Path):
    runs, sources, errors, inputs = [], {}, [], []
    seen = set()
    # A latest stage is retained when execution never produced a final run.json.
    folders = set((experiment / "outputs").glob("*/*/paired"))
    folders.update((experiment / "outputs").glob("*/*/pure"))
    for folder in sorted(folders):
        path = folder / "run.json"
        final = path.is_file()
        if not final:
            stages = sorted((folder / "stages").glob("*.json"))
            if not stages:
                continue
            path = stages[-1]
        _inside(path, experiment)
        version, sample, condition = folder.relative_to(experiment / "outputs").parts
        content = path.read_bytes()
        inputs.append({"path": path.relative_to(experiment).as_posix(),
                       "sha256": hashlib.sha256(content).hexdigest()})
        try:
            run = DetectorExperiment.model_validate_json(content)
        except (ValueError, OSError) as exc:
            errors.append({"path": path.relative_to(experiment).as_posix(),
                           "error": type(exc).__name__, "retained": True})
            continue
        if run.run_id in seen:
            errors.append({"path": path.relative_to(experiment).as_posix(),
                           "error": "duplicate_run_id", "retained": True})
            continue
        seen.add(run.run_id)
        sources[run.run_id] = {"version": version, "sample": sample, "condition": condition,
                               "source": path.relative_to(experiment).as_posix(),
                               "record_state": "final" if final else "interrupted_stage"}
        runs.append(run)
    return runs, sources, errors, inputs


def _raw_vlm_coordinates(vlm):
    """Diagnostic only: binding/schema errors never become coordinate errors."""
    if not vlm or vlm.json_status != "success" or not isinstance(vlm.parsed, dict):
        return {"status": "not_evaluable", "valid": 0, "invalid": 0, "null": 0}
    objects = vlm.parsed.get("objects")
    if not isinstance(objects, list):
        return {"status": "invalid_structure", "valid": 0, "invalid": 0, "null": 0}
    valid = invalid = null = 0
    for obj in objects:
        box = obj.get("bbox") if isinstance(obj, dict) else "missing"
        if box is None:
            null += 1
            continue
        legal = (isinstance(box, list) and len(box) == 4 and all(
            isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in box)
            and box[0] < box[2] and box[1] < box[3])
        valid += int(legal)
        invalid += int(not legal)
    return {"status": "invalid" if invalid else "success" if valid else "null_or_empty",
            "valid": valid, "invalid": invalid, "null": null,
            "scope": "numeric geometry only; schema/identity/quality acceptance unchanged"}


def _method_rows(runs, sources):
    rows = []
    for run in runs:
        source = sources[run.run_id]
        vlm = run.vlm
        for method in run.results:
            detection = method.detection
            row = {
                **source, "run_id": run.run_id, "result_id": method.result_id,
                "dataset_split": run.dataset_split, "method": method.method,
                "detector": method.detector, "mode": run.mode,
                "simulated": run.simulated or not method.real,
                "run_status": run.stages.get("run", "unknown"),
                "status": method.status, "json_status": vlm.json_status if vlm else "not_applicable",
                "semantic_status": vlm.semantic_status if vlm else "not_applicable",
                "vlm_box_status": vlm.box_status if vlm else "not_applicable",
                "subject_format_status": vlm.selection_status if vlm else "not_applicable",
                "selection_status": method.selection.status,
                "selection_reason": method.selection.reason,
                "selected_count": len(method.selection.selected_ids),
                "candidate_count": len(method.candidates),
                "raw_candidate_count": len(detection.raw_candidates) if detection else None,
                "invalid_coordinate_count": detection.metadata.get("invalid_coordinate_count")
                if detection else None,
                "coordinate_status": detection.status if detection else
                (_raw_vlm_coordinates(vlm)["status"] if vlm else "not_applicable"),
                "vlm_raw_coordinate_diagnostic": _raw_vlm_coordinates(vlm) if vlm else None,
                "vlm_status": vlm.status if vlm else "not_applicable",
                "vlm_cache_hit": vlm.cache_hit if vlm else False,
                "vlm_result_id": vlm.result_id if vlm else None,
                "detection_cache_hit": detection.cache_hit if detection else False,
                "detection_cache_source": detection.cache_source if detection else None,
                "detection_device": detection.config.device if detection else None,
                "semantic_object_count": len(vlm.semantics) if vlm else None,
                "queries_from_task": method.queries.get("from_task", []),
                "queries_from_vlm": method.queries.get("from_vlm", []),
                "queries_merged": method.queries.get("merged", []),
                "unsupported_targets": method.unsupported_targets,
                "method_stages": method.stages, "method_timings": method.timings,
                "run_timings": run.timings, "vlm_usage": vlm.usage.model_dump() if vlm else None,
                "vlm_seconds": vlm.elapsed_seconds if vlm else None,
                "run_wait_seconds": run.timings.get("total"),
                "prompt_version": run.provenance.get("localization_prompt_version"),
                "prompt_sha256": run.provenance.get("localization_prompt_sha256"),
                "sent_sha256": run.image.get("sent_sha256"),
                "task_prompt_sha256": run.task_prompt_sha256,
                "human_quality_metrics": "unevaluated",
                "ai_reference_confirmed": False,
            }
            for stage in ("load", "preprocess", "inference", "postprocess", "selection",
                          "query_conversion", "worker_and_ipc_overhead"):
                row[f"{stage}_seconds"] = method.timings.get(stage)
            rows.append(row)
    return rows


def _request_summary(runs, ledger, sources):
    requests, unaccounted_ledger, unknown = [], [], []
    seen_attempts, observed_units = set(), set()
    for run in runs:
        vlm = run.vlm
        if not vlm or not vlm.real or vlm.cache_hit or run.simulated:
            continue
        source = sources[run.run_id]
        unit = f"{source['version']}/{source['sample']}/{source['condition']}"
        attempts = [a for a in vlm.attempts if a.get("request_sent") is True]
        if attempts:
            observed_units.add(unit)
        for index, attempt in enumerate(attempts):
            identity = attempt.get("attempt_id") or f"{vlm.result_id}:{index}"
            if identity in seen_attempts:
                continue
            seen_attempts.add(identity)
            requests.append({"unit": unit, "attempt_id": identity, "status": attempt.get("status"),
                             "vlm_status": vlm.status, "cost": vlm.cost,
                             "cost_scope": vlm.result_id,
                             "currency": vlm.config.price.currency, "source": "run_attempt"})
    for entry in ledger:
        if entry.get("condition") != "paired" or entry.get("unit") in observed_units:
            continue
        if entry.get("request_sent") is True:
            unit = entry.get("unit")
            if any(r["unit"] == unit for r in requests):
                continue
            unaccounted_ledger.append(unit)
            requests.append({"unit": unit, "attempt_id": None,
                             "status": entry.get("vlm_status", "unknown"),
                             "vlm_status": entry.get("vlm_status", "unknown"),
                             "cost": entry.get("cost"), "cost_scope": unit,
                             "currency": "unknown", "source": "request_ledger"})
        elif entry.get("request_sent") is not False:
            unknown.append(entry.get("unit"))
    currencies, billed = defaultdict(lambda: {"known_amount": 0.0, "known_calls": 0,
                                              "unknown_calls": 0}), set()
    for request in requests:
        if request["cost_scope"] in billed:
            continue
        billed.add(request["cost_scope"])
        cost = request["cost"]
        amount = cost.get("amount") if isinstance(cost, dict) else None
        currency = cost.get("currency", request["currency"]) if cost else request["currency"]
        total = currencies[currency]
        if isinstance(amount, (int, float)) and math.isfinite(amount):
            total["known_amount"] += amount
            total["known_calls"] += 1
        else:
            total["unknown_calls"] += 1
    for total in currencies.values():
        total["total_amount"] = total["known_amount"] if not total["unknown_calls"] else None
        if not total["known_calls"]:
            total["known_amount"] = None
    return {"real_vlm_request_count": len(requests),
            "non_success_request_count": sum(r["status"] not in SUCCESS for r in requests),
            "transport_or_response_failure_count": sum(r["status"] in TRANSPORT_FAILURES
                                                       for r in requests),
            "request_status_counts": dict(Counter(r["status"] for r in requests)),
            "requests": requests, "request_sent_unknown_units": unknown,
            "ledger_only_requests": unaccounted_ledger,
            "currencies": dict(currencies), "local_compute_cost": None,
            "cost_note": "Known amounts are configured estimates, not verified bills; unknown is not 0."}


def _local_summary(runs, local_ledger):
    observed, seen = [], set()
    for run in runs:
        for method in run.results:
            detection = method.detection
            if not detection or not detection.real:
                continue
            identity = detection.result_id
            if identity in seen:
                continue
            seen.add(identity)
            observed.append({"detector": detection.config.detector,
                             "device": detection.config.device, "status": detection.status,
                             "cache_hit": detection.cache_hit, "result_id": identity})
    new = [r for r in observed if not r["cache_hit"]]
    caches = [r for r in observed if r["cache_hit"]]
    ledger_ids = {r.get("result_id") for r in local_ledger}
    absent = list({r.get("result_id"): r for r in local_ledger
                   if r.get("result_id") not in seen}.values())
    return {"new_detection_attempt_count": len(new) + len(absent),
            "new_detection_result_count": len(new), "cache_result_count": len(caches),
            "cpu_new_detection_result_count": sum(r["device"] == "cpu" for r in new),
            "cpu_cache_result_count": sum(r["device"] == "cpu" for r in caches),
            "new_results_by_detector": dict(Counter(r["detector"] for r in new)),
            "cache_results_by_detector": dict(Counter(r["detector"] for r in caches)),
            "new_result_status_counts": dict(Counter(r["status"] for r in new)),
            "local_inference_ledger_count": len(local_ledger),
            "unique_ledger_result_count": len(ledger_ids), "ledger_results_without_run": absent,
            "ledger_only_device_unknown_count": len(absent),
            "count_note": "New results include failed runtime attempts; cache hits are not new inference."}


def _paired_changes(rows, samples, candidate):
    by_unit = {(r["version"], r["sample"], r["method"]): r for r in rows
               if r["condition"] == "paired"}
    comparisons = []
    fields = ("status", "json_status", "semantic_status", "vlm_box_status",
              "subject_format_status", "selection_status", "selected_count", "candidate_count",
              "invalid_coordinate_count", "unsupported_targets", "queries_merged")
    comparable = ("json_status", "semantic_status", "vlm_box_status", "subject_format_status")
    for sample in samples:
        for method in METHODS:
            old, new = by_unit.get(("v0", sample, method)), by_unit.get((candidate, sample, method))
            record = {"sample": sample, "method": method, "baseline": "v0", "candidate": candidate,
                      "human_quality_change": "unevaluated", "ai_reference_confirmed": False}
            if old is None or new is None:
                record.update(engineering_change="missing", baseline_present=old is not None,
                              candidate_present=new is not None)
            else:
                changes = {k: {"v0": old[k], candidate: new[k]} for k in fields if old[k] != new[k]}
                up = any(old[k] != "success" and new[k] == "success" for k in comparable)
                down = any(old[k] == "success" and new[k] != "success" for k in comparable)
                direction = "mixed" if up and down else "improved" if up else "regressed" if down \
                    else "changed" if changes else "unchanged"
                same_image = bool(old["sent_sha256"] and
                                  old["sent_sha256"] == new["sent_sha256"])
                same_task = bool(old["task_prompt_sha256"] and
                                 old["task_prompt_sha256"] == new["task_prompt_sha256"])
                if not same_image or not same_task:
                    direction = "incomparable_inputs"
                record.update(engineering_change=direction, changes=changes,
                              same_sent_jpeg=same_image, same_task=same_task,
                              baseline_run_id=old["run_id"], candidate_run_id=new["run_id"])
            comparisons.append(record)
    return comparisons


def _threshold_grid(runs, sources):
    """Count saved raw development candidates; neither inference nor quality scoring."""
    rows = []
    for run in runs:
        if run.dataset_split != "开发":
            continue
        for method in run.results:
            detection = method.detection
            if not detection or not detection.real or run.simulated:
                continue
            is_dino = detection.config.detector == "grounding_dino"
            if is_dino and detection.config.text_threshold != 0.25:
                rows.append({**sources[run.run_id], "detector": detection.config.detector,
                             "status": "skipped_text_threshold_not_0.25"})
                continue
            size = detection.metadata.get("source_image_size") or run.image.get("sent_size")
            for threshold in ((0.25, 0.35, 0.45) if is_dino else (0.15, 0.25, 0.35)):
                selected, legal, illegal, unknown_coordinates = [], 0, 0, 0
                for raw in detection.raw_candidates:
                    score = raw.get("score")
                    if not isinstance(score, (int, float)) or not math.isfinite(score):
                        continue
                    if not (score > threshold if is_dino else score >= threshold):
                        continue
                    selected.append(raw)
                    box = raw.get("bbox_postprocessed")
                    if raw.get("raw_coordinates_valid") is False:
                        illegal += 1
                    elif size and isinstance(box, list) and len(box) == 4 and all(
                            isinstance(v, (int, float)) and math.isfinite(v) for v in box):
                        legal_box = (0 <= box[0] < box[2] <= size[0]
                                     and 0 <= box[1] < box[3] <= size[1])
                        legal += int(legal_box)
                        illegal += int(not legal_box)
                    else:
                        unknown_coordinates += 1
                rows.append({**sources[run.run_id], "run_id": run.run_id,
                             "detection_result_id": detection.result_id,
                             "detector": detection.config.detector,
                             "threshold": threshold, "threshold_operator": ">" if is_dino else ">=",
                             "text_threshold": 0.25 if is_dino else None,
                             "raw_candidate_count": len(detection.raw_candidates),
                             "above_threshold_count": len(selected), "legal_coordinate_count": legal,
                             "invalid_coordinate_count": illegal,
                             "unknown_coordinate_count": unknown_coordinates,
                             "label_counts": dict(Counter(r.get("label_original", "")
                                                          for r in selected)),
                             "new_inference_count": 0, "quality_evaluated": False})
    return rows


def summarize(experiment: Path):
    runs, sources, errors, inputs = _load_runs(experiment)
    request_path = experiment / "request_ledger.json"
    ledger = _read_json(request_path, [])
    local_path = experiment / "local_inference_ledger.jsonl"
    local_ledger = []
    if local_path.exists():
        for number, line in enumerate(local_path.read_text("utf-8").splitlines(), 1):
            if line.strip():
                try:
                    local_ledger.append(json.loads(line))
                except ValueError:
                    errors.append({"path": local_path.name, "line": number,
                                   "error": "invalid_jsonl", "retained": True})
    rows = _method_rows(runs, sources)
    manifest = _read_json(experiment / "manifest_original.json", {})
    freeze = _read_json(experiment / "candidate_freeze.json", {})
    candidate = freeze.get("candidate", "v1")
    samples = [s["sample_id"] for s in manifest.get("samples", [])]
    samples = samples or sorted({r["sample"] for r in rows})
    summary = {
        "schema_version": "detector-iteration-engineering/1",
        "created_at": datetime.now(UTC).isoformat(), "experiment": experiment.name,
        "scope": "engineering only; no images or model judgments consumed to tune configuration",
        "human_quality_metrics": "unevaluated", "ai_reference_confirmed": False,
        "quality_note": "AI drafts remain unconfirmed; these summaries do not establish accuracy.",
        "candidate": candidate, "candidate_frozen": bool(freeze),
        "loaded_run_count": len(runs), "record_errors": errors, "source_hashes": inputs,
        "request_summary": _request_summary(runs, ledger, sources),
        "local_detection_summary": _local_summary(runs, local_ledger),
        "methods": rows, "paired_engineering_changes": _paired_changes(rows, samples, candidate),
        "development_offline_threshold_grid": _threshold_grid(runs, sources),
        "threshold_grid_note": "Development raw candidates only; text threshold fixed at 0.25 for "
                               "DINO. No new inference or threshold selection. Counts are not quality "
                               "metrics; held-out outputs are excluded from this grid.",
        "timing_note": "Stage times and shared VLM times are retained per source; repeated method rows "
                       "must not be summed as independent VLM calls or fresh cached inference.",
        "reference_counts": {"objects": sum(len(r.reference.objects) for r in runs),
                             "confirmed_objects": sum(o.confirmed for r in runs
                                                      for o in r.reference.objects),
                             "scope": "Repeated reference copies across runs; not a quality denominator"},
    }
    return summary, runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", default="iteration_20261013_01")
    parser.add_argument("--output", type=Path, help="New destination within the experiment directory")
    args = parser.parse_args()
    experiment_arg = Path(args.experiment)
    experiment = _inside(experiment_arg if experiment_arg.is_absolute() else
                         EXPERIMENTS / experiment_arg, EXPERIMENTS)
    if experiment == EXPERIMENTS.resolve() or not experiment.is_dir():
        raise ValueError("Select an existing, named experiment directory")
    destination = args.output or Path("summaries") / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    destination = _inside(destination if destination.is_absolute() else experiment / destination,
                          experiment)
    names = ("engineering_summary.json", "engineering_summary.csv", "all_runs.json", "all_runs.csv",
             "development_offline_threshold_grid.csv")
    if any((destination / name).exists() for name in names):
        raise FileExistsError("Summary files already exist; choose a new output directory")
    summary, runs = summarize(experiment)
    # Build all exports before writing; source records and failures are never touched.
    payloads = (json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"),
                _csv(summary["methods"]), export_json(runs), export_csv(runs),
                _csv(summary["development_offline_threshold_grid"]))
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in zip(names, payloads):
        path = _inside(destination / name, experiment)
        with path.open("xb") as handle:
            handle.write(content)
    print(json.dumps({"output": str(destination), "runs": len(runs),
                      "real_vlm_requests": summary["request_summary"]["real_vlm_request_count"],
                      "record_errors": len(summary["record_errors"]),
                      "human_quality_metrics": "unevaluated"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
