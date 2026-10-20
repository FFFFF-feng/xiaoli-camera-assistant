"""Loopback desktop entry that reuses existing private local resources."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_id() -> str:
    digest = hashlib.sha256()
    files = [*sorted((ROOT / "src").rglob("*.py")), Path(__file__),
             ROOT / "mobile/dist/index.html"]
    for path in files:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:20]


def configuration_id(settings) -> str:
    # Compare every effective setting, including credential rotation, without
    # exposing private values in the health response or launcher state.
    encoded = json.dumps(asdict(settings), sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:20]


def prepare_settings(resource_root: Path):
    from dotenv import load_dotenv

    from camera_assistant.config import Settings

    # Read the existing private configuration in memory; do not duplicate secrets.
    own_config = ROOT / ".env"
    inherited = not own_config.is_file() and (resource_root / ".env").is_file()
    load_dotenv(resource_root / ".env" if inherited else own_config)
    if inherited:
        for name, default in (
            ("KNOWLEDGE_DB_PATH", "data/knowledge.db"),
            ("VISION_LAB_DATA_DIR", "data/vision_lab"),
            ("CAMERA_AI_DETECTOR_PYTHON", ".venv-detectors/Scripts/python.exe"),
            ("CAMERA_AI_DETECTOR_WEIGHTS_PATH", "data/vision_lab/model_cache/grounding-dino-tiny"),
        ):
            path = Path(os.getenv(name, "").strip() or default).expanduser()
            os.environ[name] = str(path if path.is_absolute() else resource_root / path)
        # This environment summary describes the reused interpreter, not model data.
        source = resource_root / "data/vision_lab/model_cache/runtime.json"
        target = ROOT / "data/vision_lab/model_cache/runtime.json"
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    return Settings.from_env()


def main() -> None:
    import uvicorn
    from fastapi import HTTPException
    from starlette.responses import RedirectResponse, Response

    from camera_assistant.web_app import COOKIE, SESSION_SECONDS, WebSessions, create_web_app

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--knowledge-port", type=int, default=8503)
    parser.add_argument("--resource-root", type=Path, default=ROOT.parent / "xiaoli-camera-assistant")
    parser.add_argument("--launch-id", default=secrets.token_hex(16))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    settings = prepare_settings(args.resource_root.resolve())
    identity = {
        "service": "xiaoli-desktop-web", "build_id": build_id(), "pid": os.getpid(),
        "configuration_id": configuration_id(settings),
        "launch_id": args.launch_id,
        "project_root": str(ROOT), "analysis_mode": "cloud" if settings.cloud_ready else "demo",
        "stream_output": settings.stream_output, "parallel_advice": settings.parallel_advice,
        "detector_warmup": settings.detector_warmup,
        "composition_enabled": settings.composition_enabled, "detector_enabled": settings.detector_enabled,
    }
    if args.check:
        # Native stdout pipes in Windows PowerShell may use the OEM code page.
        print(json.dumps(identity, ensure_ascii=True))
        return
    origin = f"http://127.0.0.1:{args.port}"
    sessions = WebSessions(secrets.token_urlsafe(48), origin)
    sys.path.insert(0, str(ROOT / "scripts"))
    from launch_apps import LaunchError as WorkbenchLaunchError
    from launch_apps import ensure_knowledge_workbench, launch_lock

    try:
        with launch_lock(ROOT / ".launcher"):
            knowledge_url = ensure_knowledge_workbench(args.knowledge_port, {args.port})
    except WorkbenchLaunchError as error:
        raise SystemExit(f"知识库工作台启动失败：{error}") from None
    app = create_web_app(
        settings, sessions, ROOT / "mobile/dist",
        knowledge_workbench_url=knowledge_url,
    )
    launch_token = secrets.token_urlsafe(40)

    @app.get("/local-status")
    def local_status():
        # Windows PowerShell 5 otherwise decodes non-ASCII JSON paths as ANSI.
        return Response(json.dumps(identity, ensure_ascii=True), media_type="application/json")

    @app.get("/local-start/{supplied_token}")
    def local_start(supplied_token: str):
        if not secrets.compare_digest(supplied_token, launch_token):
            raise HTTPException(404, "启动链接已失效，请重新双击桌面快捷方式。")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, sessions.issue(), httponly=True, secure=False,
                            samesite="strict", max_age=SESSION_SECONDS, path="/")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    runtime = ROOT / ".launcher"
    runtime.mkdir(exist_ok=True)
    state_file = runtime / f"web-start-{os.getpid()}.tmp"
    state_file.write_text(json.dumps({
        **identity, "url": origin, "launch_url": f"{origin}/local-start/{launch_token}",
    }, ensure_ascii=False), encoding="utf-8")
    state_file.replace(runtime / "web-start.json")
    # Do not log the private local launch URL, cookie or model key.
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False,
                proxy_headers=False, log_level="warning")


if __name__ == "__main__":
    main()
