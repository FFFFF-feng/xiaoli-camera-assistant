"""Bounded, serial acceptance of the main website production pipeline.

The preparation command freezes images, requests and manual checks before any
generation. The live command uses CameraAssistantPipeline without replacing its
advice logic. Knowledge comparisons reuse the saved scene and DINO result; only
the composition and parameter generation stages may call the model again.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import threading
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from main_round_support import (
    BASELINE,
    ROOT,
    SHANGHAI,
    code_snapshot,
    controlled_settings,
    copy_database,
    database_contents,
    digest,
    error_category,
    public_settings,
    read_json,
    write_json,
)

sys.path.insert(0, str(ROOT / "src"))

from camera_assistant.config import Settings
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import SceneAnalysis, UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services import cloud
from camera_assistant.services.localization import GroundingDinoLocalizer
from vision_lab_tool.detector_models import MethodResult

CASE_IDS = ["P02", "P03", "B08", "D10", "D17", "D01"]
DEFAULT_PLAN = ROOT / "data/history/main-acceptance-plan-20261014"
MODEL_STAGE_CAP = 2
IMAGE_CALL_CAP = 6


def _local_path(value: str | Path) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Acceptance input/output must remain inside this project")
    return path


def _metadata(dataset: str, case: str) -> dict:
    manifest = read_json(ROOT / "data/vision_lab/test_sets" / dataset / "manifest.json")
    return next(item for item in manifest["samples"] if item["sample_id"] == case)


def prepare(plan: Path) -> dict:
    """Record a pre-generation commitment, without reading credentials or sending API calls."""
    requests = read_json(BASELINE / "requests.json")
    old_samples = {item["id"]: item for item in read_json(BASELINE / "preflight.json")["samples"]}
    descriptions = {
        "P02": ("original_control", "contrast_10_v1", [
            "理解市场整体热闹氛围与近处人物关系，避免只优化孤立单人。",
            "模式、ISO控制方式及手动/自动参数角色明确；自动快门应有目标或检查条件。",
            "原回答缺少参数时仅恢复参数阶段；完整说明与最终参数同步。",
            "实际照度、灯具频闪等未知现场事实保留未知，不用模型补猜。",
        ]),
        "P03": ("original_control", "contrast_10_v1", [
            "保留窗框自然取景关系与窗外景色，不把所有内容都归成摄影者所在环境。",
            "可明确窗框/室外景色，但没有用户确认时拍摄位置保持未知。",
            "不仅凭outdoor/indoor标签推断现场照度或曝光；给试拍/直方图检查条件。",
            "最终页面显示环境关系和未确认信息，参数、构图及说明不互相矛盾。",
        ]),
        "B08": ("single_subject", "complement_10_v1", [
            "识别单朵红花及黑背景，避免把背景暗当成花朵整体严重欠曝。",
            "建议围绕花瓣层次和轮廓，不要求破坏目标的全场景提亮。",
            "不推断原现场灯具位置、原参数或植物准确品种；重拍步骤与已知f/4镜头边界一致。",
        ]),
        "D10": ("multiple_subjects", "diverse_20_v1", [
            "理解中央两位跃起者、球和周围队员的关系，观众不能都当主体球员。",
            "保留多人及球上方空间，不用单人裁切裁断用户要求的附近队员。",
            "快门、连续对焦和连拍操作适合快速动作；自动光圈/ISO角色清楚。",
            "不推断得分、犯规、球速或轨迹；室内光照/频闪未知必须保留。",
        ]),
        "D17": ("mixed_environment", "diverse_20_v1", [
            "区分温室玻璃/框架、日光投影、通道、右侧果实和玻璃外蓝天。",
            "玻璃室内结构与外部日光可同时描述，拍摄位置不要仅由蓝天标签决定。",
            "明暗交错的空间不能只靠环境标签量化照度；亮部保护与阴影取舍可执行。",
            "不把投影当实体杆件，不猜植物品种/季节；构图兼顾通道纵深及果实。",
        ]),
        "D01": ("reflection", "diverse_20_v1", [
            "区分眼睛、镜框、大片镜片反光和黑白处理；反光不能被当成额外人物。",
            "理解保留亲近笑脸且减轻反光的重拍目标，说明机位/脸部/光源角度如何试调。",
            "对焦目标为眼睛；不能用快门或ISO改变镜片的几何反射关系。",
            "不给身份、健康、个性等无图像依据推断；环境位置未知仍需明确。",
        ]),
    }
    new_intents = {
        "B08": "想让这朵红花的花瓣边缘更分明，同时保持黑背景，重拍怎么摆机位和设置？",
        "D10": "我想拍下两个人跳起来争球的这一刻，附近队员也别裁断，该怎么跟焦、留空间和设置曝光？",
        "D17": "请帮我把通道的纵深、玻璃棚和右侧果实一起交代清楚，重拍时怎样兼顾亮处与阴影？",
        "D01": "保留这张黑白笑脸的亲近感，但希望眼睛更醒目、眼镜上的反光少一点，重新拍应该怎么调整？",
    }
    cases = []
    for case in CASE_IDS:
        category, dataset, checks = descriptions[case]
        image = ROOT / "data/vision_lab/test_sets" / dataset / "images" / f"{case}.jpg"
        if case in requests:
            request = deepcopy(requests[case])
            metadata = old_samples[case]
        else:
            metadata = _metadata(dataset, case)
            request = deepcopy(requests["P03"])
            request["intent"] = new_intents[case]
            request["focal_length_mm"] = 50 if case in {"B08", "D01"} else 35
            if case == "D10":
                request.update(subject_motion="快速", focus_mode="AF-C", drive_mode="continuous")
            elif case == "D01":
                request.update(subject_motion="缓慢")
        UserRequest.model_validate(request)
        if digest(image) != metadata["sha256"]:
            raise ValueError(f"{case}: source image hash differs from existing controlled metadata")
        cases.append({
            "id": case, "category": category, "dataset": dataset,
            "image": image.relative_to(ROOT).as_posix(), "sha256": digest(image),
            "source_page": metadata["source_page"], "license": metadata["license"],
            "author": metadata["author"], "request": request, "manual_checks": checks,
            "image_visually_inspected_before_generation": True,
            "participated_in_current_repair": case in {"P02", "P03"},
            "case_title_and_checks_sent_to_model": False,
        })
    manifest = {
        "created_at": datetime.now(SHANGHAI).isoformat(),
        "purpose": "First bounded production acceptance after P02/P03 repair",
        "baseline": str(BASELINE), "case_limit": 6,
        "configuration_baseline": read_json(BASELINE / "preflight.json")["settings"],
        "equipment_is_controlled_test_input": True,
        "original_requests_exactly_preserved": ["P02", "P03"],
        "frozen_before_generation": True,
        "knowledge_comparison_candidate_cases": ["P02", "B08", "D10"],
        "cases": cases,
        "evidence_boundaries": [
            "真实生成、离线重审、规则校验和人工评价分别记录。",
            "人工检查点是预先冻结的评测任务，不是用户确认事实，也不发送给模型。",
            "首次模型回答、首次可展示场景、首次可展示构图和完整结果分别计时。",
            "有库/无库对照只判断本组具体输出；不证明知识库普遍有效。",
        ],
    }
    plan.mkdir(parents=True, exist_ok=False)
    write_json(plan / "manifest.json", manifest)
    write_json(plan / "prepare.json", {
        "code": code_snapshot(), "real_model_calls": 0,
        "manifest_sha256": digest(plan / "manifest.json"),
    })
    return manifest


def _prompt_record(body: dict) -> dict:
    """Keep actual text evidence, representing transport image bytes by SHA256 only."""
    body = deepcopy(body)
    for message in body.get("messages", []):
        if isinstance(message.get("content"), list):
            for part in message["content"]:
                if part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if url.startswith("data:") and "," in url:
                        data = base64.b64decode(url.split(",", 1)[1])
                        part["image_url"]["url"] = {
                            "redacted_image_bytes": True,
                            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        }
    return body


class AcceptanceRecorder:
    def __init__(self, output: Path, case: str, *, live: bool = True):
        self.output, self.case, self.live = output, case, live
        self.stage = "unknown"
        self.purpose = "initial"
        self.calls: list[dict] = []
        self.stages: dict[str, list[dict]] = {}
        self.retrievals: list[dict] = []
        self.progress: list[dict] = []
        self.started = time.monotonic()
        self.milestones: dict[str, float] = {}
        self.original_methods: list[tuple[object, str, object]] = []
        self.actual_request = cloud._request_content

    def save(self):
        write_json(self.output / f"{self.case}-calls.json", self.calls)
        write_json(self.output / f"{self.case}-retrieval.json", self.retrievals)

    def content(self, settings, body):
        attempt = 1 + sum(item["stage"] == self.stage for item in self.calls)
        if self.stage not in {"vision", "composition", "parameters"}:
            raise RuntimeError("Unlabelled model stage; request has not been sent")
        if attempt > MODEL_STAGE_CAP or len(self.calls) >= IMAGE_CALL_CAP:
            raise RuntimeError("Per-stage/shared parameter or total model call cap exceeded")
        call = {
            "stage": self.stage, "purpose": self.purpose, "attempt": attempt,
            "model": body.get("model"), "real_model_call": self.live,
            "started_after_seconds": round(time.monotonic() - self.started, 3),
            "outcome": "started",
        }
        self.calls.append(call)
        prefix = f"{self.case}-{self.stage}-attempt{attempt}"
        write_json(self.output / f"{prefix}-request.json", _prompt_record(body))
        self.save()
        started = time.monotonic()
        try:
            if not self.live:
                raise RuntimeError("This command does not provide offline model fixtures")
            content = self.actual_request(settings, body)
            (self.output / f"{prefix}.txt").write_text(content, encoding="utf-8")
            try:
                parsed = cloud.extract_json(content)
                write_json(self.output / f"{prefix}-parsed.json", parsed)
                call["json_valid"] = True
            except cloud.ModelServiceError:
                call.update(json_valid=False, format_issue="json_format")
            call["outcome"] = "returned"
            self.milestones.setdefault("first_raw_model_result_seconds", time.monotonic() - self.started)
            return content
        except cloud.ModelServiceError as exc:
            call.update(outcome="ModelServiceError", error_category=error_category(exc),
                        error_message=str(exc))
            raise
        except Exception as exc:
            call.update(outcome=type(exc).__name__)
            raise
        finally:
            call["seconds"] = round(time.monotonic() - started, 3)
            self.save()

    def wrap(self, instance, method: str, stage: str, purpose: str = "initial"):
        original = getattr(instance, method)
        self.original_methods.append((instance, method, original))

        def measured(*args, **kwargs):
            prior_stage, prior_purpose = self.stage, self.purpose
            self.stage, self.purpose = stage, purpose
            started = time.monotonic()
            entry = {"method": method, "purpose": purpose,
                     "started_after_seconds": round(started - self.started, 3)}
            index = len(self.stages.get(stage, [])) + 1
            try:
                result = original(*args, **kwargs)
                entry["status"] = getattr(result, "status", "success")
                if hasattr(result, "model_dump"):
                    write_json(self.output / f"{self.case}-{stage}-structured-{index}.json",
                               result.model_dump(mode="json"))
                if stage in {"vision", "composition"}:
                    self.milestones.setdefault(f"first_{stage}_result_seconds", time.monotonic() - self.started)
                return result
            except cloud.ModelServiceError as exc:
                entry.update(status="ModelServiceError", error_category=error_category(exc),
                             error_message=str(exc))
                raise
            except Exception as exc:
                entry["status"] = type(exc).__name__
                raise
            finally:
                entry["seconds"] = round(time.monotonic() - started, 3)
                self.stages.setdefault(stage, []).append(entry)
                self.stage, self.purpose = prior_stage, prior_purpose

        setattr(instance, method, measured)

    def attach(self, pipeline: CameraAssistantPipeline):
        self.wrap(pipeline.vision_analyzer, "analyze", "vision")
        if pipeline.localizer is not None:
            self.wrap(pipeline.localizer, "localize", "detector")
        if pipeline.composition_advisor is not None:
            self.wrap(pipeline.composition_advisor, "recommend", "composition")
        self.wrap(pipeline.advisor, "recommend", "parameters")
        for method in ("correct", "correct_parameters", "correct_recommendation"):
            if hasattr(pipeline.advisor, method):
                self.wrap(pipeline.advisor, method, "parameters", "parameter_correction")
        original = pipeline.retriever.search
        self.original_methods.append((pipeline.retriever, "search", original))

        def search(query, *args, **kwargs):
            hits = original(query, *args, **kwargs)
            record = {"query": query, "arguments": kwargs,
                      "hits": [hit.model_dump(mode="json") for hit in hits]}
            store = getattr(pipeline.retriever, "store", None)
            if store is not None:
                conditions = {}
                for hit in hits:
                    revision = store.get_revision(hit.metadata["knowledge_id"],
                                                  int(hit.metadata["version"]))
                    conditions[hit.document_id] = revision.record.conditions
                record["card_conditions"] = conditions
            self.retrievals.append(record)
            self.save()
            return hits

        pipeline.retriever.search = search

    def detach(self):
        for instance, method, original in reversed(self.original_methods):
            setattr(instance, method, original)

    def on_progress(self, message: str):
        self.progress.append({"seconds": round(time.monotonic() - self.started, 3), "message": message})

    def summary(self, *, result=None, error=None) -> dict:
        finished = time.monotonic() - self.started
        stage_seconds = {stage: round(sum(item["seconds"] for item in values), 3)
                         for stage, values in self.stages.items()}
        recommendation = result.recommendation if result is not None else None
        errors = [item for item in self.calls if item["outcome"] != "returned"]
        recovery = getattr(result, "parameter_recovery", None) if result is not None else None
        return {
            "case": self.case, "returned": result is not None,
            "error_type": type(error).__name__ if error else None,
            "complete_result_seconds": round(finished, 3),
            "first_website_advice_seconds": round(finished, 3),
            "website_result_timing_note": "app.py only renders advice after pipeline.run returns",
            "milestones": {key: round(value, 3) for key, value in self.milestones.items()},
            "stage_seconds": stage_seconds, "stages": self.stages,
            "calls": self.calls, "progress": self.progress,
            "real_model_calls": len(self.calls),
            "parameter_correction_calls": sum(item["purpose"] == "parameter_correction" for item in self.calls),
            "format_problem_count": sum(item.get("json_valid") is False for item in self.calls),
            "transport_failures": [{"stage": item["stage"], "category": item.get("error_category"),
                                    "seconds": item["seconds"]} for item in errors],
            "parameter_recovery": recovery.model_dump(mode="json") if hasattr(recovery, "model_dump") else recovery,
            "parameters_generated": recommendation.shooting_mode != "未生成" if recommendation else False,
            "validation_notes": recommendation.validation_notes if recommendation else [],
            "safety_notes": recommendation.safety_notes if recommendation else [],
            "manual_evaluation_status": "pending",
            "rules_are_not_accuracy_measurement": True,
        }


_page_hook_lock = threading.Lock()
_page_hook_installed = False


def install_page_recording(plan: Path, output: Path) -> None:
    """Observe the actual app.py page flow without changing input or recommendation behavior.

    The separate Streamlit launcher imports this hook, then executes app.py as its
    entry point. There is no hidden image injection: a browser must upload the
    frozen image and submit its matching form values. Duplicate submissions and
    inputs outside the six-case manifest are rejected before a model call.
    """
    global _page_hook_installed
    if _page_hook_installed:
        return
    plan, output = _local_path(plan), _local_path(output)
    manifest = read_json(plan / "manifest.json")
    if digest(plan / "manifest.json") != read_json(plan / "prepare.json")["manifest_sha256"]:
        raise ValueError("Frozen manifest has changed; prepare a new evidence plan")
    if [item["id"] for item in manifest["cases"]] != CASE_IDS:
        raise ValueError("Website acceptance requires the six predeclared cases")
    if not output.exists():
        output.mkdir(parents=True)
        write_json(output / "manifest.json", manifest)
        write_json(output / "website-session.json", {
            "started_at": datetime.now(SHANGHAI).isoformat(), "code": code_snapshot(),
            "plan": str(plan), "plan_sha256": digest(plan / "manifest.json"),
            "launcher": "scripts/run_acceptance_website.py", "actual_entry": "app.py",
            "execution": "browser_upload_and_form_submission_on_port_8501",
            "cases_max": 6, "calls_per_image_max": IMAGE_CALL_CAP,
            "calls_per_stage_max": MODEL_STAGE_CAP,
        })
    elif not (output / "website-session.json").is_file():
        raise ValueError("Website output exists but is not an acceptance session")
    if digest(output / "manifest.json") != digest(plan / "manifest.json"):
        raise ValueError("Website output belongs to a different frozen manifest")
    original_run = CameraAssistantPipeline.run

    def recorded_run(pipeline, image_content, request, *, on_progress=None):
        if not _page_hook_lock.acquire(blocking=False):
            raise RuntimeError("Acceptance runs must be serial")
        try:
            image_hash = hashlib.sha256(image_content).hexdigest()
            matching = [item for item in manifest["cases"] if item["sha256"] == image_hash]
            if len(matching) != 1:
                raise ValueError("Uploaded image does not match a frozen acceptance case")
            case = matching[0]
            expected = UserRequest.model_validate(case["request"])
            if request.model_dump(mode="json") != expected.model_dump(mode="json"):
                write_json(output / f"{case['id']}-input-mismatch.json", {
                    "expected": expected.model_dump(mode="json"),
                    "actual": request.model_dump(mode="json"),
                    "real_model_calls": 0,
                })
                raise ValueError("Page form values differ from the frozen controlled request")
            if (output / f"{case['id']}-calls.json").exists():
                raise ValueError("This case has already consumed its single full-flow attempt")
            settings = pipeline.settings
            baseline_settings = read_json(BASELINE / "preflight.json")["settings"]
            checked = ("vision_model", "text_model", "preset", "response_format", "format_retry_count",
                       "timeout_seconds", "max_output_tokens", "disable_thinking", "detector_device",
                       "detector_revision")
            if any(getattr(settings, key) != baseline_settings[key] for key in checked):
                raise ValueError("Page model configuration differs from the controlled baseline")
            if not settings.cloud_ready or not settings.composition_enabled or not settings.detector_enabled:
                raise ValueError("Acceptance page is not using the GLM+DINO production flow")
            if not isinstance(pipeline.retriever, ManagedKnowledgeRetriever):
                raise TypeError("Acceptance page must use the managed knowledge library")
            source_db = pipeline.retriever.store.db_path
            if not (output / "preflight.json").exists():
                before = database_contents(source_db)
                copy_database(source_db, output / "knowledge-snapshot.db")
                write_json(output / "preflight.json", {
                    "started_at": datetime.now(SHANGHAI).isoformat(), "code": code_snapshot(),
                    "settings": public_settings(settings), "source_database": str(source_db),
                    "source_database_before": before, "knowledge_state": "production",
                    "plan": str(plan), "plan_sha256": digest(plan / "manifest.json"),
                    "execution": "actual_app.py_browser_flow", "port": 8501,
                })
            recorder = AcceptanceRecorder(output, case["id"])
            recorder.attach(pipeline)

            def progress(message):
                recorder.on_progress(message)
                if on_progress:
                    on_progress(message)

            result, error = None, None
            try:
                with patch.object(cloud, "_request_content", recorder.content):
                    result = original_run(pipeline, image_content, request, on_progress=progress)
                write_json(output / f"{case['id']}-pipeline.json", result.model_dump(mode="json"))
                sent = base64.b64decode(result.inspection.model_image_data_url.split(",", 1)[1])
                (output / f"{case['id']}-sent.jpg").write_bytes(sent)
                return result
            except Exception as exc:
                error = exc
                raise
            finally:
                recorder.detach()
                trial = recorder.summary(result=result, error=error)
                trial.update(actual_app_page_submission=True, source_image_sha256=image_hash,
                             submitted_request=request.model_dump(mode="json"))
                write_json(output / f"{case['id']}-summary.json", trial)
                previous = read_json(output / "summary.json")["trials"] if (output / "summary.json").exists() else []
                previous.append(trial)
                write_json(output / "summary.json", {
                    "trials": previous, "completed": len(previous),
                    "real_model_calls": sum(item["real_model_calls"] for item in previous),
                    "parameter_correction_calls": sum(item["parameter_correction_calls"] for item in previous),
                    "manual_evaluation_status": "pending", "actual_app_page_submission": True,
                    "accuracy_measured": False,
                })
                before = read_json(output / "preflight.json")["source_database_before"]
                after = database_contents(source_db)
                write_json(output / "postflight.json", {
                    "finished_at": datetime.now(SHANGHAI).isoformat(), "code": code_snapshot(),
                    "source_database_after": after, "source_database_logically_unchanged": before == after,
                })
        finally:
            _page_hook_lock.release()

    CameraAssistantPipeline.run = recorded_run
    _page_hook_installed = True


class FixedVision:
    def __init__(self, scene: SceneAnalysis):
        self.scene = scene

    def analyze(self, *args, **kwargs):
        return self.scene.model_copy(deep=True)


class FixedLocalizer:
    def __init__(self, localization: MethodResult | None):
        self.localization = localization

    def localize(self, *args, **kwargs):
        return self.localization.model_copy(deep=True) if self.localization else None


class NoKnowledgeRetriever(ManagedKnowledgeRetriever):
    def search(self, *args, **kwargs):
        return []


class FixedComposition:
    def __init__(self, advice):
        self.advice = advice

    def recommend(self, *args, **kwargs):
        return self.advice.model_copy(deep=True) if self.advice is not None else None


def _trial(pipeline, case: dict, output: Path) -> dict:
    recorder = AcceptanceRecorder(output, case["id"])
    image = _local_path(ROOT / case["image"])
    if digest(image) != case["sha256"]:
        raise ValueError(f"{case['id']}: input image changed after manifest freeze")
    recorder.attach(pipeline)
    result, error = None, None
    print(json.dumps({"case": case["id"], "event": "started"}), flush=True)
    try:
        with patch.object(cloud, "_request_content", recorder.content):
            result = pipeline.run(image.read_bytes(), UserRequest.model_validate(case["request"]),
                                  on_progress=recorder.on_progress)
        write_json(output / f"{case['id']}-pipeline.json", result.model_dump(mode="json"))
        sent = base64.b64decode(result.inspection.model_image_data_url.split(",", 1)[1])
        (output / f"{case['id']}-sent.jpg").write_bytes(sent)
    except Exception as exc:  # noqa: BLE001 - safe error metadata preserves independent cases
        error = exc
    finally:
        recorder.detach()
    summary = recorder.summary(result=result, error=error)
    write_json(output / f"{case['id']}-summary.json", summary)
    print(json.dumps({"case": case["id"], "event": "completed", "returned": result is not None,
                      "real_model_calls": len(recorder.calls),
                      "seconds": summary["complete_result_seconds"]}), flush=True)
    return summary


def run_live(plan: Path, output: Path, knowledge_db: Path | None, knowledge_status: str) -> dict:
    manifest_path = plan / "manifest.json"
    manifest = read_json(manifest_path)
    if digest(manifest_path) != read_json(plan / "prepare.json")["manifest_sha256"]:
        raise ValueError("Frozen manifest has changed; prepare a new evidence plan")
    if len(manifest["cases"]) != 6 or [item["id"] for item in manifest["cases"]] != CASE_IDS:
        raise ValueError("First round must contain exactly the six predeclared cases")
    config_env = Settings.from_env()
    source_db = knowledge_db or config_env.knowledge_db_path or ROOT / "data/knowledge.db"
    before = database_contents(source_db)
    output.mkdir(parents=True, exist_ok=False)
    database = output / "knowledge-snapshot.db"
    copy_database(source_db, database)
    config = controlled_settings(BASELINE, database, live=True)
    write_json(output / "manifest.json", manifest)
    write_json(output / "preflight.json", {
        "started_at": datetime.now(SHANGHAI).isoformat(), "code": code_snapshot(),
        "settings": public_settings(config), "plan": str(plan), "plan_sha256": digest(manifest_path),
        "knowledge_state": knowledge_status, "source_database": str(source_db),
        "source_database_before": before, "calls_per_stage_max": MODEL_STAGE_CAP,
        "calls_per_image_max": IMAGE_CALL_CAP, "execution": "serial_production_pipeline",
        "equipment_is_controlled_test_input": True, "manual_evaluation_status": "pending",
    })
    localizer = GroundingDinoLocalizer(config)
    pipeline = CameraAssistantPipeline(config, localizer=localizer)
    started, trials = time.monotonic(), []
    try:
        for case in manifest["cases"]:
            trials.append(_trial(pipeline, case, output))
            summary = {"trials": trials, "completed": len(trials),
                       "real_model_calls": sum(item["real_model_calls"] for item in trials),
                       "parameter_correction_calls": sum(item["parameter_correction_calls"] for item in trials),
                       "wall_seconds": round(time.monotonic() - started, 3),
                       "manual_evaluation_status": "pending", "accuracy_measured": False}
            write_json(output / "summary.json", summary)
    finally:
        localizer.client.stop_worker()
        after = database_contents(source_db)
        write_json(output / "postflight.json", {
            "finished_at": datetime.now(SHANGHAI).isoformat(), "code": code_snapshot(),
            "source_database_after": after, "source_database_logically_unchanged": before == after,
        })
    return summary


def compare_knowledge(baseline: Path, output: Path, cases: list[str], knowledge_db: Path,
                      knowledge_status: str) -> dict:
    if not 2 <= len(cases) <= 3 or len(set(cases)) != len(cases):
        raise ValueError("Knowledge comparison requires two or three distinct cases")
    manifest = read_json(baseline / "manifest.json")
    records = {item["id"]: item for item in manifest["cases"]}
    if any(case not in records for case in cases):
        raise ValueError("Knowledge comparison cases must come from completed acceptance")
    output.mkdir(parents=True, exist_ok=False)
    db = output / "knowledge-snapshot.db"
    before = database_contents(knowledge_db)
    copy_database(knowledge_db, db)
    config = controlled_settings(BASELINE, db, live=True)
    write_json(output / "preflight.json", {
        "started_at": datetime.now(SHANGHAI).isoformat(), "code": code_snapshot(),
        "settings": public_settings(config), "visual_baseline": str(baseline), "cases": cases,
        "knowledge_state": knowledge_status, "source_database_before": before,
        "visual_and_dino_reused": True, "visual_model_calls": 0, "dino_calls": 0,
        "stage_order": ["parameters"], "branch_order": ["without", "with"],
        "composition_reused": True,
        "composition_reason": "Isolated library contains technique cards only, no composition cards",
        "limitation": "对照输出有随机性；本次小样本不证明知识库普遍有效。",
    })
    trials = []
    for case in cases:
        from camera_assistant.composition_models import CompositionAdvice

        saved = read_json(baseline / f"{case}-pipeline.json")
        scene = SceneAnalysis.model_validate(saved["scene"])
        localization = MethodResult.model_validate(saved["localization"]) if saved["localization"] else None
        for branch in ("without", "with"):
            branch_dir = output / branch
            branch_dir.mkdir(exist_ok=True)
            retriever = (ManagedKnowledgeRetriever(KnowledgeStore(db)) if branch == "with"
                         else NoKnowledgeRetriever(KnowledgeStore(db)))
            pipeline = CameraAssistantPipeline(config, vision_analyzer=FixedVision(scene),
                                               localizer=FixedLocalizer(localization), retriever=retriever,
                                               composition_advisor=FixedComposition(
                                                   CompositionAdvice.model_validate(saved["composition"])
                                                   if saved["composition"] else None))
            trial = _trial(pipeline, records[case], branch_dir)
            trial["branch"] = branch
            trial["reused_visual_and_dino"] = True
            if trial["returned"]:
                final = read_json(branch_dir / f"{case}-pipeline.json")
                trial["scene_exactly_reused"] = final["scene"] == saved["scene"]
                trial["dino_exactly_reused"] = final["localization"] == saved["localization"]
                trial["inspection_metrics_exactly_reused"] = final["inspection"] == saved["inspection"]
                if not trial["scene_exactly_reused"] or not trial["dino_exactly_reused"]:
                    raise ValueError("Knowledge branch did not preserve the saved scene/DINO evidence")
            if any(item["stage"] == "vision" for item in trial["calls"]):
                raise ValueError("Knowledge comparison unexpectedly generated a visual answer")
            trials.append(trial)
            write_json(output / "summary.json", {
                "trials": trials, "real_model_calls": sum(item["real_model_calls"] for item in trials),
                "visual_model_calls": 0, "dino_calls": 0, "manual_citation_audit_status": "pending",
                "knowledge_state": knowledge_status, "accuracy_measured": False,
            })
    write_json(output / "postflight.json", {
        "finished_at": datetime.now(SHANGHAI).isoformat(), "code": code_snapshot(),
        "source_database_after": database_contents(knowledge_db),
        "source_database_logically_unchanged": before == database_contents(knowledge_db),
    })
    return read_json(output / "summary.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare", help="Freeze six cases; sends no API requests")
    preparation.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    live = commands.add_parser("live", help="Run six full production flows serially")
    live.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    live.add_argument("--output", type=Path, required=True)
    live.add_argument("--live", action="store_true", required=True)
    live.add_argument("--knowledge-db", type=Path)
    live.add_argument("--knowledge-status", choices=["production", "isolated_test"], default="production")
    comparison = commands.add_parser("compare", help="Reuse saved scene/DINO; run with/without knowledge")
    comparison.add_argument("--baseline", type=Path, required=True)
    comparison.add_argument("--output", type=Path, required=True)
    comparison.add_argument("--knowledge-db", type=Path, required=True)
    comparison.add_argument("--knowledge-status", choices=["production", "isolated_test"], required=True)
    comparison.add_argument("--cases", nargs="+", default=["P02", "B08", "D10"])
    comparison.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        manifest = prepare(_local_path(args.plan))
        print(json.dumps({"plan": str(args.plan), "cases": [item["id"] for item in manifest["cases"]],
                          "real_model_calls": 0}, ensure_ascii=False), flush=True)
        return 0
    if args.command == "live":
        summary = run_live(_local_path(args.plan), _local_path(args.output),
                           _local_path(args.knowledge_db) if args.knowledge_db else None,
                           args.knowledge_status)
    else:
        summary = compare_knowledge(_local_path(args.baseline), _local_path(args.output), args.cases,
                                    _local_path(args.knowledge_db), args.knowledge_status)
    print(json.dumps({"output": str(args.output), "real_model_calls": summary["real_model_calls"]},
                     ensure_ascii=False), flush=True)
    return 0 if all(item["returned"] for item in summary["trials"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
