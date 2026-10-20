"""Start the authenticated LAN demo gateway, not the knowledge admin UI."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def apply_local_configuration(port: int, demo: bool) -> None:
    """Reuse the local web launcher's model/proxy policy, never its web session."""
    from launch_web import local_environment

    environment, _ = local_environment(port, demo)
    os.environ.update({key: value for key, value in environment.items()
                       if not key.startswith("WEB_")})


def load_token() -> tuple[str, Path]:
    path = ROOT / ".launcher" / "mobile-access.json"
    configured = os.getenv("MOBILE_API_TOKEN", "").strip()
    if configured:
        return configured, path
    if path.exists():
        token = json.loads(path.read_text(encoding="utf-8"))["token"]
        if not isinstance(token, str) or len(token) < 24:
            raise ValueError("Invalid stored token; check .launcher/mobile-access.json")
        return token, path
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": token}, indent=2), encoding="utf-8")
    return token, path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--local-config", action="store_true",
                        help="Reuse this project's local model and proxy configuration")
    parser.add_argument(
        "--demo", action="store_true", help="Force offline rule demo; no cloud calls"
    )
    args = parser.parse_args()
    try:
        from dataclasses import replace

        import uvicorn

        from camera_assistant.config import Settings
        from camera_assistant.mobile_api import create_app

        if args.local_config:
            apply_local_configuration(args.port, args.demo)
        settings = Settings.from_env()
        if args.demo:
            settings = replace(settings, demo_mode=True)
        token, token_path = load_token()
        with socket.socket() as probe:
            probe.bind((args.host, args.port))
        app = create_app(settings, token)
    except ImportError:
        print('Missing dependency. Run: python -m pip install -e ".[mobile]"')
        return 1
    except (ValueError, OSError, KeyError):
        print("Startup failed: check port, configuration, and local token file.")
        return 1
    print(f"Mobile API port: {args.port}. Mode: {'cloud' if settings.cloud_ready else 'demo'}")
    if args.host == "0.0.0.0":
        print("LAN DEMO ONLY: use your computer Wi-Fi IPv4 address on the phone.")
        print("Do not expose this HTTP endpoint to the public internet.")
    print(f"Connection token: open {token_path} locally (or use MOBILE_API_TOKEN from .env).")
    print("Photos are not retained by this gateway. Ctrl+C stops the service.")
    uvicorn.run(app, host=args.host, port=args.port, access_log=False, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
