"""Product ownership of the optional local segmentation runtime and evidence."""
import hashlib
import importlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image


def api():
    return importlib.import_module("camera_assistant.services.segmentation_provider")


def settings(**changes):
    values = {"segmentation_backend": "grabcut", "segmentation_weights_path": None,
              "segmentation_weights_sha256": "", "segmentation_device": "cpu",
              "segmentation_fallback": True, "segmentation_timeout_seconds": 10.0,
              "segmentation_evidence": False}
    return SimpleNamespace(**{**values, **changes})


def obj(identifier="object1"):
    return SimpleNamespace(object_id=identifier, bbox=(.1, .1, .9, .9),
                           outline=[[0, 0], [1, 0], [1, 1], [0, 1]],
                           contours=[], holes=[], details=[], source_details=None,
                           representation="silhouette", label="PRIVATE REMOTE TEXT")


@pytest.fixture(autouse=True)
def release_provider():
    yield
    if "camera_assistant.services.segmentation_provider" in sys.modules:
        api().close_providers()


def test_default_is_lazy_grabcut_and_context_is_copied_to_parallel_thread(monkeypatch):
    module = api()
    monkeypatch.setitem(sys.modules, "torch", None)
    provider = module.get_provider()
    assert provider.identity()["backend"] == "grabcut"
    assert provider.diagnostics()["inference_proven"] is False
    provider.record_actual("grabcut")
    assert provider.diagnostics()["last_actual_backend"] == "grabcut"
    assert provider.diagnostics()["inference_proven"] is True
    with module.use_segmentation(settings(segmentation_backend="mobile_sam")):
        current = module.get_provider()
        assert current.identity()["backend"] == "mobile_sam"
        context = copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(context.run, module.get_provider).result() is current
    assert module.get_provider().identity()["backend"] == "grabcut"


def test_missing_weight_and_bad_hash_have_frozen_failures_without_fallback(tmp_path):
    module = api()
    rgb = np.zeros((16, 16, 3), np.uint8)
    provider = module.get_provider(settings(segmentation_backend="mobile_sam"))
    assert provider.segment_many(rgb, [obj()])["object1"].code == "weights_missing"
    assert provider.diagnostics()["last_actual_backend"] is None
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"not a checkpoint")
    provider = module.get_provider(settings(segmentation_backend="mobile_sam",
        segmentation_weights_path=weights, segmentation_weights_sha256="0" * 64))
    result = provider.segment_many(rgb, [obj()])["object1"]
    assert result.code == "weights_invalid" and result.mask is None
    assert not provider.diagnostics()["inference_proven"]
    assert str(weights) not in json.dumps(provider.identity())


class Backend:
    backend = "mobile_sam"
    model_version = "MobileSAM-vit_t"
    device = "cpu"
    preprocessing_version = "sam-ResizeLongestSide1024-RGB-normalize-pad-native-logits-v1"

    def __init__(self, digest):
        self.weights_sha256 = digest
        self.encodes = self.decodes = self.closes = 0
        self.started = Event()
        self.release = None

    def load(self):
        pass

    def encode(self, rgb):
        self.shape = rgb.shape[:2]
        self.encodes += 1
        self.started.set()
        if self.release is not None:
            assert self.release.wait(3)

    def predict(self, box):
        from camera_assistant.services.segmentation import MaskCandidates
        self.decodes += 1
        masks = np.zeros((1, *self.shape), dtype=bool)
        masks[:, 2:-2, 2:-2] = True
        return MaskCandidates(masks, np.array([.8]))

    def reset_image(self):
        pass

    def close(self):
        self.closes += 1


def synthetic_runtime(monkeypatch, module):
    from camera_assistant.services.segmentation import SegmentationRuntime
    backends = []

    def factory(path, *, device, expected_sha256):
        backend = Backend(expected_sha256)
        backends.append(backend)
        return SegmentationRuntime(backend_factory=lambda: backend)

    monkeypatch.setattr(module, "SegmentationRuntime", factory)
    return backends


