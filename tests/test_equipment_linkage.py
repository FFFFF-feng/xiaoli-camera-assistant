from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_device_selection import photo, pipeline

from camera_assistant.knowledge.models import KnowledgeRecord, SourceInfo
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import UserRequest
from camera_assistant.services.lens_knowledge import EquipmentSelectionError

ROOT = Path(__file__).resolve().parents[1]
CANON_LENS = "canon_ef_s_18_55_f4_56_is_stm"


def test_all_known_cameras_have_native_lens_options_and_provenance(tmp_path):
    app = pipeline(tmp_path)
    known = [
        p for p in app.camera_knowledge.list_profiles() if not p.profile_id.startswith("generic_")
        and p.capability_level != "catalog"
    ]
    assert len(known) == 14
    assert len(app.phone_knowledge.list_profiles()) == 16
    assert len(app.lens_knowledge.list_profiles()) == 12
    for camera in known:
        assert camera.mount != "unknown" and camera.source_url.startswith("https://")
        assert app.lens_knowledge.for_camera(camera)
        if camera.capability_level == "basic":
            assert camera.native_iso_min is None and camera.native_iso_max is None
            assert camera.max_mechanical_shutter is None and camera.ibis_stops is None
    assert all(
        lens.source_url.startswith("https://") and lens.checked_at == "2026-10-14"
        for lens in app.lens_knowledge.list_profiles()
    )


@pytest.mark.parametrize(
    "camera_id,lens_id",
    [
        ("canon_eos_200d_ii", CANON_LENS),
        ("canon_eos_r50", "canon_rf_s_18_45_f45_63_is_stm"),
        ("nikon_z50", "nikon_z_dx_16_50_f35_63_vr"),
        ("sony_a6400", "sony_e_18_55_f35_56_oss"),
        ("fujifilm_x_s20", "fujifilm_xf_18_55_f28_4"),
        ("panasonic_g100", "panasonic_g_12_32_f35_56"),
    ],
)
def test_native_lenses_are_listed(camera_id, lens_id, tmp_path):
    app = pipeline(tmp_path)
    camera = app.camera_knowledge.resolve(camera_id, "不清楚")
    assert lens_id in {lens.lens_id for lens in app.lens_knowledge.for_camera(camera)}


@pytest.mark.parametrize(
    "camera_id,lens_id",
    [
        ("canon_eos_r50", CANON_LENS),  # 需要转接，不能默认已安装。
        ("canon_eos_200d_ii", "sony_e_18_55_f35_56_oss"),
        ("sony_a7_iv", "sony_e_18_55_f35_56_oss"),  # 裁切模式暂不自动启用。
        ("nikon_z5", "nikon_z_dx_16_50_f35_63_vr"),
        ("generic_unknown", CANON_LENS),
        ("canon_eos_r50", "not-a-real-lens"),
    ],
)
def test_cross_mount_crop_or_unknown_lens_is_rejected(camera_id, lens_id, tmp_path):
    with pytest.raises(EquipmentSelectionError):
        pipeline(tmp_path).run(
            photo(),
            UserRequest(intent="拍人像", camera_profile_id=camera_id, camera_lens_id=lens_id),
        )


@pytest.mark.parametrize(
    "requested,effective,aperture",
    [(None, 18, 4), (8, 18, 4), (35, 35, 5.6), (55, 55, 5.6), (1200, 55, 5.6)],
)
def test_lens_constraints_and_sensor_override_reach_recommendation(
    requested, effective, aperture, tmp_path
):
    result = pipeline(tmp_path).run(
        photo(),
        UserRequest(
            intent="拍人像，希望背景虚化",
            camera_profile_id="canon_eos_200d_ii",
            camera_format="全画幅",
            camera_lens_id=CANON_LENS,
            focal_length_mm=requested,
            max_aperture=1.2,
        ),
    )
    assert result.camera_profile.sensor_format == "APS-C"
    equipment = result.equipment_settings
    assert equipment.camera_lens.lens_id == CANON_LENS
    assert equipment.focal_length_mm == effective
    assert equipment.equivalent_focal_length_mm == round(effective * 1.6, 2)
    assert equipment.max_aperture == aperture
    assert result.recommendation.aperture.startswith(f"f/{aperture:g}")
    assert "f/1.2" not in result.recommendation.aperture
    assert result.camera_profile.native_iso_max is None
    assert "未完整核验" in " ".join(result.recommendation.validation_notes)


def test_prime_focal_is_not_zoom_and_lens_is_not_assumed(tmp_path):
    app = pipeline(tmp_path)
    empty = app.run(photo(), UserRequest(intent="拍人像", camera_profile_id="canon_eos_r8"))
    assert empty.equipment_settings.camera_lens is None
    selected = app.run(
        photo(),
        UserRequest(
            intent="拍人像",
            camera_profile_id="canon_eos_r8",
            camera_lens_id="canon_rf_50_f18_stm",
            focal_length_mm=85,
        ),
    )
    assert selected.equipment_settings.focal_length_mm == 50
    assert selected.equipment_settings.max_aperture == 1.8


