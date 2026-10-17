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
from camera_assistant.services.drawing_geometry import contained_outline, simple_outline
from camera_assistant.services.pixel_strokes import structural_strokes
from camera_assistant.services.scene_context import context_mask, scene_remainder, trace_context
from camera_assistant.services import scene_structure

_SLOT = BoundedSemaphore(1)
cv2.setNumThreads(1)
MAX_EDGE = 720
DETAIL_EDGE = 1280
PET_ITERATIONS = 5
_ALGORITHM_VERSION = "pixel-contours-v4-tonal-details"
_CACHE = MemoryContourCache()
_STRUCTURE_FAILURE_CODES = frozenset({
    "structure_low_contrast", "structure_density_exceeded", "structure_paths_insufficient",
    "structure_coverage_insufficient",
})


class ContourFailure(ValueError):
    """Stable local reason without image bytes, provider text or raw inputs."""

    def __init__(self, code: str, message: str, *, object_id: str | None = None,
                 stage: str = "segmentation"):
        super().__init__(message)
        self.code = code
        self.object_id = object_id
        self.stage = stage


def _simplify(contour, closed=True, detail=False):
    epsilon = max(1.4 if detail else .6, cv2.arcLength(contour, closed) * (.006 if detail else .001))
    for _ in range(24):
        points = cv2.approxPolyDP(contour, epsilon, closed).reshape(-1, 2)
        if len(points) <= 64:
            return points
        epsilon *= 1.3
    raise ContourFailure("outline_too_complex", "轮廓过于复杂", stage="simplification")


