"""Apply the allowlisted camera directory release; dry-run unless --apply is used."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ROOT = Path("/opt/xiaoli-release-20261014/xiaoli")
ARCHIVE = Path("/tmp/xiaoli-camera-catalog-20261015.tar.gz")
SHA256 = "730013c69958cbb82d2f13145429bacadaa5dd417e33dec56d0ccd79d06fa4e0"
RUNTIME = {
    "models.py",
    "pipeline.py",
    "mobile_api.py",
    "services/camera_knowledge.py",
    "services/lens_knowledge.py",
    "services/advisor.py",
    "services/validator.py",
}
FRONTEND = {"types.ts", "device-selection.mjs", "components/DevicePicker.vue", "App.vue"}
LICENSES = {"CameraDatabase-MIT.txt", "Lensfun-CC-BY-SA-3.0.txt", "NOTICE.txt"}
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    "deploy/.env",
    "-f",
    "deploy/compose.yaml",
    "-f",
    "deploy/compose.prebuilt.yaml",
    "-f",
    "deploy/compose.ip.yaml",
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def allowed(name):
    return (
        (
            name.removeprefix("src/camera_assistant/") in RUNTIME
            and name.startswith("src/camera_assistant/")
        )
        or (name.removeprefix("mobile/src/") in FRONTEND and name.startswith("mobile/src/"))
        or name == "knowledge/cameras/camera_catalog.json"
        or (
            name.startswith("knowledge/cameras/catalog_licenses/")
            and PurePosixPath(name).name in LICENSES
        )
        or name == "mobile/dist/index.html"
        or (
            name.startswith("mobile/dist/assets/index-")
            and "/" not in name.removeprefix("mobile/dist/assets/")
            and PurePosixPath(name).suffix in {".js", ".css"}
        )
    )


def replace_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(data)
        temporary.flush()
        os.fchmod(temporary.fileno(), 0o644)
        filename = temporary.name
    os.replace(filename, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if ROOT.resolve() != ROOT or not (ROOT / "deploy/.env").is_file():
        raise SystemExit("Unexpected deployment root")
    if digest(ARCHIVE.read_bytes()) != SHA256:
        raise SystemExit("Archive checksum mismatch")
    payload = {}
    with tarfile.open(ARCHIVE) as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(set(names)) != len(names) or any(not member.isfile() for member in members):
            raise SystemExit("Unsafe archive member")
        manifest = json.load(archive.extractfile("catalog-release.json"))
        if manifest["release"] != "camera-catalog-20261015":
            raise SystemExit("Wrong release")
        records = manifest["files"]
        if set(names) != {"catalog-release.json", *records}:
            raise SystemExit("Archive differs from manifest")
        for name, record in records.items():
            target = ROOT / name
            if not allowed(name) or not target.resolve().is_relative_to(ROOT):
                raise SystemExit("Target not allowlisted: " + name)
            data = archive.extractfile(name).read()
            if digest(data) != record["sha256"]:
                raise SystemExit("File checksum mismatch: " + name)
            # The public frontend already includes this picker and concurrent
            # composition improvements. Never overwrite that newer frontend.
            if name.startswith("mobile/"):
                continue
            current = digest(target.read_bytes()) if target.exists() else None
            if current != record["previous_sha256"]:
                raise SystemExit("Server version changed; no files written: " + name)
            payload[name] = data
    print("Preflight passed:", len(payload), "files", flush=True)
    if not args.apply:
        return
    backup = ROOT.parent / (
        "camera-catalog-backup-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + ".tar.gz"
    )
    with tarfile.open(backup, "w:gz") as saved:
        for name in payload:
            if (ROOT / name).exists():
                saved.add(ROOT / name, arcname=name, recursive=False)
    print("Backup:", backup, flush=True)
    for name, data in payload.items():
        replace_file(ROOT / name, data)
    try:
        subprocess.run([*COMPOSE, "up", "-d", "--build", "--no-deps", "app"], cwd=ROOT, check=True)
    except subprocess.CalledProcessError:
        with tarfile.open(backup) as saved:
            for member in saved.getmembers():
                replace_file(ROOT / member.name, saved.extractfile(member).read())
        subprocess.run([*COMPOSE, "up", "-d", "--build", "--no-deps", "app"], cwd=ROOT, check=False)
        raise
    subprocess.run([*COMPOSE, "ps"], cwd=ROOT, check=True)
    print("Release applied. Await health and authenticated UI checks.", flush=True)


if __name__ == "__main__":
    main()
