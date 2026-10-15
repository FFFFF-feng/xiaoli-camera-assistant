"""Auditable P01–P10 replay/live harness for the main website production pipeline.

Offline replay supplies saved model *content* and DINO candidates only. Parsing,
subject association, parameter validation and final advice review remain production
code. Neither valid JSON nor passing these checks is an accuracy measurement.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from camera_assistant.config import Settings
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services import cloud
from camera_assistant.services.localization import GroundingDinoLocalizer
from vision_lab_tool.detector_models import DetectionResult

BASELINE = ROOT / "data/history/main-round-20261014-105503"
DATASET = ROOT / "data/vision_lab/test_sets/contrast_10_v1"
SHANGHAI = timezone(timedelta(hours=8))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                    encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def control_manifest(baseline: Path) -> Path:
    """Saved live answers reuse the original round's controlled-image manifest."""
    info = read_json(baseline / "preflight.json")
    if "samples" in info:
        return baseline
    original = Path(info.get("control_manifest", info.get("baseline", ""))).resolve()
    if not original.is_relative_to(ROOT) or not (original / "preflight.json").is_file():
        raise RuntimeError("Saved run has no valid project-local controlled input manifest")
    if "samples" not in read_json(original / "preflight.json"):
        raise RuntimeError("Controlled input manifest does not contain image hashes")
    return original


def database_contents(path: Path) -> dict:
    """Read logically committed data and schema without touching the source DB."""
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        schema = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        ).fetchall()
        tables = {}
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall():
            # Names come from sqlite_master; double quotes protect unusual legal names.
            escaped = name.replace('"', '""')
            rows = connection.execute(f'SELECT * FROM "{escaped}"').fetchall()
            rows = sorted(json.dumps(row, ensure_ascii=False, default=str) for row in rows)
            tables[name] = {"rows": len(rows), "sha256": hashlib.sha256(
                "\n".join(rows).encode("utf-8")).hexdigest()}
        statuses = dict(connection.execute(
            "SELECT status,count(*) FROM revisions GROUP BY status"
        ).fetchall())
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {"schema_sha256": hashlib.sha256(json.dumps(
            schema, ensure_ascii=False).encode("utf-8")).hexdigest(),
            "tables": tables, "statuses": statuses, "integrity_check": integrity}


def copy_database(source: Path, target: Path) -> None:
    with (closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as origin,
          closing(sqlite3.connect(target)) as destination):
        origin.backup(destination)


def controlled_settings(baseline: Path, database: Path, *, live: bool) -> Settings:
    saved = read_json(baseline / "preflight.json")["settings"]
    if live:
        # This is the same secure credential resolution used by app.py. Never serialize it.
        config = Settings.from_env()
        key = config.api_key or Settings._zhipu_key()
        if not key:
            raise RuntimeError("现有安全配置未提供模型密钥；没有发送请求。")
    else:
        config = Settings(demo_mode=False, api_key="offline-fixture-only",
                          base_url="https://example.invalid/v1",
                          vision_model=saved["vision_model"], text_model=saved["text_model"],
                          timeout_seconds=120, max_image_mb=15, knowledge_dir=ROOT / "knowledge")
        key = config.api_key
    return replace(config, demo_mode=False, api_key=key,
                   base_url=("https://open.bigmodel.cn/api/paas/v4" if live
                             else "https://example.invalid/v1"),
                   vision_model=saved["vision_model"], text_model=saved["text_model"],
                   preset=saved["preset"], response_format=saved["response_format"],
                   format_retry_count=saved["format_retry_count"],
                   timeout_seconds=saved["timeout_seconds"],
                   max_output_tokens=saved["max_output_tokens"],
                   disable_thinking=saved["disable_thinking"],
                   composition_enabled=True, detector_enabled=True,
                   detector_device=saved["detector_device"],
                   detector_revision=saved["detector_revision"],
                   detector_box_threshold=saved.get("box_threshold", saved.get("detector_box_threshold")),
                   detector_text_threshold=saved.get("text_threshold", saved.get("detector_text_threshold")),
                   knowledge_mode="managed", knowledge_db_path=database)


def public_settings(config: Settings) -> dict:
    names = ("demo_mode", "base_url", "vision_model", "text_model", "preset",
             "response_format", "format_retry_count", "timeout_seconds",
             "max_output_tokens", "disable_thinking", "composition_enabled", "detector_enabled",
             "detector_device", "detector_revision", "detector_box_threshold",
             "detector_text_threshold", "detector_timeout_seconds", "knowledge_mode")
    return {name: getattr(config, name) for name in names}


