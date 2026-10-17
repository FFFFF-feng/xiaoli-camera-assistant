"""Small CPU-only per-object silhouettes, reused in a *new* composition layout.

GrabCut is not semantic segmentation: similar backgrounds and occlusion can
still produce wrong boundaries. Never turn a failed mask into a rectangle.
"""
from __future__ import annotations

import base64
import hashlib
import io
from threading import BoundedSemaphore

import cv2
import numpy as np
from PIL import Image

from camera_assistant.composition_models import ObservedObject, ObservedScene
from camera_assistant.models import ImageInspection
from camera_assistant.services.contour_cache import MemoryContourCache
from camera_assistant.services.drawing_geometry import simple_outline
from camera_assistant.services.pixel_strokes import structural_strokes
from camera_assistant.services.scene_context import context_mask, scene_remainder, trace_context

_SLOT = BoundedSemaphore(1)
cv2.setNumThreads(1)
MAX_EDGE = 720
DETAIL_EDGE = 1280
_ALGORITHM_VERSION = "pixel-contours-v1"
_CACHE = MemoryContourCache()


def _simplify(contour, closed=True, detail=False):
    epsilon = max(1.4 if detail else .6, cv2.arcLength(contour, closed) * (.006 if detail else .001))
    for _ in range(24):
        points = cv2.approxPolyDP(contour, epsilon, closed).reshape(-1, 2)
        if len(points) <= 64:
            return points
        epsilon *= 1.3
    raise ValueError("轮廓过于复杂")


