from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import BaseModel
from starlette.datastructures import UploadFile
from starlette.requests import Request

from camera_assistant import mobile_api
from camera_assistant.config import Settings
from camera_assistant.services import cloud

TOKEN = "test-stream-token-not-a-real-secret"
AUTH = {"Authorization": "Bearer " + TOKEN}


def configured(**updates):
    return replace(Settings(True, "", "https://example.invalid", "", "", 5, 1,
                            Path(__file__).resolve().parents[1] / "knowledge"), **updates)


def photo():
    data = BytesIO()
    Image.new("RGB", (100, 80), (100, 120, 90)).save(data, format="JPEG")
    return data.getvalue()


def form(*, streaming=True, mode="demo", **updates):
    return {"user_request": json.dumps({"intent": "窗边静物"}), "consent": "true",
            "expected_analysis_mode": mode, "stream_events": str(streaming).lower(), **updates}


def upload(client, *, streaming=True, mode="demo", headers=AUTH, content=None, **updates):
    return client.post("/api/v1/analyze", headers=headers,
                       files={"file": ("scene.jpg", photo() if content is None else content,
                                       "image/jpeg")},
                       data=form(streaming=streaming, mode=mode, **updates))


def decoded(response):
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line]


class Value(BaseModel):
    label: str = "校验后的结果"


class FakePipeline:
    def __init__(self, run=None):
        self.calls = []
        self.behavior = run

    def run(self, content, request, **options):
        self.calls.append(options)
        if self.behavior is not None:
            return self.behavior(content, request, **options)
        if "on_progress" in options:
            options["on_progress"]("正在识别画面。")
            options["on_partial"]({"kind": "scene", "value": Value(label="静物")})
            options["on_partial"]({"kind": "parameters", "value": Value(label="已校验参数")})
        return Value()


def test_demo_stream_orders_progress_validated_partial_and_final_without_cloud(monkeypatch):
    monkeypatch.setattr(mobile_api, "observe_stream", lambda _: pytest.fail("demo cloud call"))
    pipeline = FakePipeline()
    with TestClient(mobile_api.create_app(configured(), TOKEN, pipeline)) as client:
        response = upload(client, image_provenance="device_camera")
    events = decoded(response)
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert [event["type"] for event in events] == [
        "progress", "progress", "partial", "partial", "result",
    ]
    assert events[2]["kind"] == "scene" and events[2]["value"] == {"label": "静物"}
    assert events[3]["kind"] == "parameters"
    result = events[-1]
    assert result["image_provenance"] == "device_camera"
    assert result["analysis_mode"] == "demo" and len(result["request_id"]) == 32
    assert result["result"] == {"label": "校验后的结果"}
    assert all(event["elapsed_seconds"] >= 0 for event in events)
    assert "parallel_advice" not in pipeline.calls[0]
    assert "data:image" not in response.text and TOKEN not in response.text


def test_default_json_envelope_and_cloud_parallel_setting_are_compatible():
    pipeline = FakePipeline()
    settings = configured(demo_mode=False, api_key="private-test-key", vision_model="vision",
                          text_model="text", parallel_advice=False)
    with TestClient(mobile_api.create_app(settings, TOKEN, pipeline)) as client:
        response = upload(client, streaming=False, mode="cloud")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert {"request_id", "analysis_mode", "image_provenance", "result"} <= response.json().keys()
    assert response.json()["scene_photo_count"] == 1
    assert pipeline.calls == [{"parallel_advice": False}]


@pytest.mark.parametrize("stream_enabled", [True, False])
def test_cloud_activity_contains_only_allowed_metadata(monkeypatch, stream_enabled):
    observed = []

    @contextmanager
    def observe(callback):
        observed.append(True)
        callback({"phase": "content", "request_id": "safe-id", "chars": 18, "seconds": .2,
                  "response_content": "private raw model text", "secret": "private-test-key"})
        yield

    monkeypatch.setattr(mobile_api, "observe_stream", observe)
    settings = configured(demo_mode=False, api_key="private-test-key", vision_model="vision",
                          text_model="text", stream_output=stream_enabled)
    pipeline = FakePipeline()
    with TestClient(mobile_api.create_app(settings, TOKEN, pipeline)) as client:
        response = upload(client, mode="cloud")
    events = decoded(response)
    activities = [event for event in events if event["type"] == "activity"]
    assert bool(observed) is stream_enabled
    assert activities == ([{"type": "activity", "phase": "content", "request_id": "safe-id",
                           "chars": 18, "seconds": .2}] if stream_enabled else [])
    assert pipeline.calls[0]["parallel_advice"] is True
    assert "private" not in response.text


