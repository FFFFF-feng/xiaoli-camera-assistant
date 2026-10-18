"""Synthetic failure repros; no claim of replaying unavailable cloud inputs."""
import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw
from test_pixel_contours import inspection, metadata

from camera_assistant.services import pixel_contours as tracing
from camera_assistant.services.pixel_strokes import MAX_EDGE_PIXELS, structural_strokes


def test_dense_observed_texture_does_not_discard_valid_subject(monkeypatch):
    # Real coffee's frozen region exposed this same pre-graph density failure.
    rng = np.random.default_rng(8)
    rgb = rng.integers(40, 220, (420, 520, 3), dtype=np.uint8)
    cv2.ellipse(rgb, (260, 210), (190, 140), 0, 0, 360, (235, 235, 235), 4)
    seen = []
    from camera_assistant.services import pixel_strokes
    original = pixel_strokes.edge_chains
    def bounded(edges):
        seen.append(np.count_nonzero(edges))
        return original(edges)
    monkeypatch.setattr(pixel_strokes, "edge_chains", bounded)
    paths = structural_strokes(rgb, np.full(rgb.shape[:2], 255, np.uint8), kind="cup")
    assert paths and seen and max(seen) <= MAX_EDGE_PIXELS
    assert all(2 <= len(path) <= 64 for path in paths)


def test_visible_subject_reaches_photo_edge_without_forced_background_strip():
    image = Image.new("RGB", (240, 220), "#e2d9ce")
    draw = ImageDraw.Draw(image)
    draw.ellipse((65, 30, 205, 155), fill="#996d42", outline="#f3ebdf", width=4)
    draw.rectangle((65, 90, 205, 219), fill="#b5a695")
    data = metadata()
    data["objects"][0].update(kind="cup", bbox=[.26, .12, .87, 1])
    tracing._CACHE.clear()
    result = tracing.trace_observed_scene(data, inspection(image)).objects[0]
    assert result.bbox[3] == pytest.approx(219/220)
    assert result.bbox[0] > .2 and result.bbox[2] < .9


def test_leg_gap_boundaries_survive_external_silhouette_extraction(monkeypatch):
    rgb = np.full((160, 220, 3), 220, np.uint8)
    foreground = np.zeros((160, 220), np.uint8)
    cv2.rectangle(foreground, (30, 35), (190, 130), 255, -1)
    cv2.rectangle(foreground, (90, 75), (112, 115), 0, -1)
    rgb[foreground > 0] = 50
    data = metadata()
    data["objects"][0].update(kind="pet", bbox=[.1, .1, .95, .95])
    obj = tracing.observed_metadata(data).objects[0]
    def known_mask(patch, mask, *_args):
        # Project the test's exact mask through the same padded crop as _trace.
        mask[:] = np.where(foreground[1:160, 7:220] > 0, cv2.GC_FGD, cv2.GC_BGD)
    monkeypatch.setattr(tracing.cv2, "grabCut", known_mask)
    # The gap is a true observed dark/light edge, not a synthetic joint.
    result = tracing._trace_single(rgb, obj)
    assert result.details[0][0] == result.details[0][-1]
    assert all(.32 < x < .55 and .35 < y < .9 for x, y in result.details[0])
    assert len(result.holes) == 1
    assert all(.32 < x < .55 and .35 < y < .9 for x, y in result.holes[0])


def test_provider_holes_are_ignored_even_if_they_are_invalid():
    data = metadata()
    data["objects"][0]["holes"] = "invented-provider-hole"
    observed = tracing.observed_metadata(data)
    assert observed.objects[0].holes == []


@pytest.mark.parametrize("kind,expected", [("pet", 5), ("dog", 5), ("cat", 5), ("cup", 2), ("building", 2)])
def test_extra_segmentation_iterations_are_limited_to_animals(monkeypatch, kind, expected):
    from test_pixel_contours import building
    data = metadata()
    data["objects"][0]["kind"] = kind
    original = tracing.cv2.grabCut
    seen = []
    def record(rgb, mask, rect, bg, fg, iterations, mode):
        seen.append(iterations)
        return original(rgb, mask, rect, bg, fg, iterations, mode)
    monkeypatch.setattr(tracing.cv2, "grabCut", record)
    tracing._CACHE.clear()
    tracing.trace_observed_scene(data, inspection(building()))
    assert seen == [expected]