def test_one_runtime_multi_region_actual_identity_and_content_change_close(tmp_path, monkeypatch):
    module = api()
    backends = synthetic_runtime(monkeypatch, module)
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"first weights")
    config = settings(segmentation_backend="mobile_sam", segmentation_weights_path=weights)
    provider = module.get_provider(config)
    first_key = provider.identity()
    assert first_key["weights_sha256"] == hashlib.sha256(weights.read_bytes()).hexdigest()
    rgb = np.zeros((16, 16, 3), np.uint8)
    result = provider.segment_many(rgb, [obj(), obj("object2")])
    assert list(result) == ["object1", "object2"]
    assert all(item.mask.dtype == bool and item.mask.shape == (16, 16)
               for item in result.values())
    assert (len(backends), backends[0].encodes, backends[0].decodes) == (1, 1, 2)
    assert module.get_provider(config) is provider
    provider.segment_many(rgb, [obj(), obj("object2")])
    assert backends[0].encodes == 1
    assert provider.diagnostics()["inference_proven"]
    assert provider.diagnostics()["last_weights_sha256"] == first_key["weights_sha256"]
    weights.write_bytes(b"replacement weights")
    assert provider.identity()["weights_sha256"] != first_key["weights_sha256"]
    assert backends[0].closes == 1
    assert not provider.diagnostics()["inference_proven"]
    provider.segment_many(rgb, [obj()])
    assert len(backends) == 2
    module.get_provider(settings())
    assert backends[1].closes == 1


def test_close_waits_for_native_work_and_is_idempotent(tmp_path, monkeypatch):
    module = api()
    backends = synthetic_runtime(monkeypatch, module)
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"weights")
    provider = module.get_provider(settings(segmentation_backend="mobile_sam",
                                           segmentation_weights_path=weights))
    # First call constructs the persistent runtime; changing image forces another encode.
    rgb = np.zeros((16, 16, 3), np.uint8)
    provider.segment_many(rgb, [obj()])
    backend = backends[0]
    backend.started.clear()
    backend.release = Event()
    rgb[0, 0] = 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        inference = pool.submit(provider.segment_many, rgb, [obj()])
        assert backend.started.wait(1)
        closing = pool.submit(module.close_providers)
        assert not closing.done()
        backend.release.set()
        assert inference.result()["object1"].status == "success"
        closing.result()
    module.close_providers()
    assert backend.closes == 1


def test_evidence_disabled_performs_no_io_and_enabled_exports_safe_correspondence(tmp_path, monkeypatch):
    module = api()
    evidence_root = tmp_path / "evidence"
    monkeypatch.setattr(module, "_EVIDENCE_ROOT", evidence_root)
    mask = np.zeros((16, 16), bool)
    mask[2:14, 2:14] = True
    provider = module.get_provider()
    assert provider.export_evidence("1" * 64, {"object1": mask}, [obj()], []) is None
    assert not evidence_root.exists()
    provider = module.get_provider(settings(segmentation_evidence=True))
    provider.record_actual("grabcut")
    manifest = provider.export_evidence("1" * 64,
        {"object1": mask, "../../escape": mask}, [obj()],
        [{"object_id": "object1", "backend": "grabcut", "component_count": 1,
          "raw_response": "PRIVATE REMOTE TEXT", "message": "PRIVATE REMOTE TEXT"}])
    assert manifest is not None and Path(manifest).is_file()
    data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    assert data["input_sha256"] == "1" * 64
    assert data["actual_backend"] == "grabcut"
    assert data["source_ids"] == ["object1"]
    assert data["masks"]["object1"]["sha256"] == hashlib.sha256(mask.tobytes()).hexdigest()
    assert "PRIVATE" not in json.dumps(data)
    assert "../../escape" not in json.dumps(data)
    for path in evidence_root.iterdir():
        assert path.parent == evidence_root and not path.is_symlink()
    assert len(list(evidence_root.glob("*.svg"))) == 1
    assert "<polygon" in next(evidence_root.glob("*.svg")).read_text(encoding="utf-8")
    saved = next(evidence_root.glob("*.png"))
    assert np.array_equal(np.asarray(Image.open(saved)) > 0, mask)


