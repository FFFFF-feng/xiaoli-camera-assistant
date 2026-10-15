"""Review candidate claims against independent inputs and a small physics registry.

The registry checks control/effect relationships, not arbitrary prose truth. Image
references remain observations from a model, and entity correspondence has no
verifier here. Camera position outcomes are consequently trial conditions.
"""
from __future__ import annotations

import re

from camera_assistant.candidate_models import CandidateOperation
from camera_assistant.composition_models import CompositionAdvice
from camera_assistant.models import CameraProfile, CameraRecommendation, SceneAnalysis, UserRequest
from camera_assistant.services.composition_trials import (
    goal_field_checks,
    interpret_actions,
    render_actions,
)
from camera_assistant.services.photography_targets import resolve_photography_scope

CONTROL_EFFECTS = {
    "aperture": {"depth_of_field", "recorded_brightness"},
    "shutter": {"motion_blur", "recorded_brightness"},
    "iso": {"recorded_brightness", "noise"},
    "exposure_compensation": {"recorded_brightness"},
    "shutter_type": {"shutter_vibration"},
    "ibis": {"camera_shake"},
    "camera_position": {"framing", "background_separation"},
    "focal_length": {"framing", "depth_of_field"},
    "focus": {"focus_plane"},
}
CONTROL_TARGETS = {
    "aperture": {"aperture", "camera"}, "shutter": {"shutter_speed", "camera"},
    "iso": {"iso", "camera"}, "exposure_compensation": {"exposure_compensation", "camera"},
    "shutter_type": {"shutter_type", "camera"}, "ibis": {"camera"},
    "camera_position": {"camera"}, "focal_length": {"lens", "focal_length_mm"},
    "focus": {"focus", "camera"},
}


def review_operations(
    operations: list[CandidateOperation], request: UserRequest,
    scene: SceneAnalysis | None = None, camera: CameraProfile | None = None,
    recommendation: CameraRecommendation | None = None,
) -> tuple[list[CandidateOperation], list[str]]:
    reviewed, notes = [], []
    for operation in operations:
        problem = None
        if operation.expected_effect not in CONTROL_EFFECTS.get(operation.control, set()):
            problem = "操作与预期效果没有受支持的物理规则"
        elif operation.target not in CONTROL_TARGETS.get(operation.control, set()):
            problem = "操作对象未匹配可审核的控制项"
        elif operation.control == "ibis" and (camera is None or camera.ibis_stops <= 0):
            problem = "没有核验到机身防抖能力"
        elif operation.control in {"aperture", "shutter", "iso"}:
            state = getattr(recommendation, "exposure_state", None)
            key = "shutter_speed" if operation.control == "shutter" else operation.control
            parameter = state.parameters.get(key) if state else None
            if parameter is None or parameter.role != "manual_setting":
                problem = "最终控制状态不是用户可直接设置的参数"
            elif operation.expected_effect == "recorded_brightness" and (
                state.mode != "M" or state.iso_control != "manual"
            ):
                problem = "自动曝光可能反向响应，不能审核为直接改变记录亮度的操作"
        elif operation.control == "exposure_compensation":
            state = getattr(recommendation, "exposure_state", None)
            parameter = state.parameters.get("exposure_compensation") if state else None
            if parameter is None or parameter.role in {"not_applicable", "unknown"}:
                problem = "最终曝光控制状态未确认补偿可以改变记录亮度"
        if not operation.preconditions:
            problem = problem or "缺少可核对的操作前提"
        for fact in operation.preconditions:
            if fact.source == "user":
                # A quote must occur in the original input; declaring source=user is insufficient.
                settings = request.model_dump()
                value = settings.get(fact.key)
                if fact.key == "intent":
                    valid = bool(fact.evidence.strip() and fact.evidence in request.intent)
                else:
                    valid = value is not None and str(value) == fact.evidence
                if not valid:
                    problem = problem or "用户依据不匹配原始输入"
            elif fact.source == "equipment":
                value = getattr(camera, fact.key, None) if camera else None
                if not camera or not camera.source_url or value is None or str(value) != fact.evidence:
                    problem = problem or "器材依据不匹配本地核验档案"
            else:
                # Neither an image-model claim nor an unknown premise establishes a fact.
                problem = problem or "照片模型观察或未知条件尚无独立事实核验"
        if operation.object_ids:
            problem = problem or "对象及实体对应关系尚未独立核验，仅可现场确认"
        if operation.control in {"camera_position", "focal_length"}:
            problem = problem or "现场几何与镜头范围尚需实拍确认"
        if problem:
            notes.append(f"候选操作 {operation.control}：{problem}；未计为已审核操作。")
        else:
            reviewed.append(operation)
    return reviewed, list(dict.fromkeys(notes))


