"""Package an allowlisted application snapshot, excluding credentials and local data."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ["src", "knowledge", "assets", "mobile/src", "mobile/tests", "mobile/dist"]
FILES = [
    "pyproject.toml", "README.md", "Dockerfile", ".dockerignore", ".env.example",
    "Dockerfile.prebuilt", "Dockerfile.prebuilt.dockerignore", "deploy/compose.prebuilt.yaml",
    "mobile/package.json", "mobile/package-lock.json", "mobile/index.html",
    "mobile/tsconfig.json", "mobile/vite.config.ts", "mobile/capacitor.config.ts",
    "deploy/compose.yaml", "deploy/compose.dino.yaml", "deploy/Caddyfile",
    "deploy/production.env.example", "deploy/Caddyfile.ip", "deploy/compose.ip.yaml",
    "scripts/start_web.py", "scripts/configure_web_deploy.py",
    "scripts/build_release.py", "docs/web-experience-deployment.md",
]


def main():
    if not (ROOT / "mobile/dist/index.html").is_file():
        raise SystemExit("请先在 mobile 执行 npm run build。")
    paths = {ROOT / file for file in FILES}
    for folder in FOLDERS:
        paths.update(path for path in (ROOT / folder).rglob("*") if path.is_file())
    paths = sorted(path for path in paths if "__pycache__" not in path.parts
                   and path.suffix not in {".pyc", ".pem", ".key", ".db", ".sqlite", ".sqlite3"}
                   and not path.is_symlink())
    for path in paths:
        if not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise SystemExit(f"打包目标无效：{path.name}")
        if path.name.startswith(".env") and path.name != ".env.example":
            raise SystemExit("打包拒绝私有环境配置。")
    output = ROOT / "output/releases"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "xiaoli-web-experience.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        for path in paths:
            info = package.gettarinfo(path, arcname="xiaoli/" + path.relative_to(ROOT).as_posix())
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as source:
                package.addfile(info, source)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "includes_working_changes": True,
        "archive_sha256": digest,
        "files": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"已生成 {archive.name}，共 {len(paths)} 文件；不包含本地密钥、照片、数据库及实验记录。")


if __name__ == "__main__":
    main()
