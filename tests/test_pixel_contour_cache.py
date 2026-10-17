"""Reuse exact CPU work without changing geometry, validation or ownership."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest
from test_pixel_contours import building, inspection, metadata

from camera_assistant.services import pixel_contours as tracing


@pytest.fixture(autouse=True)
def empty_cache():
    cache = getattr(tracing, "_CACHE", None)
    if cache is not None:
        cache.clear()
    yield
    if cache is not None:
        cache.clear()


def count_segmentation(monkeypatch):
    calls = []
    original = tracing._trace

    def record(rgb, obj):
        calls.append(obj.object_id)
        return original(rgb, obj)

    monkeypatch.setattr(tracing, "_trace", record)
    return calls


def test_exact_repeat_avoids_real_segmentation_and_returns_independent_geometry(monkeypatch):
    calls = count_segmentation(monkeypatch)
    photo = inspection(building())
    first = tracing.trace_observed_scene(metadata(), photo)
    expected = first.model_dump()
    first.objects[0].outline[0][0] = .12345
    first.limitations.append("caller-private-note")
    second = tracing.trace_observed_scene(metadata(), photo)
    assert calls == ["object1"]
    assert second.model_dump() == expected
    second.objects[0].identity_features.append("another-caller-note")
    assert tracing.trace_observed_scene(metadata(), photo).model_dump() == expected
    assert calls == ["object1"]


def test_key_uses_image_bytes_and_normalized_metadata_not_discarded_model_paths(monkeypatch):
    calls = count_segmentation(monkeypatch)
    photo = inspection(building())
    first = tracing.trace_observed_scene(metadata(), photo)
    changed = deepcopy(metadata())
    changed["objects"][0].update(outline="broken-model-path", details="discarded",
                                 contours="discarded", source_details="discarded")
    photo = photo.model_copy(deep=True)
    photo.model_image_data_url = photo.model_image_data_url.replace("image/png", "image/unused")
    # These inspection fields are not read by the tracing algorithm.
    photo.metrics.width = 999
    photo.metrics.height = 999
    assert tracing.trace_observed_scene(changed, photo) == first
    assert calls == ["object1"]


@pytest.mark.parametrize("changed", ["pixels", "bbox", "features", "limitations", "version", "resolution"])
def test_algorithm_effective_inputs_invalidate_cache(monkeypatch, changed):
    calls = count_segmentation(monkeypatch)
    photo, source = inspection(building()), metadata()
    first = tracing.trace_observed_scene(source, photo)
    if changed == "pixels":
        photo = inspection(building(True))
    elif changed == "bbox":
        source["objects"][0]["bbox"] = [.14, .1, .86, .9]
    elif changed == "features":
        source["objects"][0]["identity_features"] = ["完整屋顶", "窗户"]
    elif changed == "limitations":
        source["limitations"] = ["different evidence note"]
    elif changed == "version":
        monkeypatch.setattr(tracing, "_ALGORITHM_VERSION", "test-algorithm-version")
    else:
        monkeypatch.setattr(tracing, "MAX_EDGE", tracing.MAX_EDGE - 1)
    second = tracing.trace_observed_scene(source, photo)
    assert calls == ["object1", "object1"]
    if changed == "pixels":
        assert second.objects[0].outline != first.objects[0].outline


def test_validation_and_failed_segmentation_are_not_hidden_or_cached(monkeypatch):
    photo, source = inspection(building()), metadata()
    original = tracing._trace
    calls = []

    def fail_once(rgb, obj):
        calls.append(obj.object_id)
        if len(calls) == 1:
            raise ValueError("temporary contour failure")
        return original(rgb, obj)

    monkeypatch.setattr(tracing, "_trace", fail_once)
    with pytest.raises(ValueError, match="主要物体轮廓提取失败"):
        tracing.trace_observed_scene(source, photo)
    good = tracing.trace_observed_scene(source, photo)
    assert good.objects[0].outline
    assert tracing.trace_observed_scene(source, photo) == good
    assert len(calls) == 2
    invalid = deepcopy(source)
    invalid["objects"][0]["bbox"] = [.8, .1, .2, .9]
    with pytest.raises(ValueError):
        tracing.trace_observed_scene(invalid, photo)
    too_many = deepcopy(source)
    too_many["objects"] = [{**source["objects"][0], "object_id": f"object{i}"} for i in range(1, 6)]
    with pytest.raises(ValueError, match="对象数量过多"):
        tracing.trace_observed_scene(too_many, photo)


def test_concurrent_same_key_rechecks_after_cpu_slot_without_duplicate_work(monkeypatch):
    photo, source = inspection(building()), metadata()
    original = tracing._trace
    entered, release, waiting = Event(), Event(), Event()
    calls = []
    original_get = tracing._CACHE.get

    def record_miss(key):
        value = original_get(key)
        if value is None and entered.is_set() and not release.is_set():
            waiting.set()
        return value

    def held(rgb, obj):
        calls.append(obj.object_id)
        entered.set()
        assert release.wait(timeout=2)
        return original(rgb, obj)

    monkeypatch.setattr(tracing, "_trace", held)
    monkeypatch.setattr(tracing._CACHE, "get", record_miss)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(tracing.trace_observed_scene, source, photo)
        assert entered.wait(timeout=2)
        second = executor.submit(tracing.trace_observed_scene, source, photo)
        assert waiting.wait(timeout=2)
        release.set()
        a, b = first.result(timeout=3), second.result(timeout=3)
    assert a == b and a is not b
    assert calls == ["object1"]


def test_cached_result_needs_no_cpu_slot_or_rng_mutation(monkeypatch):
    photo = inspection(building())
    first = tracing.trace_observed_scene(metadata(), photo)

    def no_random_work(*_):
        pytest.fail("a cache hit started segmentation")

    monkeypatch.setattr(tracing.cv2, "setRNGSeed", no_random_work)
    assert tracing._SLOT.acquire(blocking=False)
    try:
        assert tracing.trace_observed_scene(metadata(), photo) == first
    finally:
        tracing._SLOT.release()


def test_cache_has_lru_entry_and_exact_payload_byte_limits():
    from camera_assistant.services.contour_cache import MemoryContourCache

    cache = MemoryContourCache(max_entries=2, max_bytes=8)
    cache.put(b"a", b"123")
    cache.put(b"b", b"456")
    assert cache.get(b"a") == b"123"  # Refresh a before entry-limit eviction.
    cache.put(b"c", b"78")
    assert cache.get(b"b") is None
    assert cache.get(b"a") == b"123" and cache.get(b"c") == b"78"
    cache.put(b"d", b"1234567")
    assert len(cache) == 1 and cache.size_bytes == 7
    cache.put(b"oversized", b"123456789")
    assert len(cache) == 1 and cache.size_bytes == 7
    cache.put(b"d", b"x")
    assert len(cache) == 1 and cache.size_bytes == 1
    cache.clear()
    assert len(cache) == 0 and cache.size_bytes == 0
