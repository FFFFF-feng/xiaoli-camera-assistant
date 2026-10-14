"""Exercise the real scene catalog and conservative applicability boundary."""

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.models import (
    ExifInfo,
    ImageInspection,
    ImageMetrics,
    SceneAnalysis,
    UserRequest,
)
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase
from camera_assistant.services.phone_knowledge import PhoneKnowledgeBase
from camera_assistant.services.scene_knowledge import SceneKnowledgeBase
from camera_assistant.services.vision import DemoVisionAnalyzer

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = ROOT / "data/knowledge_drafts/photography-20261013"


def cards():
    return {
        record["knowledge_id"]: record
        for path in (COLLECTION / "upload_cards").glob("*.json")
        for record in [json.loads(path.read_text(encoding="utf-8"))]
    }


def inspection():
    return ImageInspection(
        exif=ExifInfo(camera_model="Reference photo camera, not target equipment"),
        metrics=ImageMetrics(
            width=320,
            height=240,
            mean_brightness=0.5,
            contrast=0.2,
            shadow_ratio=0.1,
            highlight_ratio=0.1,
            sharpness_score=50,
        ),
        model_image_data_url="data:image/jpeg;base64,fixture",
    )


def scene(**updates):
    return SceneAnalysis(
        scene_type="pet_portrait",
        subject="猫咪",
        environment="indoor",
        lighting="available light",
        brightness="medium",
        backlight=False,
        subject_motion="static",
        dynamic_range="medium",
        desired_effects=[],
        confidence=0.8,
    ).model_copy(update=updates)


def build_context(request, analysis, camera, subject="pet", localization=None):
    spec = importlib.util.find_spec("camera_assistant.knowledge.context")
    assert spec is not None, "The pipeline needs a shared, conservative context builder"
    module = importlib.import_module("camera_assistant.knowledge.context")
    return module.build_knowledge_conditions(request, analysis, camera, subject, localization)


@pytest.mark.parametrize(
    ("intent", "motion", "expected"),
    [
        ("拍建筑的垂直线", "静止", "architecture"),
        ("拍星空银河和前景", "静止", "astro_landscape"),
        ("拍鸟类飞行", "快速", "bird"),
        ("拍演唱会舞台", "缓慢", "concert_stage"),
        ("拍烟花绽放", "不确定", "fireworks"),
        ("拍雾天风光", "静止", "fog_landscape"),
        ("拍集体合影", "静止", "group_portrait"),
        ("拍室内篮球比赛", "快速", "indoor_sports"),
        ("拍微距花蕊", "静止", "macro"),
        ("拍车辆追随摇拍", "快速", "motion"),
        ("拍静止猫咪的表情", "静止", "pet_portrait"),
        ("拍棚拍人像", "静止", "portrait"),
        ("拍产品静物", "静止", "product_still"),
        ("拍雪景脚印", "静止", "snow_landscape"),
        ("拍窗边人像", "静止", "window_portrait"),
        ("拍正在奔跑的小猫", "快速", "fast_pet"),
        ("拍正在奔跑的小狗", "快速", "fast_pet"),
    ],
)
def test_runtime_candidates_distinguish_real_knowledge_categories(intent, motion, expected):
    catalog = SceneKnowledgeBase(ROOT / "knowledge/recognition/scene_profiles.yaml")
    candidates = catalog.find_candidates(
        UserRequest(intent=intent, subject_motion=motion), inspection()
    )
    assert candidates[0].profile_id == expected
    normalized = catalog.normalize(scene(scene_type=expected), candidates)
    assert normalized.scene_type == expected


def test_all_collection_scene_constraints_are_registered():
    catalog = SceneKnowledgeBase(ROOT / "knowledge/recognition/scene_profiles.yaml")
    missing = {
        value
        for card in cards().values()
        for value in (
            card["conditions"].get("scene", [])
            if isinstance(card["conditions"].get("scene"), list)
            else [card["conditions"].get("scene")]
        )
        if value is not None and value not in catalog.profile_by_id
    }
    assert missing == set()


