from __future__ import annotations

import io
import json
import os
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from vision_lab_tool.detector_models import DetectorConfig
from vision_lab_tool.detectors.base import file_provenance, finish_result, pixel_xyxy
from vision_lab_tool.detectors.client import DetectorClient


def test_non_square_original_pixels_not_unletterboxed_again():
    assert pixel_xyxy([20, 10, 180, 90], 200, 100) == [.1, .1, .9, .9]


@pytest.mark.parametrize("box", [[0, 0, 201, 90], [20, 90, 180, 10],
                                 [0, 0, 0, 10], [float("nan"), 0, 10, 10]])
def test_invalid_coordinates_fail_without_clipping(box):
    with pytest.raises(ValueError):
        pixel_xyxy(box, 200, 100)


def test_raw_coordinate_failures_and_dedup_evidence_survive():
    config = DetectorConfig(detector="yolo26", dedup_iou=.5)
    raw = [{"raw_index": index, "label_original": "person", "score": .9 - index * .1,
            "score_kind": "test", "bbox_native": [20, 10, 180, 90],
            "bbox_postprocessed": [20, 10, 180, 90], "coordinate_basis": "sent pixels"}
           for index in range(3)]
    raw[2]["bbox_postprocessed"] = [-1, 10, 180, 90]
    result = finish_result(config, "test", raw, raw, (200, 100), {}, {})
    assert result.status == "partial_coordinates"
    assert len(result.raw_candidates) == 3
    assert len(result.candidates) == 2
    assert len(result.filtered_candidates) == 1
    assert result.metadata["dedup_removed"] == [{"object_id": "test_1", "kept_id": "test_0"}]
    assert "raw_index=2" in result.diagnostics[0]


def test_official_clipped_boxes_do_not_repair_raw_validity():
    item = {"raw_index": 0, "bbox_postprocessed": [0, 0, 20, 20],
            "raw_coordinates_valid": False}
    result = finish_result(DetectorConfig(detector="yolo26"), "test", [item], [item],
                           (200, 100), {}, {})
    assert result.status == "coordinate_error"
    assert result.raw_candidates == [item]
    assert result.candidates == []


def test_weights_hash_changes_invalidate_fingerprint(tmp_path):
    path = tmp_path / "yolo26n.pt"
    path.write_bytes(b"old")
    original = file_provenance(path)
    path.write_bytes(b"changed")
    assert file_provenance(path)["sha256"] != original["sha256"]


def test_missing_runtime_does_not_start_worker(tmp_path):
    client = DetectorClient(tmp_path)
    client._start = lambda: pytest.fail("missing environment must not spawn")
    result = client.detect(SimpleNamespace(), [], DetectorConfig(detector="yolo26"))
    assert result.status == "environment_missing"
    assert not client.readiness(result.config)["ready"]


def prepared_client(tmp_path):
    python = tmp_path / "python.exe"
    python.write_bytes(b"dummy")
    runtime = tmp_path / "data/vision_lab/model_cache/runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(json.dumps({"imports_ok": True, "cuda_available": False}))
    weights = tmp_path / "yolo26n.pt"
    weights.write_bytes(b"test")
    client = DetectorClient(tmp_path, python)
    buffer = io.BytesIO()
    Image.new("RGB", (80, 40)).save(buffer, "JPEG")
    image = SimpleNamespace(sent_bytes=buffer.getvalue(), metadata=lambda: {"sent_size": [80, 40]})
    return client, image, DetectorConfig(detector="yolo26", weights_path=str(weights),
                                         timeout_seconds=1)


class SilentProcess:
    def __init__(self):
        self.stdin = io.StringIO()
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout):
        return self.returncode


def test_timeout_kills_worker_and_does_not_retry(tmp_path):
    client, image, config = prepared_client(tmp_path)
    worker = SilentProcess()
    client._worker = worker
    starts = []
    client._start = lambda: starts.append(True) or worker
    result = client.detect(image, [], config)
    assert result.status == "timeout"
    assert starts == [True]
    assert worker.returncode == 0
    assert result.timings["wall_total"] >= 1


def test_cancel_is_distinct_from_worker_exit(tmp_path):
    client, image, config = prepared_client(tmp_path)
    worker = SilentProcess()
    client._worker = worker
    started = threading.Event()
    client._start = lambda: started.set() or worker
    results = []
    thread = threading.Thread(target=lambda: results.append(client.detect(image, [], config)))
    thread.start()
    assert started.wait(timeout=1)
    client.stop_worker()
    thread.join(timeout=2)
    assert results[0].status == "cancelled"


def test_readiness_cpu_half_and_gpu_are_explicit(tmp_path):
    client, _image, config = prepared_client(tmp_path)
    assert client.readiness(config)["ready"]
    assert client.readiness(config.model_copy(update={"precision": "float16"}))["status"] == "precision_unsupported"
    assert client.readiness(config.model_copy(update={"device": "cuda:0"}))["status"] == "device_unavailable"


def test_worker_spawn_disables_network_autoinstall_and_hides_window(tmp_path, monkeypatch):
    client, _image, _config = prepared_client(tmp_path)
    captured = {}

    def popen(command, **kwargs):
        captured.update(kwargs)
        return SilentProcess()

    monkeypatch.setattr("vision_lab_tool.detectors.client.subprocess.Popen", popen)
    client._start()
    assert captured["env"]["HF_HUB_OFFLINE"] == "1"
    assert captured["env"]["YOLO_AUTOINSTALL"] == "false"
    if os.name == "nt":
        assert captured["creationflags"] != 0
    client.stop_worker()