def _paired_reflection(text: str) -> bool:
    positive = re.sub(r"(?:不要求|不需要|不把|不追求|不建立|避免|无需)[^，。;；]*", "", text)
    paired = bool(re.search(r"真实人物|真人|实体人物|现实人物|实际人物|直接人物|本人", positive)
                  and re.search(r"反射|倒影|镜像|映像", positive))
    conditional = bool(re.search(r"(?:若|如果|只有).{0,30}(?:现场确认|核验|确认).{0,30}(?:同一|配对|对应)", positive))
    return paired and not conditional


def _parameter_condition(text: str) -> bool:
    return bool(re.search(r"ISO|EV|f\s*/|快门|曝光|光圈|防抖|电子前帘|EFCS", text, re.IGNORECASE))


def _relative_moves(actions: list[str]) -> list[str]:
    """Compatibility wrapper; direction labels no longer collapse action kinds."""
    return render_actions(interpret_actions(actions))


def final_composition_review(
    advice: CompositionAdvice | None, recommendation: CameraRecommendation,
    request: UserRequest, scene: SceneAnalysis, camera: CameraProfile | object,
) -> CompositionAdvice | None:
    """Reconcile prose and trial conditions only after final parameter validation."""
    if advice is None or advice.status == "demo":
        return advice
    proposals, notes = [], list(advice.notes)
    for proposal in advice.proposals:
        text = " ".join([proposal.goal, *proposal.actions, *proposal.reasons])
        if _paired_reflection(text):
            # A semantic list of person/reflection is no correspondence measurement.
            notes.append("未核验真实人物与倒影的实体配对，已移除依赖该配对的方案。")
            continue
        source_actions = list(proposal.action_evidence or proposal.actions)
        trial_actions = interpret_actions(source_actions)
        checks = goal_field_checks(request.intent)
        updates = {"action_evidence": source_actions, "trial_actions": trial_actions,
                   "field_checks": checks}
        for field in ("tradeoffs", "conditions", "limitations", "reasons"):
            original = getattr(proposal, field)
            kept = [item for item in original if not _parameter_condition(item)]
            if len(kept) < len(original):
                notes.append("已用最终参数控制条件替换构图中的旧曝光、当前设置或防抖说明。")
            updates[field] = kept
        parameter_actions = [item for item in proposal.actions if _parameter_condition(item)]
        if parameter_actions and proposal.action_type != "camera_position":
            retained_actions = [item for item in proposal.actions if not _parameter_condition(item)]
            updates["actions"] = retained_actions + ["曝光控制操作按下方最终参数条件执行，并试拍检查直方图和清晰度。"]
            notes.append("构图动作中的曝光控制已同步为最终参数，旧数值与旧操作前提未保留。")
        if proposal.action_type == "camera_position":
            # Keep the relative move, not its unmeasured predicted result. Output goals
            # are intentions; no viewpoint change is certified from a single photo.
            actions = render_actions(trial_actions)
            if not actions:
                if re.search(r"检查|保留|取景|观察|比较", " ".join(source_actions)):
                    actions = ["在现场重新取景并检查用户指定主体和四边余量。"]
                    updates["action_type"] = "reshoot"
                    notes.append("方案没有明确机位移动，已按实际取景检查改为重拍类型。")
                else:
                    notes.append("机位方案没有可独立执行的相对取景动作，已移除。")
                    notes.append("模型动作原文待确认，未生成替代动作：" + "；".join(source_actions))
                    continue
            actions.append("比较调整前后的主体比例、背景、遮挡和四边余量；只有符合拍摄目标时才采用该机位。")
            updates["actions"] = actions
            updates["reasons"] = [
                "相机位置会改变取景与前后景的相对关系；具体背景、比例和反射变化需现场比较。"
            ]
            updates["tradeoffs"] = ["调整取景可能改变环境信息、主体比例或遮挡关系，需要与用户目标比较后取舍。"]
            updates["conditions"] = ["先确认现场有可安全调整的位置；相对移动方向只供试取景。"]
            updates["limitations"] = ["单张参考图没有测距、画外环境和移动后的视角证据，不能保证该机位改善画面或曝光。"]
            if re.search(r"高光|过曝|过亮", proposal.goal):
                updates["goal"] = "试取景并检查高光、主体与背景关系"
            notes.append("机位效果已改为现场比较条件，未把模型预测作为可见事实。")
        elif parameter_actions:
            # A nominal focal_length proposal that changes only aperture is not
            # a validated change of focal length. Make its effective action explicit.
            updates["action_type"] = "reshoot"
            updates["goal"] = "按拍摄目标试拍并检查景深、主体与背景关系"
            updates["reasons"] = ["曝光参数及控制角色以最终建议为准，景深、虚化与清晰度须在现场检查。"]
            updates["tradeoffs"] = ["改变曝光或光圈可能改变运动效果、景深与画质，需要试拍比较。"]
            updates["conditions"] = ["先确认最终拍摄模式及用户可设置的控制项。"]
            updates["limitations"] = ["不能凭参考照片保证多层景物同时清晰或背景分离程度。"]
        elif proposal.action_type == "crop":
            updates["actions"] = ["预览建议裁切框，检查所有主体的当前可见部位、遮挡、四边余量与用户保护要求；确认后再采用。"]
            updates["conditions"] = ["裁切只涉及原图当前可见内容；是否本来完整与环境关系是否满足仍需核对。"]
            updates["reasons"] = ["已按关联候选框检查裁切几何；框与可见范围不能证明遮挡的身体或细部完整。"]
            updates["tradeoffs"] = ["裁切可能减少环境信息，不能恢复画外或被遮挡内容。"]
        if not updates["reasons"]:
            updates["reasons"] = ["该构图方案需结合用户目标现场比较，原参数相关解释未保留。"]
        if not updates["tradeoffs"]:
            updates["tradeoffs"] = ["取景改变可能减少环境信息，需要与主体表现权衡。"]
        if checks:
            # These are program trials, never statements that the depicted
            # scene already passed a focus, lighting, or framing measurement.
            updates["actions"] = [*updates.get("actions", proposal.actions),
                                  *(check.observe for check in checks)]
            updates["conditions"].extend("采用判据：" + check.accept_when for check in checks)
            updates["conditions"].extend("保护内容：" + check.protect for check in checks)
        scope = resolve_photography_scope(request.intent, scene.objects, scene.main_subject_ids)
        if scope["protection_instructions"]:
            updates["conditions"].append("按用户原文检查保护内容：" + "；".join(scope["protection_instructions"]))
        updates["conditions"].append("取景目标以用户原始请求为准：" + request.intent)
        if any(goal["goal"] == "freeze_motion" for goal in scope["imaging_goals"]):
            updates["conditions"].append("凝固动作依赖实际快门与主体运动，机位或裁切不能代替曝光时间控制；按最终快门试拍检查。")
        if re.search(r"真实人物|真人|实体人物|直接人物", text) and re.search(r"反射|倒影|镜像", text):
            updates["conditions"].append("真实人物与倒影的对应关系尚未核验；仅在现场独立确认后才尝试配对构图。")
        state = getattr(recommendation, "exposure_state", None)
        if state is not None:
            labels = {"aperture": "光圈", "shutter_speed": "快门", "iso": "ISO", "exposure_compensation": "曝光补偿"}
            natures = {"manual_setting": "用户设置", "auto_target": "自动控制目标", "observed": "观测值", "unknown": "控制未确认", "not_applicable": "不适用"}
            controls = "；".join(
                f"{labels.get(name, name)}={parameter.value}（{natures.get(parameter.role, parameter.role)}）"
                for name, parameter in state.parameters.items()
            )
            updates["conditions"].append("本方案曝光条件以最终参数为准：" + controls)
        elif recommendation.shooting_mode == "未生成":
            updates["conditions"].append("参数阶段未完成；构图不能据此假定快门、ISO或曝光已满足。")
        else:
            updates["conditions"].append("曝光按最终建议试拍，现场照度与主体运动仍需检查。")
        if request.handheld and not request.tripod:
            updates["conditions"].append("手持试拍后放大检查抖动与主体运动模糊；经验快门不是清晰保证。")
        updates["limitations"] = updates["limitations"] or ["效果未实拍验证。"]
        reviewed, operation_notes = review_operations(
            proposal.candidate_operations, request, scene,
            camera if isinstance(camera, CameraProfile) else None, recommendation,
        )
        updates["reviewed_operations"] = reviewed
        notes.extend(operation_notes)
        proposals.append(proposal.model_copy(update=updates))
    observations = []
    for item in advice.observations:
        if _parameter_condition(item) or re.search(r"当前使用|器材|焦段|手持|三脚架", item):
            continue
        if re.search(r"眼镜|镜片", request.intent) and re.search(r"反光.*(?:影响|遮|挡).*眼|眼.*(?:被|受).*反光", item):
            observations.append("模型观察到镜片反光；反光与眼睛实际位置及表现的关系需对照原图核对。")
        elif re.search(r"争球|篮球|队员", request.intent) and re.search(r"(?:队员|球员).{0,12}(?:截断|裁断)", item):
            observations.append("模型提出人物边界风险；须核对争球者、附近队员与背景观众，不能凭该描述确认谁被截断。")
        elif re.search(r"完整|无截断|没有截断|未被裁切|没有裁切", item):
            observations.append("模型识别到主体；是否完整、可见部位、遮挡与画面边缘尚需核对原图。")
        else:
            observations.append(item)
    if len(observations) < len(advice.observations):
        notes.append("已移除画面观察中的参数、器材或当前曝光推断；用户输入与参考图观测不能互相替代。")
    return advice.model_copy(update={
        "proposals": proposals, "status": advice.status if proposals else "unavailable",
        "observations": observations, "notes": list(dict.fromkeys(notes)),
    })