@pytest.mark.parametrize(
    ("intent", "motion", "expected"),
    [
        ("拍猫咪静止趴着", "不确定", "pet_portrait"),
        ("拍正在奔跑的小猫", "静止", "pet_portrait"),
        ("拍静止小猫", "快速", "fast_pet"),
        ("拍猫咪的表情", "不确定", "pet_portrait"),
    ],
)
def test_explicit_motion_takes_precedence_over_subject_keyword(intent, motion, expected):
    catalog = SceneKnowledgeBase(ROOT / "knowledge/recognition/scene_profiles.yaml")
    candidates = catalog.find_candidates(
        UserRequest(intent=intent, subject_motion=motion), inspection()
    )
    assert candidates[0].profile_id == expected


@pytest.mark.parametrize(
    ("intent", "expected_motion"),
    [
        ("拍猫咪静止趴着", "static"),
        ("拍不静止的猫咪", "unknown"),
        ("拍不是正在奔跑的小猫", "unknown"),
        ("拍静止猫咪和正在奔跑的小猫", "unknown"),
        ("拍静止背景前正在奔跑的小猫", "fast"),
    ],
)
def test_direct_user_fact_reaches_scene_motion_without_inference_from_image(
    intent, expected_motion
):
    catalog = SceneKnowledgeBase(ROOT / "knowledge/recognition/scene_profiles.yaml")
    request = UserRequest(intent=intent)
    image = inspection()
    candidates = catalog.find_candidates(request, image)
    result = DemoVisionAnalyzer().analyze(image, request, candidates)
    assert result.subject_motion == expected_motion


def test_context_keeps_canonical_subject_and_omits_unprovided_device_facts():
    camera = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
        "generic_unknown", "不清楚"
    )
    context = build_context(UserRequest(intent="拍静止猫咪"), scene(), camera)
    assert context["scene"] == "pet_portrait"
    assert context["subject"] == "pet"
    assert context["motion"] == "static"
    assert context["subject_confirmed"] is False
    assert context["capture_mode"] == "still_photo"
    assert context["lighting"] == "available light"
    assert (
        not {"camera_model", "app", "os_major", "shutter_type", "drive_mode", "focus_mode"}
        & context.keys()
    )
    assert context["camera_profile_id"] == "generic_unknown"


def test_known_phone_derives_only_exact_model_native_app_and_requested_mode():
    phone = PhoneKnowledgeBase(ROOT / "knowledge/devices/phone_profiles.yaml").resolve("iPhone 15")
    context = build_context(UserRequest(intent="拍猫咪", device_type="phone"), scene(), phone)
    assert context["camera_model"] == "Apple iPhone 15"
    assert context["app"] == "Apple Camera"
    assert context["capture_mode"] == "photo"
    assert context["device_type"] == "phone"
    assert "camera_format" not in context
    assert "os_major" not in context


def test_known_phone_profile_cannot_be_replaced_by_free_text_target_model():
    phone = PhoneKnowledgeBase(ROOT / "knowledge/devices/phone_profiles.yaml").resolve("iPhone 15")
    request = UserRequest(intent="拍猫咪", device_type="phone").model_copy(
        update={
            "target_model_name": "Samsung Galaxy S24",
            "os_major": 18,
        }
    )
    context = build_context(request, scene(), phone)
    assert context["camera_model"] == "Apple iPhone 15"
    assert context["os_major"] == "iOS 18"
    assert context["app"] == "Apple Camera"
    assert not ManagedKnowledgeRetriever._applicable(
        cards()["photo20261011-equipment-s24ultra"]["conditions"], context
    )


def test_known_camera_profile_cannot_retrieve_a_different_body_from_free_text():
    camera = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
        "canon_eos_r50", "APS-C"
    )
    request = UserRequest(intent="拍风光").model_copy(update={"target_model_name": "Sony α7 IV"})
    context = build_context(request, scene(), camera)
    assert context["camera_model"] == "Canon EOS R50"
    assert context["camera_format"] == "APS-C"
    assert not ManagedKnowledgeRetriever._applicable(
        cards()["photo20261011-equipment-sony-a7iv"]["conditions"], context
    )


