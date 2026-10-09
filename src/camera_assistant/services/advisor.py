from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from camera_assistant.config import Settings
from camera_assistant.models import (
    CameraProfile,
    CameraRecommendation,
    KnowledgeHit,
    SceneAnalysis,
    UserRequest,
)


class RecommendationAdvisor(Protocol):
    def recommend(
        self,
        request: UserRequest,
        scene: SceneAnalysis,
        knowledge_hits: list[KnowledgeHit],
        camera: CameraProfile,
    ) -> CameraRecommendation: ...


class DemoRecommendationAdvisor:
    """演示模式下基于少量确定性规则生成参数。"""

    def recommend(
        self,
        request: UserRequest,
        scene: SceneAnalysis,
        knowledge_hits: list[KnowledgeHit],
        camera: CameraProfile,
    ) -> CameraRecommendation:
        intent = request.intent.lower()
        wide_aperture = self._wide_aperture(request)
        base: dict[str, object] = {
            "shooting_mode": camera.aperture_priority_name,
            "aperture": "f/4",
            "shutter_speed": self._safe_shutter(request, camera, minimum=125),
            "iso": self._auto_iso(camera, preferred_max=1600),
            "exposure_compensation": "0 EV",
            "focus_mode": camera.single_focus_name,
            "metering_mode": camera.metering_name,
            "drive_mode": "单张拍摄",
            "white_balance": "自动白平衡",
            "reasons": ["先使用容易操作的半自动模式，让相机完成基础测光。"],
            "risks": ["现场参考图经过自动曝光处理，建议仍需观察相机测光表。"],
            "adjustments": ["如果照片偏暗，先增加 +0.3 至 +0.7 EV 曝光补偿。"],
            "confidence": 0.72,
        }

        if "long_exposure" in scene.desired_effects or any(word in intent for word in ("拉丝", "丝绸")):
            base.update(
                shooting_mode="M 手动模式",
                aperture="f/8–f/11",
                shutter_speed="0.5–2s",
                iso="ISO 100",
                focus_mode=f"{camera.single_focus_name}，合焦后可锁定",
                drive_mode="2 秒延时拍摄",
                reasons=["慢门能记录水流轨迹，低 ISO 有助于保留画质。"],
                risks=["慢门必须尽量保持机位稳定，白天可能需要减光镜。"],
                adjustments=["拉丝不明显时延长曝光；画面过亮时使用 ND 减光镜。"],
                confidence=0.84,
            )
        elif scene.subject_motion == "fast" or "freeze_motion" in scene.desired_effects:
            base.update(
                shooting_mode=camera.shutter_priority_name,
                aperture=wide_aperture,
                shutter_speed="1/800s",
                iso=self._auto_iso(camera, preferred_max=6400),
                focus_mode=camera.continuous_focus_name,
                drive_mode="高速连拍",
                reasons=["快速主体先保证足够快的快门，再让自动 ISO 补足曝光。"],
                risks=["弱光下 ISO 可能升高并产生噪点。"],
                adjustments=["仍有运动模糊时提高到 1/1000s；噪点过多时寻找更亮环境。"],
                confidence=0.86,
            )
        elif scene.scene_type in {"outdoor_portrait", "indoor_portrait", "fast_pet"} or "shallow_depth_of_field" in scene.desired_effects:
            base.update(
                aperture=wide_aperture,
                shutter_speed=self._safe_shutter(request, camera, minimum=160),
                iso=self._auto_iso(camera, preferred_max=3200),
                focus_mode=f"眼部 AF；主体移动时使用 {camera.continuous_focus_name}",
                reasons=["较大光圈能获得浅景深，同时保证眼睛处于焦平面。"],
                risks=["距离过近且光圈过大时，双眼可能无法同时清晰。"],
                adjustments=["背景不够虚时靠近主体，并让主体远离背景。"],
                confidence=0.83,
            )
        elif scene.scene_type in {"handheld_night", "tripod_night"} or scene.brightness == "low":
            if request.tripod:
                base.update(
                    shooting_mode="M 手动模式",
                    aperture="f/8",
                    shutter_speed="1–4s",
                    iso="ISO 100–400",
                    drive_mode="2 秒延时拍摄",
                    reasons=["三脚架允许用慢门和低 ISO 换取更干净的夜景。"],
                    risks=["画面中的行人和车辆会形成拖影。"],
                    adjustments=["高光过曝时缩短快门，不要优先收缩光圈。"],
                    confidence=0.84,
                )
            else:
                base.update(
                    shooting_mode=camera.aperture_priority_name,
                    aperture=wide_aperture,
                    shutter_speed=self._safe_shutter(request, camera, minimum=80),
                    iso=self._auto_iso(camera, preferred_max=6400),
                    focus_mode=f"{camera.single_focus_name}；低对比区域可切换手动对焦",
                    reasons=["手持夜景需要兼顾安全快门和较大光圈。"],
                    risks=["现场光线过暗时噪点不可避免。"],
                    adjustments=["优先寻找支撑物稳定相机，再考虑降低 ISO。"],
                    confidence=0.76,
                )
        elif scene.scene_type in {"daylight_landscape", "sunset_backlight"}:
            base.update(
                aperture="f/8",
                iso="ISO 100–400",
                focus_mode=camera.single_focus_name,
                reasons=["f/8 通常能兼顾景深与镜头成像质量。"],
                risks=["手持时不能为了低 ISO 使用过慢快门。"],
                adjustments=["前后景无法同时清晰时，使用三脚架并考虑景深合成。"],
                confidence=0.8,
            )
        elif scene.scene_type == "food_closeup":
            base.update(
                aperture="f/4–f/5.6",
                shutter_speed=self._safe_shutter(request, camera, minimum=125),
                iso=self._auto_iso(camera, preferred_max=1600),
                focus_mode=f"{camera.single_focus_name}，单点对焦",
                reasons=["中等光圈能保留主体层次，同时避免景深过浅。"],
                adjustments=["颜色偏黄时尝试手动选择钨丝灯或自定义白平衡。"],
                confidence=0.79,
            )

        if "silhouette" in scene.desired_effects:
            base["exposure_compensation"] = "-1.0 至 -2.0 EV"
            base["reasons"].append("剪影效果需要保护明亮背景，并让主体保持暗部。")

        if scene.backlight and "silhouette" not in scene.desired_effects:
            base["exposure_compensation"] = "+0.3 至 +1.0 EV"
            base["risks"].append("逆光补偿过多可能导致天空高光溢出。")

        return CameraRecommendation(**base)

    @staticmethod
    def _auto_iso(camera: CameraProfile, preferred_max: int) -> str:
        upper = min(preferred_max, camera.recommended_auto_iso_max, camera.native_iso_max)
        return f"Auto ISO {camera.native_iso_min}–{upper}"

    @staticmethod
    def _wide_aperture(request: UserRequest) -> str:
        if request.max_aperture:
            return f"f/{request.max_aperture:g}–f/{max(request.max_aperture + 1.2, 2.8):g}"
        return "f/2.8–f/4（以镜头能力为准）"

    @staticmethod
    def _safe_shutter(request: UserRequest, camera: CameraProfile, minimum: int) -> str:
        crop = camera.crop_factor
        focal = request.focal_length_mm or 50
        target = max(minimum, int(focal * crop))
        standards = [30, 60, 80, 100, 125, 160, 200, 250, 320, 400, 500, 640, 800, 1000]
        denominator = next((value for value in standards if value >= target), 1000)
        return f"1/{denominator}s 或更快"