def test_similar_phone_variants_have_independent_lenses_and_variable_aperture(tmp_path):
    phones = pipeline(tmp_path).phone_knowledge
    pro = phones.resolve("iPhone 15 Pro")
    promax = phones.resolve("iPhone 15 Pro Max")
    assert pro.lenses[-1].equivalent_focal_length_mm == 77
    assert promax.lenses[-1].equivalent_focal_length_mm == 120
    assert "pro" not in pro.modes  # iPhone Pro的名字不是手调ISO模式。
    ultra = phones.resolve("小米14Ultra")
    assert len(ultra.lenses) == 4 and ultra.lenses[0].aperture_control == "variable"
    assert ultra.lenses[0].aperture_max == 4
    assert phones.resolve("小米14").lenses[0].aperture_control == "fixed"


def test_phone_lens_switch_clears_unverified_mode_and_ignores_camera_lens(tmp_path):
    app = pipeline(tmp_path)
    result = app.run(
        photo(),
        UserRequest(
            intent="手机拍人像",
            device_type="phone",
            phone_profile_id="apple_iphone_15_pro",
            phone_lens_id="telephoto_3x",
            phone_capture_mode="portrait",
            camera_lens_id=CANON_LENS,
            focal_length_mm=800,
        ),
    )
    assert result.equipment_settings is None
    assert "照片 / 自动" in result.recommendation.shooting_mode
    assert result.recommendation.aperture.startswith("3×长焦 f/2.8")
    assert any("模式组合尚未核验" in note for note in result.knowledge_notes)


def test_managed_retrieval_filters_actual_lens_and_mount(tmp_path):
    app = pipeline(tmp_path)
    database = tmp_path / "isolated.db"
    store = KnowledgeStore(database)
    for identifier, lens in [
        ("matching-lens", CANON_LENS),
        ("wrong-lens", "sony_e_18_55_f35_56_oss"),
    ]:
        record = KnowledgeRecord(
            knowledge_id=identifier,
            library_id="equipment",
            title="镜头人像测试",
            kind="guideline",
            content="镜头 人像 背景 虚化；合成测试，不是正式摄影知识。",
            conditions={
                "device_type": "camera",
                "camera_mount": "canon_ef",
                "camera_lens_id": lens,
            },
            source=SourceInfo(name="synthetic", retrieval_allowed=True),
            author="fixture",
        )
        store.save_draft(record)
        store.submit(identifier)
        store.approve(identifier, reviewer="test-reviewer")
        store.publish(identifier)
    from camera_assistant.pipeline import CameraAssistantPipeline

    managed = CameraAssistantPipeline(
        replace(app.settings, knowledge_mode="managed", knowledge_db_path=database)
    )
    result = managed.run(
        photo(),
        UserRequest(
            intent="镜头人像背景虚化",
            camera_profile_id="canon_eos_200d_ii",
            camera_lens_id=CANON_LENS,
        ),
    )
    assert [hit.metadata["knowledge_id"] for hit in result.knowledge_hits] == ["matching-lens"]


def test_web_camera_lens_focal_and_sensor_linkage(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("CLOUD_API_KEY", "")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy")
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(tmp_path / "ui.db"))
    app = AppTest.from_file(ROOT / "app.py", default_timeout=20).run()
    app.text_input(key="camera_model_query").set_value("200D II").run()
    assert app.selectbox(key="camera_model").value == "canon_eos_200d_ii"
    assert any(field.value == "APS-C（半画幅）" and field.disabled for field in app.text_input)
    app.selectbox(key="camera_lens").set_value(CANON_LENS).run()
    assert app.slider(key="camera_focal").min == 18
    assert app.slider(key="camera_focal").max == 55
    app.slider(key="camera_focal").set_value(55).run()
    assert any("88mm" in item.value for item in app.caption)
    app.text_input(key="camera_model_query").set_value("佳能R50").run()
    assert app.selectbox(key="camera_lens").value == ""
    assert not any("EF-S 18" in value for value in app.selectbox(key="camera_lens").options)
    assert not app.exception


def test_web_phone_model_and_lens_linkage(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy")
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(tmp_path / "phone-ui.db"))
    app = AppTest.from_file(ROOT / "app.py", default_timeout=20).run()
    app.radio(key="capture_device").set_value("手机").run()
    app.text_input(key="phone_model_query").set_value("iPhone 15 Pro Max").run()
    assert "5×长焦" in app.selectbox(key="phone_lens").options
    assert "3×长焦" not in app.selectbox(key="phone_lens").options
    app.selectbox(key="phone_lens").set_value("telephoto_5x").run()
    assert app.selectbox(key="phone_mode").options == ["照片 / 自动"]
    assert any("120mm" in value.value for value in app.caption)
    app.text_input(key="phone_model_query").set_value("小米14 Ultra").run()
    assert app.selectbox(key="phone_lens").value == "main"
    assert any("可变范围" in value.value for value in app.caption)
    assert not app.exception
