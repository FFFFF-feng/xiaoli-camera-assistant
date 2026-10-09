from __future__ import annotations

from pathlib import Path

import yaml

from camera_assistant.models import CameraFormat, CameraProfile


class CameraKnowledgeBase:
    """读取机型能力，并为未知机型提供画幅级兜底配置。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw_profiles = payload.get("profiles", [])
        if not isinstance(raw_profiles, list) or not raw_profiles:
            raise ValueError("机型知识库为空或格式不正确。")
        self.profiles = {
            str(raw["profile_id"]): CameraProfile.model_validate(raw) for raw in raw_profiles
        }

    def list_profiles(self) -> list[CameraProfile]:
        return list(self.profiles.values())

    def resolve(self, profile_id: str, fallback_format: CameraFormat) -> CameraProfile:
        if profile_id in self.profiles and profile_id != "generic_unknown":
            return self.profiles[profile_id]
        fallback_id = {
            "全画幅": "generic_full_frame",
            "APS-C": "generic_aps_c",
            "M4/3": "generic_m43",
            "不清楚": "generic_unknown",
        }[fallback_format]
        return self.profiles[fallback_id]

