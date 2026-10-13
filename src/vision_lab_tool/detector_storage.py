"""Atomic, privacy-scrubbed detector histories in a separate namespace."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image

from vision_lab_tool.detector_evaluation import result_metrics, validate_review
from vision_lab_tool.detector_models import DetectorExperiment
from vision_lab_tool.detector_reference import reference_ready, validate_reference_inventory
from vision_lab_tool.security import scrub


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False)
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        text = "'" + text
    return text


def export_json(runs: list[DetectorExperiment], secrets=()) -> bytes:
    return json.dumps(
        scrub([run.model_dump(mode="json") for run in runs], secrets),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")


def export_csv(runs: list[DetectorExperiment], secrets=()) -> bytes:
    rows = []
    billed_vlm = set()
    for run in runs:
        for result in run.results:
            review = run.evaluations.get(result.result_id)
            metrics = result_metrics(run, result)
            vlm = run.vlm
            first_cost_row = bool(
                vlm
                and vlm.real
                and not run.simulated
                and not vlm.cache_hit
                and vlm.result_id not in billed_vlm
                and vlm.attempts
                and not all(a.get("request_sent") is False for a in vlm.attempts)
            )
            if vlm:
                billed_vlm.add(vlm.result_id)
            method_row = {
                "schema_version": run.schema_version,
                "experiment_id": run.experiment_id,
                "run_id": run.run_id,
                "attempt_id": run.attempt_id,
                "result_id": result.result_id,
                "created_at": run.created_at,
                "image_sha256": run.image.get("original_sha256"),
                "sent_image_sha256": run.image.get("sent_sha256"),
                "image_metadata": run.image,
                "mode": run.mode,
                "experiment_version": run.experiment_version,
                "dataset_split": run.dataset_split,
                "task_prompt": run.task_prompt,
                "task_prompt_sha256": run.task_prompt_sha256,
                "dictionary_version": run.dictionary_version,
                "method": result.method,
                "detector": result.detector,
                "vlm_model_id": vlm.config.model_id if vlm else "",
                "vlm_result_id": vlm.result_id if vlm else "",
                "status": result.status,
                "stages": result.stages,
                "run_stages": run.stages,
                "simulated": run.simulated or not result.real,
                "selection_status": result.selection.status,
                "auto_selected_ids": result.selection.selected_ids,
                "human_selected_ids": review.human_selected_ids if review else [],
                "selection_rule": result.selection.rule_version,
                "selection_reason": result.selection.reason,
                "associations": result.selection.associations,
                "queries": result.queries,
                "unsupported_targets": result.unsupported_targets,
                "raw_candidates": result.detection.raw_candidates if result.detection else [],
                "filtered_candidates": [o.model_dump(mode="json") for o in result.candidates],
                "detector_metadata": result.detection.metadata if result.detection else {},
                "detector_config": result.detection.config.model_dump(mode="json")
                if result.detection
                else {},
                "cache_hit": result.detection.cache_hit
                if result.detection
                else (vlm.cache_hit if vlm else False),
                "cache_source": result.detection.cache_source
                if result.detection
                else (vlm.cache_source if vlm else None),
                "timings": result.timings,
                "run_timings": run.timings,
                "vlm_raw_answer": vlm.raw_answer if vlm else "",
                "vlm_status": vlm.status if vlm else "",
                "vlm_json_status": vlm.json_status if vlm else "",
                "vlm_box_status": vlm.box_status if vlm else "",
                "vlm_semantic_status": vlm.semantic_status if vlm else "",
                "vlm_usage": vlm.usage.model_dump(mode="json") if vlm else {},
                "shared_vlm_cost_scope": "one_shared_call"
                if first_cost_row
                else "already_counted_or_no_call",
                "shared_vlm_cost": vlm.cost if first_cost_row else None,
                "local_compute_cost": None,
                "reference_complete": run.reference.complete,
                "reference_notes": run.reference.notes,
                "reviewed": review.reviewed if review else False,
                "review_notes": review.notes if review else "",
                "box_matches": review.box_matches if review else {},
                "query_covered_gt_ids_by_source": review.query_covered_gt_ids_by_source
                if review
                else {},
                "metrics": metrics,
                "tp": metrics["tp"],
                "fp": metrics["fp"],
                "fn": metrics["fn"],
                "gt_count": metrics["gt_count"],
                "paired_count": metrics["paired_count"],
                "missing_pairs": metrics["missing_pairs"],
                "mean_iou": metrics["mean_iou"],
                "complete_task_success": metrics["complete_task_success"],
                "complete_task_success_human": metrics["complete_task_success_human"],
                "diagnostics": result.diagnostics,
            }
            for index, error in enumerate((review.errors if review else []) or [None]):
                row = dict(method_row)
                if index:
                    row["shared_vlm_cost"] = None
                    row["shared_vlm_cost_scope"] = "already_counted_or_no_call"
                row.update(
                    {
                        "error_id": error.error_id if error else "",
                        "error_type": error.tag if error else "",
                        "error_source": error.source if error else "",
                        "error_confirmed": error.confirmed if error else None,
                        "model_conclusion": error.model_conclusion if error else "",
                        "human_confirmation": error.human_confirmation if error else "",
                        "evidence": error.evidence if error else "",
                        "severity": error.severity if error else "",
                        "suspected_cause": error.suspected_cause if error else "",
                    }
                )
                rows.append(row)
    output = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: _cell(v) for k, v in scrub(row, secrets).items()} for row in rows)
    return output.getvalue().encode("utf-8-sig")


def filter_experiments(
    runs: list[DetectorExperiment],
    *,
    stage: str | None = None,
    model: str | None = None,
    task: str | None = None,
    image: str | None = None,
    error_type: str | None = None,
    confirmed: bool | None = None,
    simulated: bool | None = None,
    dataset_split: str | None = None,
) -> list[DetectorExperiment]:
    """Read-only record filter; exported identities/states remain unchanged."""
    filtered = []
    for run in runs:
        if simulated is not None and run.simulated != simulated:
            continue
        if dataset_split is not None and run.dataset_split != dataset_split:
            continue
        if task and task.casefold() not in (run.task_prompt + run.task_prompt_sha256).casefold():
            continue
        if image and image.casefold() not in json.dumps(run.image, ensure_ascii=False).casefold():
            continue
        if stage and not any(
            stage in statuses or stage in statuses.values()
            for statuses in [run.stages] + [r.stages for r in run.results]
        ):
            continue
        model_names = [c.model_id for c in run.configs] + [c.detector for c in run.configs]
        if run.vlm:
            model_names += [run.vlm.config.model_id, run.vlm.config.name]
        if model and not any(model.casefold() in name.casefold() for name in model_names):
            continue
        if error_type is not None or confirmed is not None:
            matching = [
                error
                for review in run.evaluations.values()
                for error in review.errors
                if (error_type is None or error.tag == error_type)
                and (confirmed is None or error.confirmed == confirmed)
            ]
            if not matching:
                continue
        filtered.append(run)
    return filtered


# Alternate name for callers that refer to the collection as records.
filter_records = filter_experiments


class DetectorStore:
    def __init__(self, root: Path):
        root = Path(root)
        self.root = root if root.name == "detector_experiments" else root / "detector_experiments"
        self.load_errors: list[str] = []

    @staticmethod
    def _id(value: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{32}", value):
            raise ValueError("检测历史 run_id 格式非法")
        return value

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # Windows antivirus/indexer handles can briefly deny replacement of
            # a just-written stage record. Keep the old complete file and retry
            # only PermissionError with a finite backoff (at most 0.75 seconds).
            for attempt in range(5):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (2**attempt))
        finally:
            temporary.unlink(missing_ok=True)

    def save_run(self, run: DetectorExperiment, secrets=()) -> None:
        # Revalidation catches accidental in-memory mutation without touching v1.
        checked = DetectorExperiment.model_validate(run.model_dump(mode="python"))
        validate_reference_inventory(checked)
        if checked.reference.complete and not reference_ready(checked):
            raise ValueError("完整参考须保留全部库存并有逐对象人工确认来源")
        results = {r.result_id: r for r in checked.results}
        for result_id, review in checked.evaluations.items():
            if result_id not in results:
                raise ValueError("人工评测引用不存在的 result_id")
            validate_review(checked, results[result_id], review)
        self._write(
            self.root / "runs" / f"{self._id(run.run_id)}.json",
            json.dumps(
                scrub(checked.model_dump(mode="json"), secrets),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ).encode("utf-8"),
        )

    def save_review_version(self, run: DetectorExperiment, secrets=(), prepared=None):
        """Save annotations under a new run ID; frozen inference snapshots stay untouched."""
        derived = run.model_copy(deep=True)
        derived.run_id = uuid4().hex
        derived.created_at = datetime.now(UTC).isoformat()
        derived.provenance["annotation_parent_run_id"] = run.run_id
        derived.provenance["annotation_source_run_id"] = run.provenance.get(
            "annotation_source_run_id", run.run_id,
        )
        derived.provenance["annotation_only"] = True
        derived.sample_file = None
        if prepared is not None:
            self.save_sample(derived, prepared)
        elif run.sample_file:
            image = self.load_sample(run)
            output = io.BytesIO()
            image.save(output, "PNG")
            derived.sample_file = f"{self._id(derived.run_id)}.png"
            self._write(self.root / "samples" / derived.sample_file, output.getvalue())
        self.save_run(derived, secrets)
        return derived

    def load_run(self, run_id: str) -> DetectorExperiment:
        path = self.root / "runs" / f"{self._id(run_id)}.json"
        return DetectorExperiment.model_validate_json(path.read_text("utf-8"))

    def list_runs(self) -> list[DetectorExperiment]:
        self.load_errors = []
        records = []
        for path in (self.root / "runs").glob("*.json"):
            try:
                records.append(self.load_run(path.stem))
            except (OSError, ValueError) as exc:
                self.load_errors.append(f"{path.name}: {type(exc).__name__}")
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def save_sample(self, run: DetectorExperiment, prepared) -> None:
        name = f"{self._id(run.run_id)}.png"
        output = io.BytesIO()
        prepared.corrected.save(output, "PNG")
        self._write(self.root / "samples" / name, output.getvalue())
        run.sample_file = name

    def load_sample(self, run: DetectorExperiment):
        if not run.sample_file:
            return None
        expected = f"{self._id(run.run_id)}.png"
        if run.sample_file != expected:
            raise ValueError("检测历史图片路径非法")
        with Image.open(self.root / "samples" / expected) as image:
            return image.convert("RGB")

    def filter_runs(self, **criteria) -> list[DetectorExperiment]:
        return filter_experiments(self.list_runs(), **criteria)
