"""Optional manual image-edit endpoint, isolated from normal scene analysis."""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from collections import defaultdict, deque
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from camera_assistant.config import Settings
from camera_assistant.services.image_edit import (
    EditPlan,
    ImageEditError,
    edit_reference,
    prepare_reference,
)

PREVIEW_PATH = "/api/v1/composition-preview"


def register_image_preview(app: FastAPI, settings: Settings, access_token: str) -> None:
    slot = asyncio.Semaphore(1)
    # Bounded, process-local idempotency cache. No images are written to disk or
    # shared between identities. A restart clears it; it is not a durable queue.
    jobs: dict[tuple[str, str], tuple[str, float, asyncio.Task]] = {}
    attempts: dict[str, deque] = defaultdict(deque)
    app.state.image_preview_jobs = jobs

    @app.get(PREVIEW_PATH + "/config")
    def configuration():
        return JSONResponse(settings.image_edit.public(demo=settings.demo_mode),
                            headers={"Cache-Control": "no-store"})

    @app.post(PREVIEW_PATH)
    async def generate(
        request: Request,
        file: Annotated[UploadFile, File()],
        plan: Annotated[str, Form(max_length=8192)],
        consent: Annotated[bool, Form()],
        configuration_id: Annotated[str, Form(max_length=40)],
        request_id: Annotated[str, Form(max_length=40)],
    ):
        if not consent:
            raise HTTPException(422, "请单独确认将参考图发送给图片编辑服务及可能产生的费用。")
        if not settings.image_edit.public(demo=settings.demo_mode)["available"]:
            raise HTTPException(503, "图片编辑服务尚未启用，原图与构图建议仍可使用。")
        if configuration_id != settings.image_edit.configuration_id:
            raise HTTPException(409, "图片编辑服务配置已变化，请刷新并重新确认照片发送对象。")
        try:
            identifier = str(UUID(request_id))
            edit_plan = EditPlan.model_validate(json.loads(plan))
        except (ValueError, TypeError, ValidationError):
            raise HTTPException(422, "预演方案或请求编号格式不正确。") from None
        try:
            content = await file.read(settings.max_image_mb * 1024 * 1024 + 1)
        finally:
            await file.close()
        if not content:
            raise HTTPException(422, "参考图为空，请重新选择照片。")
        if len(content) > settings.max_image_mb * 1024 * 1024:
            raise HTTPException(413, "参考图超过当前图片上传限制。")
        supplied = request.headers.get("authorization", "")
        principal = (supplied if secrets.compare_digest(supplied.encode(),
                     ("Bearer " + access_token).encode()) else request.cookies.get("xiaoli_session", ""))
        owner = hashlib.sha256(principal.encode()).hexdigest()
        fingerprint = hashlib.sha256(content + edit_plan.model_dump_json().encode()
                                     + configuration_id.encode()).hexdigest()
        key, now = (owner, identifier), time.monotonic()
        for expired in [k for k, (_, started, task) in jobs.items() if task.done() and now-started > 600]:
            del jobs[expired]
        if key in jobs:
            previous, _, task = jobs[key]
            if previous != fingerprint:
                raise HTTPException(409, "同一预演编号不能用于不同照片或方案。")
            return await asyncio.shield(task)
        if len(jobs) >= 8 or slot.locked():
            raise HTTPException(429, "预演服务正在处理其他请求，请稍后再试；未新增生成任务。")
        for expired in [k for k, q in attempts.items() if not q or now-q[-1] > 3600]:
            del attempts[expired]
        if owner not in attempts and len(attempts) >= 4096:
            raise HTTPException(429, "预演请求过多，请稍后再试。")
        recent = attempts[owner]
        while recent and now-recent[0] > 600:
            recent.popleft()
        global_recent = attempts["global"]
        while global_recent and now-global_recent[0] > 3600:
            global_recent.popleft()
        if len(recent) >= 3 or len(global_recent) >= 20:
            raise HTTPException(429, "图片预演次数已达临时上限，请稍后再试。")
        recent.append(now)
        global_recent.append(now)
        await slot.acquire()

        async def work():
            try:
                try:
                    reference = await run_in_threadpool(prepare_reference, content)
                except ImageEditError as error:
                    raise HTTPException(422, str(error)) from None
                generated = await run_in_threadpool(edit_reference, settings.image_edit, reference, edit_plan)
                return JSONResponse({"request_id": identifier, "image_data_url": generated,
                                     "ai_generated": True, "semantic_verified": False,
                                     "reference_photo_id": edit_plan.reference_photo_id,
                                     "warning": "AI构图预演，可能改变细节；不是实拍，也未验证新机位是否可实现。"},
                                    headers={"Cache-Control": "no-store"})
            except HTTPException:
                raise
            except ImageEditError as error:
                # Adapter error messages are fixed safe strings, not provider bodies.
                raise HTTPException(502, str(error)) from None
            except Exception:  # noqa: BLE001 -- never expose provider data or credentials
                raise HTTPException(502, "图片预演未完成，原图仍可使用；不会自动重复调用。") from None
            finally:
                slot.release()

        task = asyncio.create_task(work())
        jobs[key] = (fingerprint, now, task)
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        # A dropped client must not release the slot while paid work still runs.
        return await asyncio.shield(task)
