"""Deterministic reframe of observed pixels. No generated views or independent scenery moves."""
from __future__ import annotations

import logging

from camera_assistant.composition_models import (
    CompositionIntent,
    CompositionProposal,
    FramingPlan,
    ObservedScene,
    TargetBoard,
    TargetLayer,
)
from camera_assistant.services.scene_context import project_context
from camera_assistant.services.layout_presentation import layout_mode, measure_layout, needs_source_frame

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
    continuous = scene.scene_mode == "continuous"
    clipped = not continuous and needs_source_frame(scene)
    preserve_source = needs_source_frame(scene)
    if preserve_source:
        # A continuous scene has no independent movable silhouette. Preserve the
        # complete source field, including genuine edge truncation. Any requested
        # camera shift still needs a new photograph, not a fabricated 2D view.
        aspect = min(ASPECTS, key=lambda k: abs(ASPECTS[k]-photo_aspect))
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
    delta = measure_layout((sx, sy, tx, ty), [o.bbox for o in mains], photo_aspect, ASPECTS[aspect])
    mode = layout_mode(scene, delta)
    preserve_source = mode == "source_preserving"
    if preserve_source:
        sx, sy = base*ratio, base
        tx, ty = (1-sx)/2, (1-sy)/2
    logging.getLogger(__name__).debug("layout_delta=%s decision_delta=%s mode=%s",
        measure_layout((sx, sy, tx, ty), [o.bbox for o in mains], photo_aspect, ASPECTS[aspect]), delta, mode)
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
            "source_details": obj.details if obj.representation == "scene_structure" else obj.source_details,
        }))
    main = next(layer for layer in layers if layer.source_object_id == focus.object_id)
    x1, y1, x2, y2 = main.bbox
    placement = f"主体中心横向{(x1+x2)*50:.0f}%、纵向{(y1+y2)*50:.0f}%（从左上角计）。"
    size = f"主体宽约{(x2-x1)*100:.0f}%、高约{(y2-y1)*100:.0f}%，保留真实长宽比例。"
    space = f"四边余量：左{x1*100:.0f}%、右{(1-x2)*100:.0f}%、上{y1*100:.0f}%、下{(1-y2)*100:.0f}%；余量可能含其他景物，不等于留白。"
    limitations = [LIMIT, "所有景物使用同一取景变换；超出画框的环境线索被裁去，框内未绘制处不等于现场空白。"]
    if continuous:
        limitations = ["本方案保留原取景：连续场景结构线只表示原图可见边界，不是已实现侧移的新视角。",
                       "开放路径不表示封闭物体分割，也不补画画外区域；山峰与倒影、两侧建筑共享同一变换。", LIMIT]
    elif clipped:
        limitations = ["主体贴近或接触参考照片边界：保留原取景，填色闭合不代表真实物体底边；画外形体未知，不补全。",
                       "斜线区域未被参考照片覆盖，不表示已知留白；所有轮廓与内部细节使用同一变换。", LIMIT]
    elif preserve_source:
        limitations.insert(0, "实际缩放、位移和主体占比变化低于展示阈值：保留原取景，未模拟新机位。")
    if constrained and not preserve_source:
        limitations.append("为完整保留全部主要主体及边缘余量，已限制放大或偏移幅度，以图中实际占比为准。")
    # Partial extraction warnings must remain visible within the board's five
    # note budget, ahead of general descriptions of the tracing method.
    limitations.extend(sorted(scene.limitations,
        key=lambda note: not any(word in note for word in ("孔隙", "分部", "省略", "未分离", "未完整", "格式无效"))))
    if continuous:
        change = {"problem": plan.diagnosis,
                  "adjustment": "保留连续场景的真实空间关系，按现场动作调整机位、距离或拍摄时机。",
                  "benefit": "强化主体与环境的关联；透视、遮挡和实际效果需要现场试拍核对。"}
        distance_instruction = "按文字建议调整机位、距离或拍摄时机，试拍后核对场景结构与背景干扰。"
    elif clipped:
        change = {"problem": "主体贴近或接触参考照片边界，画外形体未知",
                  "adjustment": "建议适当后退重新取景，确认主体完整后再按文字建议移动机位。",
                  "benefit": "不把画外区域误当作已知留白；拍摄效果仍需现场核对。"}
        distance_instruction = "建议适当后退，重新拍摄并检查贴边部位及四边余量；画外形体未知，未模拟后退或侧移效果。"
    elif preserve_source:
        change = {"problem": plan.diagnosis, "adjustment": "按现场操作提示试拍，再核对主体位置和边缘余量。",
                  "benefit": "避免把近似原图的示意误认为新机位效果，改善仍需现场确认。"}
        distance_instruction = "当前布局变化很小，保留原取景；按文字动作试拍，检查主体、边缘和背景。"
    else:
        change = {"problem": plan.diagnosis, "adjustment": (placement+size)[:140],
                  "benefit": "用真实轮廓比较主体占比和边缘余量；拍摄效果仍需现场核对。"}
        distance_instruction = "本图仅表示取景范围与主体占比；身体移动方向和距离按文字建议现场核对。"
    board = TargetBoard(
        aspect=aspect, reference_photo_id=scene.reference_photo_id, intent=proposal.goal[:100],
        distance_relation="unknown", distance_instruction=distance_instruction,
        layers=layers, changes=[change],
        limitations=list(dict.fromkeys(limitations))[:5], render_basis="source_geometry",
        source_photo_aspect=photo_aspect, layout_mode=mode, layout_engine="local_v1",
        observed_frame=[tx, ty, tx+sx, ty+sy] if preserve_source else None,
        target_frame=[0., 0., 1., 1.] if preserve_source else None,
        unrendered_objects=[obj.label for obj in scene.unrendered_objects],
    )
    framing = FramingPlan(
        diagnosis=plan.diagnosis, visual_priority=f"先看{focus.label}，其余已观察景物保留相互位置。",
        placement=placement, scale=size, negative_space=space,
        edge_check="保留原图可见边界与已有截断；核对两侧结构、山峰及倒影的关联。" if continuous else "检查全部主要主体的外轮廓；原图未拍全的部分无法由本图恢复。",
        background_control="环境按同一取景变换呈现，不通过挪动背景虚构遮挡改善。",
        success_check="核对主体宽高占比；检查四边是否切断关键部位，并现场确认背景干扰是否减弱。",
    )
    return board, framing
