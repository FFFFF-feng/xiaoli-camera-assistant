"""Deterministic reframe of observed pixels. No generated views or independent scenery moves."""
from __future__ import annotations

from camera_assistant.composition_models import (
    CompositionIntent,
    CompositionProposal,
    FramingPlan,
    ObservedScene,
    TargetBoard,
    TargetLayer,
)
from camera_assistant.services.scene_context import project_context

ASPECTS = {"portrait": .75, "square": 1., "landscape": 4/3}
LIMIT = "这是基于已观察轮廓的取景示意，不预测侧移后的视差、透视或遮挡；请按文字动作现场试拍。"


def solve_layout(plan: CompositionIntent, scene: ObservedScene,
                 photo_aspect: float, proposal: CompositionProposal) -> tuple[TargetBoard, FramingPlan]:
    if not 0 < photo_aspect <= 100:
        raise ValueError("invalid_photo_aspect")
    mains = [obj for obj in scene.objects if obj.role == "main"]
    focus = next((obj for obj in mains if obj.object_id == plan.focus_object_id), None)
    if focus is None:
        raise ValueError("unknown_focus")
    aspect = plan.aspect if plan.aspect != "keep" else min(ASPECTS, key=lambda k: abs(ASPECTS[k]-photo_aspect))
    ratio = photo_aspect/ASPECTS[aspect]
    base = min(1., 1/ratio)
    union = [min(o.bbox[0] for o in mains), min(o.bbox[1] for o in mains),
             max(o.bbox[2] for o in mains), max(o.bbox[3] for o in mains)]
    # Protect *all* observed main subjects, even if the model focuses on one.
    requested = base * {"keep": 1., "larger": 1.35, "smaller": .8}[plan.subject_scale]
    maximum = min(.92/((union[2]-union[0])*ratio), .92/(union[3]-union[1]))
    minimum = max(max(.00501/((o.bbox[2]-o.bbox[0])*ratio),
                      .00501/(o.bbox[3]-o.bbox[1])) for o in mains)
    if minimum > maximum:
        raise ValueError("main_subjects_too_small")
    scale = min(maximum, max(requested, minimum))
    sx, sy = scale*ratio, scale
    fx, fy = (focus.bbox[0]+focus.bbox[2])/2, (focus.bbox[1]+focus.bbox[3])/2
    cx = {"left": 1/3, "center": .5, "right": 2/3}.get(plan.placement, .5+(fx-.5)*base*ratio)
    cy = {"upper": 1/3, "center": .5, "lower": 2/3}.get(plan.vertical_placement, .5+(fy-.5)*base)
    tx = max(.04-union[0]*sx, min(1-.04-union[2]*sx, cx-fx*sx))
    ty = max(.04-union[1]*sy, min(1-.04-union[3]*sy, cy-fy*sy))
    layers = []
    constrained = abs(scale-requested) > 1e-8 or abs(tx+fx*sx-cx) > 1e-8 or abs(ty+fy*sy-cy) > 1e-8
    for obj in scene.objects:
        if obj.role != "main":
            layer = project_context(obj, (sx, sy, tx, ty))
            if layer:
                layers.append(layer)
            continue
        x1, y1, x2, y2 = obj.bbox
        layers.append(TargetLayer.model_validate({
            **obj.model_dump(exclude={"object_id", "parts"}),
            "bbox": [x1*sx+tx, y1*sy+ty, x2*sx+tx, y2*sy+ty],
            "source_bbox": obj.bbox, "source_object_id": obj.object_id, "certainty": "approximate",
        }))
    main = next(layer for layer in layers if layer.source_object_id == focus.object_id)
    x1, y1, x2, y2 = main.bbox
    placement = f"主体中心横向{(x1+x2)*50:.0f}%、纵向{(y1+y2)*50:.0f}%（从左上角计）。"
    size = f"主体宽约{(x2-x1)*100:.0f}%、高约{(y2-y1)*100:.0f}%，保留真实长宽比例。"
    space = f"四边余量：左{x1*100:.0f}%、右{(1-x2)*100:.0f}%、上{y1*100:.0f}%、下{(1-y2)*100:.0f}%；余量可能含其他景物，不等于留白。"
    limitations = [LIMIT, "所有景物使用同一取景变换；超出画框的环境线索被裁去，框内未绘制处不等于现场空白。"]
    if constrained:
        limitations.append("为完整保留全部主要主体及边缘余量，已限制放大或偏移幅度，以图中实际占比为准。")
    # Partial extraction warnings must remain visible within the board's five
    # note budget, ahead of general descriptions of the tracing method.
    limitations.extend(sorted(scene.limitations,
        key=lambda note: not any(word in note for word in ("分部", "省略", "未分离", "未完整", "格式无效"))))
    board = TargetBoard(
        aspect=aspect, reference_photo_id=scene.reference_photo_id, intent=proposal.goal[:100],
        distance_relation="unknown", distance_instruction="本图仅表示取景范围与主体占比；身体移动方向和距离按文字建议现场核对。",
        layers=layers, changes=[{"problem": plan.diagnosis, "adjustment": (placement+size)[:140],
                                "benefit": "用真实轮廓比较主体占比和边缘余量；拍摄效果仍需现场核对。"}],
        limitations=list(dict.fromkeys(limitations))[:5], render_basis="source_geometry",
        source_photo_aspect=photo_aspect, layout_mode="schematic", layout_engine="local_v1",
    )
    framing = FramingPlan(
        diagnosis=plan.diagnosis, visual_priority=f"先看{focus.label}，其余已观察景物保留相互位置。",
        placement=placement, scale=size, negative_space=space,
        edge_check="检查全部主要主体的外轮廓；原图未拍全的部分无法由本图恢复。",
        background_control="环境按同一取景变换呈现，不通过挪动背景虚构遮挡改善。",
        success_check="核对主体宽高占比；检查四边是否切断关键部位，并现场确认背景干扰是否减弱。",
    )
    return board, framing
