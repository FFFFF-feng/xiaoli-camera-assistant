"""Derive exposure controls and rebuild explanations from reviewed settings.

This is a control model, not a verifier of arbitrary photography prose. Model
parameter explanations are routed here by topic and replaced with controlled
rules; unclassified scene assertions still need the independent evidence review.
"""
from __future__ import annotations

import re
import unicodedata

from camera_assistant.models import (
    CameraProfile,
    CameraRecommendation,
    ExifInfo,
    ExposureMode,
    ExposureParameter,
    ExposureState,
    ISOControl,
    SceneAnalysis,
    UserRequest,
)
from camera_assistant.services.camera_knowledge import verified_exposure_capability


def normalize_mode(value: str) -> ExposureMode:
    normalized = unicodedata.normalize("NFKC", value).strip()
    found: set[str] = set()
    aliases = {
        "M": r"(?<![A-Za-z])M(?![A-Za-z])|手动(?:曝光|模式|档)",
        "Av": r"(?<![A-Za-z])(?:Av|A)(?![A-Za-z])|光圈优先",
        "Tv": r"(?<![A-Za-z])(?:Tv|S)(?![A-Za-z])|快门优先",
        "P": r"(?<![A-Za-z])P(?![A-Za-z])|程序(?:自动|曝光)",
    }
    for mode, pattern in aliases.items():
        if re.search(pattern, normalized, re.IGNORECASE):
            found.add(mode)
    return next(iter(found)) if len(found) == 1 else "unknown"  # type: ignore[return-value]


def classify_iso(value: str) -> ISOControl:
    normalized = unicodedata.normalize("NFKC", value).strip()
    manual_control = re.fullmatch(r"(?:手动|固定)控制\s*\((?P<value>[^()]+)\)", normalized)
    if manual_control:
        # A full, unambiguous control wrapper is compatible with numeric ISO;
        # mixed alternatives still fail the same whole-field grammar below.
        normalized = manual_control.group("value").strip()
    auto_label = r"(?:auto\s*iso|iso\s*auto|auto|自动(?:\s*iso|感光度)?|iso\s*自动)"
    auto = re.fullmatch(auto_label + r"(?P<limits>.*)", normalized, re.IGNORECASE)
    if auto:
        # Parse the whole field. An Auto prefix cannot establish a coherent
        # control state when the rest says fixed/manual ISO or another operation.
        limits = auto.group("limits").strip(" \t:：,，")
        if not limits:
            return "auto"
        if (limits.startswith("（") and limits.endswith("）")) or (
            limits.startswith("(") and limits.endswith(")")
        ):
            limits = limits[1:-1].strip()
        integer = r"(?:ISO\s*)?\d+"
        range_value = rf"{integer}(?:\s*[-–—~～至到]\s*{integer})?"
        boundary = r"(?:上限(?:固定)?|下限|最高|最低|最大(?:感光度|ISO)?|不高于|max|min|up\s+to)"
        accepted = (
            rf"(?:范围(?:为)?|限制在)?\s*{range_value}"
            rf"|{boundary}\s*[:：]?\s*{integer}"
            rf"(?:\s*[,，、;；]\s*{boundary}\s*[:：]?\s*{integer})?"
        )
        if not re.fullmatch(accepted, limits, re.IGNORECASE):
            return "unknown"
        numbers = [int(number) for number in re.findall(r"\d+", limits)]
        if any(number <= 0 for number in numbers):
            return "unknown"
        if re.fullmatch(rf"(?:范围(?:为)?|限制在)?\s*{range_value}", limits, re.IGNORECASE):
            if len(numbers) == 2 and numbers[0] > numbers[1]:
                return "unknown"
        else:
            boundaries: dict[str, int] = {}
            for label, number in re.findall(
                rf"({boundary})\s*[:：]?\s*(?:ISO\s*)?(\d+)", limits, re.IGNORECASE,
            ):
                key = "min" if re.fullmatch(r"下限|最低|min", label, re.IGNORECASE) else "max"
                if key in boundaries:
                    return "unknown"
                boundaries[key] = int(number)
            if boundaries.get("min", 0) > boundaries.get("max", float("inf")):
                return "unknown"
        return "auto"
    manual = (
        r"(?:固定|手动|fixed|manual)?\s*(?:iso\s*)?\d+"
        r"(?:\s*[-–—~～至到]\s*(?:iso\s*)?\d+)?"
        r"\s*(?:[（(](?:固定|手动|手动设置)[）)])?"
    )
    if not re.fullmatch(manual, normalized, re.IGNORECASE):
        return "unknown"
    numbers = [int(number) for number in re.findall(r"\d+", normalized)]
    if any(number <= 0 for number in numbers) or (len(numbers) == 2 and numbers[0] > numbers[1]):
        return "unknown"
    return "manual"


