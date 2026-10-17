"""Synthetic backend tests; these never claim pretrained-model quality."""
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Event

import numpy as np
import pytest


def api():
    from camera_assistant.services import segmentation
    return segmentation


class SyntheticBackend:
    backend = "synthetic-test"
    model_version = "test-v1"
    weights_sha256 = None
    device = "cpu"
    preprocessing_version = "test-nearest-v1"

    def __init__(self, masks=None, scores=None, *, delay=0):
        self.masks = masks
        self.scores = scores
        self.delay = delay
        self.loads = self.encodes = self.decodes = self.resets = self.closes = 0
        self.entered = Event()
        self.release = None
        self.last_rgb = None

    def load(self):
        self.loads += 1

    def encode(self, rgb):
        self.encodes += 1
        self.last_rgb = rgb
        self.entered.set()
        if self.release:
            assert self.release.wait(3)
        time.sleep(self.delay)

    def predict(self, box):
        self.decodes += 1
        masks = self.masks
        if masks is None:
            masks = np.zeros((1, *self.last_rgb.shape[:2]), dtype=bool)
            masks[:, 2:-2, 2:-2] = True
        return api().MaskCandidates(masks, np.array([.7]) if self.scores is None else self.scores)

    def reset_image(self):
        self.resets += 1
        self.last_rgb = None

    def close(self):
        self.closes += 1
        self.reset_image()


def setup(backend=None):
    backend = backend or SyntheticBackend()
    runtime = api().SegmentationRuntime(backend_factory=lambda: backend)
    rgb = np.zeros((32, 40, 3), np.uint8)
    regions = [api().SegmentationRegion("object1", (0, 0, 1, 1))]
    return runtime, backend, rgb, regions


def test_records_order_one_load_encode_multi_object_and_six_real_timing_keys():
    runtime, backend, rgb, regions = setup()
    regions += [api().SegmentationRegion("object6", (.1, .1, .9, .9))]
    results = runtime.segment_many(rgb, regions)
    assert [r.object_id for r in results] == ["object1", "object6"]
    assert all(r.status == "success" and r.code == "mask_extracted" for r in results)
    assert all(r.mask.shape == rgb.shape[:2] and r.mask.dtype == np.bool_ for r in results)
    assert (backend.loads, backend.encodes, backend.decodes) == (1, 1, 2)
    assert all(set(r.timings) == {"queue", "load", "encode", "decode", "postprocess", "total"}
               and all(np.isfinite(v) and v >= 0 for v in r.timings.values()) for r in results)
    with pytest.raises(FrozenInstanceError):
        regions[0].object_id = "object2"
    runtime.close()


@pytest.mark.parametrize("rgb", [None, np.zeros((7, 20, 3), np.uint8),
    np.zeros((32, 40), np.uint8), np.zeros((32, 40, 3), float),
    np.zeros((2001, 2000, 3), np.uint8)])
def test_invalid_image_does_not_load_model(rgb):
    runtime, backend, _, regions = setup()
    result, = runtime.segment_many(rgb, regions)
    assert result.code == "invalid_image" and result.mask is None
    assert backend.loads == 0


@pytest.mark.parametrize("bbox,code", [
    ((0, 0, 0, 1), "invalid_bbox"), ((-.1, 0, 1, 1), "invalid_bbox"),
    ((0, 0, 1.1, 1), "invalid_bbox"), ((0, float("nan"), 1, 1), "invalid_bbox"),
    ((0, 0, 1), "invalid_bbox"), ((0, 0, .05, .5), "region_too_small"),
])
def test_invalid_boxes_are_not_clamped(bbox, code):
    runtime, backend, rgb, _ = setup()
    result, = runtime.segment_many(rgb, [api().SegmentationRegion("object1", bbox)])
    assert result.code == code and result.mask is None and backend.loads == 0


def test_duplicate_limit_empty_and_partial_invalid_batches():
    runtime, backend, rgb, regions = setup()
    assert runtime.segment_many(rgb, []) == []
    duplicate = runtime.segment_many(rgb, regions * 2)
    assert [r.code for r in duplicate] == ["duplicate_object_id"] * 2
    too_many = [api().SegmentationRegion(f"object{i}", (0, 0, 1, 1)) for i in range(1, 6)]
    assert all(r.code == "object_limit_exceeded" for r in runtime.segment_many(rgb, too_many))
    mixed = regions + [api().SegmentationRegion("object2", (1, 0, 0, 1))]
    result = runtime.segment_many(rgb, mixed)
    assert [r.code for r in result] == ["mask_extracted", "invalid_bbox"]
    assert backend.decodes == 1


