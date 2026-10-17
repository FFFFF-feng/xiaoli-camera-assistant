from __future__ import annotations

import asyncio
import base64
import io
import json
from dataclasses import replace
from pathlib import Path
from threading import Event
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from camera_assistant import image_preview_api
from camera_assistant.config import Settings
from camera_assistant.image_edit_config import ImageEditSettings
from camera_assistant.mobile_api import create_app
from camera_assistant.services import image_edit

TOKEN = "only-test-preview-token-123456789"
AUTH = {"Authorization": "Bearer " + TOKEN}


def image_bytes(format="PNG", exif=None):
    buffer = io.BytesIO()
    Image.new("RGB", (80, 100), "orange").save(buffer, format, **({"exif": exif} if exif else {}))
    return buffer.getvalue()


def editor(**kwargs):
    return ImageEditSettings(True, "https://edit.example.invalid/v1", "test-editor-secret",
                             "explicit-test-image-model", **kwargs)


def settings(edit=None, demo=False):
    return Settings(demo, "test-vision-key", "https://example.invalid", "test-vision", "test-text", 5, 1,
                    Path(__file__).resolve().parents[1] / "knowledge", image_edit=edit or editor())


def plan():
    return {"goal": "完整保留主体，适当留出右侧背景", "actions": ["保留主体完整轮廓"],
            "preserve_features": ["耳朵", "手持相机"], "reference_photo_id": "photo1"}


def upload(client, *, request_id=None, data=None, content=None, headers=None):
    body = {"consent": "true", "configuration_id": editor().configuration_id,
            "request_id": request_id or str(uuid4()), "plan": json.dumps(plan())}
    body.update(data or {})
    return client.post("/api/v1/composition-preview", data=body,
                       files={"file": ("private-name.png", content or image_bytes(), "image/png")},
                       headers=AUTH if headers is None else headers)


def test_editor_configuration_is_separate_disabled_and_secret_safe(monkeypatch):
    monkeypatch.setenv("CAMERA_AI_API_KEY", "must-not-reuse")
    monkeypatch.setenv("OPENAI_API_KEY", "also-must-not-reuse")
    assert not ImageEditSettings.from_env({}).enabled
    assert ImageEditSettings.from_env({}).api_key == ""
    assert "test-editor-secret" not in repr(editor())
    with pytest.raises(ValueError, match="独立"):
        ImageEditSettings(enabled=True)
    for url in ("http://remote.invalid/v1", "https://user:secret@example.invalid", "https://a.invalid?key=secret"):
        with pytest.raises(ValueError):
            replace(editor(), base_url=url)
    assert not editor().public(demo=True)["available"]
    with pytest.raises(ValueError, match="必须为数值") as error:
        ImageEditSettings.from_env({"CAMERA_IMAGE_EDIT_TIMEOUT_SECONDS": "sensitive-value"})
    assert "sensitive-value" not in str(error.value)


def test_reference_normalizes_orientation_and_strips_exif():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private camera note"
    normalized = image_edit.prepare_reference(image_bytes("JPEG", exif))
    with Image.open(io.BytesIO(normalized)) as image:
        assert image.size == (100, 80)
        assert not image.getexif()
    with pytest.raises(image_edit.ImageEditError):
        image_edit.prepare_reference(b"not an image")


def test_layout_is_placement_only_and_rejects_invalid_numeric_boxes():
    value = {**plan(), "layout": [{"label": "主体", "role": "main", "bbox": [.1, .1, .8, .9]}]}
    parsed = image_edit.EditPlan.model_validate(value)
    assert parsed.layout[0].bbox == [.1, .1, .8, .9]
    assert "不是物体形状" in image_edit.build_edit_prompt(parsed)
    for box in ([0, 0, True, 1], [0, 0, float("nan"), 1], [.8, .1, .1, .9], [-1, 0, 1, 1]):
        value["layout"][0]["bbox"] = box
        with pytest.raises(ValueError):
            image_edit.EditPlan.model_validate(value)


