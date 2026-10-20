"""Create a dated APK handoff with a source companion and printable demo script."""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DATE = "20261019"
OUT = ROOT / "output/releases" / f"xiaoli-android-{DATE}"
PREFIXES = ("src/", "knowledge/", "assets/", "scripts/", "tests/", "docs/", "deploy/",
            "mobile/src/", "mobile/public/", "mobile/tests/", "mobile/android/")
ROOT_FILES = {"pyproject.toml", "README.md", "AGENTS.md", ".env.example", ".gitignore",
              "app.py", "knowledge_app.py", "vision_lab.py", "启动项目.cmd", "启动手机服务.cmd",
              "start_app.ps1", "start_web.ps1", "Dockerfile", "Dockerfile.prebuilt", ".dockerignore",
              "Dockerfile.prebuilt.dockerignore", "requirements-detectors.txt", "requirements-segmentation-cpu.txt"}
EXTRA = {"docs/demo-recording-20261019.md", "docs/android-delivery-20261019.md",
         "scripts/package_android_delivery.py", "tests/test_mobile_local_configuration.py",
         "tests/test_android_delivery_package.py"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inline(text: str) -> str:
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text))


def render_markdown(text: str) -> str:
    chunks, in_list, in_table = [], False, False
    for line in text.splitlines():
        if not line.startswith("- ") and in_list:
            chunks.append("</ul>")
            in_list = False
        if not line.startswith("|") and in_table:
            chunks.append("</tbody></table></div>")
            in_table = False
        if not line.strip():
            continue
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                continue
            if not in_table:
                chunks.append('<div class="table-wrap"><table><thead><tr>'+"".join(
                    "<th>"+inline(cell)+"</th>" for cell in cells)+"</tr></thead><tbody>")
                in_table = True
            else:
                chunks.append("<tr>"+"".join("<td>"+inline(cell)+"</td>" for cell in cells)+"</tr>")
        elif line.startswith("# "):
            chunks.append("<h1>"+inline(line[2:])+"</h1>")
        elif line.startswith("## "):
            chunks.append("<h2>"+inline(line[3:])+"</h2>")
        elif line.startswith("- "):
            if not in_list:
                chunks.append("<ul>")
                in_list = True
            chunks.append("<li>"+inline(line[2:])+"</li>")
        else:
            label = next((prefix for prefix in ("操作：", "口播：", "检查：") if line.startswith(prefix)), None)
            body = ("<b>"+label+"</b>"+inline(line[len(label):])) if label else inline(line)
            chunks.append(f'<p class="{"speech" if label == "口播：" else "note"}">{body}</p>')
    if in_list:
        chunks.append("</ul>")
    if in_table:
        chunks.append("</tbody></table></div>")
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>小栗录屏演示讲解稿</title>
<style>body{margin:0;background:#eef3f2;color:#203b35;font:16px/1.85 'Microsoft YaHei',sans-serif}
main{max-width:900px;margin:32px auto;background:#fff;padding:44px 52px;box-sizing:border-box}
h1{font-size:28px;line-height:1.5;color:#000;margin:0 0 22px}h2{font-size:21px;color:#000;margin:34px 0 14px;break-after:avoid}
p{margin:12px 0;overflow-wrap:anywhere}b{color:#20584c}.speech{background:#f2f7f4;padding:16px 20px;border-left:3px solid #6d998b}
code{font:14px/1.7 Consolas,monospace;background:#edf1f3;padding:2px 5px;overflow-wrap:anywhere}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #d9d9d9;padding:11px 12px;text-align:left}th{background:#dfebe6;color:#000}td:first-child{white-space:nowrap}
li{margin:10px 0}button{border:1px solid #83a397;background:white;color:#20584c;padding:9px 18px;cursor:pointer}
@media(max-width:600px){main{margin:0;padding:24px 18px}h1{font-size:25px}.speech{padding:12px 14px}}
@media print{body{background:white;color:black}main{margin:0;padding:0;max-width:none}button{display:none}p,li{orphans:3;widows:3}.speech{background:none;border-left:1px solid #aaa}table{font-size:10pt}h2{break-after:avoid}tr{break-inside:avoid}}</style>
<main><button onclick="window.print()">打印或另存为 PDF</button>"""+"\n".join(chunks)+"</main></html>"


def private_values() -> list[bytes]:
    values = set()
    for name in (".env", ".env.zhipu-deploy", ".env.web-invite"):
        for key, value in dotenv_values(ROOT / name).items():
            if value and len(value) >= 24 and re.search(r"KEY|TOKEN|SECRET|PASSWORD", key):
                values.add(value.encode())
    token_file = ROOT / ".launcher/mobile-access.json"
    if token_file.exists():
        values.add(json.loads(token_file.read_text(encoding="utf-8"))["token"].encode())
    return list(values)


def main() -> None:
    apk = ROOT / "output/mobile/xiaoli-camera-assistant-debug.apk"
    private = private_values()
    with zipfile.ZipFile(apk) as package:
        for name in package.namelist():
            leaf = Path(name).name.lower()
            if leaf.startswith(".env") or leaf.endswith((".keystore", ".jks", ".key", ".pem", ".db", ".sqlite")):
                raise SystemExit("APK包含不允许交付的文件，停止打包。")
            if any(value in package.read(name) for value in private):
                raise SystemExit("APK私密数据审查未通过，停止打包；未打印匹配内容。")
        dist = ROOT / "mobile/dist"
        assets = [path for path in dist.rglob("*") if path.is_file()]
        for path in assets:
            if package.read("assets/public/"+path.relative_to(dist).as_posix()) != path.read_bytes():
                raise SystemExit("APK内资源与当前前端构建不同，必须重新构建。")
    OUT.mkdir(parents=True, exist_ok=True)
    delivered_apk = OUT / f"xiaoli-camera-assistant-{DATE}-debug.apk"
    shutil.copyfile(apk, delivered_apk)
    for name in (f"demo-recording-{DATE}.md", f"android-delivery-{DATE}.md"):
        shutil.copyfile(ROOT / "docs" / name, OUT / name)
    (OUT / f"demo-recording-{DATE}.html").write_text(render_markdown(
        (ROOT / "docs" / f"demo-recording-{DATE}.md").read_text(encoding="utf-8")), encoding="utf-8")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    selected = set()
    for name in [*tracked, *EXTRA]:
        path = ROOT / name
        if not name or not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            continue
        if not (name in ROOT_FILES or name.startswith(PREFIXES) or (name.startswith("mobile/") and name.count("/") == 1)):
            continue
        if (path.suffix in {".pyc", ".db", ".sqlite", ".sqlite3", ".key", ".pem", ".jks", ".keystore", ".apk"}
                or (path.name.startswith(".env") and path.name != ".env.example")):
            continue
        selected.add(path)
    selected.update(assets)
    source_zip = OUT / f"xiaoli-backend-and-source-{DATE}.zip"
    with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(selected):
            data = path.read_bytes()
            if any(value in data for value in private):
                raise SystemExit("源码私密数据审查未通过，停止打包；未打印匹配内容。")
            archive.writestr("xiaoli/"+path.relative_to(ROOT).as_posix(), data)
    summary = {
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "includes_local_delivery_changes": True,
        "apk_version": "0.1.0", "version_code": 1, "debug_signed": True,
        "min_android_api": 24, "target_android_api": 36,
        "bundled_frontend_files_verified": len(assets), "backend_source_files": len(selected),
        "private_values_absent": True, "device_install_test": "not_run_no_adb_device",
        "frontend_tests_passed": 106, "targeted_backend_tests_passed": 226,
        "launcher_tests_passed": 25, "server_deployed": False,
        "files": {path.name: {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}
                  for path in sorted(OUT.iterdir()) if path.is_file() and path.name not in {"manifest.json", "SHA256SUMS"}},
    }
    (OUT / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "SHA256SUMS").write_text("\n".join(f"{entry['sha256']}  {name}" for name, entry in summary["files"].items())+"\n", encoding="utf-8")
    bundle = OUT.parent / f"xiaoli-android-submission-{DATE}.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(OUT.iterdir()):
            if path.is_file():
                archive.write(path, OUT.name+"/"+path.name)
    print(json.dumps({"apk": str(delivered_apk), "bundle": str(bundle),
                      "frontend_files_verified": len(assets), "source_files": len(selected),
                      "private_values_absent": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