def code_snapshot() -> dict:
    files = [ROOT / "app.py", *sorted((ROOT / "src/camera_assistant").rglob("*.py")),
             *sorted((ROOT / "knowledge/cameras").rglob("*.yaml"))]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                            capture_output=True, check=True).stdout.strip()
    return {"commit": commit, "working_source_sha256": {
        path.relative_to(ROOT).as_posix(): digest(path) for path in files}}


def original_image(baseline: Path, sample: str) -> Path:
    controls = control_manifest(baseline)
    records = {entry["id"]: entry for entry in read_json(controls / "preflight.json")["samples"]}
    path = DATASET / "images" / f"{sample}.jpg"
    if digest(path) != records[sample]["sha256"]:
        raise RuntimeError(f"{sample} 原图 SHA256 与基线不符；没有发送请求。")
    return path


class SavedDetectorClient:
    def __init__(self, path: Path):
        self.result = (DetectionResult.model_validate(read_json(path)["detection"])
                       if path.exists() else None)
        self.calls = 0

    def detect(self, prepared, queries, config):
        self.calls += 1
        if self.result is None:
            raise RuntimeError("No saved DINO evidence; offline replay cannot create candidates")
        return self.result.model_copy(deep=True)

    def stop_worker(self):
        pass


def error_category(error: Exception | str) -> str:
    # Only fixed production errors are stored, never HTTP headers or response bodies.
    message = str(error)
    if "超时" in message:
        return "timeout"
    if "无法连接" in message:
        return "connection"
    if "HTTP" in message:
        return "http_status"
    if "截断" in message:
        return "truncated"
    if "JSON" in message:
        return "json_format"
    if "拒绝" in message or "未完成" in message:
        return "refusal"
    return "model_or_validation"


class RunRecorder:
    def __init__(self, baseline: Path, output: Path, sample: str, *, live: bool):
        self.baseline, self.output, self.sample, self.live = baseline, output, sample, live
        self.stage = "unknown"
        self.calls: list[dict] = []
        self.stages: dict = {}
        self.original_methods: list[tuple[object, str, object]] = []
        self.actual_request_content = cloud._request_content
        self.baseline_trial = next(trial for trial in read_json(baseline / "summary.json")["trials"]
                                   if trial["sample"] == sample)

    def content(self, settings, body):
        stage = self.stage
        attempt = 1 + sum(call["stage"] == stage for call in self.calls)
        if attempt > 2 or len(self.calls) >= 6:
            raise RuntimeError("Per-image/stage model call cap exceeded; no request sent")
        call = {"stage": stage, "attempt": attempt, "model": body.get("model"),
                "response_format": body.get("response_format"), "real_model_call": self.live,
                "outcome": "started"}
        self.calls.append(call)
        write_json(self.output / f"{self.sample}-calls.json", self.calls)
        started = time.monotonic()
        try:
            if self.live:
                content = self.actual_request_content(settings, body)
            else:
                path = self.baseline / f"{self.sample}-{stage}-attempt{attempt}.txt"
                if not path.exists():
                    errors = [entry for entry in self.baseline_trial["calls"]
                              if entry["stage"] == stage and entry["outcome"] != "returned"]
                    if not errors:
                        raise RuntimeError(f"Missing saved model content: {self.sample}/{stage}")
                    failed_stage = self.baseline_trial["stages"].get(stage, {})
                    message = (errors[0].get("error_message")
                               or failed_stage.get("error_message")
                               or failed_stage.get("safe_message"))
                    if not message:
                        message = ("模型服务请求超时，请稍后重试或增加超时设置。"
                                   if self.sample in {"P04", "P05"}
                                   else "无法连接模型服务，请检查网络与接口配置。")
                    raise cloud.ModelServiceError(message)
                content = path.read_text(encoding="utf-8")
            # Model content only; prompts, credentials, headers and images are not logged here.
            (self.output / f"{self.sample}-{stage}-attempt{attempt}.txt").write_text(
                content, encoding="utf-8")
            try:
                cloud.extract_json(content)
                call["json_valid"] = True
            except cloud.ModelServiceError:
                call["json_valid"] = False
            call["outcome"] = "returned"
            return content
        except cloud.ModelServiceError as error:
            call.update(outcome="ModelServiceError", error_category=error_category(error),
                        error_message=str(error))
            raise
        finally:
            call["seconds"] = round(time.monotonic() - started, 3)
            write_json(self.output / f"{self.sample}-calls.json", self.calls)

    def wrap(self, instance, method: str, stage: str):
        original = getattr(instance, method)
        self.original_methods.append((instance, method, original))

        def measured(*args, **kwargs):
            prior_stage, self.stage = self.stage, stage
            started = time.monotonic()
            entry = {}
            try:
                value = original(*args, **kwargs)
                entry["status"] = getattr(value, "status", "success")
                if hasattr(value, "model_dump"):
                    write_json(self.output / f"{self.sample}-{stage}-structured.json",
                               value.model_dump(mode="json"))
                if stage == "vision":
                    inspection = args[0]
                    sent = base64.b64decode(inspection.model_image_data_url.split(",", 1)[1])
                    (self.output / f"{self.sample}-sent.jpg").write_bytes(sent)
                    entry["sent_sha256"] = hashlib.sha256(sent).hexdigest()
                    old_detection = read_json(
                        self.baseline / f"{self.sample}-detector-structured.json")["detection"]
                    old_hash = old_detection["metadata"]["sent_sha256"]
                    # Baseline *-sent.jpg was a re-encoded display copy, not transport bytes.
                    entry["sent_bytes_match_baseline"] = old_hash == entry["sent_sha256"]
                return value
            except cloud.ModelServiceError as error:
                entry.update(status="ModelServiceError", error_category=error_category(error),
                             error_message=str(error))
                raise
            except Exception as error:
                # Exception messages can include inputs; keep only a class name for other errors.
                entry.update(status=type(error).__name__)
                raise
            finally:
                entry["seconds"] = round(time.monotonic() - started, 3)
                self.stages[stage] = entry
                self.stage = prior_stage

        setattr(instance, method, measured)

    def attach(self, pipeline):
        self.wrap(pipeline.vision_analyzer, "analyze", "vision")
        self.wrap(pipeline.localizer, "localize", "detector")
        self.wrap(pipeline.composition_advisor, "recommend", "composition")
        self.wrap(pipeline.advisor, "recommend", "parameters")

    def detach(self):
        for instance, method, original in self.original_methods:
            setattr(instance, method, original)


