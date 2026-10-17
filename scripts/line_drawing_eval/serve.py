"""Static replay server that cannot reach a model service.

The handler serves only files under the replay directory and only for GET/HEAD.
Every request is appended to ``access.jsonl``; analysis/preview POSTs are
rejected with 403 and counted, which is the server-side half of the
"replay makes no model request" proof.
"""

from __future__ import annotations

import datetime as _dt
import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class ReplayHandler(SimpleHTTPRequestHandler):
    log_path: Path

    def do_POST(self) -> None:
        self._record("blocked_post")
        payload = json.dumps(
            {"error": "offline replay: analysis and preview POSTs are blocked"}
        ).encode()
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_PUT = do_POST
    do_PATCH = do_POST

    def do_GET(self) -> None:
        self._record("get")
        super().do_GET()

    def do_HEAD(self) -> None:
        self._record("head")
        super().do_HEAD()

    def log_message(self, fmt: str, *args: object) -> None:  # silence stderr noise
        return

    def _record(self, kind: str) -> None:
        entry = {
            "at": _dt.datetime.now().isoformat(timespec="milliseconds"),
            "kind": kind,
            "method": self.command,
            "path": self.path,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def create_server(root: Path, port: int = 0, log_path: Path | None = None) -> ThreadingHTTPServer:
    root = root.resolve()
    if not (root / "gallery.html").is_file():
        raise FileNotFoundError(f"gallery.html not found under {root}")
    log_path = (log_path or root / "access.jsonl").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(ReplayHandler, directory=str(root))
    ReplayHandler.log_path = log_path
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.replay_root = root  # type: ignore[attr-defined]
    server.log_path = log_path  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args(argv)
    server = create_server(args.root, args.port, args.log)
    host, port = server.server_address[:2]
    print(f"offline replay: http://{host}:{port}/gallery.html", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
