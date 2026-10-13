"""Bounded real paired experiment; immutable outputs, no automatic paid retry."""
from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision_lab_tool.configuration import resolve_key
from vision_lab_tool.credentials import KeyVault
from vision_lab_tool.detector_models import (
    DetectionResult,
    DetectorConfig,
    DetectorExperiment,
    DetectorReference,
)
from vision_lab_tool.detector_runner import run_experiment
from vision_lab_tool.detector_storage import DetectorStore, export_csv, export_json
from vision_lab_tool.detectors.client import DetectorClient
from vision_lab_tool.images import overlay, prepare_image
from vision_lab_tool.models import ModelConfig, VisibleObject


def write_json(path, value):
    DetectorStore._write(path, json.dumps(value, ensure_ascii=False, indent=2,
                                         allow_nan=False).encode("utf-8"))


def save_artifacts(folder, image, run):
    if run.vlm:
        (folder / "vlm_raw.txt").write_text(run.vlm.raw_answer, encoding="utf-8")
    for result in run.results:
        artifact_name = (f"detector_only_{result.detector}" if result.method == "detector_only"
                         else result.method)
        visible = [VisibleObject(object_id=o.object_id, label=o.label_display,
                                 bbox=o.bbox, confidence=None) for o in result.candidates]
        overlay(image.corrected, visible).save(folder / f"{artifact_name}_overlay.jpg")
        compact = [VisibleObject(object_id=str(i), label=o.label_display,
                                 bbox=o.bbox, confidence=None) for i, o in enumerate(result.candidates)]
        overlay(image.corrected, compact).save(folder / f"{artifact_name}_review_overlay.jpg")
        rows = [{"display_index": i, **o.model_dump(mode="json")}
                for i, o in enumerate(result.candidates)]
        if rows:
            with (folder / f"{artifact_name}_candidates.csv").open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)


@contextmanager
def ledger_lock(out):
    """Serialize budget reservations across bounded concurrent CLI processes."""
    path = out / "request_ledger.lock"
    started = time.monotonic()
    while True:
        try:
            handle = path.open("x", encoding="utf-8")
            break
        except FileExistsError:
            if time.monotonic() - started > 10:
                raise RuntimeError("Budget ledger lock busy; no request sent") from None
            time.sleep(.05)
    try:
        handle.write(str(Path.cwd()))
        handle.close()
        yield
    finally:
        handle.close()
        path.unlink()


def reserve_unit(out, unit, condition):
    path = out / "request_ledger.json"
    with ledger_lock(out):
        ledger = json.loads(path.read_text("utf-8")) if path.exists() else []
        if any(e["unit"] == unit for e in ledger):
            raise ValueError("Previous attempted unit retained; explicit new attempt required")
        if condition == "paired" and sum(e["condition"] == "paired" for e in ledger) >= 30:
            raise ValueError("30 VLM request budget reached")
        entry = {"unit": unit, "condition": condition, "status": "reserved_before_execution",
                 "started_at": datetime.now(UTC).isoformat(), "request_sent": None,
                 "price_estimate": None}
        ledger.append(entry)
        write_json(path, ledger)
        return entry