def build_exposure_state(
    recommendation: CameraRecommendation,
    request: UserRequest,
    camera: CameraProfile | None = None,
    reference_exif: ExifInfo | None = None,
) -> ExposureState:
    mode = normalize_mode(recommendation.shooting_mode)
    iso_control = classify_iso(recommendation.iso)
    roles = {"aperture": "unknown", "shutter_speed": "unknown"}
    if mode == "M":
        roles = {"aperture": "manual_setting", "shutter_speed": "manual_setting"}
    elif mode == "Av":
        roles = {"aperture": "manual_setting", "shutter_speed": "auto_target"}
    elif mode == "Tv":
        roles = {"aperture": "auto_target", "shutter_speed": "manual_setting"}
    elif mode == "P":
        roles = {"aperture": "auto_target", "shutter_speed": "auto_target"}
    roles["iso"] = {
        "manual": "manual_setting", "auto": "auto_target", "unknown": "unknown",
    }[iso_control]
    roles["exposure_compensation"] = "unknown"
    capability = verified_exposure_capability(camera)
    support = capability.get("m_auto_iso_compensation", "unknown")
    if (mode in {"Av", "Tv", "P"} and iso_control != "unknown") or (mode == "M" and iso_control == "auto"
                                               and support == "supported"):
        roles["exposure_compensation"] = "manual_setting"
    elif mode == "M" and iso_control == "manual":
        roles["exposure_compensation"] = "not_applicable"
    parameters = {
        key: ExposureParameter(value=getattr(recommendation, key), role=role)
        for key, role in roles.items()
    }
    observations: dict[str, ExposureParameter] = {}
    if reference_exif is not None:
        for key, exif_key in (("aperture", "aperture"), ("shutter_speed", "exposure_time"),
                              ("iso", "iso"), ("exposure_compensation", "exposure_compensation")):
            value = getattr(reference_exif, exif_key)
            if value is not None:
                observations[key] = ExposureParameter(
                    value=str(value), role="observed", source="reference_exif",
                )
    return ExposureState(
        mode=mode, iso_control=iso_control, parameters=parameters,
        current_settings=request.current_settings,
        reference_observations=observations, lens_max_aperture=request.max_aperture,
        m_auto_iso_compensation=support,
        capability_source_url=str(capability.get("m_auto_iso_compensation_source", "")),
        capability_conditions=list(capability.get("m_auto_iso_compensation_conditions", [])),
    )


_CONTROL_TOPICS = {
    "shooting_mode": r"(?:^|\W)(?:M|Av|Tv|A|S|P)(?:档|模式|\W|$)|手动模式|光圈优先|快门优先|测光|曝光",
    "aperture": r"光圈|景深|虚化|背景分离|f\s*/",
    "shutter_speed": r"快门|曝光时间|慢门|长曝光|手持|防抖|运动模糊|凝固|冻结|拉丝|拖影|秒|\d\s*/\s*\d",
    "iso": r"iso|感光度|噪点|进光|亮度",
    "exposure_compensation": r"曝光补偿|正.{0,4}补偿|负.{0,4}补偿|(?<![A-Za-z])EV(?![A-Za-z])",
}
_SCENE_ACTION = re.compile(
    r"机位|角度|视角|视点|靠近|接近|后退|退后|前移|后移|左移|右移|平移|蹲下|俯拍|仰拍"
    r"|低(?:角度|机位)|高(?:角度|机位)|倒影|反射|配对|主体比例|(?:眼睛|双眼|眼部).{0,6}(?:比例|占比|放大|更大)"
    r"|相机(?:高度|位置|放|摆|抬)|(?:向|往)(?:左|右|前|后|上|下)",
    re.IGNORECASE,
)
_FOCUS_ACTION = re.compile(r"对焦|合焦|锁焦|焦点|对焦点|AF[- ]?[SC]|MF|focus", re.IGNORECASE)
_WB_ACTION = re.compile(r"白平衡|色温|偏色|偏黄|偏蓝|white\s*balance", re.IGNORECASE)
_DRIVE_ACTION = re.compile(r"连拍|单拍|单张|驱动|drive|定时拍摄|延时拍摄", re.IGNORECASE)


