"""Build a secret-free device-options overlay against the deployed snapshot."""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "src/camera_assistant/models.py",
    "src/camera_assistant/pipeline.py",
    "src/camera_assistant/mobile_api.py",
    "src/camera_assistant/knowledge/context.py",
    "src/camera_assistant/services/phone_knowledge.py",
    "src/camera_assistant/services/device_reference_catalog.py",
    "src/camera_assistant/services/device_optics.py",
    "mobile/src/App.vue",
    "mobile/src/types.ts",
    "mobile/src/device-selection.mjs",
    "mobile/src/components/DevicePicker.vue",
    "scripts/launch_apps.py",
    "scripts/launch_web.py",
    "启动项目.cmd",
    "README.md",
    "scripts/verify_managed_retrieval.py",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build():
    baseline = ROOT / "output/server-20261019/xiaoli-server-20261019.tar.gz"
    output = ROOT / "output/server-devices-20261020"
    output.mkdir(parents=True, exist_ok=True)
    names = set(TARGETS)
    names.update(p.relative_to(ROOT).as_posix()
                 for p in (ROOT / "mobile/dist").rglob("*") if p.is_file())
    records, payload = {}, {}
    with tarfile.open(baseline) as previous:
        old = {m.name.removeprefix("xiaoli/"): m for m in previous if m.isfile()}
        for name in sorted(names):
            data = (ROOT / name).read_bytes()
            member = old.get(name)
            before = previous.extractfile(member).read() if member else None
            if data == before:
                continue
            payload[name] = data
            records[name] = {"before": digest(before) if before is not None else None,
                             "after": digest(data), "size": len(data)}
    manifest = {"schema": 1, "release": "device-options-20261020", "files": records,
                "baseline_archive_sha256": digest(baseline.read_bytes())}
    payload["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    archive = output / "xiaoli-device-options-20261020.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        for name, data in payload.items():
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(data), 0o644
            package.addfile(member, io.BytesIO(data))
    checksum = digest(archive.read_bytes())
    (output / "manifest.json").write_bytes(payload["manifest.json"])
    (output / "SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size,
                      "sha256": checksum, "changed_files": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    build()