def test_provider_stream_failure_is_terminal_safe_and_never_retried():
    def fail(*args, **kwargs):
        kwargs["on_progress"]("正在分析。")
        raise RuntimeError("private provider body private-test-key")

    pipeline = FakePipeline(fail)
    with TestClient(mobile_api.create_app(configured(), TOKEN, pipeline)) as client:
        response = upload(client)
    events = decoded(response)
    assert events[-1]["type"] == "error"
    assert events[-1]["detail"] == mobile_api.ANALYSIS_FAILURE
    assert len(events[-1]["request_id"]) == 32
    assert not any(event["type"] == "result" for event in events)
    assert len(pipeline.calls) == 1
    assert "private" not in response.text


def test_heartbeat_while_waiting_for_model(monkeypatch):
    monkeypatch.setattr(mobile_api, "STREAM_HEARTBEAT_SECONDS", .01)

    def slow(*args, **kwargs):
        time.sleep(.05)
        return Value()

    with TestClient(mobile_api.create_app(configured(), TOKEN, FakePipeline(slow))) as client:
        events = decoded(upload(client))
    assert any(event["type"] == "heartbeat" for event in events)
    assert events[-1]["type"] == "result"


@pytest.mark.parametrize("updates,expected", [
    ({"headers": {}}, 401),
    ({"consent": "false"}, 422),
    ({"mode": "cloud"}, 409),
    ({"content": b"not an image"}, 422),
    ({"content": b""}, 422),
    ({"content": b"x" * (1024 * 1024 + 1)}, 413),
])
def test_streaming_uses_existing_auth_consent_mode_and_image_validation(updates, expected):
    pipeline = FakePipeline()
    with TestClient(mobile_api.create_app(configured(), TOKEN, pipeline)) as client:
        response = upload(client, **updates)
    assert response.status_code == expected
    assert pipeline.calls == []


def test_streaming_real_cloud_transport_remains_offline_and_never_exposes_json_deltas(monkeypatch):
    from test_cloud_streaming import stream_response, successful_stream
    from test_cloud_transport import transport

    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return stream_response(successful_stream('{"private advice":"not rendered raw"}'))[0]

    transport(monkeypatch, handler)
    settings = configured(demo_mode=False, api_key="private-test-key", vision_model="vision",
                          text_model="text")

    def invoke(*args, **kwargs):
        assert cloud.request_json(settings, {}) == {"private advice": "not rendered raw"}
        kwargs["on_partial"]({"kind": "parameters", "value": Value()})
        return Value()

    with TestClient(mobile_api.create_app(settings, TOKEN, FakePipeline(invoke))) as client:
        response = upload(client, mode="cloud")
    events = decoded(response)
    assert len(sent) == 1 and sent[0]["stream"] is True
    assert [event["phase"] for event in events if event["type"] == "activity"] == [
        "request_started", "content", "finished",
    ]
    assert events[-1]["type"] == "result"
    assert "private advice" not in response.text and "not rendered raw" not in response.text


@pytest.mark.parametrize("disconnect_before_worker", [False, True])
def test_disconnect_keeps_background_slot_until_thread_finishes(
    monkeypatch, disconnect_before_worker,
):
    """Control both legal orderings of disconnect and threadpool worker startup."""
    release_worker = threading.Event()

    async def exercise():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        allow_worker = asyncio.Event()
        real_threadpool = mobile_api.run_in_threadpool

        def slow(*args, **kwargs):
            loop.call_soon_threadsafe(entered.set)
            assert release_worker.wait(5)
            return Value()

        async def controlled_threadpool(*args, **kwargs):
            await allow_worker.wait()
            return await real_threadpool(*args, **kwargs)

        monkeypatch.setattr(mobile_api, "run_in_threadpool", controlled_threadpool)
        if not disconnect_before_worker:
            allow_worker.set()
        app = mobile_api.create_app(configured(), TOKEN, FakePipeline(slow))
        # Build multipart bytes without a network connection.
        prepared = httpx.Request("POST", "http://test/api/v1/analyze", headers=AUTH,
                                 files={"file": ("scene.jpg", photo(), "image/jpeg")}, data=form())
        body = prepared.read()
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                 "http_version": "1.1", "method": "POST", "scheme": "http",
                 "path": "/api/v1/analyze", "raw_path": b"/api/v1/analyze",
                 "query_string": b"", "root_path": "",
                 "headers": [(key.lower(), value) for key, value in prepared.headers.raw],
                 "client": ("127.0.0.1", 1234), "server": ("test", 80)}
        disconnected = asyncio.Event()
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body":
                if not disconnect_before_worker:
                    await asyncio.wait_for(entered.wait(), 5)
                disconnected.set()

        response = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(response, 5)
            assert len(app.state.analysis_tasks) == 1
            task = next(iter(app.state.analysis_tasks))
            assert not task.done() and not task.cancelled()
            if disconnect_before_worker:
                assert not entered.is_set()
                allow_worker.set()
            await asyncio.wait_for(entered.wait(), 5)
            assert not task.done() and not task.cancelled()
            release_worker.set()
            assert (await asyncio.wait_for(asyncio.shield(task), 5))["result"] == {
                "label": "校验后的结果",
            }
            await asyncio.sleep(0)
            assert not app.state.analysis_tasks
        finally:
            allow_worker.set()
            release_worker.set()

    try:
        asyncio.run(exercise())
    finally:
        release_worker.set()


