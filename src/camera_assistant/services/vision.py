from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from camera_assistant.config import Settings
from camera_assistant.models import (
    ImageInspection,
    SceneAnalysis,
    SceneCandidate,
    UserRequest,
)


class VisionAnalyzer(Protocol):
    def analyze(
        self,
        inspection: ImageInspection,
        request: UserRequest,
        candidates: list[SceneCandidate],
    ) -> SceneAnalysis: ...


class DemoVisionAnalyzer:
    """用于无 API 环境的可重复场景分析替身。"""

    def analyze(
        self,
        inspection: ImageInspection,
        request: UserRequest,
        candidates: list[SceneCandidate],
    ) -> SceneAnalysis:
        intent = request.intent.lower()
        selected = candidates[0]

        brightness_value = inspection.metrics.mean_brightness
        brightness = "low" if brightness_value < 0.32 else "high" if brightness_value > 0.72 else "medium"
        environment = "indoor" if any(word in intent for word in ("室内", "餐厅", "房间")) else "outdoor"
        if any(word in intent for word in ("夜", "星空", "霓虹")):
            lighting = "low light"
        elif brightness == "high":
            lighting = "bright light"
        else:
            lighting = "available light"

        motion_map = {"静止": "static", "缓慢": "slow", "快速": "fast", "不确定": selected.default_motion}
        effects: list[str] = []
        effect_words = {
            "虚化": "shallow_depth_of_field",
            "清楚": "freeze_motion",
            "清晰": "sharp_subject",
            "拉丝": "long_exposure",
            "丝绸": "long_exposure",
            "剪影": "silhouette",
            "低噪": "low_noise",
            "电影": "cinematic_mood",
        }
        for keyword, effect in effect_words.items():
            if keyword in intent and effect not in effects:
                effects.append(effect)

        backlight = any(word in intent for word in ("逆光", "夕阳", "剪影"))
        high_dynamic = inspection.metrics.shadow_ratio > 0.08 and inspection.metrics.highlight_ratio > 0.03
        return SceneAnalysis(
            scene_type=selected.profile_id,
            scene_label=selected.label,
            subject=selected.subject,
            environment=selected.environment if selected.environment != "unknown" else environment,
            lighting=lighting,
            brightness=brightness,
            backlight=backlight,
            subject_motion=motion_map[request.subject_motion],
            dynamic_range="high" if high_dynamic or backlight else "medium",
            desired_effects=effects,
            confidence=min(0.82, 0.56 + selected.score / 30),
            notes=["当前使用演示识别器；接入多模态 API 后将直接分析画面内容。"],
            recognition_evidence=selected.evidence,
            candidate_scenes=[candidate.label for candidate in candidates],
            retrieval_terms=selected.retrieval_terms,
        )


class OpenAICompatibleVisionAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze(
        self,
        inspection: ImageInspection,
        request: UserRequest,
        candidates: list[SceneCandidate],
    ) -> SceneAnalysis:
        schema = SceneAnalysis.model_json_schema()
        candidate_payload = [
            candidate.model_dump(exclude={"score"}) for candidate in candidates
        ]
        prompt = f"""
你是摄影场景分析器。结合现场照片、用户需求、器材条件、图像统计和内部场景知识库，返回严格 JSON。
不要直接推荐相机参数，不要输出 Markdown。
scene_type 必须从候选场景的 profile_id 中选择；scene_label 使用对应中文名称。
recognition_evidence 必须写明画面中实际观察到的主体、光线和运动依据，不能只复述用户要求。

用户输入：{request.model_dump_json()}
图像统计：{inspection.metrics.model_dump_json()}
原图 EXIF：{inspection.exif.model_dump_json()}
内部场景候选：{json.dumps(candidate_payload, ensure_ascii=False)}
JSON Schema：{json.dumps(schema, ensure_ascii=False)}
""".strip()
        payload = {
            "model": self.settings.vision_model,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": inspection.model_image_data_url},
                        },
                    ],
                }
            ],
        }
        content = self._request(payload)
        return SceneAnalysis.model_validate(self._extract_json(content))

    def _request(self, payload: dict[str, object]) -> str:
        with httpx.Client(timeout=self.settings.timeout_seconds) as client:
            response = client.post(
                f"{self.settings.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        return str(content)

    @staticmethod
    def _extract_json(content: str) -> dict[str, object]:
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
        candidate = fenced.group(1) if fenced else content
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end < 0:
            raise ValueError("多模态模型没有返回可解析的 JSON。")
        return json.loads(candidate[start : end + 1])
