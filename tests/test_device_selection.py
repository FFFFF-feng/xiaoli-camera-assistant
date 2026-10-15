from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from camera_assistant.config import Settings
from camera_assistant.models import UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase

ROOT = Path(__file__).resolve().parents[1]


def pipeline(tmp_path: Path) -> CameraAssistantPipeline:
    return CameraAssistantPipeline(
        Settings(
            demo_mode=True,
            api_key="",
            base_url="https://example.invalid",
            vision_model="",
            text_model="",
            timeout_seconds=5,
            max_image_mb=15,
            knowledge_dir=ROOT / "knowledge",
            knowledge_mode="legacy",
            knowledge_db_path=tmp_path / "unused.db",
        )
    )


def photo() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (100, 80), (110, 120, 100)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.mark.parametrize(
    "query,expected",
    [
        ("佳能R50", "canon_eos_r50"),
        ("ＳＯＮＹ　Ａ６７００", "sony_a6700"),
        ("富士 X S20", "fujifilm_x_s20"),
        ("尼康 Z 50", "nikon_z50"),
    ],
)
def test_camera_exact_aliases(query: str, expected: str) -> None:
    catalog = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml")
    assert catalog.resolve(query, "不清楚").profile_id == expected
    assert [p.profile_id for p in catalog.search(query)] == [expected]


@pytest.mark.parametrize("query", ["Canon EOS R50 V Future", "Nikon Z50 II Future", "Sony a6700 II"])
def test_unknown_camera_variant_does_not_inherit(query: str) -> None:
    catalog = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml")
    assert catalog.search(query) == []
    assert catalog.resolve(query, "不清楚").profile_id == "generic_unknown"


def test_camera_brand_search_does_not_resolve_as_specific_model() -> None:
    catalog = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml")
    matches = catalog.search("佳能")
    assert len(matches) >= 5
    assert all(p.brand == "Canon" for p in matches)
    assert catalog.resolve("佳能", "全画幅").profile_id == "generic_full_frame"


@pytest.mark.parametrize(
    "name",
    [
        "iPhone 15 Pro Future",
        "小米14 Ultra Future",
        "vivo X100 Pro Future",
        "荣耀 Magic6 Pro Future",
    ],
)
def test_unknown_phone_name_overrides_stale_known_selection(name: str, tmp_path: Path) -> None:
    result = pipeline(tmp_path).run(
        photo(),
        UserRequest(
            intent="拍人像",
            device_type="phone",
            device_model_name=name,
            phone_profile_id="xiaomi_14",
            phone_capture_mode="pro",
            phone_lens_id="telephoto",
            phone_pro_controls_confirmed=True,
        ),
    )
    assert result.camera_profile.profile_id == "generic_phone"
    assert result.camera_profile.display_name == f"{name}（能力未收录）"
    assert result.camera_profile.modes == ["auto"]
    assert result.camera_profile.lenses[0].aperture is None
    assert "自动" in result.recommendation.iso
    assert "S / SPEED" not in result.recommendation.shutter_speed
    assert any(name in note and "未收录" in note for note in result.recommendation.validation_notes)
    assert not (tmp_path / "unused.db").exists()


def test_unknown_camera_preserves_name_but_not_known_profile(tmp_path: Path) -> None:
    result = pipeline(tmp_path).run(
        photo(),
        UserRequest(
            intent="拍风景",
            camera_profile_id="canon_eos_r50",
            device_model_name="Canon EOS R8 Future",
            camera_format="全画幅",
        ),
    )
    assert result.camera_profile.profile_id == "generic_full_frame"
    assert result.camera_profile.display_name == "Canon EOS R8 Future（能力未收录）"
    assert any("不是该型号已核实" in note for note in result.recommendation.validation_notes)


@pytest.mark.parametrize(
    "device,name,expected",
    [("phone", " 苹果15 ", "apple_iphone_15"), ("camera", "佳能R50", "canon_eos_r50")],
)
def test_manual_exact_name_can_match_existing_catalog(
    device, name, expected, tmp_path: Path
) -> None:
    result = pipeline(tmp_path).run(
        photo(), UserRequest(intent="拍静物", device_type=device, device_model_name=name)
    )
    assert result.camera_profile.profile_id == expected
    assert "能力未收录" not in result.camera_profile.display_name


@pytest.mark.parametrize("name", ["x" * 121, "vivo\nX100", "camera\tmodel", "bad\x00", "bad\x7f"])
def test_model_name_validation(name: str) -> None:
    with pytest.raises(ValidationError):
        UserRequest(intent="拍静物", device_model_name=name)


def test_camera_ui_search_and_manual_input_clear_stale_result(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("CLOUD_API_KEY", "")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy")
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(tmp_path / "ui.db"))
    app = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    app.text_input(key="camera_model_query").set_value("佳能R50").run()
    assert app.selectbox(key="camera_model").value == "canon_eos_r50"
    app.session_state["last_result"] = pipeline(tmp_path).run(photo(), UserRequest(intent="拍静物"))
    app.text_input(key="camera_model_query").set_value("Nikon Z50 II Future").run()
    assert app.selectbox(key="camera_model").value == "generic_unknown"
    assert "last_result" not in app.session_state
    assert app.info
    app.text_input(key="camera_model_query").set_value("").run()
    app.text_input(key="camera_manual_model").set_value("Canon EOS R8").run()
    assert not app.exception


def test_unknown_camera_ui_does_not_present_generic_numbers_as_real_specs(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("CLOUD_API_KEY", "")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy")
    app = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    app.session_state["last_result"] = pipeline(tmp_path).run(
        photo(), UserRequest(intent="拍静物", device_model_name="Canon EOS R8 Future")
    )
    app.run()
    assert not app.exception
    assert any("能力未收录" in item.value for item in app.markdown)
    assert not any(
        "机械快门最高" in item.value or "标准 ISO" in item.value for item in app.markdown
    )
