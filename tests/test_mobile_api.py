import asyncio
import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from camera_assistant.config import Settings
from camera_assistant.mobile_api import GatewayMiddleware, create_app
from camera_assistant.pipeline import CameraAssistantPipeline

TOKEN = "test-mobile-token-not-a-real-secret"
AUTH = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture
def settings():
    return Settings(
        True,
        "",
        "https://example.invalid",
        "",
        "",
        5,
        1,
        Path(__file__).resolve().parents[1] / "knowledge",
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, TOKEN)) as instance:
        yield instance


def photo(format="JPEG", exif=None):
    data = BytesIO()
    options = {"exif": exif} if exif else {}
    Image.new("RGB", (100, 80), (100, 120, 90)).save(data, format=format, **options)
    return data.getvalue()


def upload(client, content=None, request=None, consent="true", headers=AUTH):
    return client.post(
        "/api/v1/analyze",
        headers=headers,
        files={"file": ("scene.jpg", photo() if content is None else content, "image/jpeg")},
        data={
            "user_request": json.dumps(request or {"intent": "窗边静物"}),
            "consent": consent,
            "expected_analysis_mode": "demo",
        },
    )


def test_health_does_not_expose_credentials(client):
    data = client.get("/health").json()
    assert data["service"] == "xiaoli-mobile-api"
    assert data["analysis_mode"] == "demo"
    assert "api_key" not in data and TOKEN not in str(data)
    assert client.get("/docs").status_code == 404


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic " + TOKEN}]
)
def test_auth_required_before_multipart(client, headers):
    assert client.get("/api/v1/devices", headers=headers).status_code == 401
    assert upload(client, headers=headers).status_code == 401


def test_devices(client):
    response = client.get("/api/v1/devices", headers=AUTH)
    assert response.status_code == 200
    assert any(p["profile_id"] == "generic_phone" for p in response.json()["phones"])
    assert response.json()["catalog_summary"] == {
        "coverage": "partial",
        "manual_model_input": True,
        "known_cameras": 4345,
        "adapted_cameras": 14,
        "catalog_only_cameras": 4331,
        "camera_catalog_release": "2026-10-15",
        "known_phones": 15,
        "equipment_linkage": True,
        "camera_lenses": 12,
    }
    assert len(response.json()["camera_lenses"]) == 12
    camera = next(p for p in response.json()["cameras"] if p["profile_id"] == "canon_eos_200d_ii")
    assert camera["sensor_format"] == "APS-C" and camera["mount"] == "canon_ef"


def test_catalog_compression_preserves_content_and_auth(client):
    compressed = client.get("/api/v1/devices", headers={**AUTH, "Accept-Encoding": "gzip"})
    plain = client.get("/api/v1/devices", headers={**AUTH, "Accept-Encoding": "identity"})
    assert compressed.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in compressed.headers["vary"].lower()
    assert "content-encoding" not in plain.headers
    assert compressed.json() == plain.json()
    assert int(compressed.headers["content-length"]) < int(plain.headers["content-length"]) / 3
    assert client.get("/api/v1/devices", headers={"Accept-Encoding": "gzip"}).status_code == 401
    assert "content-encoding" not in client.get("/health").headers


def test_camera_lens_api_linkage_and_incompatible_lens(client):
    payload = {
        "intent": "拍人像",
        "camera_profile_id": "canon_eos_200d_ii",
        "camera_lens_id": "canon_ef_s_18_55_f4_56_is_stm",
        "focal_length_mm": 55,
        "max_aperture": 1.2,
    }
    response = upload(client, request=payload)
    assert response.status_code == 200
    assert response.json()["result"]["equipment_settings"]["equivalent_focal_length_mm"] == 88
    payload["camera_profile_id"] = "canon_eos_r50"
    response = upload(client, request=payload)
    assert response.status_code == 422
    assert "重新选择镜头" in response.json()["detail"]


