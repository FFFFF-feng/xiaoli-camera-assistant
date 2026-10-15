"""Assess omitted recommendations separately from unmeasured on-site facts."""
import re

from pydantic import ValidationError

from camera_assistant.models import CameraProfile, CameraRecommendation, PhoneProfile, UserRequest
from camera_assistant.recovery_models import ParameterRecovery
from camera_assistant.services.cloud import ModelFormatError, ModelServiceError


def assess_parameters(recommendation: CameraRecommendation, request: UserRequest,
                      camera: CameraProfile | PhoneProfile,
                      candidate: CameraRecommendation | None = None) -> ParameterRecovery:
    if isinstance(camera, PhoneProfile):
        # Phone controls deliberately use directional guidance, not fabricated numbers.
        return ParameterRecovery(status="complete")
    state = recommendation.exposure_state
    missing = []
    if state is None or state.mode == "unknown":
        missing.append("shooting_mode")
    if state is None or state.iso_control == "unknown":
        missing.append("iso")
    for name in ("aperture", "shutter_speed"):
        if state is None or state.parameters[name].role == "unknown":
            missing.append(name)
    for name in ("focus_mode", "drive_mode", "white_balance"):
        if getattr(recommendation, name).strip() in {"", "未生成", "未知", "不确定"}:
            missing.append(name)
    if state is not None and (state.mode in {"Av", "Tv", "P"} and state.iso_control != "unknown" or
                             state.mode == "M" and state.iso_control == "auto" and
                             state.m_auto_iso_compensation == "supported") and not compensation_is_numeric(recommendation.exposure_compensation):
        missing.append("exposure_compensation")
    fact_parameters = []
    if "aperture" in missing and request.max_aperture is None and candidate is not None and re.search(
        r"镜头.{0,10}(?:能力|可用|最大)|(?:能力|可用|最大).{0,5}光圈", candidate.aperture,
    ):
        fact_parameters.append("aperture")
    confirmations = []
    if state is not None and state.mode == "M" and state.iso_control == "auto" and (
        state.m_auto_iso_compensation == "unknown"
    ):
        confirmations.append("请核对实际机型是否支持 M 档 Auto ISO 曝光补偿及其适用条件；模型不能补出器材能力。")
    # These facts are always conditional, never grounds for a new model request.
    if request.max_aperture is None:
        confirmations.append("请确认当前镜头在所用焦距下的最大光圈；建议光圈须在镜头可用范围内。")
    issues = [f"{name}：模型建议缺失、控制方式不明确或未通过数值校验。"
              for name in missing if name not in fact_parameters]
    issues.extend(f"{name}：缺少用户提供的实际器材能力，不得补猜；保留待确认。"
                  for name in fact_parameters)
    if missing:
        confirmations.append("模型仍未形成完整方案；请确认缺失项对应的推荐模式、ISO 控制方式及机身实际显示的光圈/快门，再按测光与试拍核对。")
    if "shutter_speed" in missing:
        if state is not None and state.mode in {"Av", "P"}:
            confirmations.append(
                "快门缺少可校验目标：先补充明确的曝光时间目标或区间及秒单位；"
                "再设置已确认的光圈与 ISO，半按快门查看机身实际快门，并与目标比较。"
                "若未达目标，先核对 Auto ISO 是否触及上限或固定 ISO 是否可提高；"
                "仍无法满足时评估稳定支撑或改用能直接设置快门的模式，重新测光试拍并检查模糊、噪点与高光。"
                "不要把自动快门当成可直接固定的设置，也不要从参考图猜现场照度。"
            )
        else:
            confirmations.append(
                "快门缺少有效数值：先补充带秒单位的曝光时间目标并确认当前模式允许直接设置；"
                "设置后半按快门查看实际快门与测光，试拍检查模糊和高光，确认前不执行依赖快门值的操作。"
            )
    return ParameterRecovery(status="incomplete" if set(missing) - set(fact_parameters) else (
        "needs_confirmation" if confirmations else "complete"),
        missing_parameters=missing, fact_parameters=fact_parameters,
        issues=issues, user_confirmations=confirmations)


def compensation_is_numeric(value: str) -> bool:
    signed = r"[+-]?\d+(?:\.\d+)?"
    return bool(re.fullmatch(
        rf"\s*{signed}\s*(?:EV)?\s*(?:[-–—~～至到]\s*{signed}\s*(?:EV)?)?\s*",
        value, re.IGNORECASE,
    ))


def compensation_within_capability(value: str, camera: CameraProfile | None) -> bool:
    from camera_assistant.services.camera_knowledge import verified_exposure_capability

    if not compensation_is_numeric(value):
        return False
    capability = verified_exposure_capability(camera)
    lower = capability.get("exposure_compensation_min")
    upper = capability.get("exposure_compensation_max")
    if lower is None or upper is None:
        return True  # numeric only; actual unverified limits must remain a user condition
    return all(float(lower) <= float(number) <= float(upper)
               for number in re.findall(r"[+-]?\d+(?:\.\d+)?", value))


def recoverable_error(error: Exception) -> bool:
    return not isinstance(error, ModelServiceError) or isinstance(error, ModelFormatError)


def error_feedback(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return "；".join(f"{'.'.join(str(x) for x in item['loc'])}：{item['type']}"
                        for item in error.errors(include_input=False, include_url=False))
    if isinstance(error, ModelServiceError):
        return str(error)
    return "参数结构未通过解析或审核；请完整填写所有推荐字段并保持控制关系一致。"
