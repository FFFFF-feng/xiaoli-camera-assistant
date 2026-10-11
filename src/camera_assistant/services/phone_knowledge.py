from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

from camera_assistant.models import PhoneProfile

PHONE_MODE_NAMES = {"auto": "照片 / 自动", "portrait": "人像", "night": "夜间", "pro": "专业 / Pro"}


def normalized_model_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s_-]+", "", text)


class PhoneKnowledgeBase:
    """明确型号和别名匹配；未知型号不继承相邻型号的功能。"""

    def __init__(self, path: Path) -> None:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        profiles = [PhoneProfile.model_validate(item) for item in payload.get("profiles", [])]
        self.profiles = {item.profile_id: item for item in profiles}
        if (
            not profiles
            or len(profiles) != len(self.profiles)
            or "generic_phone" not in self.profiles
        ):
            raise ValueError("手机目录缺少兜底档案或存在重复型号")
        self.aliases: dict[str, str] = {}
        for profile in profiles:
            for alias in [
                profile.profile_id,
                profile.model,
                profile.display_name,
                *profile.aliases,
            ]:
                key = normalized_model_name(alias)
                previous = self.aliases.get(key)
                if previous and previous != profile.profile_id:
                    raise ValueError("手机型号别名冲突")
                self.aliases[key] = profile.profile_id

    def list_profiles(self) -> list[PhoneProfile]:
        return list(self.profiles.values())

    def search(self, query: str) -> list[PhoneProfile]:
        key = normalized_model_name(query)
        if not key:
            return self.list_profiles()
        if key in self.aliases:
            return [self.profiles[self.aliases[key]]]
        # 带代际数字的具体型号不能按前缀把基础版替换为Ultra/Pro等变体。
        if any(char.isdigit() for char in key):
            return []
        ids = {profile_id for name, profile_id in self.aliases.items() if key in name}
        return [profile for profile in self.profiles.values() if profile.profile_id in ids]

    def resolve(self, identifier: str) -> PhoneProfile:
        profile_id = self.aliases.get(normalized_model_name(identifier), "generic_phone")
        return self.profiles[profile_id]