def test_two_disconnected_workers_keep_slots_and_third_waits_until_completion():
    release_worker = threading.Event()
    entered = 0
    lock = threading.Lock()

    def slow(*args, **kwargs):
        nonlocal entered
        with lock:
            entered += 1
        assert release_worker.wait(5)
        return Value()

    pipeline = FakePipeline(slow)
    app = mobile_api.create_app(configured(), TOKEN, pipeline)
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/v1/analyze")

    async def invoke():
        return await endpoint(web_request=Request({"type": "http", "path": "/api/v1/analyze"}),
                              file=UploadFile(BytesIO(photo()), filename="scene.jpg"),
                              user_request=json.dumps({"intent": "窗边静物"}), consent=True,
                              expected_analysis_mode="demo", image_provenance="original_upload",
                              stream_events=True)

    async def exercise():
        for _ in range(2):
            response = await invoke()
            await anext(response.body_iterator)
            await response.body_iterator.aclose()
        async with asyncio.timeout(2):
            while entered < 2:
                await asyncio.sleep(.001)
        third = asyncio.create_task(invoke())
        await asyncio.sleep(.03)
        assert not third.done() and len(pipeline.calls) == 2
        release_worker.set()
        response = await asyncio.wait_for(third, 1)
        await anext(response.body_iterator)
        await response.body_iterator.aclose()
        await asyncio.gather(*tuple(app.state.analysis_tasks))
        assert entered == 3

    try:
        asyncio.run(exercise())
    finally:
        release_worker.set()


def test_cancelled_json_response_does_not_cancel_background_worker():
    entered = threading.Event()
    release_worker = threading.Event()

    def slow(*args, **kwargs):
        entered.set()
        assert release_worker.wait(5)
        return Value()

    app = mobile_api.create_app(configured(), TOKEN, FakePipeline(slow))
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/v1/analyze")

    async def exercise():
        response = asyncio.create_task(endpoint(
            web_request=Request({"type": "http", "path": "/api/v1/analyze"}),
            file=UploadFile(BytesIO(photo()), filename="scene.jpg"),
            user_request=json.dumps({"intent": "窗边静物"}), consent=True,
            expected_analysis_mode="demo", image_provenance="original_upload", stream_events=False,
        ))
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(.001)
        response.cancel()
        with pytest.raises(asyncio.CancelledError):
            await response
        task = next(iter(app.state.analysis_tasks))
        assert not task.cancelled() and not task.done()
        release_worker.set()
        assert (await asyncio.wait_for(task, 1))["result"] == {"label": "校验后的结果"}

    try:
        asyncio.run(exercise())
    finally:
        release_worker.set()


def test_activity_content_is_throttled_and_final_char_count_retained(monkeypatch):
    @contextmanager
    def observe(callback):
        callback({"phase": "request_started", "request_id": "safe-id", "chars": 0, "seconds": 0})
        for chars in range(1, 501):
            callback({"phase": "content", "request_id": "safe-id", "chars": chars, "seconds": .1})
        callback({"phase": "finished", "request_id": "safe-id", "chars": 500, "seconds": .1})
        yield

    monkeypatch.setattr(mobile_api, "observe_stream", observe)
    settings = configured(demo_mode=False, api_key="private-test-key", vision_model="vision",
                          text_model="text")
    with TestClient(mobile_api.create_app(settings, TOKEN, FakePipeline())) as client:
        events = decoded(upload(client, mode="cloud"))
    activities = [event for event in events if event["type"] == "activity"]
    assert [event["phase"] for event in activities] == ["request_started", "content", "finished"]
    assert activities[-1]["chars"] == 500


def test_performance_settings_default_and_env_overrides(monkeypatch, tmp_path):
    import camera_assistant.config as module

    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    for name in ("STREAM_OUTPUT", "PARALLEL_ADVICE", "DETECTOR_WARMUP"):
        monkeypatch.delenv("CAMERA_AI_" + name, raising=False)
    assert module.Settings.from_env().stream_output
    assert module.Settings.from_env().parallel_advice
    assert module.Settings.from_env().detector_warmup
    for name in ("STREAM_OUTPUT", "PARALLEL_ADVICE", "DETECTOR_WARMUP"):
        monkeypatch.setenv("CAMERA_AI_" + name, "false")
    settings = module.Settings.from_env()
    assert not settings.stream_output and not settings.parallel_advice and not settings.detector_warmup
