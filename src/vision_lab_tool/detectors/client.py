"""Persistent hidden worker with file IPC; importing this module never imports torch."""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from vision_lab_tool.detector_models import DetectionResult, DetectorConfig

from .base import PROJECT_ROOT, read_manifest, weights_path

if TYPE_CHECKING:
    from vision_lab_tool.images import PreparedImage


class DetectorClient:
    def __init__(self, root: Path = PROJECT_ROOT, python: Path | None = None):
        self.root = Path(root).resolve()
        self.python = Path(python) if python else self.root / ".venv-detectors/Scripts/python.exe"
        if os.name != "nt" and python is None:
            self.python = self.root / ".venv-detectors/bin/python"
        self._worker = None
        self._generation = 0
        self._lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._log = None

    def readiness(self, config: DetectorConfig) -> dict:
        path = weights_path(config, self.root)
        diagnostics = []
        status = "ready"
        runtime_file = self.root / "data/vision_lab/model_cache/runtime.json"
        try:
            runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            runtime = {}
        if not self.python.is_file() or not runtime.get("imports_ok"):
            status = "environment_missing"
            diagnostics.append("独立检测环境未准备；运行 scripts/prepare_detectors.ps1。")
        if config.detector == "grounding_dino":
            present = (path.is_dir() and (path / "config.json").is_file()
                       and bool(list(path.glob("*.safetensors"))))
        else:
            present = path.is_file() and path.name == "yolo26n.pt"
        if not present:
            status = "model_missing" if status == "ready" else status
            diagnostics.append("本地权重不存在或型号不符；点击推理不会自动下载。")
        if config.device not in ("cpu", "cuda:0"):
            status = "device_unavailable"
            diagnostics.append("首版支持 cpu 和 cuda:0；请检查设备。")
        elif config.device == "cuda:0" and not runtime.get("cuda_available", False):
            status = "device_unavailable"
            diagnostics.append("独立环境 PyTorch 没有可用 CUDA；可选择 CPU。")
        if config.precision == "float16" and config.device == "cpu":
            status = "precision_unsupported"
            diagnostics.append("CPU 首版使用 float32；没有静默更换精度。")
        return {"ready": status == "ready", "status": status, "diagnostics": diagnostics,
                "python": str(self.python), "weights_path": str(path),
                "manifest": read_manifest(path), "runtime": runtime}

    def _start(self):
        with self._process_lock:
            if self._worker and self._worker.poll() is None:
                return self._worker
            cache = self.root / "data/vision_lab/detector_experiments/worker"
            cache.mkdir(parents=True, exist_ok=True)
            if self._log:
                self._log.close()
            self._log = (cache / "worker.log").open("a", encoding="utf-8")
            env = os.environ.copy()
            env.update({"PYTHONPATH": str(self.root / "src"), "PYTHONUTF8": "1",
                        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "YOLO_AUTOINSTALL": "false",
                        "YOLO_CONFIG_DIR": str(cache / "ultralytics"),
                        "MPLCONFIGDIR": str(cache / "matplotlib")})
            Path(env["YOLO_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
            Path(env["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self._worker = subprocess.Popen(
                [str(self.python), "-u", "-m", "vision_lab_tool.detectors.worker"],
                cwd=self.root, env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=self._log, text=True, encoding="utf-8", creationflags=flags,
            )
            return self._worker

    def detect(self, image: PreparedImage, queries: list[str],
               config: DetectorConfig) -> DetectionResult:
        prepared = self.readiness(config)
        if not prepared["ready"]:
            return DetectionResult(config=config, status=prepared["status"],
                                   diagnostics=prepared["diagnostics"], metadata=prepared)
        if config.detector == "grounding_dino" and not queries:
            return DetectionResult(config=config, status="query_missing",
                                   diagnostics=["Grounding DINO 需要英文类别查询。"])
        with self._lock:
            started = time.perf_counter()
            generation = self._generation
            temp_root = self.root / "data/vision_lab/detector_experiments/worker"
            temp_root.mkdir(parents=True, exist_ok=True)
            try:
                worker = self._start()
                with tempfile.TemporaryDirectory(prefix="request-", dir=temp_root) as folder:
                    image_path, output_path = Path(folder) / "sent.jpg", Path(folder) / "result.json"
                    image_path.write_bytes(image.sent_bytes)
                    request = {"image_path": str(image_path), "output_path": str(output_path),
                               "config": config.model_dump(mode="json"), "queries": queries,
                               "image_metadata": image.metadata()}
                    worker.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
                    worker.stdin.flush()
                    while not output_path.exists():
                        elapsed = time.perf_counter() - started
                        if self._generation != generation:
                            return DetectionResult(config=config, status="cancelled",
                                                   diagnostics=["用户停止本地检测 worker。"],
                                                   timings={"wall_total": elapsed})
                        if elapsed >= config.timeout_seconds:
                            self.stop_worker()
                            return DetectionResult(config=config, status="timeout",
                                                   diagnostics=["检测超时；worker 已停止，下次重新加载。"],
                                                   timings={"wall_total": elapsed})
                        if worker.poll() is not None:
                            return DetectionResult(config=config, status="runtime_error",
                                                   diagnostics=[f"检测 worker 提前退出，exit={worker.returncode}；见 worker.log。"],
                                                   timings={"wall_total": elapsed})
                        time.sleep(0.05)
                    result = DetectionResult.model_validate_json(output_path.read_text("utf-8"))
                    result.timings["wall_total"] = time.perf_counter() - started
                    result.timings["worker_and_ipc_overhead"] = max(
                        0.0, result.timings["wall_total"] - result.timings.get("total", 0))
                    result.metadata["sent_sha256"] = hashlib.sha256(image.sent_bytes).hexdigest()
                    return result
            except (OSError, ValueError) as exc:
                if self._generation != generation:
                    return DetectionResult(config=config, status="cancelled",
                                           diagnostics=["用户停止本地检测 worker。"],
                                           timings={"wall_total": time.perf_counter() - started})
                self.stop_worker()
                return DetectionResult(config=config, status="runtime_error",
                                       diagnostics=[f"本地 worker 通信失败：{type(exc).__name__}。"],
                                       timings={"wall_total": time.perf_counter() - started})

    def stop_worker(self):
        self._generation += 1
        with self._process_lock:
            worker = self._worker
            self._worker = None
            if worker and worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=3)
            if worker and worker.stdin:
                worker.stdin.close()
            if self._log:
                self._log.close()
                self._log = None


_client = DetectorClient()
atexit.register(_client.stop_worker)


def detect(image, queries, config):
    return _client.detect(image, queries, config)


def readiness(config):
    return _client.readiness(config)


def stop_worker():
    return _client.stop_worker()
