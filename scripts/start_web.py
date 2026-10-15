"""Start the complete web client and API; only loopback is enabled by default."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if args.demo:
        os.environ["APP_DEMO_MODE"] = "true"
        os.environ["CAMERA_AI_DETECTOR_ENABLED"] = "false"
        os.environ["CAMERA_AI_COMPOSITION_ENABLED"] = "true"
    os.environ.setdefault("WEB_ORIGIN", f"http://127.0.0.1:{args.port}")
    uvicorn.run("camera_assistant.web_app:from_env", factory=True, host=args.host,
                port=args.port, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