def _depends_on(text: str, parameters: set[str]) -> bool:
    return any(re.search(_CONTROL_TOPICS[key], text, re.IGNORECASE)
               for key in parameters if key in _CONTROL_TOPICS)


def _basic_reasons(recommendation: CameraRecommendation, state: ExposureState,
                   request: UserRequest) -> list[str]:
    mode = state.mode
    controls = {
        "M": "M 档由你设置光圈和快门；ISO 是否自动，取决于单独的 ISO 设置。",
        "Av": "Av/A 档由你设置光圈，相机按测光自动决定快门；快门建议是观察目标，不能同时直接固定。",
        "Tv": "Tv/S 档由你设置快门，相机按测光自动决定光圈；光圈建议是观察目标，不能同时直接固定。",
        "P": "P 档由相机按测光决定光圈与快门；建议值是观察目标，程序偏移能力以机身界面为准。",
        "unknown": "拍摄模式未明确，暂不能确定哪些参数可直接设置；先在相机界面确认模式。",
    }
    reasons = [controls[mode]]
    if state.iso_control == "manual":
        if mode == "M":
            reasons.append(f"ISO {recommendation.iso} 是手动建议值；在光圈和快门不变时，调整 ISO 可改变记录亮度，不能改变镜头进光量。")
        elif mode in {"Av", "Tv", "P"}:
            reasons.append(f"ISO {recommendation.iso} 是手动建议值；相机通常会通过自动快门或光圈响应 ISO 变化以维持测光目标，不能把 ISO 当作独立调亮暗操作。")
        else:
            reasons.append(f"ISO {recommendation.iso} 给出了手动候选值；模式未确认时，不能确定相机是否自动抵消 ISO 变化，应先核对控制状态。")
    elif state.iso_control == "auto":
        reasons.append(f"{recommendation.iso} 由相机自动决定实际 ISO；若给出范围或上限，它们是控制目标，需观察是否触及边界。")
    else:
        reasons.append("建议未明确 ISO 是自动还是手动；先核对 ISO 控制状态，再调整曝光。")
    # Render numeric targets only. Free-text notes inside a settings field must
    # not become program-authored guarantees when echoed in the explanation.
    apertures = re.findall(r"f\s*/\s*(\d+(?:\.\d+)?)", recommendation.aperture, re.IGNORECASE)
    aperture_target = " 至 ".join(f"f/{value}" for value in apertures) or "数值未确认"
    shutter_value = re.split(r"[（(]", recommendation.shutter_speed, maxsplit=1)[0]
    if "无法校验" in shutter_value:
        shutter_value = "数值未确认"
    reasons.extend([
        f"光圈建议 {aperture_target}；景深还取决于焦距和对焦距离，不能保证不同距离的内容同时清晰。",
        f"快门建议 {shutter_value}；需试拍检查主体运动和相机抖动，安全快门经验不能保证清晰。",
        "光圈、焦距和对焦距离不变时，提高 ISO 或加快快门不会直接减小光学景深。",
    ])
    if request.max_aperture is not None:
        reasons.append(f"用户填写的最大光圈 f/{request.max_aperture:g} 是镜头能力边界，不能据此知道当前光圈。")
    if mode == "M" and state.iso_control == "manual":
        reasons.append("M 档加固定 ISO 时，曝光补偿不能直接改变实际曝光；亮暗需要通过快门、光圈或 ISO 调整。")
    elif mode == "M" and state.iso_control == "auto":
        if state.m_auto_iso_compensation == "supported":
            reasons.append("已核验本机 M 档支持 Auto ISO 曝光补偿：在非闪光拍摄中补偿通过自动 ISO 改变记录亮度；仍需检查 ISO 响应与范围边界。")
        else:
            reasons.append("尚未核验本机 M 档加 Auto ISO 是否支持曝光补偿，不能把补偿作为有效调亮暗操作。")
    elif mode in {"Av", "Tv", "P"}:
        reasons.append("曝光补偿调整自动曝光目标；实际由相机自动参数响应，达到光圈、快门或 ISO 边界时仍可能无法实现目标。")
    reasons.extend([
        "对焦需以机身实际合焦与放大检查为准；静止主体可用本机支持的单次或手动对焦，移动主体可尝试连续对焦，任何模式都不能保证一次清晰。",
        "测光提供曝光参考；M 档固定 ISO 时需由你调整实际参数，高动态范围场景不能仅凭测光保证高光与暗部都保留细节。",
        "单拍或连拍按本机支持的驱动方式与捕捉时机选择；连拍不能代替合适的对焦和曝光时间，也不能保证每张清晰。",
        "自动白平衡可作为试拍起点；出现偏色时按现场光源比较色温或自定义白平衡，白平衡不能代替曝光检查。",
    ])
    return reasons


