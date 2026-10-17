"""Offline warmup contract: load the real cache path without speculative inference."""
from __future__ import annotations

import io
import json
import threading
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from camera_assistant.config import Settings
from camera_assistant.services.localization import GroundingDinoLocalizer
from vision_lab_tool.detector_models import DetectionResult, DetectorConfig
from vision_lab_tool.detectors.client import DetectorClient
from vision_lab_tool.detectors.worker import _run_request


@pytest.fixture
def adapter_calls(monkeypatch):
    """Replace only framework loading/inference; run the real worker/cache code."""
    events = []

    class Adapter:
        def __init__(self, config):
            events.append(("load", config.model_dump()))

        def detect(self, image, queries, config, *, cold=False):
            events.append(("detect", image.size, queries, config.model_dump(), cold))
            return DetectionResult(config=config, status="success", metadata={
                "model_cache_hit": not cold, "queries": queries,
            })

    monkeypatch.setattr(
        "vision_lab_tool.detectors.grounding_dino_hf.GroundingDinoHF", Adapter
    )
    monkeypatch.setattr("vision_lab_tool.detectors.worker.provenance", lambda config: {
        "model_revision": "verified-local", "weights": [{"sha256": "same-local-weights"}],
    })
    return events


@pytest.fixture
def prepared(tmp_path):
    python = tmp_path / "python.exe"
    python.write_bytes(b"test interpreter")
    runtime = tmp_path / "data/vision_lab/model_cache/runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(json.dumps({"imports_ok": True, "cuda_available": False}))
    weights = tmp_path / "weights"
    weights.mkdir()
    (weights / "config.json").write_text("{}")
    (weights / "model.safetensors").write_bytes(b"test weights")
    config = DetectorConfig(detector="grounding_dino", weights_path=str(weights),
                            box_threshold=.37, text_threshold=.28, timeout_seconds=1)
    buffer = io.BytesIO()
    Image.new("RGB", (80, 40)).save(buffer, "JPEG")
    image = SimpleNamespace(sent_bytes=buffer.getvalue(), metadata=lambda: {"sent_size": [80, 40]})
    return DetectorClient(tmp_path, python), image, config


class WorkerProcess:
    """File IPC boundary double; model caching and protocol handling remain real."""
    def __init__(self, *, before_request=None):
        self.stdin = self
        self.returncode = None
        self.requests = []
        self.models = OrderedDict()
        self.before_request = before_request
        self.pending = ""

    def write(self, value):
        self.pending += value

    def flush(self):
        request = json.loads(self.pending)
        self.pending = ""
        self.requests.append(request)
        if self.before_request:
            self.before_request(request)
        result = _run_request(request, self.models, SimpleNamespace())
        Path(request["output_path"]).write_text(result.model_dump_json(), encoding="utf-8")

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout):
        return self.returncode

    def close(self):
        pass


def connect_process(client, process):
    client._worker = process
    client._start = lambda: process


def test_warmup_loads_without_image_queries_or_inference_and_detect_reuses_model(
    prepared, adapter_calls,
):
    client, image, config = prepared
    process = WorkerProcess()
    connect_process(client, process)

    ready = client.warmup(config)
    assert ready["ready"]
    assert [event[0] for event in adapter_calls] == ["load"]
    warm_request = process.requests[0]
    assert warm_request["operation"] == "warmup"
    assert not {"image_path", "image_metadata", "queries"} & set(warm_request)

    result = client.detect(image, ["cat", "tree"], config)
    assert result.status == "success" and result.real
    assert result.metadata["queries"] == ["cat", "tree"]
    assert result.metadata["model_cache_hit"]
    assert [event[0] for event in adapter_calls] == ["load", "detect"]
    assert adapter_calls[0][1] == adapter_calls[1][3] == config.model_dump()
    assert adapter_calls[1][1:3] == ((80, 40), ["cat", "tree"])
    assert adapter_calls[1][-1] is False
    client.stop_worker()


def test_failed_load_is_not_cached_and_real_detection_can_retry(prepared, monkeypatch):
    client, image, config = prepared
    loads = []

    class FlakyAdapter:
        def __init__(self, received_config):
            loads.append(received_config)
            if len(loads) == 1:
                raise RuntimeError("synthetic load failure")

        def detect(self, image, queries, config, *, cold=False):
            return DetectionResult(config=config, status="success", metadata={"cold": cold})

    monkeypatch.setattr(
        "vision_lab_tool.detectors.grounding_dino_hf.GroundingDinoHF", FlakyAdapter
    )
    monkeypatch.setattr("vision_lab_tool.detectors.worker.provenance", lambda config: {
        "model_revision": "verified-local", "weights": [],
    })
    processes = []

    def start():
        if client._worker is None:
            client._worker = WorkerProcess()
            processes.append(client._worker)
        return client._worker

    client._start = start
    ready = client.warmup(config)
    assert not ready["ready"] and ready["status"] == "runtime_error"
    assert not processes[0].models
    assert processes[0].poll() == 0 and client._worker is None

    result = client.detect(image, ["cat"], config)
    assert result.status == "success" and result.metadata["cold"]
    assert len(processes) == len(loads) == 2
    assert processes[1].requests[0]["operation"] == "detect"
    client.stop_worker()


