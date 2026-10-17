"""Explicit live HTTP regression. Reports contain counts/codes, never photos, model bodies or keys."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def local_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise argparse.ArgumentTypeError("只允许本机HTTP地址，不向外部站点上传测试照片。")
    return value.rstrip("/")


def summarize(data: dict, sample_id: str, seconds: float) -> dict:
    """Whitelist evidence; raw provider and scene/user text never reach the report."""
    from camera_assistant.composition_models import CompositionAdvice

    value = data.get("result", {}).get("composition")
    advice = CompositionAdvice.model_validate(value) if value else None
    boards = [p.storyboard for p in advice.proposals if p.storyboard] if advice else []
    node = subprocess.run(["node", "--input-type=module", "-e",
        ("import {usableTargetBoard} from './mobile/src/target-board.mjs';"
        "let s='';process.stdin.on('data',v=>s+=v);process.stdin.on('end',()=>"
        "process.stdout.write(JSON.stringify(JSON.parse(s).map(v=>!!usableTargetBoard(v)))));")],
        input=json.dumps([b.model_dump() for b in boards]), text=True, capture_output=True, cwd=ROOT, check=True)
    accepted = json.loads(node.stdout)
    return {"sample_id": sample_id, "seconds": round(seconds, 2), "analysis_mode": data.get("analysis_mode"),
            "trace_id": advice.trace_id if advice else None,
            "diagnostics": [d.model_dump() for d in advice.diagnostics] if advice else [],
            "proposal_count": len(advice.proposals) if advice else 0,
            "backend_board_count": len(boards), "frontend_contract_accepted": accepted,
            "local_board_count": sum(b.layout_engine == "local_v1" for b in boards),
            "success": bool(boards) and all(accepted) and all(b.layout_engine == "local_v1" for b in boards)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True, help="固定场景样本，只在--live时上传")
    parser.add_argument("--url", type=local_origin, default="http://127.0.0.1:8080")
    parser.add_argument("--repeat", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--live", action="store_true", help="真实上传并调用当前已配置模型，可能计费")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--intent", default="突出主要主体，保留形态与细节，给出清晰可执行的推荐构图")
    args = parser.parse_args(argv)
    if not args.live:
        print("未执行：添加 --live 才会真实上传和调用模型；--repeat 指定次数，最多5次。")
        return 0
    from launch_web import local_environment

    _, mode = local_environment(urlsplit(args.url).port or 80)
    if mode != "cloud":
        raise SystemExit("当前本机配置不是云模型模式，未执行真实模型验收。")
    content = args.image.read_bytes()
    sample_id = hashlib.sha256(content).hexdigest()[:12]
    headers = {"Origin": args.url, "X-Xiaoli-Client": "web"}
    rows = []
    with httpx.Client(base_url=args.url, headers=headers, timeout=540, trust_env=False) as client:
        client.post("/session").raise_for_status()
        for index in range(args.repeat):
            print(f"真实上传分析 {index+1}/{args.repeat}；不自动重试失败请求。", flush=True)
            started = time.monotonic()
            result = client.post("/api/v1/analyze", files={"file": ("scene.jpg", content, "image/jpeg")},
                data={"consent": "true", "expected_analysis_mode": "cloud", "image_provenance": "original_upload",
                      "user_request": json.dumps({"intent": args.intent,
                                                 "device_type": "phone"}, ensure_ascii=False)})
            if result.status_code != 200:
                row = {"sample_id": sample_id, "success": False, "http_status": result.status_code}
            else:
                row = summarize(result.json(), sample_id, time.monotonic()-started)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    report = args.report or ROOT / "output/composition-stability" / f"upload-{time.time_ns()}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"kind": "live_http_upload", "runs": rows,
        "successes": sum(row["success"] for row in rows), "total": len(rows)}, indent=2), encoding="utf-8")
    print(f"脱敏报告：{report}")
    return 0 if all(row["success"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