def test_hole_and_disconnected_components_are_preserved_and_caller_masks_isolated():
    mask = np.zeros((1, 32, 40), bool)
    mask[0, 3:22, 3:22] = True
    mask[0, 8:12, 8:12] = False
    mask[0, 25:29, 30:35] = True
    runtime, backend, rgb, regions = setup(SyntheticBackend(mask))
    result, = runtime.segment_many(rgb, regions)
    assert np.array_equal(result.mask, mask[0])
    result.mask[:] = False
    again, = runtime.segment_many(rgb, regions)
    assert np.array_equal(again.mask, mask[0])
    assert backend.encodes == 1


@pytest.mark.parametrize("mask,code", [
    (np.zeros((1, 32, 40), bool), "mask_empty"),
    (np.ones((1, 32, 40), bool), "mask_full_frame"),
    (np.ones((1, 32, 40), np.uint8), "mask_invalid"),
    (np.zeros((0, 32, 40), bool), "mask_invalid"),
])
def test_degenerate_masks_fail_and_invalidate_embedding(mask, code):
    runtime, backend, rgb, regions = setup(SyntheticBackend(mask))
    for _ in range(2):
        result, = runtime.segment_many(rgb, regions)
        assert result.code == code and result.mask is None
    assert backend.encodes == 2


def test_candidate_selection_is_valid_finite_deterministic_not_accuracy():
    masks = np.zeros((3, 32, 40), bool)
    masks[0] = True
    masks[1, 2:10, 3:12] = True
    masks[2, 4:12, 6:14] = True
    runtime, _, rgb, regions = setup(SyntheticBackend(masks, np.array([1., .8, .8])))
    result, = runtime.segment_many(rgb, regions)
    assert result.candidate_count == 3
    assert np.array_equal(result.mask, masks[1])
    assert "index=1" in result.selection_basis and "not_accuracy" in result.selection_basis
    runtime.close()
    runtime, _, rgb, regions = setup(SyntheticBackend(masks[1:2], np.array([np.nan])))
    assert runtime.segment_many(rgb, regions)[0].code == "mask_invalid"


def test_nearest_restore_preserves_binary_topology_without_smoothing():
    mask = np.zeros((1, 8, 10), bool)
    mask[:, 1:7, 1:9] = True
    mask[:, 3:5, 4:6] = False
    runtime, _, rgb, regions = setup(SyntheticBackend(mask))
    result, = runtime.segment_many(rgb, regions)
    assert np.array_equal(result.mask, mask[0].repeat(4, 0).repeat(4, 1))


def test_rgb_content_and_complete_prompts_invalidate_only_embedding_cache():
    runtime, backend, rgb, regions = setup()
    runtime.segment_many(rgb, regions)
    hit = runtime.segment_many(rgb.copy(), regions)[0]
    assert hit.timings["load"] == hit.timings["encode"] == 0
    assert backend.last_rgb is not rgb
    rgb[0, 0] = 99
    runtime.segment_many(rgb, regions)
    runtime.segment_many(rgb, [api().SegmentationRegion("object1", (.1, 0, 1, 1))])
    assert (backend.loads, backend.encodes) == (1, 3)
    runtime.close()
    runtime.close()
    assert backend.closes == 1 and backend.last_rgb is None
    assert runtime.segment_many(rgb, regions)[0].code == "backend_unavailable"


def test_queue_has_bounded_wait_and_predictor_never_runs_concurrently():
    backend = SyntheticBackend()
    backend.release = Event()
    runtime, _, rgb, regions = setup(backend)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(runtime.segment_many, rgb, regions)
        assert backend.entered.wait(1)
        start = time.perf_counter()
        second = runtime.segment_many(rgb, regions)
        assert second[0].code == "compute_slot_busy"
        assert .45 <= time.perf_counter() - start < 1
        backend.release.set()
        assert first.result()[0].code == "mask_extracted"


