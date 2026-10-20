from dataclasses import replace

import pytest
from test_device_selection import photo, pipeline

from camera_assistant.knowledge.models import KnowledgeRecord
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import UserRequest
from camera_assistant.services.device_reference_catalog import (
    camera_reference_mounts,
    read_reference_devices,
    reference_lenses_for,
)
from camera_assistant.services.lens_knowledge import EquipmentSelectionError


def publish(db, identity, payload, *, status="published", split="reference", conditions=None):
    store = KnowledgeStore(db)
    record = KnowledgeRecord.model_validate({"knowledge_id": identity, "library_id": "equipment",
        "kind": "manufacturer_fact", "author": "source-author", "title": identity,
        "content": "测试资料，非实拍结论。", "payload": payload, "dataset_split": split,
        "conditions": conditions or {},
        "source": {"name": "fixture", "url": "https://example.com/spec", "retrieval_allowed": True}})
    store.save_draft(record)
    if status == "published":
        store.submit(identity)
        store.approve(identity, "fixture-maintainer")
        store.publish(identity)


def phone(db, **changes):
    publish(db, changes.pop("identity", "phone-test"), {
        "brand": "HUAWEI", "model_variant": "HUAWEI Test 90 Pro", "region_scope": "中国大陆",
        "specifications": {"cameras": {"rear_entries": [{"role": "主摄"}, {"role": "超广角"},
                                                        {"role": "2倍数字裁切"}]}},
    }, conditions={"device_type": "phone", "camera_model": "HUAWEI Test 90 Pro", "region_scope": "中国大陆"}, **changes)


def lens(db, identity="lens-test", mount="Sony E", brand="Test", **changes):
    publish(db, identity, {"entity_type": "lens", "model": "18-55mm", "brand": brand,
                           "mounts": [mount]}, **changes)


def test_only_published_reference_devices_are_registered(tmp_path):
    db = tmp_path / "knowledge.db"
    phone(db)
    phone(db, identity="draft", status="draft")
    phone(db, identity="evaluation", status="draft", split="evaluation")
    lens(db)
    publish(db, "adapter", {"entity_type": "adapter", "model": "Adapter", "mounts": ["Sony E"]})
    phones, lenses = read_reference_devices(db)
    assert len(phones) == len(lenses) == 1
    assert phones[0].brand == "Huawei" and "华为Test 90 Pro" in phones[0].aliases
    assert phones[0].modes == ["auto"] and not phones[0].pro_controls
    assert [item.lens_id for item in phones[0].lenses] == ["main", "rear_1"]
    assert all(item.aperture is None for item in phones[0].lenses)
    assert lenses[0]["mount_keys"] == ["sony_e"]
    assert lenses[0]["controls_hardware_limits"]  # 18-55mm是型号中明写的焦段，现可联动。
    assert lenses[0]["focal_min_mm"] == 18 and lenses[0]["focal_max_mm"] == 55
    assert lenses[0]["max_aperture_wide"] is None


def test_same_lens_name_different_brands_not_merged(tmp_path):
    db = tmp_path / "knowledge.db"
    lens(db)
    lens(db, "other-brand", brand="Other")
    assert len(read_reference_devices(db)[1]) == 2


def test_catalog_mount_is_reference_only_and_cannot_override_known_camera(tmp_path):
    db = tmp_path / "unused.db"
    lens(db, mount="Nikon F AF")
    app = pipeline(tmp_path)
    camera = app.camera_knowledge.resolve("Nikon D850", "不清楚")
    assert camera.mount == "unknown"
    assert camera_reference_mounts(camera) == {"nikon_f"}
    references = read_reference_devices(db)[1]
    assert reference_lenses_for(camera, references)
    canon = app.camera_knowledge.resolve("canon_eos_r50", "不清楚")
    assert not reference_lenses_for(canon, references, "nikon_f")
    assert app.lens_knowledge.for_camera(camera) == []


def test_pipeline_reference_lens_keeps_manual_numbers_and_rejects_cross_mount(tmp_path):
    app = pipeline(tmp_path)
    lens(tmp_path / "unused.db")
    app = type(app)(app.settings)
    reference = app.lens_references[0]
    request = UserRequest(intent="拍摄静物", camera_profile_id="sony_a6400",
        camera_lens_reference_id=reference["reference_id"], focal_length_mm=35, max_aperture=8)
    result = app.run(photo(), request)
    assert result.equipment_settings.camera_lens is None
    assert result.equipment_settings.focal_length_mm == 35
    assert result.equipment_settings.max_aperture == 8
    with pytest.raises(EquipmentSelectionError):
        app.run(photo(), request.model_copy(update={"camera_profile_id": "canon_eos_r50"}))


def test_added_phone_resolves_and_retrieves_its_model_specific_knowledge(tmp_path):
    app = pipeline(tmp_path)
    phone(tmp_path / "unused.db")
    app = type(app)(replace(app.settings, knowledge_mode="managed"))
    profile = app.phone_knowledge.resolve("华为Test 90 Pro")
    assert profile.profile_id.startswith("kb_phone_")
    result = app.run(photo(), UserRequest(intent="人像拍摄", device_type="phone", phone_profile_id=profile.profile_id))
    assert result.camera_profile.profile_id == profile.profile_id
    assert any(hit.metadata["knowledge_id"] == "phone-test" for hit in result.knowledge_hits)
    assert app.phone_knowledge.resolve("HUAWEI Test 90 Pro Future").profile_id == "generic_phone"


def test_missing_database_not_created(tmp_path):
    path = tmp_path / "missing.db"
    assert read_reference_devices(path) == ([], [])
    assert not path.exists()


def test_devices_api_exposes_reference_options(tmp_path):
    from fastapi.testclient import TestClient

    from camera_assistant.mobile_api import create_app

    app = pipeline(tmp_path)
    phone(tmp_path / "unused.db")
    lens(tmp_path / "unused.db")
    token = "fixture-reference-device-token-not-secret"
    with TestClient(create_app(app.settings, token)) as client:
        response = client.get("/api/v1/devices", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200
    data = response.json()
    assert len(data["lens_references"]) == 1
    assert data["device_reference_summary"]["phone_catalog_profiles"] == 1
    assert any(p["model"] == "HUAWEI Test 90 Pro" for p in data["phones"])
    assert len(data["camera_lenses"]) == 12


def test_existing_phone_adaptation_has_priority_over_reference_card(tmp_path):
    app = pipeline(tmp_path)
    original = app.phone_knowledge.resolve("iPhone 15").model_copy(deep=True)
    publish(tmp_path / "unused.db", "duplicate-phone", {
        "brand": "Apple", "model_variant": "Apple iPhone 15", "region_scope": "中国大陆",
        "aliases": ["iPhone 15"],
    }, conditions={"device_type": "phone"})
    updated = type(app)(app.settings)
    assert updated.phone_knowledge.resolve("iPhone 15") == original