def test_main_failure_keeps_safe_reason_and_object_identity():
    tracing._CACHE.clear()
    with pytest.raises(ValueError) as caught:
        tracing.trace_observed_scene(metadata(), inspection(Image.new("RGB", (300, 240), "white")))
    assert getattr(caught.value, "code", None) == "region_uninformative"
    assert caught.value.object_id == "object1" and caught.value.stage == "segmentation"
    assert len(tracing._CACHE) == 0


def test_pet_processing_keeps_detail_resolution_within_the_existing_bound(monkeypatch):
    from test_pixel_contours import building
    data = metadata()
    data["objects"][0]["kind"] = "pet"
    shapes = []
    original = tracing._trace
    def record(rgb, obj):
        shapes.append(rgb.shape[:2])
        return original(rgb, obj)
    monkeypatch.setattr(tracing, "_trace", record)
    tracing._CACHE.clear()
    tracing.trace_observed_scene(data, inspection(building().resize((1500, 1200))))
    assert shapes and tracing.MAX_EDGE < max(shapes[0]) <= tracing.DETAIL_EDGE


def test_pet_background_remainder_has_a_small_structural_budget():

    from camera_assistant.services.scene_context import scene_remainder
    data = metadata()
    data["objects"][0].update(kind="pet", bbox=[.3, .3, .7, .8])
    subject = tracing.observed_metadata(data).objects[0]
    rng = np.random.default_rng(31)
    rgb = rng.integers(0, 256, (300, 400, 3), np.uint8)
    cv2.line(rgb, (0, 50), (399, 50), (10, 10, 10), 4)
    result = scene_remainder(rgb, [subject], "object2")
    assert result is None or len(result.details) <= 10


def test_small_chromatic_feature_is_preserved_from_pixels_in_its_actual_location():
    rgb = np.full((160, 240, 3), 30, np.uint8)
    cv2.ellipse(rgb, (40, 60), (13, 10), 20, 0, 360, (20, 110, 200), -1)
    paths = structural_strokes(rgb, np.full((160, 240), 255, np.uint8), kind="pet")
    assert paths and paths[0][0].tolist() == paths[0][-1].tolist()
    center = paths[0].mean(axis=0)
    assert np.linalg.norm(center-[40, 60]) < 5


def test_uncertain_object_kind_does_not_erase_large_observed_tonal_details():
    # Live06 labelled the coffee cup "building". Pixel-supported broad regions
    # must survive this metadata error without pretending the class is correct.
    rgb = np.full((200, 240, 3), (110, 70, 40), np.uint8)
    cv2.ellipse(rgb, (115, 95), (85, 65), 0, 0, 360, (230, 215, 180), 5)
    cv2.ellipse(rgb, (110, 85), (50, 28), -20, 0, 360, (225, 210, 175), -1)
    cv2.circle(rgb, (85, 70), 18, (240, 230, 205), -1)
    mask = np.full(rgb.shape[:2], 255, np.uint8)
    cup = structural_strokes(rgb, mask, kind='cup')
    uncertain = structural_strokes(rgb, mask, kind='building')
    assert [path.tolist() for path in uncertain] == [path.tolist() for path in cup]


@pytest.mark.parametrize("reason,expected", [
    ("structure_coverage_insufficient", "structure_coverage_insufficient"),
    ("private raw request data", "structure_processing_failed"),
])
def test_continuous_failure_has_fixed_safe_stage_and_reason(monkeypatch, reason, expected):
    from test_pixel_contours import building
    data = metadata()
    data["scene_mode"] = "continuous"
    def fail(*_):
        raise ValueError(reason)
    monkeypatch.setattr(tracing.scene_structure, "trace_structure", fail)
    tracing._CACHE.clear()
    with pytest.raises(tracing.ContourFailure) as caught:
        tracing.trace_observed_scene(data, inspection(building()))
    assert caught.value.code == expected and caught.value.stage == "structure"
    assert caught.value.object_id == "object1"
    assert "private" not in str(caught.value) and len(tracing._CACHE) == 0
