from __future__ import annotations

from pathlib import Path

import yaml

from camera_assistant.models import CameraFormat, CameraProfile

# A small source-reviewed capability registry, separate from retrieved knowledge
# cards and model evidence. Unknown models remain unknown, including other Canon
# models. The official EOS R50 M-mode manual was checked on 2026-10-14.
VERIFIED_EXPOSURE_CAPABILITIES: dict[str, dict[str, object]] = {
    "canon_eos_r50": {
        "exposure_compensation_min": -3.0,
        "exposure_compensation_max": 3.0,
        "exposure_compensation_range_source":
            "https://asia.canon/en/consumer/eos-r50/body/specification",
        "m_auto_iso_compensation": "supported",
        "m_auto_iso_compensation_source":
            "https://cam.start.canon/en/C011/manual/html/UG-03_CustomShooting_0050.html",
        "m_auto_iso_compensation_conditions": [
            "仅在 M 档并启用 Auto ISO 时适用。",
            "官方说明：Auto ISO 闪光摄影不应用此曝光补偿。",
            "试拍时检查实际 ISO 是否响应，以及是否触及自动 ISO 范围边界。",
        ],
    },
}


def verified_exposure_capability(camera: CameraProfile | None) -> dict[str, object]:
    """Do not trust a capability merely asserted in generated recommendation data."""
    if camera is None:
        return {}
    return dict(VERIFIED_EXPOSURE_CAPABILITIES.get(camera.profile_id, {}))


class CameraKnowledgeBase:
    """读取机型能力，并为未知机型提供画幅级兜底配置。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw_profiles = payload.get("profiles", [])
        if not isinstance(raw_profiles, list) or not raw_profiles:
            raise ValueError("机型知识库为空或格式不正确。")
        self.profiles = {}
        for raw in raw_profiles:
            profile = CameraProfile.model_validate(raw)
            capability = verified_exposure_capability(profile)
            self.profiles[profile.profile_id] = profile.model_copy(update=capability)

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

