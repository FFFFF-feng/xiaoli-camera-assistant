from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from camera_assistant.models import CameraProfile, UserRequest
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase
from camera_assistant.services.lens_knowledge import EquipmentSelectionError, LensKnowledgeBase
from test_device_selection import photo, pipeline

ROOT = Path(__file__).resolve().parents[1]


def catalog():
    return CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml")


def test_deduplicated_directory_counts_and_unknown_hardware() -> None:
    profiles = catalog().list_profiles()
    known = [item for item in profiles if not item.profile_id.startswith("generic_")]
    base = [item for item in known if item.capability_level == "catalog"]
    assert len(known) == 4345
    assert len(base) == 4331
    assert all(item.mount == "unknown" and item.crop_factor is None for item in base)
    assert all(
        item.native_iso_min is None
        and item.native_iso_max is None
        and item.max_mechanical_shutter is None
        and item.ibis_stops is None
        for item in base
    )
    assert all(item.catalog_sources and item.source_url.startswith("https://") for item in base)
    assert not any(item.brand in {"Generic", "Apple", "Huawei", "Nokia"} for item in base)


def test_known_verified_profile_ids_are_not_shadowed_by_company_names() -> None:
    item = catalog().resolve("nikon_z50", "不清楚")
    assert item.capability_level == "detailed" and item.mount == "nikon_z"
    assert item.profile_id == "nikon_z50"
    assert len(catalog().search("Nikon Z50")) == 1


@pytest.mark.parametrize("name", ["Canon EOS R50 V", "Nikon Z50 II", "Nikon D850"])
def test_new_names_are_selectable_without_inheriting_old_capabilities(name: str) -> None:
    item = catalog().resolve(name, "不清楚")
    assert item.profile_id.startswith("catalog_")
    assert item.capability_level == "catalog"
    assert item.max_electronic_shutter is None and item.crop_factor is None


def test_conflicting_s200_is_not_published_and_not_inherited() -> None:
    assert catalog().resolve("Canon PowerShot S200", "不清楚").profile_id == "generic_unknown"
    report = json.loads(
        (ROOT / "knowledge_sources/camera-catalog-release-20261015/deduplication.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("Canon PowerShot S200" in group["models"] for group in report["excluded_groups"])


def test_directory_cannot_sneak_in_unverified_capabilities() -> None:
    item = next(
        profile for profile in catalog().list_profiles() if profile.capability_level == "catalog"
    )
    for changes in ({"native_iso_max": 51200}, {"crop_factor": 1.5}, {"mount": "canon_rf"}):
        with pytest.raises(ValidationError):
            CameraProfile.model_validate(item.model_dump() | changes)


def test_catalog_only_camera_never_gets_compatible_lens_or_fake_equivalence(tmp_path) -> None:
    app = pipeline(tmp_path)
    item = app.camera_knowledge.resolve("Nikon D850", "不清楚")
    assert app.lens_knowledge.for_camera(item) == []
    request = UserRequest(
        intent="拍摄风景",
        camera_profile_id=item.profile_id,
        camera_format="全画幅",
        focal_length_mm=50,
    )
    result = app.run(photo(), request)
    assert result.camera_profile.profile_id == item.profile_id
    assert result.equipment_settings.equivalent_focal_length_mm is None
    assert "未核验" in result.recommendation.aperture
    assert result.recommendation.shooting_mode == "机内可用曝光模式（能力未核验）"
    assert "未核验" in " ".join(result.recommendation.validation_notes)
    with pytest.raises(EquipmentSelectionError):
        app.run(photo(), request.model_copy(update={"camera_lens_id": "nikon_z_50_f18_s"}))


def test_unverified_mount_metadata_is_never_used_for_lens_compatibility() -> None:
    item = catalog().resolve("Nikon D850", "不清楚")
    lenses = LensKnowledgeBase(ROOT / "knowledge/cameras/lens_profiles.yaml")
    assert not lenses.for_camera(
        item.model_copy(update={"mount": "nikon_z", "sensor_format": "全画幅"})
    )
