from __future__ import annotations

import csv
import io
import json
import os
import re
from pathlib import Path

from PIL import Image

from vision_lab_tool.evaluation import result_metrics
from vision_lab_tool.models import Evaluation, ModelConfig, RunRecord
from vision_lab_tool.security import scrub


def export_json(runs: list[RunRecord], secrets=()) -> bytes:
    return json.dumps(
        scrub([run.model_dump(mode="json") for run in runs], secrets),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ).encode("utf-8")


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        text = "'" + text
    return text


def export_csv(runs: list[RunRecord], secrets=()) -> bytes:
    rows = []
    for run in runs:
        for result in run.results:
            evaluation = run.evaluations.get(result.result_id, Evaluation())
            metrics = result_metrics(run, result)
            for error in evaluation.errors or [None]:
                rows.append(
                    {
                        "run_id": run.run_id,
                        "result_id": result.result_id,
                        "image_sha256": run.image["original_sha256"],
                        "mode": run.mode,
                        "experiment_version": run.experiment_version,
                        "prompt_version": run.prompt_version,
                        "prompt_sha256": run.prompt_sha256,
                        "dataset_split": run.dataset_split,
                        "provider": result.config.provider,
                        "protocol": result.config.protocol,
                        "config_id": result.config.config_id,
                        "model_name": result.config.name,
                        "model_id": result.config.model_id,
                        "actual_model": result.actual_model,
                        "simulated": result.config.protocol == "mock",
                        "status": result.status,
                        "call_success": result.call_success,
                        "format_pass": result.format_pass,
                        "elapsed_seconds": result.elapsed_seconds,
                        "input_tokens": result.usage.input_tokens,
                        "output_tokens": result.usage.output_tokens,
                        "cached_tokens": result.usage.cached_tokens,
                        "reasoning_tokens": result.usage.reasoning_tokens,
                        "cost": result.cost["amount"] if result.cost else None,
                        "currency": result.config.price.currency,
                        "reviewed": evaluation.reviewed,
                        "scores": evaluation.scores,
                        "scene_match": metrics["scene_match"],
                        "ious": metrics["ious"],
                        "error_tag": error.tag if error else "",
                        "model_conclusion": error.model_conclusion if error else "",
                        "human_confirmation": error.human_confirmation if error else "",
                        "severity": error.severity if error else "",
                        "evidence": error.evidence if error else "",
                        "suspected_cause": error.suspected_cause if error else "",
                        "correct_notes": evaluation.correct_notes,
                        "reference_notes": run.reference.notes,
                        "raw_answer": result.raw_answer,
                        "diagnostic": result.error,
                    }
                )
    buffer = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: _cell(v) for k, v in scrub(row, secrets).items()} for row in rows)
    return buffer.getvalue().encode("utf-8-sig")


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _write(self, path: Path, data: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    @staticmethod
    def _id(run_id: str):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("历史 run_id 格式非法")
        return run_id

    def save_run(self, run: RunRecord, secrets=()):
        self._write(
            self.root / "runs" / f"{self._id(run.run_id)}.json",
            json.dumps(
                scrub(run.model_dump(mode="json"), secrets),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ).encode("utf-8"),
        )

    def load_run(self, run_id: str) -> RunRecord:
        path = self.root / "runs" / f"{self._id(run_id)}.json"
        return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[RunRecord]:
        # Corrupt records remain visible as an explicit UI warning via load_errors.
        self.load_errors = []
        records = []
        for path in sorted((self.root / "runs").glob("*.json"), reverse=True):
            try:
                records.append(self.load_run(path.stem))
            except (ValueError, OSError) as exc:
                self.load_errors.append(f"{path.name}: {type(exc).__name__}")
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def save_configs(self, configs: list[ModelConfig], secrets=()):
        self._write(
            self.root / "configs.json",
            json.dumps(
                scrub([c.model_dump(mode="json") for c in configs], secrets),
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )

    def load_configs(self) -> list[ModelConfig] | None:
        path = self.root / "configs.json"
        if not path.exists():
            return None
        configs = [ModelConfig.model_validate(c) for c in json.loads(path.read_text("utf-8"))]
        if len({c.config_id for c in configs}) != len(configs):
            raise ValueError("配置 ID 重复")
        return configs

    def save_templates(self, templates: dict, secrets=()):
        self._write(
            self.root / "templates.json",
            json.dumps(scrub(templates, secrets), ensure_ascii=False, indent=2).encode(),
        )

    def load_templates(self) -> dict:
        path = self.root / "templates.json"
        return json.loads(path.read_text("utf-8")) if path.exists() else {}

    def save_sample(self, run: RunRecord, image):
        name = f"{self._id(run.run_id)}.png"
        buffer = io.BytesIO()
        image.corrected.save(buffer, "PNG")
        self._write(self.root / "samples" / name, buffer.getvalue())
        run.sample_file = name

    def load_sample(self, run: RunRecord):
        if not run.sample_file:
            return None
        expected = f"{self._id(run.run_id)}.png"
        if run.sample_file != expected:
            raise ValueError("历史图片路径非法")
        with Image.open(self.root / "samples" / expected) as image:
            return image.convert("RGB")