def _review_workflow_adjustments(texts: list[str]) -> list[str]:
    """Keep unclassified workflow only; rebuild scene/focus/color operations.

    The routing recognizes an operation domain, not whether its arbitrary
    explanation is true. Relative viewpoint effects and focus success therefore
    remain trial conditions even when the original prose sounded plausible.
    """
    reviewed = []
    for text in texts:
        if _SCENE_ACTION.search(text):
            reviewed.append(
                "在安全可行且不惊扰主体时，试取景比较相对机位或角度；检查主体比例、背景、遮挡和四边余量，只有符合用户保护要求时才采用。不能由单张参考图保证眼睛比例或背景变化。"
            )
        elif _FOCUS_ACTION.search(text):
            reviewed.append("若主体对焦不实，请核对对焦点与实际合焦；如眼睛可见，可放大检查眼睛。移动主体需按本机支持的连续对焦方式试拍，不能保证清晰。")
        elif _WB_ACTION.search(text):
            reviewed.append("若试拍偏黄、偏蓝或有明显偏色，按现场光源比较自动与可用白平衡设置，再检查颜色；不能由参考图保证色温设置正确。")
        elif _DRIVE_ACTION.search(text):
            reviewed.append("按本机可用的单拍、连拍或定时方式试拍，检查捕捉时机、运动模糊与合焦；稳定支撑和连拍都不保证主体清晰。")
        else:
            reviewed.append(text)
    return reviewed


