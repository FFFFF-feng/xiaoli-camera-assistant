"""Exercise the product's backend routing with offline, known pixel masks."""
from dataclasses import replace

import cv2
import numpy as np
import pytest
from test_pixel_contours import building, inspection, metadata

from camera_assistant.config import PROJECT_ROOT, Settings
from camera_assistant.services import pixel_contours as tracing
from camera_assistant.services.segmentation import SegmentationResult


def settings(**overrides):
    return Settings(demo_mode=True, api_key="", base_url="https://example.invalid/v1",
                    vision_model="", text_model="", timeout_seconds=10, max_image_mb=15,
                    knowledge_dir=PROJECT_ROOT / "knowledge", **overrides)


def test_default_segmentation_is_optional_and_environment_is_explicit(monkeypatch):
    for key in ("CAMERA_AI_SEGMENTATION_BACKEND", "CAMERA_AI_SEGMENTATION_WEIGHTS_PATH"):
        monkeypatch.delenv(key, raising=False)
    assert settings().segmentation_backend == "grabcut"
    options = Settings.segmentation_options({"CAMERA_AI_SEGMENTATION_BACKEND": "mobile_sam",
        "CAMERA_AI_SEGMENTATION_TIMEOUT_SECONDS": "30", "CAMERA_AI_SEGMENTATION_FALLBACK": "false"})
    configured = settings(**options)
    assert configured.segmentation_backend == "mobile_sam"
    assert configured.segmentation_timeout_seconds == 30
    assert configured.segmentation_fallback is False
    with pytest.raises(ValueError):
        replace(configured, segmentation_device="cuda:0")
    with pytest.raises(ValueError):
        replace(configured, segmentation_weights_sha256="untrusted")


class OfflineProvider:
    def __init__(self, *, failed=None, disconnected=False):
        self.failed = failed
        self.disconnected = disconnected
        self.settings = settings(segmentation_backend="mobile_sam")
        self.calls = []
        self.actual = []
        self.evidence = []
        self.weight = "a" * 64

    def identity(self):
        return {"backend": "mobile_sam", "weights_sha256": self.weight,
                "fallback": self.settings.segmentation_fallback}

    def record_actual(self, backend, **kwargs):
        self.actual.append((backend, kwargs))

    def export_evidence(self, *args, **kwargs):
        self.evidence.append((args, kwargs))

    def segment_many(self, rgb, objects):
        self.calls.append((rgb.shape, [obj.object_id for obj in objects]))
        # A stepped roof and three windows, derived from this exact RGB image.
        mask = np.any(rgb < 200, axis=2)
        if self.disconnected:
            mask[:] = False
            mask[40:200, 60:130] = True
            mask[50:200, 170:240] = True
        return {obj.object_id: SegmentationResult(obj.object_id,
            "failed" if self.failed else "success", self.failed or "mask_extracted",
            None if self.failed else mask.copy(), "mobile_sam", "offline-test", self.weight,
            "cpu", {"encode": .01}, 1, "offline-known-mask") for obj in objects}


@pytest.fixture
def provider(monkeypatch):
    tracing._CACHE.clear()
    value = OfflineProvider()
    monkeypatch.setattr(tracing, "get_provider", lambda: value)
    yield value
    tracing._CACHE.clear()


def test_explicit_model_routes_one_batch_and_reuses_actual_masks(provider, monkeypatch):
    data = metadata()
    data["objects"].append({**data["objects"][0], "object_id": "object2", "role": "prop"})
    monkeypatch.setattr(cv2, "grabCut", lambda *_: pytest.fail("successful model must supply foreground"))
    result = tracing.trace_observed_scene(data, inspection(building()))
    assert provider.calls == [((240, 300, 3), ["object1", "object2"])]
    assert all(row.actual_backend == "mobile_sam" for row in result.processing)
    assert result.objects[0].holes  # actual window gaps; never universally filled
    assert len(result.objects[0].outline) > 6
    assert provider.evidence and provider.actual


def test_failure_falls_back_explicitly_and_is_not_success_cached(provider):
    provider.failed = "weights_missing"
    first = tracing.trace_observed_scene(metadata(), inspection(building()))
    assert first.processing[0].requested_backend == "mobile_sam"
    assert first.processing[0].actual_backend == "grabcut"
    assert first.processing[0].fallback_code == "weights_missing"
    assert not len(tracing._CACHE)
    provider.failed = None
    second = tracing.trace_observed_scene(metadata(), inspection(building()))
    assert len(provider.calls) == 2
    assert second.processing[0].actual_backend == "mobile_sam"


def test_cache_binds_actual_weight_identity(provider):
    request = inspection(building())
    tracing.trace_observed_scene(metadata(), request)
    cached = tracing.trace_observed_scene(metadata(), request)
    assert len(provider.calls) == 1
    assert cached.processing[0].cache_hit is True
    provider.weight = "b" * 64
    tracing.trace_observed_scene(metadata(), request)
    assert len(provider.calls) == 2


