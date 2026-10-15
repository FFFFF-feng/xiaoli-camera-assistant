"""原生卡口镜头目录及服务端器材联动约束。"""

from __future__ import annotations

from pathlib import Path

import yaml

from camera_assistant.models import CameraLensProfile, CameraProfile, EquipmentSettings, UserRequest


class EquipmentSelectionError(ValueError):
    pass


class LensKnowledgeBase:
    def __init__(self, path: Path) -> None:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        profiles = [
            CameraLensProfile.model_validate(item) for item in (payload or {}).get("lenses", [])
        ]
        self.profiles = {item.lens_id: item for item in profiles}
        if len(self.profiles) != len(profiles):
            raise ValueError("镜头目录编号重复")

    def list_profiles(self) -> list[CameraLensProfile]:
        return list(self.profiles.values())

    def for_camera(self, camera: CameraProfile) -> list[CameraLensProfile]:
        # 本版只列原生卡口、原生画幅可用项，不默认转接或开启裁切模式。
        if camera.capability_level == "catalog":
            return []
        return [
            p
            for p in self.profiles.values()
            if camera.mount != "unknown"
            and p.mount == camera.mount
            and camera.sensor_format in p.sensor_formats
        ]

    def normalize(
        self, request: UserRequest, camera: CameraProfile
    ) -> tuple[UserRequest, EquipmentSettings, list[str]]:
        notes: list[str] = []
        lens = None
        focal = request.focal_length_mm
        aperture = request.max_aperture
        if request.camera_lens_id:
            lens = next(
                (p for p in self.for_camera(camera) if p.lens_id == request.camera_lens_id), None
            )
            if lens is None:
                raise EquipmentSelectionError(
                    "所选镜头未收录或与当前机身的原生卡口/画幅不匹配，请重新选择镜头。"
                )
            focal = min(
                max(focal if focal is not None else lens.focal_min_mm, lens.focal_min_mm),
                lens.focal_max_mm,
            )
            if focal != request.focal_length_mm:
                notes.append(
                    f"当前实际焦距已按所选镜头限制在 {lens.focal_min_mm}–{lens.focal_max_mm}mm 范围，本次使用 {focal}mm。"
                )
            limit = lens.conservative_aperture(focal)
            aperture = max(aperture or limit, limit)
            notes.append(f"已使用 {lens.display_name} 的焦段和光圈约束，不是假设机身自带此镜头。")
            if lens.max_aperture_wide != lens.max_aperture_tele and focal != lens.focal_min_mm:
                notes.append(
                    f"中间焦段最大光圈未逐档核验，按长焦端 f/{limit:g} 作为保守可用光圈起点，不代表真实逐档最大光圈。"
                )
        effective = request.model_copy(
            update={
                "camera_profile_id": camera.profile_id,
                "camera_format": camera.sensor_format,
                "focal_length_mm": focal,
                "max_aperture": aperture,
            }
        )
        settings = EquipmentSettings(
            camera_lens=lens,
            sensor_format=camera.sensor_format,
            focal_length_mm=focal,
            equivalent_focal_length_mm=round(focal * camera.crop_factor, 2)
            if focal is not None and camera.sensor_format != "不清楚" and camera.crop_factor is not None
            else None,
            max_aperture=aperture,
        )
        return effective, settings, notes
