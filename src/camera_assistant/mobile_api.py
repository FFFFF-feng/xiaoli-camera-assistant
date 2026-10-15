"""Read-only mobile gateway. Knowledge administration stays on the desktop."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import secrets
import time
import warnings
from collections.abc import Callable
from contextlib import nullcontext
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, StreamingResponse

from camera_assistant.config import Settings
from camera_assistant.models import UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services.cloud import observe_stream
from camera_assistant.services.lens_knowledge import EquipmentSelectionError

logger = logging.getLogger(__name__)
SERVICE_ID = "xiaoli-mobile-api"
API_VERSION = "1"
MAX_PIXELS = 40_000_000
STREAM_HEARTBEAT_SECONDS = 10
ANALYSIS_FAILURE = "分析失败，请稍后重试；若持续失败，请联系维护者检查模型配置。"


class GatewayMiddleware:
    """Authenticate before parsing/spooling multipart, including chunked requests."""

    def __init__(self, app, token: str, body_limit: int, session_auth=None):
        self.app = app
        self.token = token.encode("utf-8")
        self.body_limit = body_limit
        self.session_auth = session_auth

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        if scope["path"].startswith("/api/") and scope["method"] != "OPTIONS":
            supplied = headers.get(b"authorization", b"")
            authorized = secrets.compare_digest(supplied, b"Bearer " + self.token)
            if self.session_auth is not None:
                authorized = authorized or self.session_auth(scope)
            if not authorized:
                response = JSONResponse({"detail": "连接令牌不正确，请在连接页重新填写。"}, 401)
                return await response(scope, receive, send)
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "无效的请求长度。"}, 400)(scope, receive, send)
        if length < 0 or length > self.body_limit:
            return await JSONResponse({"detail": "上传内容超过大小限制。"}, 413)(
                scope, receive, send
            )
        # Bound all incoming chunks before handing any bytes to the multipart parser.
        # The bounded buffer avoids Starlette converting a receive exception into a 400.
        chunks = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > self.body_limit:
                return await JSONResponse({"detail": "上传内容超过大小限制。"}, 413)(
                    scope, receive, send
                )
            chunks.append(message)
            if not message.get("more_body", False):
                break

        async def bounded_receive():
            return chunks.pop(0) if chunks else await receive()

        await self.app(scope, bounded_receive, send)


def create_app(
    settings: Settings,
    access_token: str,
    pipeline: CameraAssistantPipeline | None = None,
    session_auth: Callable[[dict], bool] | None = None,
) -> FastAPI:
    if len(access_token) < 24 or access_token != access_token.strip():
        raise ValueError("MOBILE_API_TOKEN 必须为至少 24 个字符且无首尾空格。")
    pipeline = pipeline or CameraAssistantPipeline(settings)
    app = FastAPI(
        title="小栗手机接口", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None
    )
    max_bytes = settings.max_image_mb * 1024 * 1024
    app.add_middleware(
        GatewayMiddleware, token=access_token, body_limit=max_bytes + 65536,
        session_auth=session_auth,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",
            "https://localhost",
            "capacitor://localhost",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    slots = asyncio.Semaphore(2)
    # Keep paid work alive independently of the HTTP response/consumer lifetime.
    analysis_tasks: set[asyncio.Task] = set()
    app.state.analysis_tasks = analysis_tasks

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": SERVICE_ID,
            "api_version": API_VERSION,
            "analysis_mode": "cloud" if settings.cloud_ready else "demo",
            "requires_token": True,
            "max_image_mb": settings.max_image_mb,
            "composition_enabled": settings.composition_enabled,
            "detector_enabled": settings.detector_enabled,
        }

    @app.get("/api/v1/devices")
    def devices():
        return {
            "catalog_summary": {
                "coverage": "partial",
                "manual_model_input": True,
                "equipment_linkage": True,
                "camera_lenses": len(pipeline.lens_knowledge.list_profiles()),
                "adapted_cameras": sum(p.capability_level != "catalog"
                    and not p.profile_id.startswith("generic_")
                    for p in pipeline.camera_knowledge.list_profiles()),
                "catalog_only_cameras": sum(p.capability_level == "catalog"
                    for p in pipeline.camera_knowledge.list_profiles()),
                "camera_catalog_release": "2026-10-15",
                "known_cameras": sum(
                    not p.profile_id.startswith("generic_")
                    for p in pipeline.camera_knowledge.list_profiles()
                ),
                "known_phones": sum(
                    p.profile_id != "generic_phone"
                    for p in pipeline.phone_knowledge.list_profiles()
                ),
            },
            "cameras": [
                p.model_dump(mode="json", exclude_none=p.capability_level == "catalog",
                             exclude_defaults=p.capability_level == "catalog")
                for p in pipeline.camera_knowledge.list_profiles()
            ],
            "phones": [p.model_dump(mode="json") for p in pipeline.phone_knowledge.list_profiles()],
            "camera_lenses": [
                p.model_dump(mode="json") for p in pipeline.lens_knowledge.list_profiles()
            ],
        }

    @app.post("/api/v1/analyze")
    async def analyze(
        file: Annotated[UploadFile, File()],
        user_request: Annotated[str, Form(max_length=8192)],
        consent: Annotated[bool, Form()],
        expected_analysis_mode: Annotated[Literal["demo", "cloud"], Form()],
        image_provenance: Annotated[
            Literal["original_upload", "device_camera"], Form()
        ] = "original_upload",
        stream_events: Annotated[bool, Form()] = False,
    ):
        if not consent:
            raise HTTPException(422, "请先确认照片上传与分析说明。")
        actual_mode = "cloud" if settings.cloud_ready else "demo"
        if expected_analysis_mode != actual_mode:
            raise HTTPException(409, "分析方式已改变，请重新连接并确认上传说明。")
        try:
            payload = json.loads(user_request)
            if not isinstance(payload, dict) or set(payload) - set(UserRequest.model_fields):
                raise ValueError("unknown fields")
            request = UserRequest.model_validate(payload)
            if not request.intent.strip() or len(request.intent.strip()) < 2:
                raise ValueError("empty intent")
        except (ValueError, ValidationError):
            raise HTTPException(422, "拍摄需求或器材参数格式不正确。") from None
        image_content = await file.read(max_bytes + 1)
        await file.close()
        if not image_content:
            raise HTTPException(422, "请选择照片。")
        if len(image_content) > max_bytes:
            raise HTTPException(413, f"照片不能超过 {settings.max_image_mb} MB。")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(image_content)) as img:
                    if img.format not in {"JPEG", "PNG"}:
                        raise ValueError("format")
                    if img.width * img.height > MAX_PIXELS:
                        raise ValueError("pixels")
                    img.verify()
        except (
            ValueError,
            OSError,
            SyntaxError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            raise HTTPException(
                422, "仅支持有效 JPEG / PNG（不超过 4000 万像素）；HEIC / RAW 请先导出。"
            ) from None
        request_id = uuid4().hex
        try:
            async with asyncio.timeout(5):
                await slots.acquire()
        except TimeoutError:
            raise HTTPException(429, "服务正在分析其他照片，请稍后再试。") from None
        started = time.monotonic()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)
        accepting_events = True
        last_activity: dict[str, float] = {}

        def elapsed():
            return round(time.monotonic() - started, 3)

        def enqueue(event):
            if accepting_events:
                # Slow readers may lose redundant progress; validated results are retained.
                if event["type"] in {"activity", "progress"} and queue.qsize() >= 240:
                    return
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(event)

        def emit(event):
            # Callbacks can arrive from either of the parallel model threads.
            if stream_events:
                loop.call_soon_threadsafe(enqueue, event)

        def progress(message):
            emit({"type": "progress", "message": message, "elapsed_seconds": elapsed()})

        def activity(event):
            identifier = event.get("request_id", "")
            now = time.monotonic()
            if event.get("phase") == "content":
                if now - last_activity.get(identifier, -1) < .2:
                    return
                last_activity[identifier] = now
            elif event.get("phase") == "finished":
                last_activity.pop(identifier, None)
            emit({"type": "activity", **{
                key: event[key] for key in ("phase", "request_id", "chars", "seconds")
                if key in event
            }})

        def partial(event):
            if event.get("kind") not in {"scene", "parameters"}:
                return
            value = event["value"]
            if isinstance(value, BaseModel):
                value = value.model_dump(mode="json")
            emit({"type": "partial", "kind": event["kind"], "value": value,
                  "elapsed_seconds": elapsed()})

        def invoke():
            options = {"parallel_advice": settings.parallel_advice} if settings.cloud_ready else {}
            if stream_events:
                options.update(on_progress=progress, on_partial=partial)
            observer = (observe_stream(activity) if stream_events and settings.stream_output
                        and settings.cloud_ready else nullcontext())
            with observer:
                return pipeline.run(image_content, request, **options)

        async def run_analysis():
            try:
                result = await run_in_threadpool(invoke)
                envelope = {
                    "request_id": request_id,
                    "analysis_mode": actual_mode,
                    "image_provenance": image_provenance,
                    "result": result.model_dump(mode="json"),
                }
                emit({"type": "result", **envelope, "elapsed_seconds": elapsed()})
                return envelope
            except EquipmentSelectionError:
                emit({"type": "error", "detail": "器材选择不匹配，请重新确认相机与镜头。",
                      "request_id": request_id})
                raise
            except Exception as exc:  # noqa: BLE001 -- sanitize all provider failures
                logger.warning("Analysis failed request_id=%s exception_type=%s",
                               request_id, type(exc).__name__)
                emit({"type": "error", "detail": ANALYSIS_FAILURE, "request_id": request_id})
                raise HTTPException(502, ANALYSIS_FAILURE) from None
            finally:
                # Cancellation of a response never releases a still-running worker's slot.
                slots.release()

        task = asyncio.create_task(run_analysis())
        analysis_tasks.add(task)

        def completed(finished):
            analysis_tasks.discard(finished)
            # Consume exceptions even when a disconnected client is no longer awaiting.
            if not finished.cancelled():
                finished.exception()

        task.add_done_callback(completed)
        if stream_events:
            async def events():
                nonlocal accepting_events
                try:
                    yield json.dumps({"type": "progress", "message": "照片已接收，正在准备分析。",
                                      "elapsed_seconds": elapsed()}, ensure_ascii=False) + "\n"
                    while True:
                        try:
                            event = await asyncio.wait_for(
                                queue.get(), timeout=STREAM_HEARTBEAT_SECONDS,
                            )
                        except TimeoutError:
                            event = {"type": "heartbeat", "elapsed_seconds": elapsed()}
                        yield json.dumps(event, ensure_ascii=False) + "\n"
                        if event["type"] in {"result", "error"}:
                            break
                finally:
                    accepting_events = False

            return StreamingResponse(events(), media_type="application/x-ndjson", headers={
                "Cache-Control": "no-store", "X-Accel-Buffering": "no",
            })
        try:
            return await asyncio.shield(task)
        except EquipmentSelectionError as exc:
            raise HTTPException(422, str(exc)) from None

    return app
