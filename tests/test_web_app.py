import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from camera_assistant.config import Settings
from camera_assistant.web_app import COOKIE, WebSessions, create_web_app

ORIGIN = "https://xiaoli.example.com"
HEADERS = {"Origin": ORIGIN, "X-Xiaoli-Client": "web"}


@pytest.fixture
def client(tmp_path):
    frontend = tmp_path / "dist"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<html>小栗</html>", encoding="utf-8")
    (frontend / "assets" / "app.js").write_text("console.log('app')")
    settings = Settings(True, "", "https://example.invalid", "", "", 5, 1,
                        Path(__file__).resolve().parents[1] / "knowledge")
    sessions = WebSessions("s" * 48, ORIGIN)
    with TestClient(create_web_app(replace(settings, composition_enabled=True), sessions, frontend),
                    base_url=ORIGIN) as instance:
        yield instance


def start_session(client):
    return client.post("/session", headers=HEADERS)


def test_expiring_signed_session_cannot_be_forged():
    import base64
    sessions = WebSessions("s" * 48, ORIGIN)
    token = sessions.issue()
    assert sessions.valid(token)
    assert not sessions.valid(token[:-5] + "abcde")
    assert not sessions.valid(base64.urlsafe_b64encode(b"0.nonce.signature").decode())
    assert not WebSessions("different" * 8, ORIGIN).valid(token)


def test_web_requires_https_and_real_session_secret_on_public_origin():
    with pytest.raises(ValueError):
        WebSessions("s" * 48, "http://xiaoli.example.com")
    with pytest.raises(ValueError):
        WebSessions("replace-with-at-least-32-random-characters", ORIGIN)
    with pytest.raises(ValueError):
        WebSessions("short", ORIGIN)
    assert WebSessions("s" * 48, ORIGIN).secure
    assert not WebSessions("s" * 48, "http://127.0.0.1:8080").secure


def test_static_client_and_private_routes(client):
    assert "小栗" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/web-config").json() == {"web_client": True}
    assert client.get("/api/v1/devices", headers=HEADERS).status_code == 401
    for path in ["/.env", "/knowledge_app.py", "/vision_lab.py", "/data/knowledge.db"]:
        assert client.get(path).status_code == 404


def test_static_assets_transfer_completely_over_real_http(tmp_path):
    """TestClient alone misses disconnect races in streamed FileResponse bodies."""
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    frontend = tmp_path / "dist"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<html>小栗</html>", encoding="utf-8")
    assets = {"app.js": b"console.log('app');\n" * 9000, "app.css": b"body{color:red}\n" * 1200}
    for name, content in assets.items():
        (frontend / "assets" / name).write_bytes(content)
    settings = Settings(True, "", "https://example.invalid", "", "", 5, 1,
                        Path(__file__).resolve().parents[1] / "knowledge")
    app = create_web_app(settings, WebSessions("s" * 48, ORIGIN), frontend)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as browser:
                for name, content in assets.items():
                    response = browser.get(f"/assets/{name}")
                    assert response.status_code == 200
                    assert response.content == content
                    assert response.headers["x-content-type-options"] == "nosniff"
                    partial = browser.get(f"/assets/{name}", headers={"Range": "bytes=10-99"})
                    assert partial.status_code == 206
                    assert partial.content == content[10:100]
                    assert browser.head(f"/assets/{name}").content == b""
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        assert not thread.is_alive()


def test_cookie_security_csrf_and_logout(client):
    assert client.post("/session").status_code == 403
    assert client.post("/session", headers={**HEADERS, "Origin": "https://attacker.invalid"}).status_code == 403
    assert client.post("/session", headers={"Origin": ORIGIN}).status_code == 403
    response = start_session(client)
    assert response.status_code == 200
    assert all(v in response.headers["set-cookie"] for v in ["HttpOnly", "Secure", "SameSite=strict"])
    assert client.get("/api/v1/devices", headers=HEADERS).status_code == 200
    assert client.get("/api/v1/devices", headers={**HEADERS, "Origin": "https://attacker.invalid"}).status_code == 401
    assert client.get("/api/v1/devices").status_code == 401
    assert client.delete("/session", headers=HEADERS).status_code == 200
    assert COOKIE not in client.cookies
    assert client.get("/api/v1/devices", headers=HEADERS).status_code == 401


def test_complete_web_photo_analysis(client):
    start_session(client)
    image = BytesIO()
    Image.new("RGB", (100, 80), (100, 120, 90)).save(image, format="JPEG")
    def upload(headers):
        return client.post("/api/v1/analyze", headers=headers,
            files={"file": ("scene.jpg", image.getvalue(), "image/jpeg")},
            data={"consent": "true", "expected_analysis_mode": "demo",
                  "user_request": json.dumps({"intent": "窗边静物", "device_type": "phone"})})
    assert upload({"X-Xiaoli-Client": "web"}).status_code == 401
    result = upload(HEADERS)
    assert result.status_code == 200
    assert result.json()["result"]["composition"]["status"] == "demo"
    assert "model_image_data_url" not in result.text
    assert result.headers["cache-control"] == "no-store"
    for _ in range(5):
        assert upload(HEADERS).status_code == 200
    assert upload(HEADERS).status_code == 429


def test_session_creation_rate_limit(client):
    for _ in range(10):
        assert start_session(client).status_code == 200
    assert start_session(client).status_code == 429


def test_web_sessions_still_require_signed_cookie_and_same_origin():
    sessions = WebSessions("s" * 48, ORIGIN)
    scope = {"method": "POST", "headers": [(b"origin", ORIGIN.encode()), (b"x-xiaoli-client", b"web")]}
    assert not sessions.auth(scope)
    scope["headers"].append((b"cookie", f"{COOKIE}={sessions.issue()}".encode()))
    assert sessions.auth(scope)
    scope["headers"][0] = (b"origin", b"https://attacker.invalid")
    assert not sessions.auth(scope)


def test_cloud_starts_and_issues_session_without_credentials(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>小栗</html>", encoding="utf-8")
    settings = Settings(False, "test-key", "https://example.invalid", "vision", "text", 5, 1,
                        Path(__file__).resolve().parents[1] / "knowledge")
    sessions = WebSessions("s" * 48, ORIGIN)
    with TestClient(create_web_app(settings, sessions, tmp_path), base_url=ORIGIN) as client:
        assert client.get("/health").json()["analysis_mode"] == "cloud"
        assert client.get("/api/v1/devices", headers=HEADERS).status_code == 401
        assert start_session(client).status_code == 200
        assert client.get("/api/v1/devices", headers=HEADERS).status_code == 200
