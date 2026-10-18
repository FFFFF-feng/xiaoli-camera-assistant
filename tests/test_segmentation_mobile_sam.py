"""Local optional dependency/weight failure semantics, no network or downloads."""
import hashlib
import importlib.util

import numpy as np
import pytest

from camera_assistant.services.segmentation import SegmentationRegion, SegmentationRuntime


def call(path, **kwargs):
    with SegmentationRuntime(path, **kwargs) as runtime:
        return runtime.segment_many(np.zeros((16, 16, 3), np.uint8),
                                    [SegmentationRegion("object1", (0, 0, 1, 1))])[0]


def test_empty_and_hash_mismatched_weights_are_rejected_before_import(tmp_path):
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"")
    assert call(weights).code == "weights_invalid"
    weights.write_bytes(b"not a state dictionary")
    result = call(weights, expected_sha256="0"*64)
    assert result.code == "weights_invalid" and result.weights_sha256 is None


def test_uninstalled_backend_returns_unavailable_without_import_side_effects(tmp_path, monkeypatch):
    import sys
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"not loaded")
    monkeypatch.setitem(sys.modules, "mobile_sam", None)
    result = call(weights)
    assert result.code == "backend_unavailable" and result.weights_sha256 is None


@pytest.mark.skipif(importlib.util.find_spec("mobile_sam") is None,
                    reason="optional MobileSAM installation is deliberately absent")
def test_corrupt_state_dictionary_and_invalid_device(tmp_path):
    weights = tmp_path / "corrupt.pt"
    weights.write_bytes(b"not a state dictionary")
    result = call(weights)
    assert result.code == "weights_invalid" and result.weights_sha256 is None
    result = call(weights, device="mps")
    assert result.code == "device_unavailable"
    assert result.weights_sha256 is None


def test_content_hash_matches_real_file_when_expected_hash_is_wrong(tmp_path):
    weights = tmp_path / "fake.pt"
    weights.write_bytes(b"diagnostic data")
    assert hashlib.sha256(weights.read_bytes()).hexdigest() != "1" * 64
    assert call(weights, expected_sha256="1"*64).code == "weights_invalid"