def trial_summary(result, recorder: RunRecorder, seconds: float) -> dict:
    recommendation = result.recommendation
    state = getattr(recommendation, "exposure_state", None)
    return {
        "sample": recorder.sample, "returned": True, "seconds": round(seconds, 3),
        "stages": recorder.stages, "calls": recorder.calls,
        "scene": result.scene.scene_type,
        "selection": result.localization.selection.status if result.localization else None,
        "selection_reason": result.localization.selection.reason if result.localization else None,
        "task_scope": result.localization.queries.get("task_scope") if result.localization else None,
        "composition_status": result.composition.status if result.composition else None,
        "proposals": len(result.composition.proposals) if result.composition else 0,
        "parameters_generated": recommendation.shooting_mode != "未生成",
        "mode": recommendation.shooting_mode, "aperture": recommendation.aperture,
        "shutter": recommendation.shutter_speed, "iso": recommendation.iso,
        "exposure_compensation": recommendation.exposure_compensation,
        "exposure_state": state.model_dump(mode="json") if state else None,
        "validation_notes": recommendation.validation_notes,
        "safety_notes": recommendation.safety_notes,
        "parameter_hits": [hit.document_id for hit in result.knowledge_hits],
        "composition_hits": [hit.document_id for hit in result.composition_knowledge_hits],
    }