def test_significant_disconnected_mask_is_reported_not_silently_truncated(provider):
    provider.disconnected = True
    result = tracing.trace_observed_scene(metadata(), inspection(building()))
    assert result.processing[0].actual_backend == "grabcut"
    assert result.processing[0].fallback_code == "mask_multiple_components"
    assert not len(tracing._CACHE)


def test_disabled_fallback_fails_with_fixed_code_and_exports_failure(provider):
    provider.settings = replace(provider.settings, segmentation_fallback=False)
    provider.failed = "backend_unavailable"
    with pytest.raises(tracing.ContourFailure) as error:
        tracing.trace_observed_scene(metadata(), inspection(building()))
    assert error.value.code == "backend_unavailable"
    assert provider.evidence[-1][1]["failed_code"] == "backend_unavailable"
    assert not len(tracing._CACHE)


def test_continuous_scene_keeps_structure_without_model_batch(provider, monkeypatch):
    from camera_assistant.services import scene_structure

    data = metadata()
    data["scene_mode"] = "continuous"
    obj = tracing.observed_metadata(data).objects[0]
    monkeypatch.setattr(scene_structure, "trace_structure", lambda *_: obj)
    result = tracing.trace_observed_scene(data, inspection(building()))
    assert not provider.calls
    assert result.processing[0].actual_backend == "scene_structure"
    assert provider.actual == []  # Open edge tracing is not model inference proof.


def test_significant_thin_hole_cannot_be_filled_during_simplification():
    rgb = np.zeros((1280, 1280, 3), dtype=np.uint8)
    rgb[100:1180, 100:1180] = 100
    mask = np.zeros(rgb.shape[:2], dtype=np.bool_)
    mask[100:1180, 100:1180] = True
    mask[150:1130, 640] = False
    data = metadata()
    data["objects"][0]["bbox"] = [100/1280, 100/1280, 1180/1280, 1180/1280]
    obj = tracing.observed_metadata(data).objects[0]
    with pytest.raises(tracing.ContourFailure) as error:
        tracing._trace_single(rgb, obj, foreground_mask=mask)
    assert error.value.code == "mask_hole_invalid"


def test_non_main_context_fallback_has_correct_final_provenance(provider, monkeypatch):
    provider.failed = "weights_missing"
    data = metadata()
    data["objects"].append({**data["objects"][0], "object_id": "object2", "role": "prop"})
    original = tracing._trace

    def trace(rgb, obj):
        if obj.object_id == "object2":
            raise tracing.ContourFailure("region_uninformative", "test-only", object_id=obj.object_id)
        return original(rgb, obj)

    monkeypatch.setattr(tracing, "_trace", trace)
    monkeypatch.setattr(tracing, "trace_context", lambda rgb, obj, **_: obj.model_copy(update={
        "representation": "context_lines", "outline": [], "details": [[[0, 0], [1, 1]]]}))
    result = tracing.trace_observed_scene(data, inspection(building()))
    row = next(item for item in result.processing if item.object_id == "object2")
    assert row.actual_backend == "scene_context"
    assert row.fallback_code == "region_uninformative"
    assert row.code == "context_fallback"


def test_opt_in_grabcut_evidence_captures_the_actual_foreground(provider):
    provider.identity = lambda: {"backend": "grabcut", "fallback": True}
    provider.evidence_enabled = True
    result = tracing.trace_observed_scene(metadata(), inspection(building()))
    args, _ = provider.evidence[-1]
    masks = args[1]
    assert masks["object1"].dtype == np.bool_
    assert masks["object1"].shape == (240, 300)
    assert masks["object1"][80, 80] and not masks["object1"][10, 10]
    assert result.processing[0].mask_backend == "grabcut"
    assert tracing._CAPTURE_MASKS.get() is None


def test_observation_entry_uses_explicit_settings_and_publishes_local_provenance(monkeypatch):
    from camera_assistant.services import observed_composition, segmentation_provider
    from camera_assistant.services.composition_trace import observe_diagnostics

    segmentation_provider.close_providers()
    tracing._CACHE.clear()
    monkeypatch.setattr(observed_composition, "request_json", lambda *_: metadata())
    configured = settings(segmentation_backend="mobile_sam")  # missing weights; no Torch needed
    diagnostics = []
    try:
        with observe_diagnostics(diagnostics.append):
            result = observed_composition.observe_objects(configured, inspection(building()), {})
        row = result.processing[0]
        assert row.requested_backend == "mobile_sam" and row.actual_backend == "grabcut"
        assert row.fallback_code == "weights_missing"
        published = [event.segmentation for event in diagnostics if event.segmentation]
        assert published == [row]
        health = segmentation_provider.get_provider(configured).diagnostics()
        assert health["configured_backend"] == "mobile_sam"
        assert health["last_actual_backend"] == "grabcut" and health["inference_proven"]
        assert health["last_weights_sha256"] is None
    finally:
        segmentation_provider.close_providers()
        tracing._CACHE.clear()