def test_reference_adapter_sends_real_reference_and_only_supported_explicit_options(monkeypatch):
    captured = []
    real_client = httpx.Client

    def respond(request):
        captured.append(request)
        assert request.url == "https://edit.example.invalid/v1/images/edits"
        assert request.headers["authorization"] == "Bearer test-editor-secret"
        assert b'filename="reference.jpg"' in request.content
        assert b"private-name" not in request.content
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]})

    monkeypatch.setattr(image_edit.httpx, "Client",
                        lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    output = image_edit.edit_reference(editor(), image_bytes(), image_edit.EditPlan.model_validate(plan()))
    assert output.startswith("data:image/png;base64,")
    assert len(captured) == 1 and b"input_fidelity" not in captured[0].content
    image_edit.edit_reference(editor(input_fidelity="high"), image_bytes(), image_edit.EditPlan.model_validate(plan()))
    assert b"input_fidelity" in captured[1].content
    assert b"high" in captured[1].content


@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "https://untrusted.invalid"}),
    httpx.Response(401, text="secret-token-and-internal-error"),
    httpx.Response(200, json={"data": [{"url": "http://127.0.0.1/private"}]}),
    httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(b"<svg/>").decode()}]}),
    httpx.Response(200, json={"data": [{"b64_json": "bad-base64"}]}),
])
def test_no_redirects_remote_result_downloads_or_secret_error_leaks(monkeypatch, response):
    calls = []
    real_client = httpx.Client

    def respond(request):
        calls.append(request.url)
        return response

    monkeypatch.setattr(image_edit.httpx, "Client",
                        lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(image_edit.ImageEditError) as error:
        image_edit.edit_reference(editor(), image_bytes(), image_edit.EditPlan.model_validate(plan()))
    assert len(calls) == 1
    assert "secret-token" not in str(error.value)


def test_preview_is_opt_in_authenticated_and_configuration_bound(monkeypatch):
    monkeypatch.setattr(image_preview_api, "edit_reference", lambda *_: pytest.fail("must not call editor"))
    with TestClient(create_app(settings(), TOKEN)) as client:
        assert upload(client, headers={}).status_code == 401
        public = client.get("/api/v1/composition-preview/config", headers=AUTH)
        assert public.json()["provider"] == "edit.example.invalid"
        assert "secret" not in public.text
        assert upload(client, data={"consent": "false"}).status_code == 422
        assert upload(client, data={"configuration_id": "old-provider"}).status_code == 409
        assert upload(client, data={"request_id": "invalid"}).status_code == 422
        assert upload(client, data={"plan": json.dumps({**plan(), "base_url": "http://internal"})}).status_code == 422
    for disabled in (settings(ImageEditSettings()), settings(demo=True)):
        with TestClient(create_app(disabled, TOKEN)) as client:
            assert not client.get("/api/v1/composition-preview/config", headers=AUTH).json()["available"]
            assert upload(client).status_code == 503


def test_preview_response_idempotency_identity_binding_and_throttle(monkeypatch):
    calls = []

    def fake(_, content, request):
        calls.append(request)
        assert content.startswith(b"\xff\xd8")
        return "data:image/png;base64," + base64.b64encode(image_bytes()).decode()

    monkeypatch.setattr(image_preview_api, "edit_reference", fake)
    with TestClient(create_app(settings(), TOKEN)) as client:
        identifier = str(uuid4())
        first = upload(client, request_id=identifier)
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-store"
        assert first.json()["ai_generated"] and not first.json()["semantic_verified"]
        assert upload(client, request_id=identifier).json() == first.json()
        assert len(calls) == 1
        assert upload(client, request_id=identifier, data={"plan": json.dumps({**plan(), "goal": "新方案"})}).status_code == 409
        assert upload(client).status_code == 200
        assert upload(client).status_code == 200
        assert upload(client).status_code == 429
        assert len(calls) == 3


def test_failed_edit_keeps_original_workflow_and_is_not_automatically_retried(monkeypatch):
    calls = []

    def fake(*_):
        calls.append(1)
        raise RuntimeError("private-api-key-provider-response")

    monkeypatch.setattr(image_preview_api, "edit_reference", fake)
    with TestClient(create_app(settings(), TOKEN)) as client:
        identifier = str(uuid4())
        for _ in range(2):
            result = upload(client, request_id=identifier)
            assert result.status_code == 502 and "private-api-key" not in result.text
        assert len(calls) == 1
        assert client.get("/api/v1/devices", headers=AUTH).status_code == 200
        assert upload(client, content=b"broken").status_code == 422
        assert len(calls) == 1


def test_disconnected_response_does_not_release_paid_worker_or_duplicate_work(monkeypatch):
    started, release = Event(), Event()
    calls = []

    def fake(*_):
        calls.append(1)
        started.set()
        if not release.wait(5):
            raise RuntimeError("test timeout")
        return "data:image/png;base64," + base64.b64encode(image_bytes()).decode()

    monkeypatch.setattr(image_preview_api, "edit_reference", fake)

    async def run():
        application = create_app(settings(), TOKEN)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://testserver") as client:
            identifier = str(uuid4())

            def submit(value):
                return client.post("/api/v1/composition-preview", headers=AUTH,
                    files={"file": ("scene.png", image_bytes(), "image/png")}, data={
                        "consent": "true", "configuration_id": editor().configuration_id,
                        "request_id": value, "plan": json.dumps(plan())})

            first = asyncio.create_task(submit(identifier))
            try:
                assert await asyncio.to_thread(started.wait, 2)
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
                blocked = await submit(str(uuid4()))
                assert blocked.status_code == 429
                duplicate = asyncio.create_task(submit(identifier))
                release.set()
                result = await duplicate
                assert result.status_code == 200 and len(calls) == 1
            finally:
                release.set()

    asyncio.run(run())