def test_evidence_retention_only_removes_owned_flat_records(tmp_path, monkeypatch):
    module = api()
    root = tmp_path / "evidence"
    monkeypatch.setattr(module, "_EVIDENCE_ROOT", root)
    monkeypatch.setattr(module, "_MAX_EVIDENCE_RECORDS", 2)
    provider = module.get_provider(settings(segmentation_evidence=True))
    root.mkdir()
    untouched = root / "user-note.txt"
    untouched.write_text("keep", encoding="utf-8")
    directory = root / ("f" * 32 + "-unrelated")
    directory.mkdir()
    for _ in range(3):
        assert provider.export_evidence("2" * 64, {}, [], [],
                                        failed_code="foreground_empty") is not None
    assert len(list(root.glob("*-manifest.json"))) == 2
    assert untouched.read_text(encoding="utf-8") == "keep" and directory.is_dir()


def test_actual_failed_load_does_not_become_model_success(tmp_path, monkeypatch):
    module = api()
    monkeypatch.setitem(sys.modules, "mobile_sam", None)
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"fake locally present weights")
    provider = module.get_provider(settings(segmentation_backend="mobile_sam",
                                           segmentation_weights_path=weights))
    result = provider.segment_many(np.zeros((16, 16, 3), np.uint8), [obj()])["object1"]
    assert result.code == "backend_unavailable"
    assert not provider.diagnostics()["inference_proven"]
    provider.record_actual("grabcut", code="fallback_mask_extracted")
    assert provider.diagnostics()["configured_backend"] == "mobile_sam"
    assert provider.diagnostics()["last_actual_backend"] == "grabcut"


def test_oversize_weight_fails_before_runtime_can_read_or_load_it(tmp_path, monkeypatch):
    module = api()
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"too large for bounded reader")
    monkeypatch.setattr(module, "_MAX_WEIGHT_BYTES", 4)
    provider = module.get_provider(settings(segmentation_backend="mobile_sam",
                                           segmentation_weights_path=weights))
    result = provider.segment_many(np.zeros((16, 16, 3), np.uint8), [obj()])["object1"]
    assert result.code == "weights_invalid"
    assert not provider.diagnostics()["inference_proven"]


def test_evidence_capacity_is_byte_bounded_and_refuses_invalid_inputs(tmp_path, monkeypatch):
    module = api()
    root = tmp_path / "evidence"
    monkeypatch.setattr(module, "_EVIDENCE_ROOT", root)
    provider = module.get_provider(settings(segmentation_evidence=True))
    first = provider.export_evidence("3" * 64, {}, [], [])
    assert first is not None
    size = sum(path.stat().st_size for path in root.iterdir())
    monkeypatch.setattr(module, "_MAX_EVIDENCE_BYTES", size + 10)
    second = provider.export_evidence("4" * 64, {}, [], [])
    assert second is not None and not Path(first).exists()
    assert sum(path.stat().st_size for path in root.iterdir()) <= size + 10
    assert provider.export_evidence("bad digest", {}, [], []) is None
    monkeypatch.setattr(module, "_MAX_EVIDENCE_BYTES", 1)
    assert provider.export_evidence("5" * 64, {}, [], []) is None
    assert Path(second).exists()


def test_evidence_uses_this_batch_backend_instead_of_global_last_call(tmp_path, monkeypatch):
    module = api()
    monkeypatch.setattr(module, "_EVIDENCE_ROOT", tmp_path / "evidence")
    provider = module.get_provider(settings(segmentation_evidence=True))
    provider.record_actual("mobile_sam", weights_sha256="f" * 64)
    mask = np.zeros((16, 16), bool)
    mask[2:14, 2:14] = True
    manifest = provider.export_evidence("6" * 64, {"object1": mask}, [obj()], [{
        "object_id": "object1", "actual_backend": "grabcut", "status": "success",
        "mask_backend": "mobile_sam", "fallback_code": "outline_self_intersection",
        "weights_sha256": "f" * 64,
        "timings": {"total": .25, "encode": .1, "raw": "private"},
    }])
    data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    assert data["actual_backend"] == "grabcut"
    assert data["weights_sha256"] is None
    assert data["actual_backends"] == {"object1": "grabcut"}
    assert data["masks"]["object1"]["source_backend"] == "mobile_sam"
    assert data["masks"]["object1"]["weights_sha256"] == "f" * 64
    assert data["processing"][0]["fallback_code"] == "outline_self_intersection"
    assert data["processing"][0]["timings"] == {"total": .25, "encode": .1}
