"""Deterministic geometry shared by sketch labels and photography instructions.

Coordinates describe regions from a photograph, not segmentation masks or a
prediction of what a different camera position would reveal.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable

from camera_assistant.composition_models import CompositionAdvice, CompositionSketch
from camera_assistant.models import ImageInspection, SceneAnalysis

FRAME_ASPECTS = {"portrait": 3 / 4, "landscape": 4 / 3, "square": 1.0}
SIDE_NAMES = {"left": "左侧", "right": "右侧", "top": "上方", "bottom": "下方"}
CAMERA_INSTRUCTIONS = {
    "stay": "保持当前机位，按取景器检查画面边缘。",
    "left": "向左调整机位，再检查取景与边缘。",
    "right": "向右调整机位，再检查取景与边缘。",
    "closer": "适当靠近主体，观察取景与对焦，并保留边缘余量。",
    "farther": "适当后退，观察主体占比并检查边缘余量。",
    "lower": "适当降低机位，检查取景与主体完整性。",
    "higher": "适当提高机位，检查取景与主体完整性。",
}


def _percent(value: float) -> int:
    """Match JavaScript Math.round for nonnegative normalized coordinates."""
    return math.floor(value * 100 + .5)


_GEOMETRY_NUMBER = re.compile(r"\d+(?:\.\d+)?\s*[%％]|百分之|\d+\s*/\s*\d+|[一二三四五六七八九十两]+分之[一二三四五六七八九十两]+")
_TARGET_GEOMETRY = re.compile(
    r"留白|占比|居中|中线|中心|三分|黄金分割|(?:左|右|上|下)(?:侧|方|边|部|半)|顶部|底部|"
    r"(?:运动|行进|前进)方向.{0,8}(?:空间|余量)|"
    r"(?:放在|放到|摆在|置于|移到).{0,12}(?:画面|位置|区域)|"
    r"(?:主体|主角|人物|宠物|咖啡杯).{0,8}(?:位于|处于|位置|摆位)"
)
_MOVEMENTS = (
    ("left", r"向左|往左|左移|左侧.{0,5}(?:移动|平移)|(?:移动|平移).{0,5}左侧"),
    ("right", r"向右|往右|右移|右侧.{0,5}(?:移动|平移)|(?:移动|平移).{0,5}右侧"),
    ("closer", r"靠近|前移|向前|往前|向(?:主体|咖啡杯|杯子|物体|人物|宠物)(?:方向)?(?:缓慢)?移动"),
    ("farther", r"后退|退后|远离|向后|往后"),
    ("lower", r"降低.{0,6}(?:机位|相机)|(?:机位|相机).{0,6}降低|蹲下|放低|压低机位"),
    ("higher", r"提高.{0,6}(?:机位|相机)|(?:机位|相机).{0,6}提高|抬高机位"),
)


def expanded_source_box(source: list[float], margin: float) -> list[float]:
    """Pad each side by a fraction of the unpadded source width/height."""
    dx, dy = (source[2] - source[0]) * margin, (source[3] - source[1]) * margin
    return [max(0, source[0] - dx), max(0, source[1] - dy),
            min(1, source[2] + dx), min(1, source[3] + dy)]


def fit_box(target: list[float], source: list[float], photo_aspect: float,
            frame_aspect: float) -> list[float]:
    """Contain the source photograph region in a normalized destination slot."""
    ratio = photo_aspect * (source[2] - source[0]) / (source[3] - source[1])
    width = min(target[2] - target[0], (target[3] - target[1]) * ratio / frame_aspect)
    height = width * frame_aspect / ratio
    x, y = (target[0] + target[2] - width) / 2, (target[1] + target[3] - height) / 2
    return [x, y, x + width, y + height]


def _contains(outer: list[float], inner: list[float]) -> bool:
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and outer[2] >= inner[2] and outer[3] >= inner[3])


def _subtract(region: list[float], obstacle: list[float]) -> list[list[float]]:
    x1, y1 = max(region[0], obstacle[0]), max(region[1], obstacle[1])
    x2, y2 = min(region[2], obstacle[2]), min(region[3], obstacle[3])
    if x1 >= x2 or y1 >= y2:
        return [region]
    return [box for box in ([region[0], region[1], x1, region[3]],
                            [x2, region[1], region[2], region[3]],
                            [region[0], region[1], region[2], y1],
                            [region[0], y2, region[2], region[3]])
            if box[2] - box[0] > .01 and box[3] - box[1] > .01]


def space_region(main_box: list[float], side: str,
                 obstacles: Iterable[list[float]] = ()) -> list[float] | None:
    """Choose available space only on the requested side; never invent a side."""
    regions = {"left": [0, 0, main_box[0], 1], "right": [main_box[2], 0, 1, 1],
               "top": [0, 0, 1, main_box[1]], "bottom": [0, main_box[3], 1, 1]}
    if side not in regions:
        return None
    remaining = [regions[side]]
    for obstacle in obstacles:
        remaining = [piece for region in remaining for piece in _subtract(region, obstacle)]
        remaining = sorted(remaining, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), reverse=True)[:128]
    remaining = [region for region in remaining
                 if min(region[2] - region[0], region[3] - region[1]) >= .06
                 and (region[2] - region[0]) * (region[3] - region[1]) >= .04]
    return max(remaining, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), default=None)


def _space_side(sketch: CompositionSketch) -> str:
    if "space_side" in sketch.model_fields_set:
        return sketch.space_side
    # Compatibility with old responses: two directions, including 上下/左右,
    # cannot authorize one arbitrary blue region.
    if re.search(r"上下|左右|两侧|四周|四边|周围", sketch.space_note):
        return "none"
    found = [side for side, pattern in (("left", r"左侧|左边|左方|画面左"),
                                        ("right", r"右侧|右边|右方|画面右"),
                                        ("top", r"上方|上侧|顶部|上边"),
                                        ("bottom", r"下方|下侧|底部|下边"))
             if re.search(pattern, sketch.space_note)]
    return found[0] if len(found) == 1 else "none"


def _without_numeric_geometry(text: str, scene_mode: bool = False) -> str:
    clauses = re.split(r"[，,；;。]", text)
    return "，".join(clause.strip() for clause in clauses
                    if clause.strip() and not _GEOMETRY_NUMBER.search(clause)
                    and not _TARGET_GEOMETRY.search(clause)
                    and not (scene_mode and re.search(r"地平线|上半|下半|中线|居中|各占|一半", clause)))


def _primary_camera_action(actions: list[str], sketch: CompositionSketch) -> str | None:
    forbidden = set()
    instructions = [*actions, sketch.camera_instruction]
    # Collect all prohibitions before choosing any arrow: a later instruction
    # must be able to veto an earlier positive action.
    for action in instructions:
        negatives = re.findall(r"(?:不要|不应|不得|不可|不能|避免)[^，。;；]*", action)
        for clause in negatives:
            forbidden.update(key for key, pattern in _MOVEMENTS if re.search(pattern, clause))
    for action in instructions:
        positive = re.sub(r"(?:不要|不应|不得|不可|不能|避免)[^，。;；]*", "", action)
        found = [(match.start(), key) for key, pattern in _MOVEMENTS
                 if (match := re.search(pattern, positive))]
        stay = re.search(r"保持(?:当前|原有|原)?机位|固定机位|原地(?:拍摄|取景)|机位不动", positive)
        no_move = re.search(r"(?:不要|无需|不必|不)(?:移动|调整)机位", action)
        if stay or no_move:
            found.append(((stay or no_move).start(), "stay"))
        if found:
            candidate = min(found)[1]
            return None if candidate in forbidden else candidate
        if re.search(r"(?:水平|横向).{0,6}(?:移动|平移)|移动机位|调整机位", positive):
            # The prose asks for a move but supplies no safe direction for an arrow.
            return None
    return None if sketch.camera_action in forbidden else sketch.camera_action


def _continuous_scene(sketch: CompositionSketch, scene: SceneAnalysis | None) -> bool:
    if (sketch.render_mode == "scene" or sum(e.role == "main" for e in sketch.elements) != 1
            or any(e.kind in {"building", "mountain"} for e in sketch.elements)):
        return True
    primary = next(e for e in sketch.elements if e.role == "main")
    if primary.source_bbox:
        regions = [expanded_source_box(e.source_bbox, sketch.source_margin) for e in sketch.elements
                   if e.source_bbox and not (e.role == "context" and _contains(primary.source_bbox, e.source_bbox))]
        for index, box in enumerate(regions):
            for other in regions[index + 1:]:
                if (min(box[2], other[2]) > max(box[0], other[0])
                        and min(box[3], other[3]) > max(box[1], other[1])):
                    return True
    facts = " ".join([*(e.label for e in sketch.elements),
                      *(e.description for e in sketch.elements)])
    if scene:
        facts += f" {scene.scene_type} {scene.subject} {scene.scene_label}"
    return bool(re.search(r"waterfall|reflection|landscape|architecture|building|瀑布|倒影|走廊|拱廊|山水|山湖|建筑", facts, re.IGNORECASE))


def resolve_sketch_geometry(advice: CompositionAdvice, inspection: ImageInspection,
                            scene: SceneAnalysis | None = None) -> CompositionAdvice:
    """Canonicalize diagram geometry after validating all original instructions."""
    if inspection.metrics.width <= 0 or inspection.metrics.height <= 0:
        return advice
    photo_aspect = inspection.metrics.width / inspection.metrics.height
    proposals, notes = [], list(advice.notes)
    for proposal in advice.proposals:
        sketch = proposal.sketch
        if not sketch:
            proposals.append(proposal)
            continue
        camera_action = _primary_camera_action(proposal.actions, sketch)
        if camera_action is None:
            notes.append("机位文字与方向标记无法可靠对应，已隐藏该方案的手稿；请按现场取景确认动作。")
            proposals.append(proposal.model_copy(update={"sketch": None}))
            continue
        primary = next((e for e in sketch.elements if e.role == "main"), None)
        scene_mode = _continuous_scene(sketch, scene) or primary is None or primary.source_bbox is None
        if not scene_mode and primary is not None and primary.source_bbox is not None:
            main_box = fit_box(primary.bbox, expanded_source_box(primary.source_bbox, sketch.source_margin),
                               photo_aspect, FRAME_ASPECTS[sketch.aspect])
            scene_mode = min(main_box[2] - main_box[0], main_box[3] - main_box[1]) < .05
        updates: dict[str, object] = {"photo_aspect": photo_aspect,
                                      "camera_action": camera_action,
                                      "camera_instruction": CAMERA_INSTRUCTIONS[camera_action]}
        actions = [cleaned for action in proposal.actions
                   if (cleaned := _without_numeric_geometry(action, scene_mode))]
        # Free prose cannot be a second authority for target position, size or
        # negative space. Apply the same rule to every displayed proposal field.
        cleaned_fields = {}
        for field, fallback in {
            "reasons": "对照手稿中的区域位置，检查主体完整性与背景干扰。",
            "tradeoffs": "调整取景可能改变背景范围，需现场确认。",
            "conditions": "在现场条件允许时调整，并检查主体完整性。",
            "limitations": "线稿不模拟新机位下的透视与遮挡，需现场试拍。",
        }.items():
            values = [_without_numeric_geometry(value, scene_mode) for value in getattr(proposal, field)]
            cleaned_fields[field] = list(dict.fromkeys(value for value in values if value)) or [fallback]
        reasons = cleaned_fields["reasons"]
        goal = _without_numeric_geometry(proposal.goal, scene_mode) or "按手稿检查取景与主体完整性"
        actions = [CAMERA_INSTRUCTIONS[camera_action], *actions]
        plan = proposal.framing_plan
        if plan:
            plan = plan.model_copy(update={key: _without_numeric_geometry(value, scene_mode)
                or "对照原照片检查主体完整性与背景干扰。" for key, value in plan.model_dump().items()})
        if scene_mode:
            reasons = ["机位调整可能改变透视、遮挡和主体占比，需要在现场取景器确认。"
                       if re.search(r"(?:机位|焦段|移动).{0,30}(?:不会改变|不改变).{0,15}(?:占比|透视|大小)", reason)
                       else reason for reason in reasons]
            elements = [e.model_copy(update={"bbox": list(e.source_bbox)})
                        for e in sketch.elements if e.source_bbox is not None]
            updates.update(render_mode="scene", elements=elements, source_margin=0,
                           space_side="none", space_note="保留原照片的完整场景，不新增方向留白标记。",
                           horizon_y=None,
                           caption="整体保留原图的透视与位置；机位调整后的取景以现场为准。",
                           narration="线稿保持原照片中的空间关系，不模拟新机位下的遮挡、透视或背景。请在现场取景器确认调整效果。")
            actions.append("对照整体线稿检查场景完整性；调整机位后的取景和透视以现场画面为准。")
            if plan:
                plan = plan.model_copy(update={
                    "placement": "整幅原图按原有位置显示，场景中的相对位置和透视保持不变。",
                    "scale": "原照片完整显示（宽100%、高100%）；线稿不模拟移动机位后的画面。",
                    "negative_space": "整幅场景示意不新增留白标记；现场检查取景边缘和背景。",
                    "success_check": "在现场取景器确认主体完整入画，并检查场景线条和画面边缘。",
                })
        else:
            assert primary is not None and primary.source_bbox is not None
            frame_aspect = FRAME_ASPECTS[sketch.aspect]
            # Keep only traced environmental regions. Props already inside the
            # main crop must not be duplicated as separately movable objects.
            elements = []
            for element in sketch.elements:
                if element.source_bbox is None:
                    continue
                if element.role != "main" and _contains(primary.source_bbox, element.source_bbox):
                    continue
                source = expanded_source_box(element.source_bbox, sketch.source_margin)
                box = fit_box(element.bbox, source, photo_aspect, frame_aspect)
                if min(box[2] - box[0], box[3] - box[1]) < .05:
                    continue
                elements.append(element.model_copy(update={"bbox": box}))
            main = next(e for e in elements if e.role == "main")
            x1, y1, x2, y2 = main.bbox
            side = _space_side(sketch)
            motion_space = re.search(r"(?:运动|行进|前进)方向", " ".join([proposal.goal, sketch.space_note, *proposal.actions]))
            if motion_space and {"left": "right", "right": "left"}.get(main.facing) == side:
                # A still image does not establish true motion direction. Do not
                # silently reverse the model's side based on a facing tag.
                side = "none"
                notes.append("运动方向留白与主体朝向标注矛盾，已取消该方向留白标记；请在现场确认运动方向。")
            obstacles = [e.bbox for e in elements if e.role == "context"]
            if space_region(main.bbox, side, obstacles) is None:
                side = "none"
            scale = f"轮廓取材区域宽约{_percent(x2 - x1)}%、高约{_percent(y2 - y1)}%"
            placement = f"轮廓取材区域中心：横向{_percent((x1 + x2) / 2)}%、纵向{_percent((y1 + y2) / 2)}%（从左上角计）。"
            margins = f"四边余量：左{_percent(x1)}%、右{_percent(1 - x2)}%、上{_percent(y1)}%、下{_percent(1 - y2)}%。"
            space_note = (f"{SIDE_NAMES[side]}保留画面余量，现场检查背景干扰。" if side != "none"
                          else "未指定可靠的单侧留白，按实际取景检查四边余量。")
            updates.update(render_mode="subject", elements=elements, space_side=side,
                           caption=f"{main.label}取材区域宽约{_percent(x2-x1)}%、高约{_percent(y2-y1)}%；" +
                                   (f"{SIDE_NAMES[side]}保留余量。" if side != "none" else "检查四边余量。"),
                           space_note=space_note,
                           narration="主体轮廓取自原照片，按原比例放入示意区域；取材中仍可能包含背景，请在现场检查主体完整性和背景干扰。")
            actions.append("按手稿中当前显示的轮廓区域占比与四边余量检查取景；取材区域包含边缘余量和区域内背景。")
            if plan:
                plan = plan.model_copy(update={"placement": placement,
                    "scale": f"建议画幅内，{scale}；保留原始比例，包含取材边缘余量和区域内背景。",
                    "negative_space": margins + space_note,
                    "success_check": "对照示意图检查取材区域占比与四边余量，并确认主体关键部位完整。"})
        proposals.append(proposal.model_copy(update={"sketch": sketch.model_copy(update=updates),
                                                     "framing_plan": plan,
                                                     "goal": goal,
                                                     **cleaned_fields,
                                                     "reasons": list(dict.fromkeys(reasons)),
                                                     "actions": list(dict.fromkeys(actions))}))
    return advice.model_copy(update={"proposals": proposals, "notes": list(dict.fromkeys(notes))})
