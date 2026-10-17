"""Build a credential-free incremental release against the deployed web snapshot."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    "src/camera_assistant/models.py",
    "src/camera_assistant/pipeline.py",
    "src/camera_assistant/mobile_api.py",
    "src/camera_assistant/services/camera_knowledge.py",
    "src/camera_assistant/services/lens_knowledge.py",
    "src/camera_assistant/services/advisor.py",
    "src/camera_assistant/services/validator.py",
    "mobile/src/types.ts",
    "mobile/src/device-selection.mjs",
    "mobile/src/components/DevicePicker.vue",
    "mobile/src/App.vue",
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    output = ROOT / "output/releases"
    paths = {name: ROOT / name for name in TARGETS}
    paths["knowledge/cameras/camera_catalog.json"] = ROOT / "knowledge/cameras/camera_catalog.json"
    paths.update(
        {
            p.relative_to(ROOT).as_posix(): p
            for p in (ROOT / "knowledge/cameras/catalog_licenses").glob("*.txt")
        }
    )
    records = {}
    changed = {}
    with tarfile.open(output / "xiaoli-web-experience.tar.gz") as previous:
        # Build only this change over the deployed frontend, leaving concurrent
        # composition work and its mobile/dist output untouched.
        stage = Path(tempfile.mkdtemp(prefix=".catalog-release-", dir=ROOT / "mobile"))
        for member in previous.getmembers():
            name = member.name.removeprefix("xiaoli/")
            if not member.isfile() or not name.startswith(("mobile/", "assets/")):
                continue
            if name.startswith("mobile/dist/"):
                continue
            destination = stage / name
            if not destination.resolve().is_relative_to(stage.resolve()):
                raise ValueError("Unsafe baseline member")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(previous.extractfile(member).read())
        for name in TARGETS:
            if name.startswith("mobile/"):
                shutil.copyfile(ROOT / name, stage / name)
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        subprocess.run([npm, "run", "build"], cwd=stage / "mobile", check=True)
        paths.update(
            {
                "mobile/dist/" + p.relative_to(stage / "mobile/dist").as_posix(): p
                for p in (stage / "mobile/dist").rglob("*")
                if p.is_file()
            }
        )
        for name, path in paths.items():
            data = path.read_bytes()
            try:
                old = previous.extractfile("xiaoli/" + name).read()
            except KeyError:
                old = None
            if old == data:
                continue
            records[name] = {
                "sha256": digest(data),
                "previous_sha256": digest(old) if old is not None else None,
            }
            changed[name] = data
    manifest = {"release": "camera-catalog-20261015", "files": records}
    metadata = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    archive = output / "xiaoli-camera-catalog-20261015.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        for name, data in {"catalog-release.json": metadata, **changed}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            package.addfile(info, io.BytesIO(data))
    (output / "camera-catalog-release.json").write_bytes(metadata)
    print(
        json.dumps(
            {
                "archive": archive.name,
                "files": len(records),
                "bytes": archive.stat().st_size,
                "sha256": digest(archive.read_bytes()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