def test_timeout_is_honest_cooperative_boundary_and_does_not_cache_failure():
    runtime, backend, rgb, regions = setup(SyntheticBackend(delay=.03))
    result, = runtime.segment_many(rgb, regions, timeout_seconds=.005)
    assert result.code == "inference_timeout" and result.mask is None
    assert result.timings["total"] >= .03
    assert backend.decodes == 0
    runtime.segment_many(rgb, regions)
    assert backend.encodes == 2


def test_unknown_backend_exception_never_leaks_text():
    class Broken(SyntheticBackend):
        def encode(self, rgb):
            raise RuntimeError("private photo path and secret")
    runtime, _, rgb, regions = setup(Broken())
    result, = runtime.segment_many(rgb, regions)
    assert result.code == "inference_failed" and "private" not in str(result)


def test_missing_weights_lazy_import_and_optional_backend():
    runtime = api().SegmentationRuntime(weights_path="definitely-not-a-weight.pt")
    rgb = np.zeros((32, 40, 3), np.uint8)
    result, = runtime.segment_many(rgb, [api().SegmentationRegion("object1", (0, 0, 1, 1))])
    assert result.code == "weights_missing" and result.weights_sha256 is None
    runtime.close()


def test_backend_cleanup_exception_is_sanitized_and_never_reuses_embedding():
    class BrokenCleanup(SyntheticBackend):
        def reset_image(self):
            raise RuntimeError("private cleanup text")
    runtime, _, rgb, regions = setup(BrokenCleanup())
    result, = runtime.segment_many(rgb, regions)
    assert result.code == "inference_failed" and result.mask is None
    assert "private" not in str(result)
    runtime.close()


def test_invalid_mask_records_actual_candidate_denominator():
    runtime, _, rgb, regions = setup(SyntheticBackend(np.zeros((3, 32, 40), bool),
                                                      np.array([.5, .6, .7])))
    result, = runtime.segment_many(rgb, regions)
    assert result.code == "mask_empty" and result.candidate_count == 3


def test_close_waits_for_active_call_and_releases_predictor_exactly_once():
    backend = SyntheticBackend()
    backend.release = Event()
    runtime, _, rgb, regions = setup(backend)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(runtime.segment_many, rgb, regions)
        assert backend.entered.wait(1)
        closing = pool.submit(runtime.close)
        assert not closing.done()
        backend.release.set()
        assert first.result()[0].status == "success"
        closing.result()
    assert backend.closes == 1 and backend.last_rgb is None


def test_caller_shape_and_mutable_box_cannot_change_owned_request_snapshot():
    runtime, backend, rgb, _ = setup()
    box = [0., 0., 1., 1.]
    regions = [api().SegmentationRegion("object1", box)]
    original_encode = backend.encode

    def mutate_caller_after_encoding(snapshot):
        original_encode(snapshot)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            rgb.shape = (40, 32, 3)  # exercise legacy caller mutation intentionally
        box[:] = [2., 2., 3., 3.]

    backend.encode = mutate_caller_after_encoding
    original_predict = backend.predict
    seen = []

    def capture_box(prompt):
        seen.append(prompt.copy())
        return original_predict(prompt)

    backend.predict = capture_box
    result, = runtime.segment_many(rgb, regions)
    assert result.code == "mask_extracted" and result.mask.shape == (32, 40)
    assert np.array_equal(seen[0], [0, 0, 40, 32])


@pytest.mark.parametrize("identifier", [[], {}, None, 4])
def test_nonstring_object_id_returns_fixed_failure_without_counter_exception(identifier):
    runtime, backend, rgb, _ = setup()
    result, = runtime.segment_many(rgb, [api().SegmentationRegion(identifier, (0, 0, 1, 1))])
    assert result.code == "invalid_bbox" and result.mask is None and backend.loads == 0


@pytest.mark.parametrize("state", ["load_failure", "closed", "timeout"])
def test_batch_failure_preserves_prevalidated_region_error(state):
    class Missing(SyntheticBackend):
        def load(self):
            raise api().BackendError("weights_missing")
    runtime, _, rgb, regions = setup(Missing())
    regions += [api().SegmentationRegion("object2", (1, 0, 0, 1))]
    options = {}
    if state == "closed":
        runtime.close()
    elif state == "timeout":
        options["timeout_seconds"] = 0
    results = runtime.segment_many(rgb, regions, **options)
    assert results[1].code == "invalid_bbox"
    assert results[0].code == {"load_failure": "weights_missing", "closed": "backend_unavailable",
                               "timeout": "inference_timeout"}[state]
