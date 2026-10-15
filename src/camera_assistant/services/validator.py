from __future__ import annotations

import re
import unicodedata
from fractions import Fraction
from math import isfinite

from camera_assistant.models import (
    CameraProfile,
    CameraRecommendation,
    PhoneProfile,
    SceneAnalysis,
    UserRequest,
)
from camera_assistant.services.exposure import (
    classify_iso,
    normalize_mode,
    reconcile_exposure_advice,
)
from camera_assistant.services.phone_advisor import PhoneRecommendationValidator


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
        updates: dict[str, object] = {}
        # These notes describe checks performed here, never model-authored verification claims.
        notes: list[str] = []
        risks = list(recommendation.risks)

        mode = normalize_mode(recommendation.shooting_mode)
        aperture_target = self._target_field(recommendation.aperture, mode in {"Tv", "P"})
        aperture_values = self._aperture_values(aperture_target)
        if aperture_values is None:
            updates["aperture"] = "无法校验光圈数值；请在镜头与机身界面确认"
            notes.append("光圈字段未通过完整数值解析；没有从说明或器材最大光圈中提取当前设置。")
        else:
            corrected_values = aperture_values
            clipped = bool(request.max_aperture is not None and any(
                value < request.max_aperture for value in aperture_values
            ))
            if clipped:
                corrected_values = tuple(max(value, request.max_aperture) for value in aperture_values)
                notes.append("已按用户填写的镜头最大光圈修正建议，区间的所有端点均受同一边界约束。")
            corrected_values = tuple(sorted(set(corrected_values)))
            canonical = "–".join(f"f/{value:g}" for value in corrected_values)
            # Retain our own compatibility display label only when its lens
            # boundary is independently known from the request. It is never a
            # current-setting observation or evidence supplied by the model.
            if clipped or (
                request.max_aperture is not None
                and min(corrected_values) == request.max_aperture
                and re.search(r"[（(]镜头最大光圈[）)]\s*$", recommendation.aperture)
            ):
                canonical += "（镜头最大光圈）"
            updates["aperture"] = canonical
            if canonical != recommendation.aperture and not clipped:
                notes.append("已统一光圈数值格式；建议值与镜头能力、用户当前设置分别记录。")

        shutter_target = self._target_field(recommendation.shutter_speed, mode in {"Av", "P"})
        shutter_target = self._normalize_shutter_target(shutter_target)
        shutter_seconds = self._shutter_seconds(shutter_target)
        if shutter_seconds is not None and shutter_target != recommendation.shutter_speed and "自动" in recommendation.shutter_speed:
            faster = shutter_target.endswith("或更快")
            shutter_target = "–".join(self._seconds_label(seconds) for seconds in shutter_seconds)
            if faster:
                shutter_target += " 或更快"
        if shutter_seconds is not None and shutter_target != recommendation.shutter_speed:
            updates["shutter_speed"] = shutter_target
            notes.append("已将明确的快门目标或毫秒单位统一为曝光时间；自动目标仍需半按快门核对实际读数。")
        if shutter_seconds is None:
            updates["shutter_speed"] = "无法校验快门数值；请在机身界面确认"
            risks.append("无法校验建议中的快门数值；请确认有效曝光时间后再拍摄。")
        if scene.subject_motion == "fast" and shutter_seconds and max(shutter_seconds) > 1 / 500:
            updates["shutter_speed"] = "1/500s 或更快"
            notes.append("快速主体的快门已修正为不慢于 1/500s。")
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
            if shutter_seconds and min(shutter_seconds) < 1 / shutter_limit:
                updates["shutter_speed"] = f"1/{shutter_limit}s"
                notes.append(f"已按该机型{shutter_label}快门 1/{shutter_limit}s 上限修正快门速度。")
                shutter_seconds = (1 / shutter_limit,)

            corrected_iso = self._clamp_iso(recommendation.iso, camera)
            if corrected_iso != recommendation.iso:
                updates["iso"] = corrected_iso
                notes.append("已按该机型的标准感光度范围修正 ISO。")

            if normalize_mode(recommendation.shooting_mode) == "Av":
                updates["shooting_mode"] = camera.aperture_priority_name
            elif normalize_mode(recommendation.shooting_mode) == "Tv":
                updates["shooting_mode"] = camera.shutter_priority_name

            if scene.subject_motion == "fast":
                updates["focus_mode"] = camera.continuous_focus_name
            elif re.fullmatch(r"(?:AF[- ]?S|single|One[- ]Shot AF)", recommendation.focus_mode, re.IGNORECASE):
                updates["focus_mode"] = camera.single_focus_name
            elif re.fullmatch(r"(?:AF[- ]?C|Servo AF)", recommendation.focus_mode, re.IGNORECASE):
                updates["focus_mode"] = camera.continuous_focus_name

            updates["metering_mode"] = camera.metering_name
            notes.append(f"已匹配 {camera.display_name} 的机身能力与品牌术语。")
            if camera.ibis_stops > 0 and scene.subject_motion != "fast":
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
        final = recommendation.model_copy(update=updates)
        changed_parameters = {key for key in ("aperture", "shutter_speed", "iso")
                              if getattr(final, key) != getattr(recommendation, key)}
        final = reconcile_exposure_advice(final, request, scene, camera, changed_parameters)
        # Rebuild these program-owned diagnostic risks from final numerical
        # facts, after routing away model-authored exposure text.
        final_risks = list(final.risks)
        if aperture_values is None:
            final_risks.append("无法校验建议中的光圈数值；不能据此认定景深或镜头能力已经满足。")
            state = final.exposure_state
            if state is not None:
                parameters = dict(state.parameters)
                parameters["aperture"] = parameters["aperture"].model_copy(update={"role": "unknown"})
                final = final.model_copy(update={
                    "exposure_state": state.model_copy(update={"parameters": parameters}),
                })
            final = final.model_copy(update={
                "adjustments": [text for text in final.adjustments if not re.search(
                    r"建议光圈|若过亮，也可收小光圈|若过暗，也可开大光圈", text,
                )] + ["光圈建议未校验；先在机身和当前镜头界面确认有效数值，再使用涉及光圈与景深的操作。"],
            })
        if shutter_seconds is None:
            final_risks.append("无法校验建议中的快门数值；请确认有效曝光时间后再拍摄。")
            state = final.exposure_state
            if state is not None:
                parameters = dict(state.parameters)
                parameters["shutter_speed"] = parameters["shutter_speed"].model_copy(update={"role": "unknown"})
                final = final.model_copy(update={
                    "exposure_state": state.model_copy(update={"parameters": parameters}),
                })
            final = final.model_copy(update={
                "adjustments": [item for item in final.adjustments if not re.search(
                    r"快门|曝光时间|延长曝光|缩短曝光", item,
                )] + ["快门建议未校验；先在机身确认有效曝光时间，再按模式使用涉及快门或运动效果的操作。"],
            })
        elif request.handheld and not request.tripod and max(shutter_seconds) >= 0.1:
            final_risks.append("当前建议包含慢门，手持容易模糊；请使用三脚架或稳定支撑。")
        final = final.model_copy(update={"risks": list(dict.fromkeys(final_risks))})
        from camera_assistant.services.parameter_recovery import compensation_within_capability

        state = final.exposure_state
        if state is not None and state.parameters["exposure_compensation"].role == "manual_setting" and not compensation_within_capability(final.exposure_compensation, camera):
            parameters = dict(state.parameters)
            parameters["exposure_compensation"] = parameters["exposure_compensation"].model_copy(
                update={"role": "unknown", "value": "无法校验补偿数值或器材范围"})
            final = final.model_copy(update={
                "exposure_compensation": "无法校验补偿数值或器材范围",
                "exposure_state": state.model_copy(update={"parameters": parameters}),
                "risks": [*final.risks, "无法校验曝光补偿数值；不要按该字段直接设置补偿。"],
                "adjustments": [item for item in final.adjustments if "补偿" not in item] + [
                    "补偿建议未校验；先核对机身允许的补偿值，使用已确认设置测光和试拍，再检查高光与主体亮度。"],
            })
        # Screen only after controls, limits, prose and fallback steps have their
        # final values. The reviewer never trusts model-authored validation notes.
        from camera_assistant.services.advice_safety import screen_parameter_advice
        return screen_parameter_advice(final, request, scene=scene, camera=camera)

    @staticmethod
    def _first_aperture(value: str) -> float | None:
        values = RecommendationValidator._aperture_values(value)
        return values[0] if values else None

    @staticmethod
    def _target_field(value: str, automatic_allowed: bool) -> str:
        """Unwrap a complete automatic-target declaration, never arbitrary prose.

        Explicit automatic control must agree with the selected mode. A bare
        automatic label or a number found in another field is not a target.
        """
        normalized = unicodedata.normalize("NFKC", value).strip()
        wrapper = re.fullmatch(
            r"(?:由相机)?自动(?:控制|决定)?\s*\((?P<target>[^()]+)\)", normalized,
        )
        if wrapper:
            if not automatic_allowed:
                return "控制角色矛盾，自动目标不能作为手动设置"
            target = wrapper.group("target").strip()
            if target.startswith("目标"):
                return re.sub(r"^目标\s*[:：]?\s*", "", target)
            # A complete speed-check clause is a target even without the word
            # 'safe'. Time-duration comparisons and other prose are not speed
            # checks; the extracted value must still pass the whole-field parser.
            boundary = r"需确保(?:快门速度)?(?:不低于|不慢于)(?:安全快门)?(?:约)?\s*"
            if re.fullmatch(boundary + r".+", target):
                return re.sub(r"^" + boundary, "不慢于", target)
            return "自动控制缺少明确目标"
        if not automatic_allowed and re.search(r"[（(][^()（）]*自动[^()（）]*[）)]", value):
            return "控制角色矛盾，自动目标不能作为手动设置"
        return value

    @staticmethod
    def _normalize_shutter_target(value: str) -> str:
        """Canonicalize only explicit speed boundaries and decimal milliseconds."""
        normalized = unicodedata.normalize("NFKC", value).strip()
        boundary = re.fullmatch(
            r"(?:不慢于|快门速度\s*(?:>=|≥))\s*(?P<value>.+)", normalized,
        )
        if boundary:
            endpoint = boundary.group("value").strip()
            seconds = RecommendationValidator._shutter_seconds(endpoint)
            if seconds is not None and len(seconds) == 1:
                return RecommendationValidator._seconds_label(seconds[0]) + " 或更快"
            return value
        decimal = r"\d+(?:\.\d+)?"
        millis = re.fullmatch(
            rf"(?P<first>{decimal})\s*(?P<first_unit>ms|毫秒)?\s*"
            rf"(?:[-–—~～至到]\s*(?P<last>{decimal})\s*(?P<last_unit>ms|毫秒)?)?",
            normalized, re.IGNORECASE,
        )
        if millis and (millis.group("first_unit") or millis.group("last_unit")):
            return "–".join(
                f"{float(number) / 1000:g}s"
                for number in (millis.group("first"), millis.group("last")) if number is not None
            )
        return value

    @staticmethod
    def _seconds_label(seconds: float) -> str:
        denominator = 1 / seconds
        if seconds < 1 and isfinite(denominator) and abs(denominator - round(denominator)) < 1e-8:
            return f"1/{round(denominator)}s"
        return f"{seconds:g}s"

    @staticmethod
    def _aperture_values(value: str) -> tuple[float, ...] | None:
        """Parse the whole numeric field, never a number embedded in prose.

        Numeric f-numbers may share an f/ prefix at either range endpoint. One
        exact, program-generated lens-boundary display label is supported for
        compatibility with saved recommendations; arbitrary notes are rejected.
        """
        normalized = unicodedata.normalize("NFKC", value).strip()
        number = r"\d+(?:\.\d+)?"
        pattern = (
            rf"(?:f\s*/\s*)?(?P<first>{number})\s*"
            rf"(?:[-–—~～至到]\s*(?:f\s*/\s*)?(?P<last>{number}))?"
            r"\s*(?:\(镜头最大光圈\))?"
        )
        match = re.fullmatch(pattern, normalized, re.IGNORECASE)
        if match is None:
            return None
        values = tuple(float(number) for number in (match.group("first"), match.group("last"))
                       if number is not None)
        return values if all(isfinite(number) and number > 0 for number in values) else None

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
                parsed_seconds = float(seconds)
                if not isfinite(parsed_seconds) or parsed_seconds <= 0:
                    return None
                endpoints.append(parsed_seconds)
            except (ValueError, ZeroDivisionError, OverflowError):
                return None
        annotation = match.group("ascii_note") or match.group("chinese_note")
        if annotation is not None:
            normalized = unicodedata.normalize("NFKC", annotation)
            if not re.fullmatch(
                r"(?:目标(?:[,，]由相机根据测光自动调整)?|由相机根据测光自动调整)",
                normalized.strip(),
            ):
                return None
        return tuple(endpoints)

    @staticmethod
    def _clamp_iso(value: str, camera: CameraProfile) -> str:
        """把明确给出的 ISO 数值限制在机型标准范围内。

        自动 ISO 的上限额外采用知识库里的保守推荐值，避免只因为机身支持
        很高的扩展 ISO，就把新手默认上限推得过高。
        """
        if classify_iso(value) == "unknown":
            return value
        upper = (
            min(camera.native_iso_max, camera.recommended_auto_iso_max)
            if classify_iso(value) == "auto"
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