def _trace_single(rgb: np.ndarray, obj: ObservedObject, *, seeded=False) -> ObservedObject:
    height, width = rgb.shape[:2]
    x1, y1, x2, y2 = [round(n * (width if i % 2 == 0 else height)) for i, n in enumerate(obj.bbox)]
    pad = max(6, round(max(x2-x1, y2-y1) * .08))
    ox, oy = max(0, x1-pad), max(0, y1-pad)
    ex, ey = min(width, x2+pad), min(height, y2+pad)
    patch = np.ascontiguousarray(rgb[oy:ey, ox:ex])
    ph, pw = patch.shape[:2]
    if min(pw, ph, x2-x1, y2-y1) < 8 or float(patch.std()) < 2:
        raise ContourFailure("region_uninformative", "物体区域太小或没有可辨认边界", object_id=obj.object_id)
    clipped = x1 == 0 or y1 == 0 or x2 == width or y2 == height
    # A visible subject may legitimately continue beyond the photo. Do not
    # label its last row/column as certain background just to satisfy a rect.
    rx, ry = max(0 if clipped else 1, x1-ox), max(0 if clipped else 1, y1-oy)
    rw, rh = min(x2-ox, pw if clipped else pw-1)-rx, min(y2-oy, ph if clipped else ph-1)-ry
    if min(rw, rh) < 4:
        raise ContourFailure("foreground_region_empty", "缺少可分离的前景区域", object_id=obj.object_id)
    mask = np.zeros((ph, pw), dtype=np.uint8)
    with_mask = seeded or clipped
    if with_mask:
        mask[ry:ry+rh, rx:rx+rw] = cv2.GC_PR_FGD
    if seeded:
        cv2.ellipse(mask, (rx+rw//2, ry+rh//2), (max(1, rw//7), max(1, rh//7)),
                    0, 0, 360, cv2.GC_FGD, cv2.FILLED)
    if with_mask and not np.any(mask == cv2.GC_BGD):
        raise ContourFailure("background_seed_unavailable", "主体占满区域，缺少可靠的背景样本", object_id=obj.object_id)
    cv2.grabCut(patch, mask, None if with_mask else (rx, ry, rw, rh),
                np.zeros((1, 65)), np.zeros((1, 65)), PET_ITERATIONS if obj.kind in {"pet", "dog", "cat"} else 2,
                cv2.GC_INIT_WITH_MASK if with_mask else cv2.GC_INIT_WITH_RECT)
    foreground = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    contours, hierarchy = cv2.findContours(foreground, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ContourFailure("foreground_empty", "未分离出物体轮廓", object_id=obj.object_id)
    outer = [i for i in range(len(contours)) if hierarchy[0][i][3] == -1]
    primary = max(outer, key=lambda i: cv2.contourArea(contours[i]))
    contour = contours[primary]
    if cv2.contourArea(contour) < max(30, rw*rh*.015):
        raise ContourFailure("foreground_insufficient", "前景轮廓不足以代表该物体", object_id=obj.object_id)
    points = _simplify(contour)
    if len(points) < 3:
        raise ContourFailure("outline_degenerate", "轮廓退化", object_id=obj.object_id, stage="simplification")
    lx, ly = contour.reshape(-1, 2).min(axis=0)
    hx, hy = contour.reshape(-1, 2).max(axis=0)
    if hx-lx < (x2-x1)*.5 or hy-ly < (y2-y1)*.5:
        raise ContourFailure("foreground_coverage_insufficient", "提取结果丢失大部分物体范围", object_id=obj.object_id)
    def local(path):
        return [[round(float((x-lx)/(hx-lx)), 5), round(float((y-ly)/(hy-ly)), 5)] for x, y in path]
    outline = local(points)
    if not simple_outline(outline):
        raise ContourFailure("outline_self_intersection", "像素轮廓含无法可靠简化的折返", object_id=obj.object_id, stage="simplification")
    selected = np.zeros_like(foreground)
    cv2.drawContours(selected, [contour], -1, 255, cv2.FILLED)
    # Keep the *inside of the silhouette*, not just foreground colour classes.
    # GrabCut may mark white facial markings/windows as background; discarding
    # those holes erased eyes, camera lenses and tail stripes from the line art.
    inner = cv2.erode(selected, np.ones((3, 3), dtype=np.uint8))
    gaps = []
    hole_paths = []
    if obj.kind in {"pet", "dog", "cat"}:
        # Preserve mask holes before the texture budget is spent on fur. A
        # hole can also be a light marking misclassified by GrabCut: this is a
        # visible boundary cue, not a new semantic part or a filled contour.
        holes = [c for i, c in enumerate(contours) if hierarchy[0][i][3] == primary
                 and cv2.contourArea(c) >= max(4, cv2.contourArea(contour)*.0008)]
        for hole in sorted(holes, key=cv2.contourArea, reverse=True)[:12]:
            points = _simplify(hole)
            if len(points) >= 3:
                path = local(points)
                if simple_outline(path) and contained_outline(outline, path):
                    hole_paths.append(path)
                if len(points) == 64:
                    points = points[:-1]
                gaps.append(local(np.vstack((points, points[0]))))
        # The fill contract is bounded to 64 vertices. Keep the more detailed
        # observed perimeter as connected open runs too, so short ear/muzzle
        # and toe turns are not erased just to fit that fill polygon budget.
        precise = cv2.approxPolyDP(contour, .5, True).reshape(-1, 2)
        precise = np.vstack((precise, precise[0]))
        for start in range(0, min(len(precise)-1, 8*63), 63):
            gaps.append(local(precise[start:start+64]))
    details = [*gaps, *[local(path) for path in structural_strokes(patch, inner, kind=obj.kind)]][:96]
    return ObservedObject.model_validate({
        **obj.model_dump(), "bbox": [(ox+int(lx))/width, (oy+int(ly))/height,
                                    (ox+int(hx))/width, (oy+int(hy))/height],
        "outline": outline, "holes": hole_paths, "details": details,
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
         "outline": [[0, 0], [1, 0], [1, 1], [0, 1]], "details": [], "contours": [], "holes": []}
        for obj in answer["objects"]
    ]})


