from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from camera_assistant.config import Settings
from camera_assistant.knowledge.importer import parse_record_file
from camera_assistant.knowledge.models import KnowledgeRecord, SourceInfo
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import CameraProfile, PhoneProfile, UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services.advisor import OpenAICompatibleRecommendationAdvisor
from camera_assistant.services.phone_advisor import DemoPhoneRecommendationAdvisor
from camera_assistant.services.phone_knowledge import PhoneKnowledgeBase
from camera_assistant.services.validator import RecommendationValidator

ROOT = Path(__file__).resolve().parents[1]


def phones() -> PhoneKnowledgeBase:
    return PhoneKnowledgeBase(ROOT / "knowledge/devices/phone_profiles.yaml")


def settings(db_path: Path, managed: bool = False) -> Settings:
    return Settings(
        demo_mode=True,
        api_key="",
        base_url="https://example.invalid/v1",
        vision_model="",
        text_model="",
        timeout_seconds=5,
        max_image_mb=15,
        knowledge_dir=ROOT / "knowledge",
        knowledge_mode="managed" if managed else "legacy",
        knowledge_db_path=db_path,
    )


def image_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (100, 80), (35, 35, 35)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("iPhone 15", "apple_iphone_15"),
        ("ＩＰＨＯＮＥ　１５", "apple_iphone_15"),
        ("苹果15", "apple_iphone_15"),
        ("apple_iphone_15", "apple_iphone_15"),
        ("Galaxy S24 Ultra", "samsung_galaxy_s24_ultra"),
        ("三星 S24 Ultra", "samsung_galaxy_s24_ultra"),
        ("小米14", "xiaomi_14"),
    ],
)
def test_exact_phone_aliases(identifier: str, expected: str) -> None:
    assert phones().resolve(identifier).profile_id == expected


@pytest.mark.parametrize(
    "identifier",
    [
        "iPhone 15 Pro",
        "iPhone 15 Plus",
        "iPhone 15 Pro Max",
        "小米14 Ultra",
        "小米14 Pro",
        "Galaxy S24",
        "Galaxy S24 FE",
    ],
)
def test_unknown_suffixes_do_not_inherit_nearby_model(identifier: str) -> None:
    assert phones().resolve(identifier).profile_id == "generic_phone"
    assert phones().search(identifier) == []


def test_phone_catalog_search_is_candidate_list_not_automatic_fuzzy_resolution() -> None:
    assert phones().search("小米")[0].profile_id == "xiaomi_14"
    assert phones().resolve("小米").profile_id == "generic_phone"
    assert len(phones().list_profiles()) == 4
    assert "pro" not in phones().resolve("iPhone 15").modes
    assert not hasattr(phones().resolve("iPhone 15"), "max_mechanical_shutter")


@pytest.mark.parametrize(
    "identifier", ["apple_iphone_15", "samsung_galaxy_s24_ultra", "xiaomi_14", "generic_phone"]
)
def test_phone_pipeline_does_not_use_camera_inputs_or_legacy_text(
    identifier: str, tmp_path: Path
) -> None:
    result = CameraAssistantPipeline(settings(tmp_path / "unused.db")).run(
        image_bytes(),
        UserRequest(
            intent="夜晚拍跑动的小狗",
            subject_motion="快速",
            device_type="phone",
            phone_profile_id=identifier,
            camera_profile_id="canon_eos_r50",
            camera_format="全画幅",
            focal_length_mm=800,
            max_aperture=16,
        ),
    )
    assert isinstance(result.camera_profile, PhoneProfile)
    assert result.camera_profile.profile_id == identifier
    assert result.knowledge_hits == []
    assert "自动" in result.recommendation.iso
    assert "自动" in result.recommendation.shutter_speed
    assert "f/16" not in result.recommendation.aperture
    assert "光圈优先" not in result.recommendation.shooting_mode
    assert not (tmp_path / "unused.db").exists()