def reconcile_exposure_advice(
    recommendation: CameraRecommendation,
    request: UserRequest,
    scene: SceneAnalysis,
    camera: CameraProfile | None = None,
    changed_parameters: set[str] | None = None,
    reference_exif: ExifInfo | None = None,
) -> CameraRecommendation:
    """Called after final numerical validation, before the final evidence review.

    Correct mode/ISO controls deterministically and rebuild all basic parameter
    explanations. This does not treat candidate JSON or its evidence as proof.
    """
    changed = set(changed_parameters or ())
    state = build_exposure_state(recommendation, request, camera, reference_exif)
    updates: dict[str, object] = {}
    notes = list(recommendation.validation_notes)
    no_ev_control = False
    if state.mode == "M" and state.iso_control == "manual":
        updates["exposure_compensation"] = "不适用（M 档＋固定 ISO）；请调整快门、光圈或 ISO"
        no_ev_control = True
        notes.append("已按 M 档与固定 ISO 联合审核，曝光补偿不作为实际曝光控制。")
    elif state.mode == "M" and state.iso_control == "auto" and state.m_auto_iso_compensation != "supported":
        updates["exposure_compensation"] = "未核验本机 M＋Auto ISO 补偿能力；不作为调亮暗操作"
        no_ev_control = True
        notes.append("M＋Auto ISO 补偿能力未知，未按品牌或其他机型推定支持。")
    elif state.mode == "unknown" or state.iso_control == "unknown":
        updates["exposure_compensation"] = "先确认拍摄模式与 ISO 控制状态；暂不提供补偿操作"
        no_ev_control = True
        notes.append("模式或 ISO 控制状态不明确，曝光控制需确认后使用。")
    if updates.get("exposure_compensation") != recommendation.exposure_compensation and "exposure_compensation" in updates:
        changed.add("exposure_compensation")
    updated = recommendation.model_copy(update=updates)
    # Broad topic routing, not a blacklist of known wrong phrases: the basic
    # exposure rationale is generated from the final controls every time.
    all_controls = set(_CONTROL_TOPICS)
    reasons = _basic_reasons(updated, state, request)
    # Arbitrary parameter-dependent prose is not proven by a valid candidate or
    # by unchanged numbers. Regenerate those topics from controls even when no
    # numeric repair was needed; preserve separately-reviewed focus, WB, scene
    # and capture workflow guidance. Valid exposure actions recur in the safe
    # equivalent steps below rather than being treated as errors.
    risks = [text for text in updated.risks if not _depends_on(text, all_controls)]
    adjustments = _review_workflow_adjustments([
        text for text in updated.adjustments if not _depends_on(text, all_controls)
    ])
    if changed:
        notes.append("参数或控制角色修正后，已重建基础曝光理由，并移除依赖旧参数的风险与备用步骤。")
    notes.append("基础曝光因果与操作步骤由最终控制状态重新生成；未把自由文本或候选依据当作事实证明。")
    if no_ev_control:
        # Compensation instructions may omit numbers or the final EV value.
        adjustments = [text for text in adjustments if not _depends_on(text, {"exposure_compensation"})]
    if state.mode == "M" and state.iso_control == "manual":
        adjustments.extend([
            "先试拍并查看直方图与高光警告；若过亮，缩短曝光时间，并重新检查运动效果。",
            "若过亮，也可收小光圈，但景深与成像效果可能改变；需现场比较。",
            "若过亮，可降低 ISO，但不低于机身已知标准下限；ISO 不改变镜头进光量或光学景深。",
            "若过暗且需要保留建议光圈与快门，优先提高 ISO 并检查噪点。",
            "若过暗、主体静止且有稳定支撑，可延长曝光，并检查运动模糊。",
            "若过暗，也可开大光圈；先检查镜头能力与所需景深。",
        ])
        if "long_exposure" in scene.desired_effects or "long_exposure" in scene.scene_type:
            adjustments.append("若必须保留慢门水流效果而高光过曝，需现场评估 ND 减光镜或等待更暗光线；先缩短曝光是改变水流效果的备用办法。")
    elif state.mode == "Av":
        adjustments.append(f"先设置建议光圈，半按快门观察实际快门是否达到目标 {updated.shutter_speed}；若达不到目标，先检查 Auto ISO 是否触及上限或固定 ISO 是否可提高，再试拍并检查高光、噪点和模糊；不能在 Av 档直接固定快门，也不能保证相机会达到目标。")
    elif state.mode == "Tv":
        adjustments.append(f"先设置建议快门，半按快门观察实际光圈是否达到目标 {updated.aperture}；若光圈已达镜头上限且仍欠曝，检查 ISO 控制方式与上限后调整可控参数，再试拍；自动目标不等于实际读数。")
    elif state.mode == "P":
        adjustments.append("检查相机实际选择的光圈与快门；需固定其中一个参数时改用相应优先模式，并重新检查曝光。")
    elif state.mode == "M" and state.iso_control == "auto" and state.m_auto_iso_compensation == "supported":
        adjustments.append("确认正在使用 Auto ISO 且不使用闪光灯，再按试拍高光与主体亮度调整曝光补偿；观察实际 ISO 是否响应，达到上下限时调整光圈或快门。")
    else:
        adjustments.append("先确认模式、ISO 控制状态与当前机型能力；确认后按测光、直方图和试拍结果调整可控参数。")
    if state.mode in {"Av", "Tv", "P"} and state.iso_control != "unknown":
        adjustments.append("若试拍主体偏暗，可增加曝光补偿；若高光过曝，可减少曝光补偿。每次调整后检查相机自动参数是否响应及是否越界，再检查高光与暗部。")
    risks.append("参考图亮度不能确定现场绝对照度；这些值是试拍起点，需要检查实际曝光与主体清晰度。")
    risks.append("光圈变大可能减小景深；所需清晰范围需在最终设置下放大检查。")
    risks.append("ISO 提高可能增加噪点；具体程度需在最终设置下检查。")
    if request.handheld and not request.tripod:
        risks.append("若实际快门较慢，手持容易模糊；请缩短曝光或使用三脚架、稳定支撑。")
    if scene.subject_motion in {"slow", "fast"}:
        risks.append("稳定支撑不能消除主体运动模糊；冻结动作需检查实际快门并试拍。")
    if "long_exposure" in scene.desired_effects or "long_exposure" in scene.scene_type:
        risks.append("慢门水流效果需要稳定机位；若有水面倒影，水面运动仍可能使倒影模糊。白天无 ND 时可能无法同时保留慢门并避免高光过曝。")
    if state.mode in {"Av", "Tv", "P"}:
        risks.append("相机自动参数可能达不到建议目标；请检查机身读数与越界警告。")
    if changed.intersection({"aperture", "shutter_speed", "iso"}):
        risks.append("原模型的相关参数条件已失效；必须用修正后的设置重新检查景深、运动效果、亮度与噪点。")
    final = updated.model_copy(update={
        "reasons": list(dict.fromkeys(reasons)), "risks": list(dict.fromkeys(risks)),
        "adjustments": list(dict.fromkeys(adjustments)),
        "validation_notes": list(dict.fromkeys(notes)),
    })
    return final.model_copy(update={
        "exposure_state": build_exposure_state(final, request, camera, reference_exif),
    })