class OpenAICompatibleRecommendationAdvisor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def recommend(
        self,
        request: UserRequest,
        scene: SceneAnalysis,
        knowledge_hits: list[KnowledgeHit],
        camera: CameraProfile,
    ) -> CameraRecommendation:
        evidence = "\n\n".join(
            f"[资料 {index}: {hit.title}]\n{hit.content}"
            for index, hit in enumerate(knowledge_hits, start=1)
        )
        prompt = f"""
你是面向摄影新手的相机参数助手。只依据提供的场景分析与检索资料提出建议。
建议应是可执行的参数范围；无法从参考图判断现场绝对照度时必须说明。
不得虚构相机能力，不得推荐比用户镜头最大光圈更大的光圈。
只返回符合 JSON Schema 的 JSON，不输出 Markdown。

用户请求：{request.model_dump_json()}
场景分析：{scene.model_dump_json()}
目标相机能力：{camera.model_dump_json()}
检索资料：
{evidence}

JSON Schema：
{json.dumps(CameraRecommendation.model_json_schema(), ensure_ascii=False)}
""".strip()
        payload = {
            "model": self.settings.text_model,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }
        with httpx.Client(timeout=self.settings.timeout_seconds) as client:
            response = client.post(
                f"{self.settings.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        return CameraRecommendation.model_validate(self._extract_json(str(content)))

    @staticmethod
    def _extract_json(content: str) -> dict[str, object]:
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
        candidate = fenced.group(1) if fenced else content
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end < 0:
            raise ValueError("推荐模型没有返回可解析的 JSON。")
        return json.loads(candidate[start : end + 1])
