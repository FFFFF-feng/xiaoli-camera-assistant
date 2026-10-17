"""Pixel-based outlines must come from actual regions, not a type-based icon."""
import base64
import io
import math
from copy import deepcopy

import numpy as np
import pytest
from PIL import Image, ImageDraw

from camera_assistant.models import ExifInfo, ImageInspection, ImageMetrics
from camera_assistant.services import pixel_contours as tracing


@pytest.fixture(autouse=True)
def empty_contour_cache():
    # Every invariant test exercises segmentation, even when its fixture pixels
    # happen to match an earlier test. Cache reuse has its own dedicated tests.
    tracing._CACHE.clear()
    yield
    tracing._CACHE.clear()


def inspection(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return ImageInspection(exif=ExifInfo(), metrics=ImageMetrics(
        width=image.width, height=image.height, mean_brightness=.5, contrast=.2,
        shadow_ratio=.1, highlight_ratio=.1, sharpness_score=5),
        model_image_data_url="data:image/png;base64,"+base64.b64encode(stream.getvalue()).decode())


def metadata():
    return {"objects": [{"object_id": "object1", "label": "带阶梯的建筑", "kind": "building",
                         "role": "main", "depth": 1, "bbox": [.15, .1, .85, .9],
                         "identity_features": ["阶梯屋顶", "三扇窗"],
                         "evidence_photo_ids": ["photo1"], "mobility": "fixed"}],
            "limitations": ["合成形状，不代表真实摄影识别结果"]}


def building(mirror=False):
    image = Image.new("RGB", (300, 240), "white")
    draw = ImageDraw.Draw(image)
    draw.polygon([(60, 210), (60, 70), (95, 70), (95, 35), (135, 35), (135, 55),
                  (195, 55), (195, 85), (240, 85), (240, 210)], fill="#8b6646")
    for x in (85, 135, 185):
        draw.rectangle((x, 115, x+20, 155), fill="#e5eef5")
    return image.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirror else image


def test_same_label_keeps_different_pixel_shapes_not_a_generic_building_icon():
    data = metadata()
    frozen = deepcopy(data)
    first = tracing.trace_observed_scene(data, inspection(building()))
    second = tracing.trace_observed_scene(data, inspection(building(True)))
    a, b = first.objects[0], second.objects[0]
    assert len(a.outline) > 6 and len(b.outline) > 6
    assert a.outline != b.outline
    assert a.details and b.details
    assert data == frozen
    assert a.source_object_id is None and a.object_id == "object1"
    assert all(0 <= n <= 1 for p in [a.outline, *a.details] for point in p for n in point)


def test_ignores_broken_model_geometry_and_uses_pixels_instead():
    data = metadata()
    data["objects"][0]["outline"] = [38, 11, 687, 254, 685]
    data["objects"][0]["details"] = "not a path"
    scene = tracing.trace_observed_scene(data, inspection(building()))
    assert len(scene.objects[0].outline) > 6


def test_uniform_image_does_not_become_a_rectangle_placeholder():
    with pytest.raises(ValueError, match="轮廓提取失败"):
        tracing.trace_observed_scene(metadata(), inspection(Image.new("RGB", (300, 240), "white")))


def test_internal_image_dimensions_are_checked_before_pixel_decode():
    image = Image.new("RGB", (2400, 2000), "white")
    with pytest.raises(ValueError, match="像素过大"):
        tracing.trace_observed_scene(metadata(), inspection(image))


def test_only_one_cpu_segmentation_can_run_at_a_time():
    assert tracing._SLOT.acquire(blocking=False)
    try:
        with pytest.raises(ValueError, match="繁忙"):
            tracing.trace_observed_scene(metadata(), inspection(building()))
    finally:
        tracing._SLOT.release()
    assert tracing.trace_observed_scene(metadata(), inspection(building()))


def test_processing_resolution_is_bounded(monkeypatch):
    seen = []
    original = tracing._trace
    def inspect_patch(rgb, obj):
        seen.append(rgb.shape)
        return original(rgb, obj)
    monkeypatch.setattr(tracing, "_trace", inspect_patch)
    image = building().resize((1500, 1200))
    tracing.trace_observed_scene(metadata(), inspection(image))
    assert seen and max(seen[0][:2]) <= tracing.MAX_EDGE
    assert np.prod(seen[0]) <= 720*720*3


def test_explicitly_held_item_is_not_relocated_as_a_duplicate(monkeypatch):
    data = metadata()
    main = data["objects"][0]
    main.update(kind="person", identity_features=["站立姿态", "手持相机"])
    data["objects"].append({**main, "object_id": "object2", "label": "相机", "kind": "object",
                            "role": "prop", "bbox": [.3, .35, .5, .6], "mobility": "movable"})
    calls = []
    original = tracing._trace
    def record(rgb, obj):
        calls.append(obj.object_id)
        return original(rgb, obj)
    monkeypatch.setattr(tracing, "_trace", record)
    result = tracing.trace_observed_scene(data, inspection(building()))
    assert [obj.object_id for obj in result.objects] == ["object1"]
    assert calls == ["object1"]


def test_failed_background_does_not_discard_successful_subject(monkeypatch):
    data = metadata()
    image = building()
    ImageDraw.Draw(image).line([(5, 20), (40, 30), (35, 70)], fill="black", width=3)
    data["objects"].append({**data["objects"][0], "object_id": "object2",
                            "label": "背景树枝", "kind": "tree", "role": "background", "bbox": [0, 0, .15, .4]})
    original = tracing._trace
    def trace(rgb, obj):
        if obj.object_id == "object2":
            raise ValueError("分离失败")
        return original(rgb, obj)
    monkeypatch.setattr(tracing, "_trace", trace)
    scene = tracing.trace_observed_scene(data, inspection(image))
    assert {"object1", "object2"} <= {obj.object_id for obj in scene.objects}
    assert len(scene.objects[0].outline) > 6
    branch = next(obj for obj in scene.objects if obj.object_id == "object2")
    assert branch.representation == "context_lines" and branch.details
    assert branch.outline == []


def test_failed_second_main_still_rejects_incomplete_subjects(monkeypatch):
    data = metadata()
    data["objects"].append({**data["objects"][0], "object_id": "object2"})
    original = tracing._trace
    def trace(rgb, obj):
        if obj.object_id == "object2":
            raise ValueError("分离失败")
        return original(rgb, obj)
    monkeypatch.setattr(tracing, "_trace", trace)
    with pytest.raises(ValueError, match="主要物体轮廓提取失败"):
        tracing.trace_observed_scene(data, inspection(building()))


def test_failed_independent_prop_keeps_its_actual_open_edges(monkeypatch):
    data = metadata()
    data["objects"].append({**data["objects"][0], "object_id": "object2", "label": "细栏杆",
                            "kind": "object", "role": "prop", "bbox": [0, 0, .15, .8]})
    image = building()
    ImageDraw.Draw(image).line([(10, 15), (10, 180)], fill="black", width=3)
    original = tracing._trace
    def trace(rgb, obj):
        if obj.role == "prop":
            raise ValueError("无法闭合分离")
        return original(rgb, obj)
    monkeypatch.setattr(tracing, "_trace", trace)
    scene = tracing.trace_observed_scene(data, inspection(image))
    prop = next(obj for obj in scene.objects if obj.object_id == "object2")
    assert prop.representation == "context_lines" and prop.details and not prop.outline


def test_model_cannot_declare_main_as_context_to_skip_pixel_segmentation():
    data = metadata()
    data["objects"][0].update(representation="context_lines", source_details=[[[0, 0], [1, 1]]])
    scene = tracing.trace_observed_scene(data, inspection(building()))
    assert scene.objects[0].representation == "silhouette"
    assert scene.objects[0].source_details is None and len(scene.objects[0].outline) > 6


def test_disconnected_flower_units_keep_both_shapes_and_their_relative_positions():
    image = Image.new("RGB", (360, 220), "#e7eff4")
    draw = ImageDraw.Draw(image)
    for cx, petals, color in ((90, 5, "#e79595"), (270, 6, "#9caddb")):
        for i in range(petals):
            x, y = cx+24*math.cos(i*2*math.pi/petals), 110+24*math.sin(i*2*math.pi/petals)
            draw.ellipse((x-21, y-21, x+21, y+21), fill=color, outline="#77636c", width=2)
        draw.ellipse((cx-8, 102, cx+8, 118), fill="#a07834")
    data = metadata()
    data["objects"][0].update(kind="flower", label="两朵形态不同的花", bbox=[.04, .07, .96, .93],
                              parts=[{"label": "左花", "kind": "flower", "bbox": [.09, .21, .43, .80]},
                                     {"label": "右花", "kind": "flower", "bbox": [.57, .21, .94, .80]}])
    frozen = deepcopy(data)
    layer = tracing.trace_observed_scene(data, inspection(image)).objects[0]
    assert len(layer.contours) == 2
    assert max(x for x, _ in layer.contours[0]) < min(x for x, _ in layer.contours[1])
    assert layer.contours[0] != layer.contours[1]
    assert layer.bbox[0] < .2 and layer.bbox[2] > .8
    assert len(layer.details) > 10
    assert all(0 <= coordinate <= 1 for path in [*layer.contours, *layer.details]
               for point in path for coordinate in point)
    assert data == frozen


def test_failed_optional_leaf_keeps_flower_but_failed_flower_is_never_silently_erased(monkeypatch):
    data = metadata()
    data["objects"][0].update(kind="flower", parts=[
        {"label": "花", "kind": "flower", "bbox": [.25, .25, .5, .5]},
        {"label": "叶", "kind": "leaf", "bbox": [.3, .3, .55, .55]}])
    parent = tracing.observed_metadata(data).objects[0]
    def extraction(_rgb, obj, **_):
        if obj.kind == "leaf":
            raise ValueError("no leaf edge")
        return obj
    monkeypatch.setattr(tracing, "_trace_single", extraction)
    result = tracing._trace(np.zeros((100, 100, 3), np.uint8), parent)
    assert len(result.contours) == 1
    def bad_flower(*_, **__):
        raise ValueError("flower failed")
    monkeypatch.setattr(tracing, "_trace_single", bad_flower)
    with pytest.raises(ValueError, match="flower failed"):
        tracing._trace(np.zeros((100, 100, 3), np.uint8), parent)


def test_same_pixels_and_observation_produce_identical_contours_across_requests():
    photo = inspection(building())
    first = tracing.trace_observed_scene(metadata(), photo)
    # Other callers may have advanced OpenCV's global generator in between.
    tracing.cv2.setRNGSeed(741)
    tracing.cv2.randn(np.zeros((8, 8), np.float32), 0, 1)
    second = tracing.trace_observed_scene(metadata(), photo)
    assert first == second


@pytest.mark.parametrize("parts", [
    [{"label": "越界", "bbox": [0, 0, .5, .5]}],
    [{"label": "重复", "bbox": [.2, .2, .4, .4]}]*2,
    [{"label": "非法", "bbox": [True, .2, .4, .4]}],
])
def test_part_regions_cannot_escape_subject_or_duplicate_it(parts):
    data = metadata()
    data["objects"][0]["parts"] = parts
    with pytest.raises(ValueError):
        tracing.observed_metadata(data)


def test_non_flower_feature_cannot_replace_the_complete_building():
    data = metadata()
    data["objects"][0]["parts"] = [
        {"label": "一扇窗", "kind": "feature", "bbox": [.28, .44, .37, .65]},
    ]
    layer = tracing.trace_observed_scene(data, inspection(building())).objects[0]
    assert layer.bbox[2]-layer.bbox[0] > .5
    assert layer.bbox[3]-layer.bbox[1] > .6
    assert layer.contours == []