def test_warmup_and_detection_are_one_at_a_time(prepared, adapter_calls):
    client, image, config = prepared
    warming = threading.Event()
    release = threading.Event()
    detecting = threading.Event()
    results = []

    def before_request(request):
        if request["operation"] == "warmup":
            warming.set()
            assert release.wait(timeout=2)
        else:
            detecting.set()

    process = WorkerProcess(before_request=before_request)
    connect_process(client, process)
    warm = threading.Thread(target=lambda: results.append(client.warmup(config)))
    detect = threading.Thread(target=lambda: results.append(client.detect(image, ["cat"], config)))
    try:
        warm.start()
        assert warming.wait(timeout=1)
        detect.start()
        assert not detecting.wait(timeout=.05)
        assert len(process.requests) == 1
    finally:
        release.set()
        warm.join(timeout=2)
        detect.join(timeout=2)
        client.stop_worker()
    assert not warm.is_alive() and not detect.is_alive()
    assert len(results) == 2
    assert results[0]["ready"] and results[1].status == "success"
    assert [request["operation"] for request in process.requests] == ["warmup", "detect"]
    assert [event[0] for event in adapter_calls] == ["load", "detect"]


def test_missing_runtime_does_not_start_warmup_worker(tmp_path):
    client = DetectorClient(tmp_path)
    client._start = lambda: pytest.fail("warmup must not prepare or download dependencies")
    result = client.warmup(DetectorConfig(detector="grounding_dino"))
    assert result["status"] == "environment_missing" and not result["ready"]


def test_localizer_warms_the_same_config_without_detection():
    configurations = []
    client = SimpleNamespace(
        warmup=lambda config: configurations.append(config) or {"ready": True},
        detect=lambda *args: pytest.fail("warmup must not infer"), stop_worker=lambda: None,
    )
    settings = Settings(demo_mode=False, api_key="", base_url="https://example.invalid/v1",
                        vision_model="offline", text_model="offline", timeout_seconds=5,
                        max_image_mb=15, knowledge_dir=Path("knowledge"))
    localizer = GroundingDinoLocalizer(settings, client=client)
    assert localizer.warmup() == {"ready": True}
    assert configurations == [localizer.config]
    assert localizer.config.precision == "float32"


def test_repeated_warmup_preserves_cached_model(prepared, adapter_calls):
    client, _image, config = prepared
    process = WorkerProcess()
    connect_process(client, process)
    assert not client.warmup(config)["metadata"]["model_cache_hit"]
    assert client.warmup(config)["metadata"]["model_cache_hit"]
    assert [event[0] for event in adapter_calls] == ["load"]
    client.stop_worker()


class SilentProcess(WorkerProcess):
    def flush(self):
        self.requests.append(json.loads(self.pending))
        self.pending = ""


def test_warmup_timeout_restarts_for_normal_detection(prepared, adapter_calls):
    client, image, config = prepared
    silent = SilentProcess()
    recovered = WorkerProcess()
    processes = iter([silent, recovered])

    def start():
        if client._worker is None:
            client._worker = next(processes)
        return client._worker

    client._start = start
    result = client.warmup(config)
    assert not result["ready"] and result["status"] == "timeout"
    assert silent.poll() == 0 and client._worker is None
    detected = client.detect(image, ["cat"], config)
    assert detected.status == "success"
    assert [event[0] for event in adapter_calls] == ["load", "detect"]
    assert adapter_calls[-1][-1] is True
    client.stop_worker()


def test_cancelled_warmup_releases_protocol_lock_for_normal_detection(prepared, adapter_calls):
    client, image, config = prepared
    silent = SilentProcess()
    started = threading.Event()
    results = []

    def start_silent():
        client._worker = silent
        started.set()
        return silent

    client._start = start_silent
    thread = threading.Thread(target=lambda: results.append(client.warmup(config)))
    thread.start()
    assert started.wait(timeout=1)
    client.stop_worker()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert not results[0]["ready"] and results[0]["status"] == "cancelled"
    recovered = WorkerProcess()
    connect_process(client, recovered)
    assert client.detect(image, ["cat"], config).status == "success"
    client.stop_worker()