def test_pro_mode_requires_current_ui_confirmation_and_never_invents_range(tmp_path: Path) -> None:
    pipeline = CameraAssistantPipeline(settings(tmp_path / "unused.db"))
    request = UserRequest(
        intent="拍运动主体",
        device_type="phone",
        phone_profile_id="xiaomi_14",
        phone_capture_mode="pro",
    )
    first = pipeline.run(image_bytes(), request)
    assert first.recommendation.iso.startswith("自动")
    second = pipeline.run(
        image_bytes(), request.model_copy(update={"phone_pro_controls_confirmed": True})
    )
    assert "未核验" in second.recommendation.iso
    assert "S / SPEED" in second.recommendation.shutter_speed
    assert "不指定数值" in second.recommendation.shutter_speed


def test_unsupported_mode_and_lens_are_normalized_before_retrieval(tmp_path: Path) -> None:
    result = CameraAssistantPipeline(settings(tmp_path / "empty.db", True)).run(
        image_bytes(),
        UserRequest(
            intent="用手机拍人像",
            device_type="phone",
            phone_profile_id="iPhone 15",
            phone_capture_mode="pro",
            phone_lens_id="telephoto_5x",
            phone_pro_controls_confirmed=True,
        ),
    )
    assert "照片 / 自动" in result.recommendation.shooting_mode
    assert "主摄" in result.recommendation.aperture
    assert "S / SPEED" not in result.recommendation.shutter_speed
    assert any("请求的手机模式" in note for note in result.knowledge_notes)
    assert any("请求的手机镜头" in note for note in result.knowledge_notes)


def test_validator_replaces_fabricated_controls_and_free_text(tmp_path: Path) -> None:
    request = UserRequest(
        intent="拍手机人像",
        device_type="phone",
        phone_profile_id="apple_iphone_15",
        phone_capture_mode="portrait",
    )
    pipeline = CameraAssistantPipeline(settings(tmp_path / "unused.db"))
    scene = pipeline.run(image_bytes(), request).scene
    phone = phones().resolve(request.phone_profile_id)
    baseline = DemoPhoneRecommendationAdvisor().recommend(request, scene, phone)
    fabricated = baseline.model_copy(
        update={
            "aperture": "f/8",
            "shutter_speed": "1/30000s",
            "iso": "ISO 102400",
            "shooting_mode": "Av 光圈优先",
            "focus_mode": "Servo AF",
            "reasons": ["请把iPhone物理光圈缩至f/8"],
            "confidence": 0.99,
        }
    )
    checked = RecommendationValidator().validate(fabricated, request, scene, phone)
    assert checked.aperture.startswith("主摄（1×） f/1.6")
    assert "景深滑块" in checked.aperture
    assert checked.iso.startswith("自动")
    assert all("f/8" not in text for text in checked.reasons)
    assert checked.confidence <= 0.65


def test_cloud_advisor_phone_branch_does_not_make_text_model_call(
    tmp_path: Path, monkeypatch
) -> None:
    request = UserRequest(
        intent="手机拍夜景", device_type="phone", phone_profile_id="apple_iphone_15"
    )
    scene = (
        CameraAssistantPipeline(settings(tmp_path / "unused.db")).run(image_bytes(), request).scene
    )
    import camera_assistant.services.advisor as advisor_module

    monkeypatch.setattr(
        advisor_module,
        "request_json",
        lambda *args, **kwargs: pytest.fail("手机受控指导不应发起文本请求"),
    )
    result = OpenAICompatibleRecommendationAdvisor(settings(tmp_path / "unused.db")).recommend(
        request, scene, [], phones().resolve("iPhone 15")
    )
    assert "Apple 相机" in result.shooting_mode


