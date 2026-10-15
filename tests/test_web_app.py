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
CODE = "test-invite-code"


@pytest.fixture
def client(tmp_path):
    frontend = tmp_path / "dist"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<html>小栗</html>", encoding="utf-8")
    (frontend / "assets" / "app.js").write_text("console.log('app')")
    settings = Settings(True, "", "https://example.invalid", "", "", 5, 1,
                        Path(__file__).resolve().parents[1] / "knowledge")
    sessions = WebSessions("s" * 48, ORIGIN, CODE)
    with TestClient(create_web_app(replace(settings, composition_enabled=True), sessions, frontend),
                    base_url=ORIGIN) as instance:
        yield instance


def login(client):
    return client.post("/session", json={"access_code": CODE}, headers=HEADERS)


def test_expiring_signed_session_cannot_be_forged():
    import base64
    sessions = WebSessions("s" * 48, ORIGIN, CODE)
    token = sessions.issue()
    assert sessions.valid(token)
    assert not sessions.valid(token[:-5] + "abcde")
    assert not sessions.valid(base64.urlsafe_b64encode(b"0.nonce.signature").decode())
    assert not WebSessions("different" * 8, ORIGIN, CODE).valid(token)


def test_web_requires_https_and_invitation_on_public_origin():
    with pytest.raises(ValueError):
        WebSessions("s" * 48, "http://xiaoli.example.com", CODE)
    with pytest.raises(ValueError):
        WebSessions("s" * 48, ORIGIN)
    assert not WebSessions("s" * 48, "http://127.0.0.1:8080").secure


def test_static_client_and_private_routes(client):
    assert "小栗" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/web-config").json()["invite_required"] is True
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
    app = create_web_app(settings, WebSessions("s" * 48, ORIGIN, CODE), frontend)
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
    assert client.post("/session", json={"access_code": CODE}).status_code == 403
    assert client.post("/session", json={"access_code": "wrong"}, headers=HEADERS).status_code == 401
    response = login(client)
    assert response.status_code == 200
    assert all(v in response.headers["set-cookie"] for v in ["HttpOnly", "Secure", "SameSite=strict"])
    assert client.get("/api/v1/devices", headers=HEADERS).status_code == 200
    assert client.get("/api/v1/devices", headers={**HEADERS, "Origin": "https://attacker.invalid"}).status_code == 401
    assert client.get("/api/v1/devices").status_code == 401
    assert client.delete("/session", headers=HEADERS).status_code == 200
    assert COOKIE not in client.cookies
    assert client.get("/api/v1/devices", headers=HEADERS).status_code == 401


def test_complete_web_photo_analysis(client):
    login(client)
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


def test_login_brute_force_limit(client):
    for _ in range(10):
        assert client.post("/session", json={"access_code": "wrong"}, headers=HEADERS).status_code == 401
    assert login(client).status_code == 429


def test_public_demo_sessions_still_require_signed_cookie_and_same_origin(tmp_path):
    sessions = WebSessions("s" * 48, ORIGIN, require_invite=False)
    scope = {"method": "POST", "headers": [(b"origin", ORIGIN.encode()), (b"x-xiaoli-client", b"web")]}
    assert not sessions.auth(scope)
    scope["headers"].append((b"cookie", f"{COOKIE}={sessions.issue()}".encode()))
    assert sessions.auth(scope)
    scope["headers"][0] = (b"origin", b"https://attacker.invalid")
    assert not sessions.auth(scope)


def test_cloud_cannot_reuse_open_demo_session_policy(tmp_path):
    settings = Settings(False, "test-key", "https://example.invalid", "vision", "text", 5, 1,
                        Path(__file__).resolve().parents[1] / "knowledge")
    sessions = WebSessions("s" * 48, ORIGIN, require_invite=False)
    with pytest.raises(ValueError, match="真实模型模式"):
        create_web_app(settings, sessions, tmp_path)
