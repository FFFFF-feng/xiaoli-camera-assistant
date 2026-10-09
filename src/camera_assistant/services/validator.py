from __future__ import annotations

import re
from fractions import Fraction

from camera_assistant.models import (
    CameraProfile,
    CameraRecommendation,
    SceneAnalysis,
    UserRequest,
)


class RecommendationValidator:
    def validate(
        self,
        recommendation: CameraRecommendation,
        request: UserRequest,
        scene: SceneAnalysis,
        camera: CameraProfile | None = None,
    ) -> CameraRecommendation:
        updates: dict[str, object] = {}
        notes = list(recommendation.validation_notes)
        risks = list(recommendation.risks)

        recommended_aperture = self._first_aperture(recommendation.aperture)
        if (
            request.max_aperture is not None
            and recommended_aperture is not None
            and recommended_aperture < request.max_aperture
        ):
            updates["aperture"] = f"f/{request.max_aperture:g}（镜头最大光圈）"
            notes.append("已按用户填写的镜头最大光圈修正建议。")

        shutter_seconds = self._first_shutter_seconds(recommendation.shutter_speed)
        if scene.subject_motion == "fast" and shutter_seconds and shutter_seconds > 1 / 500:
            updates["shutter_speed"] = "1/500s 或更快"
            notes.append("快速主体的快门已修正为不慢于 1/500s。")

        if camera is not None:
            if (
                camera.max_electronic_shutter
                and shutter_seconds
                and shutter_seconds < 1 / camera.max_electronic_shutter
            ):
                updates["shutter_speed"] = f"1/{camera.max_electronic_shutter}s"
                notes.append("已按该机型电子快门上限修正快门速度。")

            corrected_iso = self._clamp_iso(recommendation.iso, camera)
            if corrected_iso != recommendation.iso:
                updates["iso"] = corrected_iso
                notes.append("已按该机型的标准感光度范围修正 ISO。")

            if "光圈优先" in recommendation.shooting_mode:
                updates["shooting_mode"] = camera.aperture_priority_name
            elif "快门优先" in recommendation.shooting_mode:
                updates["shooting_mode"] = camera.shutter_priority_name

            if scene.subject_motion == "fast":
                updates["focus_mode"] = camera.continuous_focus_name

            updates["metering_mode"] = camera.metering_name
            notes.append(f"已匹配 {camera.display_name} 的机身能力与品牌术语。")
            if camera.ibis_stops > 0 and scene.subject_motion != "fast":
                notes.append(
                    f"该机型具备约 {camera.ibis_stops:g} 挡标称机身防抖；实际效果受镜头和拍摄姿势影响。"
                )

        if request.handheld and not request.tripod and shutter_seconds and shutter_seconds >= 0.1:
            warning = "当前建议包含慢门，手持容易模糊；请使用三脚架或稳定支撑。"
            if warning not in risks:
                risks.append(warning)

        if request.tripod and request.handheld:
            notes.append("已按三脚架优先处理；拍摄时请关闭手持状态。")

        updates["risks"] = risks
        updates["validation_notes"] = notes
        return recommendation.model_copy(update=updates)

    @staticmethod
    def _first_aperture(value: str) -> float | None:
        match = re.search(r"f\s*/\s*(\d+(?:\.\d+)?)", value, re.IGNORECASE)
        return float(match.group(1)) if match else None

    @staticmethod
    def _first_shutter_seconds(value: str) -> float | None:
        fraction_match = re.search(r"(\d+)\s*/\s*(\d+)\s*s", value, re.IGNORECASE)
        if fraction_match:
            return float(Fraction(int(fraction_match.group(1)), int(fraction_match.group(2))))
        seconds_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:–|-|至)?\s*\d*(?:\.\d+)?\s*s", value)
        return float(seconds_match.group(1)) if seconds_match else None

    @staticmethod
    def _clamp_iso(value: str, camera: CameraProfile) -> str:
        """把明确给出的 ISO 数值限制在机型标准范围内。

        自动 ISO 的上限额外采用知识库里的保守推荐值，避免只因为机身支持
        很高的扩展 ISO，就把新手默认上限推得过高。
        """
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