def _trace_single(rgb: np.ndarray, obj: ObservedObject, *, seeded=False) -> ObservedObject:
    height, width = rgb.shape[:2]
    x1, y1, x2, y2 = [round(n * (width if i % 2 == 0 else height)) for i, n in enumerate(obj.bbox)]
    pad = max(6, round(max(x2-x1, y2-y1) * .08))
    ox, oy = max(0, x1-pad), max(0, y1-pad)
    ex, ey = min(width, x2+pad), min(height, y2+pad)
    patch = np.ascontiguousarray(rgb[oy:ey, ox:ex])
    ph, pw = patch.shape[:2]
    if min(pw, ph, x2-x1, y2-y1) < 8 or float(patch.std()) < 2:
        raise ValueError("物体区域太小或没有可辨认边界")
    rx, ry = max(1, x1-ox), max(1, y1-oy)
    rw, rh = min(x2-ox, pw-1)-rx, min(y2-oy, ph-1)-ry
    if min(rw, rh) < 4:
        raise ValueError("缺少可分离的前景区域")
    mask = np.zeros((ph, pw), dtype=np.uint8)
    if seeded:
        mask[ry:ry+rh, rx:rx+rw] = cv2.GC_PR_FGD
        cv2.ellipse(mask, (rx+rw//2, ry+rh//2), (max(1, rw//7), max(1, rh//7)),
                    0, 0, 360, cv2.GC_FGD, cv2.FILLED)
    cv2.grabCut(patch, mask, None if seeded else (rx, ry, rw, rh),
                np.zeros((1, 65)), np.zeros((1, 65)), 2,
                cv2.GC_INIT_WITH_MASK if seeded else cv2.GC_INIT_WITH_RECT)
    foreground = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    contours, _ = cv2.findContours(foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("未分离出物体轮廓")
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < max(30, rw*rh*.015):
        raise ValueError("前景轮廓不足以代表该物体")
    points = _simplify(contour)
    if len(points) < 3:
        raise ValueError("轮廓退化")
    lx, ly = contour.reshape(-1, 2).min(axis=0)
    hx, hy = contour.reshape(-1, 2).max(axis=0)
    if hx-lx < (x2-x1)*.5 or hy-ly < (y2-y1)*.5:
        raise ValueError("提取结果丢失大部分物体范围")
    def local(path):
        return [[round(float((x-lx)/(hx-lx)), 5), round(float((y-ly)/(hy-ly)), 5)] for x, y in path]
    outline = local(points)
    if not simple_outline(outline):
        raise ValueError("像素轮廓含无法可靠简化的折返")
    selected = np.zeros_like(foreground)
    cv2.drawContours(selected, [contour], -1, 255, cv2.FILLED)
    # Keep the *inside of the silhouette*, not just foreground colour classes.
    # GrabCut may mark white facial markings/windows as background; discarding
    # those holes erased eyes, camera lenses and tail stripes from the line art.
    inner = cv2.erode(selected, np.ones((3, 3), dtype=np.uint8))
    details = [local(path) for path in structural_strokes(patch, inner, kind=obj.kind)]
    return ObservedObject.model_validate({
        **obj.model_dump(), "bbox": [(ox+int(lx))/width, (oy+int(ly))/height,
                                    (ox+int(hx))/width, (oy+int(hy))/height],
        "outline": outline, "details": details,
        "outline_style": "curved" if obj.kind in {"pet", "cat", "dog", "bird", "flower"} else "angular",
        "certainty": "approximate",
    })


def _trace(rgb: np.ndarray, obj: ObservedObject) -> ObservedObject:
    if not obj.parts or obj.kind != "flower":
        # A face or a held item is a detail of a person, never a replacement for
        # their whole silhouette. Compound extraction currently owns flower groups.
        return _trace_single(rgb, obj.model_copy(update={"parts": []}))
    parts = []
    for part in obj.parts:
        x1, y1, x2, y2 = part.bbox
        dx, dy = (x2-x1)*.12, (y2-y1)*.12
        region = [max(obj.bbox[0], x1-dx), max(obj.bbox[1], y1-dy),
                  min(obj.bbox[2], x2+dx), min(obj.bbox[3], y2+dy)]
        observed = ObservedObject.model_validate({
            **obj.model_dump(), "bbox": region, "parts": [], "label": part.label,
            "kind": part.kind, "contours": [],
        })
        # Each center belongs to a visually identified flower/feature, rather
        # than an arbitrary seed in the middle of the entire disconnected group.
        try:
            parts.append(_trace_single(rgb, observed, seeded=part.kind == "flower"))
        except (ValueError, cv2.error):
            if part.kind != "leaf":
                raise  # A failed flower must not be silently erased from its cluster.
            # Optional leaves may lack a separable boundary; keep real flowers.
    if not parts:
        return _trace_single(rgb, obj.model_copy(update={"parts": []}))
    box = [min(p.bbox[0] for p in parts), min(p.bbox[1] for p in parts),
           max(p.bbox[2] for p in parts), max(p.bbox[3] for p in parts)]
    def project(part, path):
        x1, y1, x2, y2 = part.bbox
        return [[round((x1+x*(x2-x1)-box[0])/(box[2]-box[0]), 5),
                 round((y1+y*(y2-y1)-box[1])/(box[3]-box[1]), 5)] for x, y in path]
    contours = [project(p, p.outline) for p in parts]
    primary = max(range(len(parts)), key=lambda i: (
        parts[i].bbox[2]-parts[i].bbox[0])*(parts[i].bbox[3]-parts[i].bbox[1]))
    details = []
    for index in range(max(len(p.details) for p in parts)):
        for part in parts:
            if index < len(part.details) and len(details) < 96:
                details.append(project(part, part.details[index]))
    return ObservedObject.model_validate({
        **obj.model_dump(), "parts": [], "bbox": box, "outline": contours[primary],
        "contours": contours, "details": details, "outline_style": "curved",
        "certainty": "approximate",
    })


def observed_metadata(answer: dict) -> ObservedScene:
    if not isinstance(answer, dict) or not isinstance(answer.get("objects"), list):
        raise TypeError("缺少原始物体")
    return ObservedScene.model_validate({**answer, "objects": [
        {**obj, "representation": "silhouette", "source_details": None,
         "outline": [[0, 0], [1, 0], [1, 1], [0, 1]], "details": [], "contours": []}
        for obj in answer["objects"]
    ]})


def trace_observed_scene(answer: dict, inspection: ImageInspection) -> ObservedScene:
    """Ignore any model-generated paths; only use its checked object metadata."""
    metadata = observed_metadata(answer)
    if len(metadata.objects) > 4:
        raise ValueError("轮廓提取任务繁忙或对象数量过多")
    raw = base64.b64decode(inspection.model_image_data_url.split(",", 1)[1], validate=True)
    if len(raw) > 8*1024*1024:
        raise ValueError("内部参考图过大")
    # Parse the actual image header before accepting a hit. Inspection metrics,
    # data-URL labels and discarded provider paths cannot select cached pixels.
    with Image.open(io.BytesIO(raw)) as image:
        if image.width*image.height > 4_000_000:
            raise ValueError("内部参考图像素过大")
    digest = hashlib.sha256(
        f"{_ALGORITHM_VERSION}:{MAX_EDGE}:{DETAIL_EDGE}:{cv2.__version__}\0".encode()
    )
    digest.update(hashlib.sha256(raw).digest())
    digest.update(metadata.model_dump_json().encode("utf-8"))
    key = digest.digest()
    cached = _CACHE.get(key)
    if cached is not None:
        return ObservedScene.model_validate_json(cached)
    if not _SLOT.acquire(timeout=.5):
        raise ValueError("轮廓提取任务繁忙或对象数量过多")
    try:
        # A concurrent caller may have completed while this one waited for the
        # existing CPU slot. Recheck to avoid segmenting identical pixels twice.
        cached = _CACHE.get(key)
        if cached is not None:
            return ObservedScene.model_validate_json(cached)
        # GrabCut initializes colour clusters randomly. A fixed seed under this
        # process-wide slot makes identical pixels/boxes reproducible.
        cv2.setRNGSeed(0)
        with Image.open(io.BytesIO(raw)) as image:
            image.thumbnail((DETAIL_EDGE, DETAIL_EDGE))
            detailed_rgb = np.asarray(image.convert("RGB"))
            if max(image.size) > MAX_EDGE:
                image.thumbnail((MAX_EDGE, MAX_EDGE))
            rgb = np.asarray(image.convert("RGB"))
        objects = []
        omitted = []
        part_notes = []
        for obj in sorted(metadata.objects, key=lambda item: item.role != "main"):
            # A held item already inside the person's/animal's silhouette must
            # not be independently relocated and drawn a second time. Require
            # explicit semantic evidence *and* containment, not a bbox alone.
            attached = any(
                parent.kind in {"person", "pet", "cat", "dog"} and parent.role == "main"
                and obj.role == "prop" and obj.mobility == "movable"
                and parent.bbox[0] <= obj.bbox[0] and parent.bbox[1] <= obj.bbox[1]
                and parent.bbox[2] >= obj.bbox[2] and parent.bbox[3] >= obj.bbox[3]
                and any(obj.label in feature and any(word in feature for word in ("手持", "拿着", "握", "抱着"))
                        for feature in parent.identity_features)
                for parent in metadata.objects
            )
            if attached:
                continue
            if obj.role == "background" or (obj.role != "main" and obj.kind in {"tree", "branch", "tree_branch"}):
                context = trace_context(rgb, obj, mask=context_mask(rgb, objects))
                if context:
                    objects.append(context)
                else:
                    omitted.append(f"“{obj.label}”没有可辨认的像素边界，未补画；空白不表示现场没有背景。")
                continue
            try:
                pixels = detailed_rgb if obj.kind == "flower" and obj.parts else rgb
                traced = _trace(pixels, obj)
                objects.append(traced)
                if obj.parts and obj.kind == "flower":
                    count = len(traced.contours)
                    part_notes.append(f"“{obj.label}”保留{count}处可分离分部轮廓；识别到{len(obj.parts)}处分部，未分离的叶片或细小部件未完整表达。")
            except (ValueError, cv2.error):
                if obj.role == "main":
                    raise ValueError("主要物体轮廓提取失败，请补充清晰的主体照片") from None
                context = trace_context(rgb, obj, mask=context_mask(rgb, objects))
                if context:
                    objects.append(context)
                else:
                    omitted.append(f"“{obj.label}”未提取到可辨认的像素边界，未补画；其空间关系需对照原图核对。")
        if not objects:
            raise ValueError("没有可用的物体轮廓")
        used_ids = {obj.object_id for obj in metadata.objects}
        identifier = next(f"object{i}" for i in range(1, 7) if f"object{i}" not in used_ids)
        remainder = scene_remainder(rgb, objects, identifier)
        if remainder:
            objects.append(remainder)
        result = ObservedScene.model_validate({**metadata.model_dump(), "objects": [o.model_dump() for o in objects],
            "limitations": ["物体区域来自视觉识别，轮廓由CPU像素分割提取；复杂背景、遮挡与细小部件可能提取不准。",
                            "环境线条来自区域内实际边界，可能含邻近景物，不是逐物体语义分割；低纹理背景不补画。",
                            *part_notes, *omitted, *metadata.limitations][:5]})
        _CACHE.put(key, result.model_dump_json().encode("utf-8"))
        return result
    finally:
        _SLOT.release()