def test_known_phone_exact_alias_still_matches_the_selected_model():
    phone = PhoneKnowledgeBase(ROOT / "knowledge/devices/phone_profiles.yaml").resolve("iPhone 15")
    request = UserRequest(intent="拍猫咪", device_type="phone").model_copy(
        update={"target_model_name": "苹果15"}
    )
    context = build_context(request, scene(), phone)
    assert context["camera_model"] == "Apple iPhone 15"
    assert ManagedKnowledgeRetriever._applicable(
        cards()["photo20261011-equipment-iphone15"]["conditions"], context
    )


def test_only_explicit_target_lens_selects_a_lens_specific_card():
    camera = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
        "canon_eos_r50", "APS-C"
    )
    request = UserRequest(intent="拍产品").model_copy(
        update={"target_lens_name": "RF50mm F1.8 STM"}
    )
    context = build_context(request, scene(), camera)
    assert context["lens_model"] == "Canon RF50mm F1.8 STM"
    constraint = cards()["photo20261012-equipment-rf50"]["conditions"]
    assert ManagedKnowledgeRetriever._applicable(constraint, context)
    assert not ManagedKnowledgeRetriever._applicable(
        constraint, {**context, "lens_model": "Canon RF50mm F1.2 L USM"}
    )
    assert "lens_model" not in build_context(UserRequest(intent="拍产品"), scene(), camera)


def test_all_collection_condition_keys_are_part_of_the_runtime_contract():
    module = importlib.import_module("camera_assistant.knowledge.context")
    unknown = {
        key for card in cards().values() for key in card["conditions"]
    } - module.KNOWLEDGE_CONDITION_KEYS
    assert unknown == set()


def test_explicit_device_facts_match_existing_specific_card_values():
    camera = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
        "generic_full_frame", "全画幅"
    )
    request = UserRequest(intent="拍静物", subject_motion="静止").model_copy(
        update={
            "target_model_name": "Sony α7 IV",
            "shutter_type": "efcs",
            "drive_mode": "single",
            "focus_mode": "MF",
            "lighting_type": "flickering_artificial",
        }
    )
    context = build_context(request, scene(subject_motion="fast"), camera)
    assert context["camera_model"] == "Sony ILCE-7M4"
    assert context["shutter_type"] == "electronic_front_curtain"
    assert context["drive_mode"] == "single"
    assert context["focus_mode"] == "manual"
    assert context["lighting"] == "flickering_artificial"
    assert context["motion"] == "static"
    assert ManagedKnowledgeRetriever._applicable(
        cards()["photo20261013b2-equipment-a7iv-long-nr"]["conditions"], context
    )
    assert ManagedKnowledgeRetriever._applicable(
        cards()["photo20261013b2-technique-peaking-check"]["conditions"], context
    )


def test_explicit_phone_os_app_and_model_are_required_for_iphone16_cards():
    phone = PhoneKnowledgeBase(ROOT / "knowledge/devices/phone_profiles.yaml").resolve("unknown")
    request = UserRequest(intent="拍猫咪", device_type="phone").model_copy(
        update={
            "target_model_name": "iPhone 16 Pro",
            "camera_app": "Apple 相机",
            "os_major": 18,
        }
    )
    context = build_context(request, scene(), phone)
    assert context["camera_model"] == "Apple iPhone 16 Pro"
    assert context["app"] == "Apple Camera"
    assert context["os_major"] == "iOS 18"
    conditions = cards()["photo20261013-equipment-iphone16pro-live-max"]["conditions"]
    assert ManagedKnowledgeRetriever._applicable(conditions, context)
    assert not ManagedKnowledgeRetriever._applicable(
        conditions, {k: v for k, v in context.items() if k != "os_major"}
    )
    assert not ManagedKnowledgeRetriever._applicable(
        conditions, {**context, "camera_model": "Apple iPhone 16"}
    )


