"""保守的原生手机相机指导；不虚构手动数值范围。"""

from __future__ import annotations

from camera_assistant.models import CameraRecommendation, PhoneProfile, SceneAnalysis, UserRequest
from camera_assistant.services.phone_knowledge import PHONE_MODE_NAMES


def safe_phone_settings(
    request: UserRequest, phone: PhoneProfile
) -> tuple[dict[str, str], list[str]]:
    mode = request.phone_capture_mode
    notes = [
        f"{phone.display_name}：能力未收录，只提供通用照片模式指导，需核对实际界面。"
        if phone.profile_id == "generic_phone"
        else f"已匹配 {phone.display_name}；以当前原生相机、系统与镜头界面为准。"
    ]
    if mode not in phone.modes:
        mode = "auto"
        notes.append("所选模式未在该型号资料中确认，已按照片模式提供保守操作。")
    lens = next((item for item in phone.lenses if item.lens_id == request.phone_lens_id), None)
    if lens is None:
        lens = next(item for item in phone.lenses if item.lens_id == "main")
        notes.append("所选镜头未收录，已按主摄说明；拍摄前请确认选中的摄像头。")
    if mode not in lens.modes:
        mode = "auto"
        notes.append("该镜头与所选模式的组合未录入，按照片模式指导；并非断言硬件不支持。")
    aperture = "镜头光圈未确认；不建议调节物理光圈"
    if lens.aperture is not None and lens.aperture_control == "fixed":
        aperture = f"{lens.name} f/{lens.aperture:g}（固定，不可手动调节）"
    elif lens.aperture_control == "variable":
        aperture = (
            f"{lens.name} f/{lens.aperture:g}–f/{lens.aperture_max:g}（可变；实际控制以当前镜头界面为准）"
            if lens.aperture is not None and lens.aperture_max is not None
            else "物理光圈范围尚未确认；按当前镜头界面核对"
        )
    if mode == "portrait":
        aperture += "；景深滑块为人像虚化控制"
    values = {
        "shooting_mode": f"{phone.native_app} · {PHONE_MODE_NAMES[mode]}",
        "aperture": aperture,
        "shutter_speed": "自动；不在当前模式直接指定快门",
        "iso": "自动；不在当前模式直接指定 ISO",
        "exposure_compensation": "观察高光与主体，使用当前界面的曝光调节控件",
        "focus_mode": "点按主体对焦；锁定功能以当前界面为准",
        "metering_mode": "由原生相机自动处理，不套用相机品牌测光菜单",
        "drive_mode": "先单张试拍；连拍与定时入口以当前界面为准",
        "white_balance": "自动白平衡",
    }
    if mode == "night":
        values["shutter_speed"] = "由夜间模式决定；屏幕时长不等同于单帧快门"
    if mode == "pro":
        if request.phone_pro_controls_confirmed:
            if "shutter" in phone.pro_controls:
                values["shutter_speed"] = "在 S / SPEED 调整曝光时间；范围未核验，不指定数值"
            if "iso" in phone.pro_controls:
                values["iso"] = "优先自动；手动 ISO 范围未核验，按预览亮度试调"
            if "focus" in phone.pro_controls:
                values["focus_mode"] = "先自动合焦，必要时用 F 细调并检查主体细节"
            if "white_balance" in phone.pro_controls:
                values["white_balance"] = "先自动；偏色明显时在 WB 中试调"
            notes.append("用户已确认当前镜头的专业控制项；仍未核验曝光数值上下限。")
        else:
            notes.append("专业控制项尚未由用户确认，不输出手动 ISO 或快门数值。")
    return values, notes


class DemoPhoneRecommendationAdvisor:
    def recommend(
        self, request: UserRequest, scene: SceneAnalysis, phone: PhoneProfile
    ) -> CameraRecommendation:
        values, notes = safe_phone_settings(request, phone)
        reasons = ["先保证主体对焦、画面稳定，再观察曝光预览；手机计算摄影不等同于相机手动曝光。"]
        risks = ["型号目录仅为官方资料核对，不是真机实拍验证；系统、地区和镜头会影响可用功能。"]
        adjustments = ["试拍后检查主体是否清晰，以及高光是否丢失；再调整取景、曝光或现场光线。"]
        if scene.subject_motion == "fast":
            reasons.append("运动主体优先寻找更亮环境、跟随主体并在合适瞬间拍摄。")
            risks.append("不要用长时间夜间合成保证冻结运动；当前没有已核验的手机快门上下限。")
            if request.phone_capture_mode == "pro" and request.phone_pro_controls_confirmed:
                adjustments.append(
                    "若 S 控件可用，逐步缩短曝光直到运动模糊减轻，同时观察噪声和亮度。"
                )
        if scene.brightness == "low":
            reasons.append("弱光先稳定手机；只有主体基本静止且本机支持时才尝试夜间模式。")
            risks.append("夜间模式拍摄期间保持稳定；主体移动仍可能产生拖影。")
        if request.phone_capture_mode == "portrait":
            reasons.append("人像虚化需要检查发丝、眼镜和轮廓边缘；不要把景深控制当作物理光圈。")
            adjustments.append("虚化边缘错误时减弱人像虚化，或改用普通照片模式。")
        return CameraRecommendation(
            **values,
            reasons=reasons,
            risks=risks,
            adjustments=adjustments,
            confidence=min(scene.confidence, 0.65),
            validation_notes=notes,
        )


class PhoneRecommendationValidator:
    def validate(
        self,
        recommendation: CameraRecommendation,
        request: UserRequest,
        scene: SceneAnalysis,
        phone: PhoneProfile,
    ) -> CameraRecommendation:
        # 对云端输出也强制应用能力边界，不能把相机设置或未经核验的手机极限放进控制字段。
        values, notes = safe_phone_settings(request, phone)
        baseline = DemoPhoneRecommendationAdvisor().recommend(request, scene, phone)
        changed = any(getattr(recommendation, key) != value for key, value in values.items())
        if changed:
            notes.append("已按手机原生模式覆盖不适用或未经核验的参数与菜单。")
        # 手机分支暂未实现逐句生成文本的事实校验，输出采用受控指导而非透传自由文本。
        return recommendation.model_copy(
            update={
                **values,
                "reasons": baseline.reasons,
                "risks": baseline.risks,
                "adjustments": baseline.adjustments,
                "confidence": min(recommendation.confidence, scene.confidence, 0.65),
                "validation_notes": list(dict.fromkeys(notes)),
            }
        )
