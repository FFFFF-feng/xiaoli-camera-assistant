"""Same-origin web experience with expiring HttpOnly sessions.

The desktop knowledge workbench and vision experiment tools are never mounted.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from http.cookies import CookieError, SimpleCookie
from pathlib import Path

from fastapi import HTTPException, Request
from starlette.datastructures import MutableHeaders
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from camera_assistant.config import PROJECT_ROOT, Settings
from camera_assistant.mobile_api import create_app

COOKIE = "xiaoli_session"
SESSION_SECONDS = 12 * 60 * 60


class WebSessions:
    def __init__(self, secret: str, origin: str):
        if len(secret) < 32:
            raise ValueError("WEB_SESSION_SECRET 至少需要 32 个字符。")
        from urllib.parse import urlsplit
        url = urlsplit(origin)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.path
                or url.query or url.fragment or url.username or url.password):
            raise ValueError("WEB_ORIGIN 必须为不带路径的完整网站地址。")
        self.secure = url.scheme == "https"
        if not self.secure and url.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("公网体验版需要 HTTPS，请配置 WEB_ORIGIN。")
        if self.secure and secret.startswith("replace-"):
            raise ValueError("请生成真实会话密钥，不能使用示例占位值。")
        self.secret = secret.encode()
        self.origin = origin
        self.trusted_proxy = os.getenv("WEB_TRUSTED_PROXY_IP", "")
        self.attempts: dict[str, deque] = defaultdict(deque)
        self.analyses: dict[str, deque] = defaultdict(deque)

    def issue(self) -> str:
        payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_urlsafe(18)}"
        signature = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(f"{payload}.{signature}".encode()).decode()

    def valid(self, value: str) -> bool:
        try:
            payload, signature = base64.urlsafe_b64decode(value).decode().rsplit(".", 1)
            expiry = int(payload.split(".", 1)[0])
            expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
            return int(time.time()) < expiry <= int(time.time()) + SESSION_SECONDS and hmac.compare_digest(signature, expected)
        except (ValueError, UnicodeError):
            return False

    def auth(self, scope: dict) -> bool:
        headers = dict(scope.get("headers", []))
        if headers.get(b"x-xiaoli-client") != b"web":
            return False
        origin = headers.get(b"origin")
        if origin and origin.decode("latin-1") != self.origin:
            return False
        if scope["method"] not in {"GET", "HEAD"} and origin != self.origin.encode():
            return False
        try:
            cookie = SimpleCookie()
            cookie.load(headers.get(b"cookie", b"").decode())
            value = cookie[COOKIE].value if COOKIE in cookie else ""
        except (ValueError, UnicodeError, CookieError):
            return False
        return self.valid(value)

    @staticmethod
    def allow(bucket: dict[str, deque], key: str, limit: int, seconds: int) -> bool:
        now = time.monotonic()
        # Bound inactive buckets as well as individual queues.
        for expired in [k for k, q in bucket.items() if not q or q[-1] < now - seconds]:
            del bucket[expired]
        if key not in bucket and len(bucket) >= 4096:
            return False
        queue = bucket[key]
        while queue and queue[0] < now - seconds:
            queue.popleft()
        if len(queue) >= limit:
            return False
        queue.append(now)
        return True

    def peer(self, request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        if self.trusted_proxy and peer == self.trusted_proxy:
            return request.headers.get("x-forwarded-for", peer).split(",")[0].strip()
        return peer


class WebGuard:
    """Apply web policy without intercepting the request/response body streams."""

    def __init__(self, app: ASGIApp, sessions: WebSessions):
        self.app = app
        self.sessions = sessions

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        sessions = self.sessions
        path = request.url.path
        rejected = None
        if path.startswith("/session") and (
            request.headers.get("origin") != sessions.origin
            or request.headers.get("x-xiaoli-client") != "web"
        ):
            rejected = JSONResponse({"detail": "请在小栗网页内操作。"}, 403)
        elif path in {"/api/v1/analyze", "/api/v1/analyze-scene", "/api/v1/composition-preview"} and sessions.auth(request.scope):
            peer = sessions.peer(request)
            cookie = request.cookies.get(COOKIE, "")
            if not sessions.allow(sessions.analyses, peer, 20, 3600):
                rejected = JSONResponse({"detail": "这个网络的体验次数已用完，请一小时后再试。"}, 429)
            elif not sessions.allow(sessions.analyses, "session:" + cookie, 6, 600):
                rejected = JSONResponse({"detail": "分析过于频繁，请稍后再试。"}, 429)

        async def send_with_headers(message: Message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "same-origin"
                headers["X-Frame-Options"] = "DENY"
                headers["Content-Security-Policy"] = (
                    "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
                    "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
                )
                if path.startswith(("/api/", "/session", "/web-config")):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await (rejected or self.app)(scope, receive, send_with_headers)


def local_workbench_url(value: str, sessions: WebSessions, request: Request) -> str | None:
    """Only advertise a launcher-provided loopback link to a local browser."""
    from urllib.parse import urlsplit

    local_hosts = {"127.0.0.1", "localhost", "::1"}
    try:
        origin = urlsplit(sessions.origin)
        url = urlsplit(value)
        if (origin.hostname not in local_hosts or sessions.trusted_proxy
                or not request.client or request.client.host not in local_hosts
                or str(request.base_url).rstrip("/") != sessions.origin
                or url.scheme != "http" or url.hostname != "127.0.0.1"
                or url.username or url.password or url.path not in {"", "/"}
                or url.query or url.fragment or url.port is None
                or not 1024 <= url.port <= 65535):
            return None
        return f"http://127.0.0.1:{url.port}/"
    except ValueError:
        return None


def create_web_app(settings: Settings, sessions: WebSessions, frontend: Path, pipeline=None,
                   *, knowledge_workbench_url: str = ""):
    app = create_app(settings, secrets.token_urlsafe(48), pipeline, session_auth=sessions.auth)
    app.add_middleware(WebGuard, sessions=sessions)

    @app.get("/web-config")
    def web_config(request: Request):
        config = {"web_client": True}
        url = local_workbench_url(knowledge_workbench_url, sessions, request)
        if url:
            config["knowledge_workbench_url"] = url
        return config

    @app.post("/session")
    def start_session(request: Request):
        peer = sessions.peer(request)
        if not sessions.allow(sessions.attempts, peer, 10, 300):
            raise HTTPException(429, "尝试过于频繁，请五分钟后重试。")
        response = JSONResponse({"status": "ok"})
        response.set_cookie(COOKIE, sessions.issue(), httponly=True, secure=sessions.secure,
                            samesite="strict", max_age=SESSION_SECONDS, path="/")
        return response

    @app.delete("/session")
    def logout():
        response = JSONResponse({"status": "ok"})
        response.delete_cookie(COOKIE, path="/", secure=sessions.secure, httponly=True, samesite="strict")
        return response

    if not (frontend / "index.html").is_file():
        raise ValueError("网页尚未构建，请先在 mobile 目录执行 npm run build。")
    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="web-assets")

    @app.get("/")
    def index():
        return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def from_env():
    settings = Settings.from_env()
    secret = os.getenv("WEB_SESSION_SECRET", "")
    origin = os.getenv("WEB_ORIGIN", "http://127.0.0.1:8080").rstrip("/")
    if not secret and origin.startswith("http://127.0.0.1:"):
        secret = secrets.token_urlsafe(48)
    sessions = WebSessions(secret, origin)
    return create_web_app(
        settings, sessions, PROJECT_ROOT / "mobile" / "dist",
        knowledge_workbench_url=os.getenv("WEB_KNOWLEDGE_WORKBENCH_URL", ""),
    )
