"""Explicit public weight preparation. Never imported or called during inference."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

from .base import MODEL_CACHE, file_provenance, manifest_path, versions

HF_MODEL = "IDEA-Research/grounding-dino-tiny"
YOLO_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt"


def main():
    parser = argparse.ArgumentParser(description="明确准备本地检测权重，不上传图片。")
    parser.add_argument("--detector", choices=("all", "grounding_dino", "yolo26"), default="all")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("YOLO_CONFIG_DIR", str(MODEL_CACHE / "ultralytics"))
    os.environ.setdefault("MPLCONFIGDIR", str(MODEL_CACHE / "matplotlib"))
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    Path(os.environ["YOLO_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    import torch

    libraries = ["torchvision"]
    if args.detector in ("all", "grounding_dino"):
        libraries.append("transformers")
    if args.detector in ("all", "yolo26"):
        libraries.append("ultralytics")
    for library in libraries:
        importlib.import_module(library)


    MODEL_CACHE.mkdir(parents=True, exist_ok=True)
    runtime = {"imports_ok": True, "python": sys.version, "executable": sys.executable,
               "platform": platform.platform(), "library_versions": versions(),
               "cuda_available": torch.cuda.is_available(), "torch_cuda": torch.version.cuda,
               "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
               "prepared_at": datetime.now(UTC).isoformat()}
    (MODEL_CACHE / "runtime.json").write_text(json.dumps(runtime, indent=2), encoding="utf-8")
    locked = sorted(f"{distribution.metadata['Name']}=={distribution.version}"
                    for distribution in importlib.metadata.distributions())
    (MODEL_CACHE / "requirements-lock.txt").write_text("\n".join(locked) + "\n", encoding="utf-8")
    print(json.dumps(runtime, ensure_ascii=True, indent=2), flush=True)
    if args.probe_only:
        return
    if args.detector in ("all", "grounding_dino"):
        from huggingface_hub import HfApi, snapshot_download

        # Resolve immutable commit first; snapshot is then pinned even when main changes.
        revision = HfApi(token=False).model_info(HF_MODEL, revision=args.revision).sha
        folder = MODEL_CACHE / "grounding-dino-tiny"
        snapshot_download(HF_MODEL, revision=revision, local_dir=folder, token=False,
                          allow_patterns=["*.json", "*.txt", "*.safetensors", "README.md"])
        files = [file_provenance(path) for path in sorted(folder.iterdir()) if path.is_file()
                 and path.name != "detector-manifest.json"]
        manifest = {"model_id": HF_MODEL, "revision": revision, "files": files,
                    "source": f"https://huggingface.co/{HF_MODEL}/tree/{revision}",
                    "license": "Apache-2.0 (official model card)",
                    "library_versions": versions(), "prepared_at": runtime["prepared_at"]}
        manifest_path(folder).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Prepared Grounding DINO Tiny: revision={revision}, files={len(files)}", flush=True)
    if args.detector in ("all", "yolo26"):
        target = MODEL_CACHE / "yolo26n.pt"
        temporary = target.with_suffix(".downloading")
        with urlopen(YOLO_URL, timeout=60) as response, temporary.open("wb") as stream:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                stream.write(chunk)
        temporary.replace(target)
        manifest = {"model_id": "Ultralytics/YOLO26n", "revision": "assets-v8.4.0",
                    "source": YOLO_URL, "files": [file_provenance(target)],
                    "license": "Ultralytics AGPL-3.0 or separately purchased Enterprise license",
                    "license_source": "https://www.ultralytics.com/license",
                    "library_versions": versions(), "prepared_at": runtime["prepared_at"]}
        manifest_path(target).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Prepared YOLO26n: {manifest['files'][0]['sha256']}", flush=True)


if __name__ == "__main__":
    main()