@pytest.mark.parametrize(
    "device,name,expected_id",
    [
        ("phone", "vivo X100 Pro Future", "generic_phone"),
        ("camera", "Canon EOS R8 Future", "generic_unknown"),
    ],
)
def test_manual_device_api_keeps_name_and_uses_generic_capabilities(
    client, device, name, expected_id
):
    response = upload(
        client,
        request={
            "intent": "窗边静物",
            "device_type": device,
            "device_model_name": name,
            "phone_profile_id": "xiaomi_14",
            "camera_profile_id": "canon_eos_r50",
            "phone_capture_mode": "pro",
            "phone_pro_controls_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    profile = response.json()["result"]["camera_profile"]
    assert profile["profile_id"] == expected_id
    assert profile["display_name"] == f"{name}（能力未收录）"
    if device == "phone":
        assert profile["modes"] == ["auto"]


@pytest.mark.parametrize("device", ["camera", "phone"])
def test_analyze_reuses_pipeline_without_returning_image_or_secret(client, device):
    exif = Image.Exif()
    exif[272] = "Original test camera"
    response = upload(client, photo(exif=exif), {"intent": "窗边静物", "device_type": device})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["analysis_mode"] == "demo"
    assert data["image_provenance"] == "original_upload"
    assert data["result"]["inspection"]["exif"]["camera_model"] == "Original test camera"
    assert data["result"]["camera_profile"]["device_type"] == device
    assert "model_image_data_url" not in response.text
    assert "data:image" not in response.text and TOKEN not in response.text


@pytest.mark.parametrize("content", [b"", b"not an image", photo("GIF")])
def test_invalid_image_rejected(client, content):
    assert upload(client, content).status_code == 422


def test_no_consent_rejected(client):
    assert upload(client, consent="false").status_code == 422


def test_mode_change_requires_new_consent(client):
    response = client.post(
        "/api/v1/analyze",
        headers=AUTH,
        files={"file": ("scene.jpg", photo(), "image/jpeg")},
        data={
            "user_request": json.dumps({"intent": "静物"}),
            "consent": "true",
            "expected_analysis_mode": "cloud",
        },
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"intent": "a"},
        {"intent": "  "},
        {"intent": "静物", "admin": True},
        {"intent": "静物", "device_type": "alien"},
        {"intent": "静物", "device_model_name": "x" * 121},
        {"intent": "静物", "device_model_name": "bad\nmodel"},
    ],
)
def test_invalid_request_rejected(client, payload):
    assert upload(client, request=payload).status_code == 422


def test_size_limit(client):
    assert upload(client, b"x" * (1024 * 1024 + 1)).status_code == 413
    assert upload(client, b"x" * (2 * 1024 * 1024)).status_code == 413


def test_cors_preflight_and_auth(client):
    response = client.options(
        "/api/v1/analyze",
        headers={
            "Origin": "http://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost"
    response = client.get("/health", headers={"Origin": "https://untrusted.invalid"})
    assert "access-control-allow-origin" not in response.headers


def test_provider_exception_is_sanitized(settings):
    pipeline = CameraAssistantPipeline(settings)

    def fail(*args):
        raise RuntimeError("Sensitive provider body with secret credential")

    pipeline.run = fail
    with TestClient(create_app(settings, TOKEN, pipeline)) as client:
        response = upload(client)
    assert response.status_code == 502
    assert "Sensitive" not in response.text and "secret" not in response.text


def test_cloud_mode_reported_only_when_ready(settings):
    cloud = replace(
        settings, demo_mode=False, api_key="test-key", vision_model="vision", text_model="text"
    )
    # No cloud call is made by /health.
    with TestClient(create_app(cloud, TOKEN)) as client:
        assert client.get("/health").json()["analysis_mode"] == "cloud"


def test_weak_token_rejected(settings):
    with pytest.raises(ValueError):
        create_app(settings, "weak")


def test_chunked_body_is_bounded_before_parser():
    called = False

    async def downstream(*args):
        nonlocal called
        called = True

    messages = [
        {"type": "http.request", "body": b"abcd", "more_body": True},
        {"type": "http.request", "body": b"efgh", "more_body": False},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "path": "/api/v1/analyze",
        "method": "POST",
        "headers": [(b"authorization", ("Bearer " + TOKEN).encode())],
    }
    asyncio.run(GatewayMiddleware(downstream, TOKEN, 6)(scope, receive, send))
    assert not called
    assert sent[0]["status"] == 413
