"""File IPC worker. All expensive imports happen only inside this interpreter."""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from collections import OrderedDict
from pathlib import Path

from PIL import Image

from vision_lab_tool.detector_models import DetectionResult, DetectorConfig

from .base import provenance, weights_path


def _offline_guard(*args, **kwargs):
    raise OSError("检测 worker 禁止网络访问；请使用明确的准备步骤下载依赖和权重。")


def _run_request(request, models, torch):
    """Handle preparation and inference with the same verified model cache."""
    started = time.perf_counter()
    config = DetectorConfig.model_validate(request["config"])
    try:
        operation = request.get("operation", "detect")
        if operation not in {"detect", "warmup"}:
            raise ValueError("未知检测 worker 操作。")
        if config.device == "cuda:0" and not torch.cuda.is_available():
            raise RuntimeError("CUDA 不可用；没有静默切换设备。")
        details = provenance(config)
        key = (config.detector, str(weights_path(config)), config.device,
               config.precision, details["model_revision"],
               tuple(file["sha256"] for file in details["weights"]))
        cold = key not in models
        if cold:
            if config.detector == "grounding_dino":
                from .grounding_dino_hf import GroundingDinoHF
                adapter = GroundingDinoHF(config)
            else:
                from .ultralytics_yolo import UltralyticsYOLO
                adapter = UltralyticsYOLO(config)
            # Insert only a successfully initialized adapter.
            models[key] = adapter
            while len(models) > 2:
                models.popitem(last=False)
        models.move_to_end(key)
        if operation == "warmup":
            return DetectionResult(
                config=config, status="ready", real=False,
                metadata={"operation": "warmup", "model_cache_hit": not cold},
                timings={"total": time.perf_counter() - started},
            )
        with Image.open(request["image_path"]) as original:
            image = original.convert("RGB")
        result = models[key].detect(image, request["queries"], config, cold=cold)
        result.metadata["image"] = request["image_metadata"]
        return result
    except Exception as exc:  # noqa: BLE001 -- framework failures must not lose other stages.
        return DetectionResult(config=config, status="runtime_error",
                               diagnostics=[f"{type(exc).__name__}: {exc}"],
                               timings={"total": time.perf_counter() - started})


def main():
    # Defense in depth: detector inference is local even if upstream libraries
    # acquire a new telemetry/downloader behavior. Preparation runs separately.
    socket.socket.connect = _offline_guard
    socket.create_connection = _offline_guard
    import torch

    torch.set_num_threads(min(4, os.cpu_count() or 1))
    models = OrderedDict()
    for line in sys.stdin:
        request = json.loads(line)
        output = Path(request["output_path"])
        result = _run_request(request, models, torch)
        # Atomic response prevents the parent from reading partial JSON.
        temporary = output.with_suffix(".writing")
        temporary.write_text(result.model_dump_json(), encoding="utf-8")
        temporary.replace(output)


if __name__ == "__main__":
    main()
