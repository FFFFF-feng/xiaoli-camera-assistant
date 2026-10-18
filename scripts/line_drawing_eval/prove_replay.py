"""Serve the static gallery locally and prove a browser replay makes no POST."""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
from pathlib import Path

from .evidence import sha256_file, write_json
from .serve import create_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gallery", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--node", default="node")
    parser.add_argument("--script", type=Path, default=Path(__file__).with_name("browser_replay.cjs"))
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    log_path = args.out / "server-access.jsonl"
    server = create_server(args.gallery, 0, log_path)
    host, port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://{host}:{port}/gallery.html"
    try:
        completed = subprocess.run(
            [args.node, str(args.script), "--url", url, "--out", str(args.out / "browser")],
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    metrics_path = args.out / "browser" / "replay-metrics.json"
    if not metrics_path.is_file():
        print(completed.stdout)
        print(completed.stderr)
        raise SystemExit(f"browser replay did not produce {metrics_path}")
    browser_metrics = json.loads(metrics_path.read_text("utf-8"))
    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    server_summary = {
        "requests": len(entries),
        "by_kind": {
            kind: sum(1 for entry in entries if entry["kind"] == kind)
            for kind in ("get", "head", "blocked_post")
        },
        "methods": {
            method: sum(1 for entry in entries if entry["method"] == method)
            for method in ("GET", "HEAD", "POST", "PUT", "PATCH")
        },
    }
    proof = {
        "schema": "line-drawing-replay-proof-v1",
        "kind": "offline_static_replay",
        "offline": True,
        "generated_model_requests": 0,
        "gallery_sha256": sha256_file(args.gallery / "gallery.html"),
        "server": server_summary,
        "browser": browser_metrics,
        "assertions": {
            "server_saw_no_successful_post": server_summary["by_kind"]["blocked_post"] == 0,
            "page_has_no_scripts": browser_metrics["contains_scripts"] is False,
            "post_probe_blocked_twice": len(browser_metrics["blocked_posts"]) == 2,
            "no_post_reached_a_handler": browser_metrics["actual_analysis_posts"] == 0,
            "no_external_requests": len(browser_metrics["blocked_external_requests"]) == 0,
            "no_page_errors": len(browser_metrics["page_errors"]) == 0,
            "no_horizontal_overflow": browser_metrics["no_horizontal_overflow"] is True,
        },
        "node_stdout": completed.stdout.strip(),
        "node_stderr": completed.stderr.strip(),
        "node_exit_code": completed.returncode,
        "server_access_log": str(log_path),
        "browser_metrics": str(args.out / "browser" / "replay-metrics.json"),
    }
    proof["ok"] = all(proof["assertions"].values()) and completed.returncode == 0
    write_json(args.out / "replay-proof.json", proof)
    print(json.dumps(proof["assertions"] | {"ok": proof["ok"]}, ensure_ascii=False, indent=2))
    return 0 if proof["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
