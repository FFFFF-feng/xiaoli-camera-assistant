from __future__ import annotations

import re
import unicodedata
from fractions import Fraction

from camera_assistant.models import (
    CameraProfile,
    CameraRecommendation,
    PhoneProfile,
    SceneAnalysis,
    UserRequest,
)
from camera_assistant.services.phone_advisor import PhoneRecommendationValidator
from camera_assistant.services.photography_facts import photography_facts, reconcile_parameter_facts


class RecommendationValidator:
    def validate(
        self,
        recommendation: CameraRecommendation,
        request: UserRequest,
        scene: SceneAnalysis,
        camera: CameraProfile | PhoneProfile | None = None,
    ) -> CameraRecommendation:
        if isinstance(camera, PhoneProfile):
            return PhoneRecommendationValidator().validate(recommendation, request, scene, camera)
        facts = photography_facts(request, scene, camera)
        # An image-derived label is a precautionary estimate, not a confirmed
        # motion fact. An explicit user status always takes precedence.
        fast_motion = facts.motion == "fast" or (facts.motion == "unknown" and scene.subject_motion == "fast")
        updates: dict[str, object] = {}
        # These notes describe checks performed here, never model-authored verification claims.
        notes: list[str] = []
        risks = list(recommendation.risks)

        recommended_aperture = self._first_aperture(recommendation.aperture)
        if (
            request.max_aperture is not None
            and recommended_aperture is not None
            and recommended_aperture < request.max_aperture
        ):
            updates["aperture"] = f"f/{request.max_aperture:g}（镜头最大光圈）"
            notes.append("已按用户填写的镜头最大光圈修正建议。")

        shutter_seconds = self._shutter_seconds(recommendation.shutter_speed)
        if shutter_seconds is None:
            updates["shutter_speed"] = "无法校验快门数值；请在机身界面确认"
            risks.append("无法校验建议中的快门数值；请确认有效曝光时间后再拍摄。")
        if fast_motion and shutter_seconds and max(shutter_seconds) > 1 / 500:
            updates["shutter_speed"] = "1/500s 或更快"
            notes.append("快速主体的快门已修正为不慢于 1/500s。" if facts.motion == "fast" else
                         "运动状态未确认；若现场确认快速运动，以不慢于 1/500s 为试拍起点。")
            shutter_seconds = (1 / 500,)

        if camera is not None:
            shutter_type = getattr(request, "shutter_type", None)
            shutter_limit = camera.max_mechanical_shutter
            shutter_label = "机械"
            if shutter_type == "electronic" and camera.max_electronic_shutter:
                shutter_limit = camera.max_electronic_shutter
                shutter_label = "电子"
            elif shutter_type == "electronic":
                notes.append("未确认该机型电子快门上限，保守使用已知机械快门边界。")
            elif shutter_type == "efcs":
                notes.append("未单独核验电子前帘快门上限，保守使用机械快门边界；请核对当前模式。")
            elif shutter_type is None:
                notes.append("未选择快门类型，保守使用机械快门边界；电子快门上限需明确选择后适用。")
            if shutter_limit is None:
                notes.append("本机快门边界尚未核验，请按实际机身菜单确认。")
            if shutter_limit is not None and shutter_seconds and min(shutter_seconds) < 1 / shutter_limit:
                updates["shutter_speed"] = f"1/{shutter_limit}s"
                notes.append(f"已按该机型{shutter_label}快门 1/{shutter_limit}s 上限修正快门速度。")
                shutter_seconds = (1 / shutter_limit,)

            corrected_iso = self._clamp_iso(recommendation.iso, camera)
            if camera.native_iso_min is None or camera.native_iso_max is None:
                corrected_iso = (
                    "Auto ISO（范围以本机菜单为准）"
                    if "auto" in recommendation.iso.lower()
                    else "低 ISO（实际数值以本机可用范围为准）"
                )
            if corrected_iso != recommendation.iso:
                updates["iso"] = corrected_iso
                notes.append(
                    "已按该机型的标准感光度范围修正 ISO。"
                    if camera.native_iso_min is not None and camera.native_iso_max is not None
                    else "本机曝光边界尚未完整核验，ISO 按实际菜单核对，不输出未经确认的硬件范围。"
                )

            if "光圈优先" in recommendation.shooting_mode:
                updates["shooting_mode"] = camera.aperture_priority_name
            elif "快门优先" in recommendation.shooting_mode:
                updates["shooting_mode"] = camera.shutter_priority_name

            if fast_motion:
                updates["focus_mode"] = camera.continuous_focus_name

            updates["metering_mode"] = camera.metering_name
            if camera.capability_level == "catalog":
                updates.update(
                    shooting_mode="机内可用曝光模式（能力未核验）",
                    focus_mode="机内可用对焦方式（能力未核验）",
                    drive_mode="按本机可用拍摄方式选择",
                    aperture="以本机或镜头可用光圈为准（未核验）",
                )
                notes.append("仅匹配基础目录，不代表完成机型适配；数值建议仅作通用试拍目标。")
            notes.append(f"已匹配 {camera.display_name} 的机身能力目录资料；未收录能力不作保证。")
            if facts.ibis == "present" and camera.ibis_stops and not fast_motion:
                notes.append(
                    f"该机型具备约 {camera.ibis_stops:g} 挡标称机身防抖；实际效果受镜头和拍摄姿势影响。"
                )

        if request.handheld and not request.tripod and shutter_seconds and max(shutter_seconds) >= 0.1:
            warning = "当前建议包含慢门，手持容易模糊；请使用三脚架或稳定支撑。"
            if warning not in risks:
                risks.append(warning)

        if request.tripod and request.handheld:
            notes.append("已按三脚架优先处理；拍摄时请关闭手持状态。")

        updates["risks"] = risks
        updates["validation_notes"] = notes
        return reconcile_parameter_facts(recommendation.model_copy(update=updates), facts)

    @staticmethod
    def _first_aperture(value: str) -> float | None:
        match = re.search(r"f\s*/\s*(\d+(?:\.\d+)?)", value, re.IGNORECASE)
        return float(match.group(1)) if match else None

    @staticmethod
    def _shutter_seconds(value: str) -> tuple[float, ...] | None:
        """Parse a complete shutter value; unsupported or invalid text returns None.

        A seconds unit may be shared by range endpoints. Without any unit, every
        endpoint must be a fraction. Only explicit shutter prefixes and speed
        modifiers are allowed, so numbers in mixed exposure prose are not seconds.
        One trailing parenthesized mode note may contain no numbers or parameters.
        """
        number = r"[+-]?\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?"
        unit = r"(?:seconds?|secs?|s|秒)"
        pattern = (
            rf"\s*(?:建议\s*)?(?:快门(?:速度)?|曝光时间)?\s*[:：]?\s*(?:约\s*)?"
            rf"(?P<first>{number})\s*(?P<first_unit>{unit})?\s*"
            rf"(?:[-–—~～至到]\s*(?P<last>{number})\s*(?P<last_unit>{unit})?)?"
            rf"\s*(?:(?:或)?(?:更快|更慢))?\s*"
            r"(?:\((?P<ascii_note>[^()（）]+)\)|（(?P<chinese_note>[^()（）]+)）)?\s*"
        )
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        if match is None:
            return None
        values = [match.group("first")]
        if match.group("last") is not None:
            values.append(match.group("last"))
        if not (match.group("first_unit") or match.group("last_unit")) and any(
            "/" not in endpoint for endpoint in values
        ):
            return None
        endpoints: list[float] = []
        for endpoint in values:
            try:
                parts = re.sub(r"\s", "", endpoint).split("/")
                seconds = Fraction(parts[0])
                if len(parts) == 2:
                    seconds /= Fraction(parts[1])
                if seconds <= 0:
                    return None
                endpoints.append(float(seconds))
            except (ValueError, ZeroDivisionError, OverflowError):
                return None
        annotation = match.group("ascii_note") or match.group("chinese_note")
        if annotation is not None:
            normalized = unicodedata.normalize("NFKC", annotation)
            parameter_terms = (
                r"(?<![A-Za-z])(?:iso|ev|seconds?|secs?)(?![A-Za-z])"
                r"|f\s*/|快门|光圈|曝光(?:时间|补偿)|焦距|感光度|秒"
            )
            if (
                not annotation.strip()
                or any(character.isnumeric() for character in annotation)
                or re.search(parameter_terms, normalized, re.IGNORECASE)
            ):
                return None
        return tuple(endpoints)

    @staticmethod
    def _clamp_iso(value: str, camera: CameraProfile) -> str:
        """把明确给出的 ISO 数值限制在机型标准范围内。

        自动 ISO 的上限额外采用知识库里的保守推荐值，避免只因为机身支持
        很高的扩展 ISO，就把新手默认上限推得过高。
        """
        if camera.native_iso_min is None or camera.native_iso_max is None:
            return value
        upper = (
            min(camera.native_iso_max, camera.recommended_auto_iso_max)
            if "auto" in value.lower()
            else camera.native_iso_max
        )
        matches = list(re.finditer(r"\d+", value))
        if not matches:
            return value

        replacements: list[tuple[int, int, str]] = []
        for match in matches:
            number = int(match.group())
            clamped = min(max(number, camera.native_iso_min), upper)
            if clamped != number:
                replacements.append((match.start(), match.end(), str(clamped)))

        corrected = value
        for start, end, replacement in reversed(replacements):
            corrected = corrected[:start] + replacement + corrected[end:]
        return corrected