def test_electronic_shutter_does_not_guess_rolling_readout():
    camera = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
        "generic_unknown", "不清楚"
    )
    request = UserRequest(intent="拍运动", subject_motion="快速").model_copy(
        update={"shutter_type": "electronic"}
    )
    context = build_context(request, scene(subject_motion="fast"), camera)
    assert context["shutter_type"] == "electronic"
    assert not ManagedKnowledgeRetriever._applicable(
        cards()["photo20261013-technique-rolling-shutter-geometry"]["conditions"], context
    )


@pytest.mark.parametrize(
    ("knowledge_id", "field", "model"),
    [
        ("photo20261011-equipment-canon-r6ii", "camera_model", "Canon EOS R6 Mark II"),
        ("photo20261011-equipment-fuji-xt5", "camera_model", "FUJIFILM X-T5"),
        ("photo20261011-equipment-iphone15", "camera_model", "Apple iPhone 15"),
        ("photo20261011-equipment-nikon-z6iii", "camera_model", "Nikon Z6III"),
        ("photo20261011-equipment-s24ultra", "camera_model", "Samsung Galaxy S24 Ultra"),
        ("photo20261011-equipment-sony-a7iv", "camera_model", "Sony ILCE-7M4"),
        ("photo20261011-equipment-xiaomi14", "camera_model", "Xiaomi 14"),
        (
            "photo20261011-equipment-fuji-18-55-pending",
            "lens_model",
            "FUJINON XF18-55mmF2.8-4 R LM OIS",
        ),
        ("photo20261011-equipment-nikon-z24-70f4", "lens_model", "NIKKOR Z 24-70mm f/4 S"),
        ("photo20261012-equipment-rf50", "lens_model", "Canon RF50mm F1.8 STM"),
        ("photo20261012-equipment-z50", "lens_model", "NIKKOR Z 50mm f/1.8 S"),
    ],
)
def test_model_specific_equipment_never_matches_another_model(knowledge_id, field, model):
    card = cards()[knowledge_id]
    correct = {
        "device_type": "phone"
        if "iphone" in knowledge_id or "s24" in knowledge_id or "xiaomi" in knowledge_id
        else "camera",
        field: model,
    }
    assert ManagedKnowledgeRetriever._applicable(card["conditions"], correct)
    assert not ManagedKnowledgeRetriever._applicable(
        card["conditions"], {**correct, field: "Different model"}
    )
    assert not ManagedKnowledgeRetriever._applicable(
        card["conditions"], {"device_type": correct["device_type"]}
    )
    assert card["version"] >= 2
    assert card["source"]["retrieval_allowed"] is False


def test_unknown_context_condition_remains_excluded():
    assert not ManagedKnowledgeRetriever._applicable(
        {"unknown_condition": "confirmed"}, {"scene": "pet_portrait"}
    )


def test_single_photo_does_not_confirm_flickering_light():
    camera = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
        "canon_eos_r50", "APS-C"
    )
    observed = scene(lighting="flickering_artificial")
    unknown = build_context(UserRequest(intent="拍舞台人物"), observed, camera)
    required = cards()["photo20261013-technique-flicker-banding"]["conditions"]
    assert not ManagedKnowledgeRetriever._applicable(required, unknown)
    confirmed = build_context(
        UserRequest(intent="拍舞台人物", lighting_type="flickering_artificial"), observed, camera
    )
    assert ManagedKnowledgeRetriever._applicable(required, confirmed)


def test_collection_manifest_identifies_current_drafts_without_granting_retrieval():
    manifest = json.loads((COLLECTION / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["cards"]) == 121
    for entry in manifest["cards"]:
        path = COLLECTION / entry["file"]
        card = json.loads(path.read_text(encoding="utf-8"))
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert card["version"] == entry["version"]
        assert card["knowledge_id"] == entry["knowledge_id"]
        assert card["source"]["retrieval_allowed"] is False
