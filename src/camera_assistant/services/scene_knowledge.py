from __future__ import annotations

import re
from pathlib import Path

import yaml

from camera_assistant.models import (
    ImageInspection,
    SceneAnalysis,
    SceneCandidate,
    UserRequest,
)


class SceneKnowledgeBase:
    """使用内部场景定义为视觉模型提供候选集和统一分类标准。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        profiles = payload.get("profiles", [])
        if not isinstance(profiles, list) or not profiles:
            raise ValueError("场景识别知识库为空或格式不正确。")
        self.profiles: list[dict[str, object]] = profiles
        self.profile_by_id = {str(profile["id"]): profile for profile in profiles}

    def find_candidates(
        self,
        request: UserRequest,
        inspection: ImageInspection,
        limit: int = 4,
    ) -> list[SceneCandidate]:
        intent = request.intent.lower()
        motion = request.subject_motion
        # 明确的运动输入优先；用户尚未选择时只采用文字中的直接运动事实。
        if motion == "不确定":
            pet = r"(?:猫咪|小猫|小狗|狗狗|宠物|猫|狗)"
            affirmative = r"(?<!不是)(?<!并非)(?<!没有)(?<!不)(?<!非)"
            static_fact = re.search(
                rf"(?:{affirmative}静止(?:的)?{pet}|{pet}(?:正在|正)?(?:静止|趴着|坐着|睡觉|不动))",
                intent,
            )
            fast_fact = re.search(
                rf"(?:{affirmative}正在(?:奔跑|跑|跳跃)(?:的)?{pet}|{pet}正在(?:奔跑|跑|跳跃))",
                intent,
            )
            if static_fact and not fast_fact:
                motion = "静止"
            elif fast_fact and not static_fact:
                motion = "快速"
        brightness = self._brightness_level(inspection.metrics.mean_brightness)
        equipment = "tripod" if request.tripod else "handheld" if request.handheld else "unknown"
        candidates: list[SceneCandidate] = []

        for profile in self.profiles:
            score = 0.0
            evidence: list[str] = []

            matched_keywords = [
                str(keyword)
                for keyword in profile.get("keywords", [])
                if str(keyword).lower() in intent
            ]
            if matched_keywords:
                score += min(len(matched_keywords), 3) * 4
                score += float(profile.get("keyword_priority", 0))
                evidence.append(f"需求命中关键词：{'、'.join(matched_keywords[:3])}")

            supported_motion = [str(value) for value in profile.get("user_motion", [])]
            if motion != "不确定" and motion in supported_motion:
                score += 2.5
                evidence.append(f"用户明确主体运动为“{motion}”")
            elif motion != "不确定" and str(profile["id"]) in {"fast_pet", "pet_portrait"}:
                score -= 8
            elif motion == "不确定" and str(profile["id"]) == "fast_pet":
                # 仅有物种词不能证明快速运动；静态照片也不提供速度依据。
                score -= 8

            supported_brightness = [str(value) for value in profile.get("brightness", [])]
            if brightness in supported_brightness:
                score += 1.2
                evidence.append(f"原图亮度特征符合“{brightness}”")

            supported_equipment = [str(value) for value in profile.get("equipment", [])]
            if equipment in supported_equipment:
                score += 1
                evidence.append("器材条件与场景建议一致")

            if str(profile["id"]) == "general_scene":
                score = max(score, 0.1)

            candidate = self._to_candidate(profile, score, evidence)
            if request.subject_motion == "不确定" and motion != "不确定":
                candidate = candidate.model_copy(
                    update={
                        "default_motion": {"静止": "static", "缓慢": "slow", "快速": "fast"}[
                            motion
                        ],
                    }
                )
            candidates.append(candidate)

        candidates.sort(key=lambda item: item.score, reverse=True)
        positive = [candidate for candidate in candidates if candidate.score > 0.1]
        if not positive:
            positive = [
                candidate for candidate in candidates if candidate.profile_id == "general_scene"
            ]
        elif not any(candidate.profile_id == "general_scene" for candidate in positive):
            general = next(
                candidate for candidate in candidates if candidate.profile_id == "general_scene"
            )
            positive.append(general)
        return positive[:limit]

    def normalize(
        self,
        analysis: SceneAnalysis,
        candidates: list[SceneCandidate],
    ) -> SceneAnalysis:
        candidate_by_id = {candidate.profile_id: candidate for candidate in candidates}
        selected = candidate_by_id.get(analysis.scene_type)

        if selected is None:
            for candidate in candidates:
                profile = self.profile_by_id[candidate.profile_id]
                aliases = {str(alias).lower() for alias in profile.get("aliases", [])}
                if analysis.scene_type.lower() in aliases:
                    selected = candidate
                    break

        if selected is None:
            selected = candidates[0]

        evidence = list(dict.fromkeys([*analysis.recognition_evidence, *selected.evidence]))
        return analysis.model_copy(
            update={
                "scene_type": selected.profile_id,
                "scene_label": selected.label,
                "recognition_evidence": evidence,
                "candidate_scenes": [candidate.label for candidate in candidates],
                "retrieval_terms": selected.retrieval_terms,
            }
        )

    @staticmethod
    def _to_candidate(
        profile: dict[str, object], score: float, evidence: list[str]
    ) -> SceneCandidate:
        return SceneCandidate(
            profile_id=str(profile["id"]),
            label=str(profile["label"]),
            description=str(profile["description"]),
            subject=str(profile.get("subject", "main subject")),
            environment=str(profile.get("environment", "unknown")),
            default_motion=str(profile.get("default_motion", "unknown")),
            retrieval_terms=[str(term) for term in profile.get("retrieval_terms", [])],
            score=round(score, 3),
            evidence=evidence,
        )

    @staticmethod
    def _brightness_level(value: float) -> str:
        if value < 0.32:
            return "low"
        if value > 0.72:
            return "high"
        return "medium"