def trace_observed_scene(answer: dict, inspection: ImageInspection) -> ObservedScene:
    """Ignore any model-generated paths; only use its checked object metadata."""
    metadata = observed_metadata(answer)
    if len(metadata.objects) > 4:
        raise ContourFailure("object_limit_exceeded", "轮廓提取任务繁忙或对象数量过多", stage="input")
    raw = base64.b64decode(inspection.model_image_data_url.split(",", 1)[1], validate=True)
    if len(raw) > 8*1024*1024:
        raise ContourFailure("image_bytes_exceeded", "内部参考图过大", stage="input")
    # Parse the actual image header before accepting a hit. Inspection metrics,
    # data-URL labels and discarded provider paths cannot select cached pixels.
    with Image.open(io.BytesIO(raw)) as image:
        if image.width*image.height > 4_000_000:
            raise ContourFailure("image_pixels_exceeded", "内部参考图像素过大", stage="input")
    digest = hashlib.sha256(
        f"{_ALGORITHM_VERSION}:{scene_structure.STRUCTURE_VERSION}:{MAX_EDGE}:{DETAIL_EDGE}:{PET_ITERATIONS}:{cv2.__version__}\0".encode()
    )
    digest.update(hashlib.sha256(raw).digest())
    digest.update(metadata.model_dump_json().encode("utf-8"))
    key = digest.digest()
    cached = _CACHE.get(key)
    if cached is not None:
        return ObservedScene.model_validate_json(cached)
    if not _SLOT.acquire(timeout=.5):
        raise ContourFailure("compute_slot_busy", "轮廓提取任务繁忙或对象数量过多", stage="queue")
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
                texture_background = (obj.kind in {"grass", "lawn", "ground", "grassland", "field"}
                                      or "草地" in obj.label)
                context = trace_context(rgb, obj, mask=context_mask(rgb, objects), sparse=texture_background)
                if context:
                    objects.append(context)
                else:
                    omitted.append(f"“{obj.label}”没有可辨认的像素边界，未补画；空白不表示现场没有背景。")
                continue
            try:
                pixels = detailed_rgb if (obj.kind == "flower" and obj.parts) or obj.kind in {"pet", "dog", "cat"} else rgb
                if getattr(metadata, "scene_mode", "objects") == "continuous" and obj.role == "main":
                    try:
                        traced = scene_structure.trace_structure(rgb, obj)
                    except ValueError as error:
                        # Only fixed local reason strings are promoted. Never
                        # copy arbitrary validation/provider text to diagnostics.
                        code = str(error) if str(error) in _STRUCTURE_FAILURE_CODES else "structure_processing_failed"
                        raise ContourFailure(code, "连续场景结构不足以可靠表达", object_id=obj.object_id,
                                             stage="structure") from None
                else:
                    traced = _trace(pixels, obj)
                objects.append(traced)
                if traced.holes:
                    warning = "主体孔隙来自像素前景/背景分割；浅色毛发或相近颜色可能误判，请对照原图核对。"
                    if warning not in part_notes:
                        part_notes.insert(0, warning)
                if obj.parts and obj.kind == "flower":
                    count = len(traced.contours)
                    part_notes.append(f"“{obj.label}”保留{count}处可分离分部轮廓；识别到{len(obj.parts)}处分部，未分离的叶片或细小部件未完整表达。")
            except (ValueError, cv2.error) as error:
                if obj.role == "main":
                    raise ContourFailure(
                        error.code if isinstance(error, ContourFailure) else "pixel_processing_failed",
                        "主要物体轮廓提取失败，请补充清晰的主体照片", object_id=obj.object_id,
                        stage=error.stage if isinstance(error, ContourFailure) else "segmentation") from None
                context = trace_context(rgb, obj, mask=context_mask(rgb, objects))
                if context:
                    objects.append(context)
                else:
                    omitted.append(f"“{obj.label}”未提取到可辨认的像素边界，未补画；其空间关系需对照原图核对。")
        if not objects:
            raise ContourFailure("no_usable_geometry", "没有可用的物体轮廓")
        used_ids = {obj.object_id for obj in metadata.objects}
        identifier = next(f"object{i}" for i in range(1, 7) if f"object{i}" not in used_ids)
        remainder = None if getattr(metadata, "scene_mode", "objects") == "continuous" else scene_remainder(rgb, objects, identifier)
        if remainder:
            objects.append(remainder)
        result = ObservedScene.model_validate({**metadata.model_dump(), "objects": [o.model_dump() for o in objects],
            "limitations": [*part_notes,
                            "物体区域来自视觉识别，轮廓由CPU像素分割提取；复杂背景、遮挡与细小部件可能提取不准。",
                            "环境线条来自区域内实际边界，可能含邻近景物，不是逐物体语义分割；低纹理背景不补画。",
                            *omitted, *metadata.limitations][:5]})
        _CACHE.put(key, result.model_dump_json().encode("utf-8"))
        return result
    finally:
        _SLOT.release()
