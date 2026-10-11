"""只下载本轮明确开放许可的两个文本页面，生成本地来源快照报告。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SOURCES = {"wikibooks-taking-photos", "wikibooks-introduction"}
MAX_BYTES = 2 * 1024 * 1024


def windows_https_download(url: str) -> bytes:
    """Windows标准HTTPS客户端回退；不改URL、不关闭证书校验、不使用登录态。"""
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if os.name != "nt" or not executable:
        raise ValueError("没有可用的标准Windows下载客户端")
    with tempfile.TemporaryDirectory(prefix="xiaoli-source-download-") as directory:
        destination = Path(directory) / "source.html"
        environment = {
            **os.environ,
            "XIAOLI_SOURCE_URL": url,
            "XIAOLI_SOURCE_OUT": str(destination),
        }
        script = (
            "Invoke-WebRequest -Uri $env:XIAOLI_SOURCE_URL -OutFile $env:XIAOLI_SOURCE_OUT "
            "-UseBasicParsing -MaximumRedirection 0 -TimeoutSec 20 -ErrorAction Stop"
        )
        completed = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment,
            capture_output=True,
            check=False,
            timeout=25,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if (
            completed.returncode
            or not destination.exists()
            or destination.stat().st_size > MAX_BYTES
        ):
            raise ValueError("标准HTTPS客户端下载失败或响应过大")
        return destination.read_bytes()


def main() -> int:
    sources = yaml.safe_load((ROOT / "knowledge_sources/sources.yaml").read_text(encoding="utf-8"))[
        "sources"
    ]
    output = ROOT / "data/source_cache/starter-v1"
    output.mkdir(parents=True, exist_ok=True)
    report = []
    with httpx.Client(
        timeout=20,
        follow_redirects=False,
        headers={"User-Agent": "XiaoliCameraAssistant/0.1 educational-source-review"},
    ) as client:
        for source in sources:
            if not source.get("full_text_download") or source["source_id"] not in ALLOWED_SOURCES:
                continue
            url = source["url"]
            if not url.startswith("https://en.wikibooks.org/wiki/Digital_Photography/"):
                raise ValueError("来源不在本轮开放文本下载范围")
            entry = {
                "source_id": source["source_id"],
                "url": url,
                "license": source["license"],
                "downloaded_at": datetime.now(UTC).isoformat(),
            }
            path = output / f"{source['source_id']}.html"
            if path.exists():
                entry.update(
                    status="exists",
                    bytes=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
                report.append(entry)
                print(source["source_id"], "本地已有快照，未覆盖")
                continue
            try:
                try:
                    with client.stream("GET", url) as response:
                        response.raise_for_status()
                        if "text/html" not in response.headers.get("content-type", ""):
                            raise ValueError("来源没有返回HTML文本")
                        data = bytearray()
                        for chunk in response.iter_bytes():
                            data.extend(chunk)
                            if len(data) > MAX_BYTES:
                                raise ValueError("来源页面超过2MiB限制")
                    entry["download_client"] = "httpx"
                except httpx.HTTPStatusError as error:
                    if error.response.status_code != 403:
                        raise
                    data = windows_https_download(url)
                    entry["download_client"] = "windows_https"
                text = data.decode("utf-8")
                if "Creative Commons" not in text or "Digital Photography" not in text:
                    raise ValueError("未识别到预期教材与许可标记")
                # 运行时下载产物不纳入Git；不下载任何图片、脚本、样式等链接资源。
                with path.open("xb") as file:
                    file.write(data)
                entry.update(
                    status="downloaded",
                    bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    file=path.name,
                )
            except (
                httpx.HTTPError,
                OSError,
                UnicodeError,
                ValueError,
                subprocess.SubprocessError,
            ) as error:
                entry.update(
                    status="failed", message="下载失败；未绕过站点限制，请用来源链接人工复核"
                )
                entry["error_type"] = type(error).__name__
                if isinstance(error, httpx.HTTPStatusError):
                    entry["http_status"] = error.response.status_code
            report.append(entry)
            print(source["source_id"], entry["status"])
    (output / "download-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return int(any(entry["status"] == "failed" for entry in report))


if __name__ == "__main__":
    raise SystemExit(main())
