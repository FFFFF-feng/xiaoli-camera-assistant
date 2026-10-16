from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import yaml

from camera_assistant.models import CameraFormat, CameraProfile
from camera_assistant.services.phone_knowledge import normalized_model_name


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
        if len(self.profiles) != len(raw_profiles):
            raise ValueError("相机目录存在重复型号编号")
        catalog_path = path.with_name("camera_catalog.json")
        if catalog_path.exists():
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            if catalog.get("schema_version") != 1 or catalog.get("kind") != "camera_directory":
                raise ValueError("相机基础目录版本或类型不正确")
            for raw in catalog["profiles"]:
                profile = CameraProfile.model_validate(raw)
                if profile.capability_level != "catalog" or profile.profile_id in self.profiles:
                    raise ValueError("基础目录不能覆盖已适配相机")
                self.profiles[profile.profile_id] = profile
        self.aliases: dict[str, str] = {}
        self.alias_candidates: dict[str, set[str]] = defaultdict(set)
        for profile in self.profiles.values():
            for alias in [
                profile.profile_id,
                profile.model,
                profile.display_name,
                *profile.aliases,
            ]:
                key = normalized_model_name(alias)
                if key:
                    self.alias_candidates[key].add(profile.profile_id)
        # 短型号可能跨品牌重复，不能把第一个匹配结果当作用户实际设备。
        self.aliases = {
            key: next(iter(ids)) for key, ids in self.alias_candidates.items() if len(ids) == 1
        }

    def list_profiles(self) -> list[CameraProfile]:
        return list(self.profiles.values())

    def search(self, query: str) -> list[CameraProfile]:
        key = normalized_model_name(query)
        if not key:
            return self.list_profiles()
        if key in self.alias_candidates:
            return [self.profiles[identity] for identity in sorted(self.alias_candidates[key])]
        translations = {
            "佳能": "canon",
            "尼康": "nikon",
            "索尼": "sony",
            "富士": "fujifilm",
            "松下": "panasonic",
            "奥林巴斯": "olympus",
            "宾得": "pentax",
        }
        for chinese, english in translations.items():
            key = key.replace(chinese, english)
        ids = {profile_id for alias, profile_id in self.aliases.items() if key in alias}
        return [profile for profile in self.profiles.values() if profile.profile_id in ids]

    def resolve(self, profile_id: str, fallback_format: CameraFormat) -> CameraProfile:
        profile_id = self.aliases.get(normalized_model_name(profile_id), "generic_unknown")
        if profile_id in self.profiles and profile_id != "generic_unknown":
            profile = self.profiles[profile_id]
            if profile.capability_level == "catalog" and fallback_format != "不清楚":
                return profile.model_copy(update={"sensor_format": fallback_format})
            return profile
        fallback_id = {
            "全画幅": "generic_full_frame",
            "APS-C": "generic_aps_c",
            "M4/3": "generic_m43",
            "不清楚": "generic_unknown",
        }[fallback_format]
        return self.profiles[fallback_id]
