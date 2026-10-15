"""Read-only mobile gateway. Knowledge administration stays on the desktop."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import secrets
import warnings
from collections.abc import Callable
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from camera_assistant.config import Settings
from camera_assistant.models import UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services.lens_knowledge import EquipmentSelectionError

logger = logging.getLogger(__name__)
SERVICE_ID = "xiaoli-mobile-api"
API_VERSION = "1"
MAX_PIXELS = 40_000_000


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
        try:
            result = await run_in_threadpool(pipeline.run, image_content, request)
        except EquipmentSelectionError as exc:
            raise HTTPException(422, str(exc)) from None
        except Exception as exc:  # noqa: BLE001 -- gateway must sanitize all provider failures
            # Never return or log provider error bodies containing credentials/images.
            logger.warning(
                "Analysis failed request_id=%s exception_type=%s", request_id, type(exc).__name__
            )
            raise HTTPException(502, "分析失败，请稍后重试；若持续失败，请联系维护者检查模型配置。") from None
        finally:
            slots.release()
        return {
            "request_id": request_id,
            "analysis_mode": "cloud" if settings.cloud_ready else "demo",
            "image_provenance": image_provenance,
            "result": result.model_dump(mode="json"),
        }

    return app