def test_managed_phone_conditions_exclude_camera_draft_and_unconfirmed_pro(tmp_path: Path) -> None:
    db = tmp_path / "managed.db"
    store = KnowledgeStore(db)
    for identifier, conditions, published in [
        ("phone-fixture", {"device_type": "phone", "phone_profile_id": "apple_iphone_15"}, True),
        ("camera-fixture", {"device_type": "camera"}, True),
        ("wrong-model", {"phone_profile_id": "xiaomi_14"}, True),
        (
            "unconfirmed-pro",
            {"phone_capture_mode": "pro", "phone_pro_controls_confirmed": True},
            True,
        ),
        ("draft-fixture", {"device_type": "phone"}, False),
    ]:
        record = KnowledgeRecord(
            knowledge_id=identifier,
            library_id="technique",
            title="手机夜景曝光测试",
            kind="guideline",
            content="合成软件行为测试，不是正式摄影知识。手机 夜景 曝光。",
            conditions=conditions,
            source=SourceInfo(name="测试素材", retrieval_allowed=True),
            author="test-author",
        )
        store.save_draft(record)
        if published:
            store.submit(identifier)
            store.approve(identifier, reviewer="test-reviewer")
            store.publish(identifier)
    result = CameraAssistantPipeline(settings(db, True)).run(
        image_bytes(),
        UserRequest(
            intent="手机夜景曝光",
            device_type="phone",
            phone_profile_id="iPhone 15",
            phone_capture_mode="pro",
            phone_pro_controls_confirmed=True,
        ),
    )
    assert [hit.metadata["knowledge_id"] for hit in result.knowledge_hits] == ["phone-fixture"]


def test_starter_rule_files_are_valid_drafts_outside_legacy_directory() -> None:
    files = sorted((ROOT / "data/knowledge_drafts/starter-v1").glob("*.md"))
    records = [parse_record_file(file) for file in files]
    assert len(records) == 17
    assert len({record.knowledge_id for record in records}) == 17
    assert sum(record.source.retrieval_allowed for record in records) == 5
    assert all(
        record.payload["verification"]["status"] == "needs_human_review" for record in records
    )
    assert all(record.source.url.startswith("https://") for record in records)
    assert all("content" not in record.model_dump()["payload"] for record in records)


def test_phone_ui_search_modes_and_unsupported_model(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy")
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(tmp_path / "ui.db"))
    app = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    assert not app.exception
    app.radio(key="capture_device").set_value("手机").run()
    app.text_input(key="phone_model_query").set_value("小米14").run()
    assert app.selectbox(key="phone_model").value == "xiaomi_14"
    app.selectbox(key="phone_mode").set_value("pro").run()
    assert app.checkbox(key="phone_pro_confirm").value is False
    app.checkbox(key="phone_pro_confirm").check().run()
    app.text_input(key="phone_model_query").set_value("iPhone 15").run()
    assert app.selectbox(key="phone_model").value == "apple_iphone_15"
    assert "专业 / Pro" not in app.selectbox(key="phone_mode").options
    assert (
        "phone_pro_confirm" not in app.session_state or not app.session_state["phone_pro_confirm"]
    )
    app.text_input(key="phone_model_query").set_value("iPhone 15 Pro").run()
    assert app.selectbox(key="phone_model").value == "generic_phone"
    assert app.info
    assert not app.exception


def test_phone_result_ui_renders_without_camera_only_fields(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy")
    request = UserRequest(
        intent="拍手机夜景", device_type="phone", phone_profile_id="apple_iphone_15"
    )
    result = CameraAssistantPipeline(settings(tmp_path / "unused.db")).run(image_bytes(), request)
    app = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    app.radio(key="capture_device").set_value("手机").run()
    app.session_state["last_result"] = result
    app.run()
    assert not app.exception
    assert any("Apple iPhone 15" in item.value for item in app.markdown)
    assert not any("机械快门最高" in item.value for item in app.markdown)


def test_camera_result_type_remains_unchanged(tmp_path: Path) -> None:
    result = CameraAssistantPipeline(settings(tmp_path / "unused.db")).run(
        image_bytes(), UserRequest(intent="相机拍风景")
    )
    assert isinstance(result.camera_profile, CameraProfile)