def finish_unit(out, unit, run):
    path = out / "request_ledger.json"
    with ledger_lock(out):
        ledger = json.loads(path.read_text("utf-8"))
        entry = next(e for e in ledger if e["unit"] == unit)
        entry.update(status="completed", run_id=run.run_id,
                     request_sent=bool(run.vlm and any(a.get("request_sent") for a in run.vlm.attempts)),
                     vlm_status=run.vlm.status if run.vlm else "not_applicable",
                     usage=run.vlm.usage.model_dump(mode="json") if run.vlm else None,
                     cost=run.vlm.cost if run.vlm else None)
        write_json(path, ledger)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default="iteration_20261013_01")
    parser.add_argument("--version", required=True, choices=["v0", "v1", "v2"])
    parser.add_argument("--samples", nargs="+", required=True)
    parser.add_argument("--pure", action="store_true")
    args = parser.parse_args()
    out = ROOT / "data/vision_lab/detector_experiments" / args.experiment
    plan = json.loads((out / "plan.json").read_text("utf-8"))
    manifest = json.loads((out / "manifest_original.json").read_text("utf-8"))
    samples = {s["sample_id"]: s for s in manifest["samples"]}
    if any(s not in samples for s in args.samples):
        raise ValueError("Unknown sample")
    if any(samples[s]["dataset_split"] == "验证" for s in args.samples):
        frozen = json.loads((out / "candidate_freeze.json").read_text("utf-8"))
        if args.version not in {"v0", frozen["candidate"]}:
            raise ValueError("Validation candidate is frozen")
    config = ModelConfig.model_validate(plan["vlm_config"])
    configs = [DetectorConfig.model_validate(c) for c in plan["detectors"]]
    prompt_version = {"v0": "localization-prompt-v1", "v1": "localization-prompt-v2",
                      "v2": "localization-prompt-v3"}[args.version]
    key = "" if args.pure else resolve_key(
        config, saved=KeyVault(ROOT / "data/vision_lab/credentials.dpapi.json").load())
    if not args.pure and not key:
        raise ValueError("Configured GLM credential unavailable")
    store = DetectorStore(ROOT / "data/vision_lab")
    client = DetectorClient()
    local_cache = out / "local_result_cache"
    local_cache.mkdir(exist_ok=True)
    completed_runs = []

    def detect(image, queries, detector_config):
        # Reuse only identical local inference conditions, independent of VLM wording.
        identity = {"sent": image.metadata()["sent_sha256"], "queries": queries,
                    "config": detector_config.model_dump(mode="json"),
                    "weights": client.readiness(detector_config)["manifest"],
                    "runtime_sha256": hashlib.sha256((ROOT / "data/vision_lab/model_cache/runtime.json")
                                                       .read_bytes()).hexdigest()}
        ck = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        cache_path = local_cache / f"{ck}.json"
        if cache_path.exists():
            result = DetectionResult.model_validate_json(cache_path.read_text("utf-8"))
            result.cache_source = result.result_id
            result.result_id = uuid4().hex
            result.cache_hit = True
            return result
        result = client.detect(image, queries, detector_config)
        write_json(cache_path, result.model_dump(mode="json"))
        with (out / "local_inference_ledger.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"sample": current_sample, "version": args.version,
                                "condition": "pure" if args.pure else "paired",
                                "result_id": result.result_id, "cache_key": ck,
                                "detector": detector_config.detector, "status": result.status,
                                "timings": result.timings}, ensure_ascii=False) + "\n")
        return result

    try:
        for current_sample in args.samples:
            sample = samples[current_sample]
            condition = "pure" if args.pure else "paired"
            unit = f"{args.version}/{current_sample}/{condition}"
            folder = out / "outputs" / args.version / current_sample / condition
            if (folder / "run.json").exists():
                # Finish derived local artifacts after an interrupted export without inference.
                run = DetectorExperiment.model_validate_json((folder / "run.json").read_text("utf-8"))
                image = prepare_image((out / "inputs" / current_sample / "original.jpg").read_bytes())
                save_artifacts(folder, image, run)
                finish_unit(out, unit, run)
                completed_runs.append(run)
                print(json.dumps({"sample": current_sample, "version": args.version,
                                  "status": "existing_completed_record_skipped"}), flush=True)
                continue
            image_path = out / "inputs" / current_sample / "original.jpg"
            image = prepare_image(image_path.read_bytes())
            frozen_input = json.loads((out / "inputs" / current_sample / "input.json").read_text("utf-8"))
            assert image.metadata()["sent_sha256"] == frozen_input["sent_sha256"]
            reference_path = out / "ai_references" / f"{current_sample}.json"
            reference = DetectorReference.model_validate(
                json.loads(reference_path.read_text("utf-8"))["reference"])
            assert not reference.complete and all(not o.confirmed and o.annotation_source == "ai"
                                                   for o in reference.objects)
            folder.mkdir(parents=True, exist_ok=True)
            reserve_unit(out, unit, condition)
            counter = 0

            def stage(run, reference=reference, folder=folder):
                nonlocal counter
                run.experiment_id = plan["experiment_id"]
                run.reference = reference.model_copy(deep=True)
                counter += 1
                store.save_run(run, secrets=[key])
                write_json(folder / "stages" / f"{counter:02}.json", run.model_dump(mode="json"))

            kwargs = {}
            if "prompt_version" in inspect.signature(run_experiment).parameters:
                kwargs["prompt_version"] = prompt_version
            elif args.version != "v0":
                raise ValueError("Versioned localization runner unavailable")
            run = run_experiment(image, configs, "pure_detection" if args.pure else "localization",
                                 sample["task_prompt"], vlm_config=config, key=key,
                                 experiment_version=f"{args.experiment}:{args.version}:{current_sample}:{condition}",
                                 dataset_split=sample["dataset_split"], detect_fn=detect,
                                 on_stage=stage, cache={}, **kwargs)
            run.experiment_id = plan["experiment_id"]
            run.reference = reference
            store.save_sample(run, image)
            store.save_run(run, secrets=[key])
            write_json(folder / "run.json", run.model_dump(mode="json"))
            save_artifacts(folder, image, run)
            finish_unit(out, unit, run)
            completed_runs.append(run)
            print(json.dumps({"sample": current_sample, "version": args.version,
                              "run_id": run.run_id, "vlm": run.vlm.status if run.vlm else None,
                              "methods": [{"method": r.method, "status": r.status,
                                           "candidates": len(r.candidates), "selection": r.selection.status,
                                           "cache_hit": r.detection.cache_hit if r.detection else False}
                                          for r in run.results]}, ensure_ascii=True), flush=True)
    finally:
        client.stop_worker()
        if completed_runs:
            batch = f"batch_{args.version}_{'_'.join(args.samples)}_{'pure' if args.pure else 'paired'}"
            DetectorStore._write(out / f"{batch}.csv",
                                 export_csv(completed_runs))
            DetectorStore._write(out / f"{batch}.json",
                                 export_json(completed_runs))


if __name__ == "__main__":
    main()