def run_round(*, baseline: Path, output: Path, cases: list[str], live: bool) -> dict:
    from camera_assistant.models import UserRequest

    output.mkdir(parents=True, exist_ok=False)
    requests = read_json(baseline / "requests.json")
    config_from_env = Settings.from_env() if live else None
    source_database = ((config_from_env.knowledge_db_path or ROOT / "data/knowledge.db")
                       if live else baseline / "knowledge-snapshot.db")
    before = database_contents(source_database)
    database = output / "knowledge-snapshot.db"
    copy_database(source_database, database)
    config = controlled_settings(baseline, database, live=live)
    selected_requests = {case: requests[case] for case in cases}
    write_json(output / "requests.json", selected_requests)
    controls = control_manifest(baseline)
    preflight = {"started_at": datetime.now(SHANGHAI).isoformat(), "mode": "live" if live else "offline",
                 "baseline": str(baseline), "code": code_snapshot(), "settings": public_settings(config),
                 "control_manifest": str(controls),
                 "samples": read_json(controls / "preflight.json")["samples"],
                 "cases": cases, "equipment_is_controlled_test_input": True,
                 "knowledge_publication_simulated": False,
                 "source_database_before": before,
                 "accuracy_measured": False,
                 "limitations": ["合法JSON、规则通过与模型置信度均不是建议正确率",
                                  "离线复用保存候选，不重测DINO；真实轮重新执行DINO"]}
    write_json(output / "preflight.json", preflight)
    started = time.monotonic()
    trials = []
    # Match the website and baseline: reuse the pipeline and loaded DINO worker.
    client = None if live else SavedDetectorClient(baseline / f"{cases[0]}-detector-structured.json")
    localizer = GroundingDinoLocalizer(config, client=client)
    pipeline = CameraAssistantPipeline(config, localizer=localizer)
    if not live:
        # Historical replay has no answer to the new correction prompt. Keep its
        # original one-stage evidence boundary rather than fabricating a reply.
        pipeline.advisor.correct_parameters = None
    for case in cases:
        case_started = time.monotonic()
        recorder = RunRecorder(baseline, output, case, live=live)
        if client is not None:
            path = baseline / f"{case}-detector-structured.json"
            client.result = (DetectionResult.model_validate(read_json(path)["detection"])
                             if path.exists() else None)
        recorder.attach(pipeline)
        print(json.dumps({"sample": case, "event": "started", "live": live}), flush=True)
        try:
            with patch.object(cloud, "_request_content", recorder.content):
                result = pipeline.run(original_image(baseline, case).read_bytes(),
                                      UserRequest.model_validate(requests[case]))
            write_json(output / f"{case}-pipeline.json", result.model_dump(mode="json"))
            trial = trial_summary(result, recorder, time.monotonic() - case_started)
        except Exception as error:  # noqa: BLE001 - preserve later independent trials with safe metadata
            trial = {"sample": case, "returned": False, "error_type": type(error).__name__,
                     "seconds": round(time.monotonic() - case_started, 3),
                     "stages": recorder.stages, "calls": recorder.calls}
            if isinstance(error, cloud.ModelServiceError):
                trial.update(error_category=error_category(error), error_message=str(error))
        finally:
            recorder.detach()
        trials.append(trial)
        summary = summarize(trials, time.monotonic() - started, live)
        write_json(output / "summary.json", summary)
        print(json.dumps({"sample": case, "event": "completed", "returned": trial["returned"],
                          "seconds": trial["seconds"], "proposals": trial.get("proposals"),
                          "parameters_generated": trial.get("parameters_generated")}), flush=True)
    localizer.client.stop_worker()
    after = database_contents(source_database)
    write_json(output / "postflight.json", {"source_database_after": after,
               "source_database_logically_unchanged": before == after,
               "finished_at": datetime.now(SHANGHAI).isoformat(),
               "code": code_snapshot(), "knowledge_publication_simulated": False})
    return summary


def summarize(trials: list[dict], seconds: float, live: bool) -> dict:
    calls = [call for trial in trials for call in trial["calls"]]
    failures = [call for call in calls if call["outcome"] != "returned"]
    return {"completed": len(trials), "wall_seconds": round(seconds, 3),
            "real_model_calls": sum(call["real_model_call"] for call in calls),
            "replayed_transport_attempts": 0 if live else len(calls),
            "returned_json_count": sum(call.get("json_valid", False) for call in calls),
            "failed_transport_calls": len(failures),
            "failure_categories": {category: sum(call.get("error_category") == category
                                                 for call in failures)
                                   for category in sorted({call.get("error_category")
                                                           for call in failures})},
            "accuracy_measured": False, "trials": trials}


def cli(*, live: bool, reviewed: bool = False) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    if reviewed:
        parser.add_argument("--baseline", type=Path, required=True,
                            help="已完成真实轮的目录，只重用其raw回答和DINO输出")
    else:
        parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cases", nargs="+", default=[f"P{number:02}" for number in range(1, 11)])
    if live:
        parser.add_argument("--live", action="store_true", required=True,
                            help="显式执行已授权的真实模型和DINO调用")
    args = parser.parse_args()
    known = read_json(args.baseline / "requests.json")
    if any(case not in known for case in args.cases) or len(args.cases) != len(set(args.cases)):
        parser.error("cases 必须为不重复的 P01–P10")
    label = "main-fix-reviewed" if reviewed else "main-fix-live" if live else "main-fix-offline"
    output = args.output or ROOT / "data/history" / (
        label + "-" + datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S"))
    summary = run_round(baseline=args.baseline.resolve(), output=output.resolve(),
                        cases=args.cases, live=live)
    print(json.dumps({"output": str(output), **{key: value for key, value in summary.items()
                                               if key != "trials"}}, ensure_ascii=False), flush=True)
    return 0 if all(trial["returned"] for trial in summary["trials"]) else 1
