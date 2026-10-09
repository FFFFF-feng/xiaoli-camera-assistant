from camera_assistant.models import (
    CameraProfile,
    CameraRecommendation,
    SceneAnalysis,
    UserRequest,
)
from camera_assistant.services.validator import RecommendationValidator


def recommendation(**updates: object) -> CameraRecommendation:
    values = {
        "shooting_mode": "A/Av",
        "aperture": "f/1.8",
        "shutter_speed": "1/125s",
        "iso": "Auto ISO",
        "exposure_compensation": "0 EV",
        "focus_mode": "AF-C",
        "metering_mode": "评价测光",
        "drive_mode": "高速连拍",
        "white_balance": "自动",
        "reasons": ["测试"],
        "risks": [],
        "adjustments": ["测试"],
        "confidence": 0.8,
    }
    values.update(updates)
    return CameraRecommendation(**values)


def scene(motion: str = "static") -> SceneAnalysis:
    return SceneAnalysis(
        scene_type="portrait",
        subject="person",
        environment="outdoor",
        lighting="available light",
        brightness="medium",
        backlight=False,
        subject_motion=motion,
        dynamic_range="medium",
        desired_effects=[],
        confidence=0.8,
    )


def test_validator_respects_lens_max_aperture() -> None:
    request = UserRequest(intent="拍人像", max_aperture=4.0)
    result = RecommendationValidator().validate(recommendation(), request, scene())

    assert result.aperture == "f/4（镜头最大光圈）"
    assert result.validation_notes


def test_validator_raises_shutter_for_fast_subject() -> None:
    request = UserRequest(intent="拍运动员", subject_motion="快速")
    result = RecommendationValidator().validate(recommendation(), request, scene("fast"))

    assert result.shutter_speed == "1/500s 或更快"


def test_validator_respects_camera_native_iso_range() -> None:
    camera = CameraProfile(
        profile_id="fujifilm_x_s20",
        brand="Fujifilm",
        model="X-S20",
        display_name="Fujifilm X-S20",
        sensor_format="APS-C",
        crop_factor=1.5,
        native_iso_min=160,
        native_iso_max=12800,
        recommended_auto_iso_max=3200,
        max_mechanical_shutter=4000,
        max_electronic_shutter=32000,
        ibis_stops=7,
        aperture_priority_name="A 光圈优先",
        shutter_priority_name="S 快门优先",
        continuous_focus_name="AF-C 连续自动对焦",
        single_focus_name="AF-S 单次自动对焦",
        metering_name="多重测光",
    )
    request = UserRequest(intent="拍流水拉丝")
    result = RecommendationValidator().validate(
        recommendation(iso="ISO 100"), request, scene(), camera
    )

    assert result.iso == "ISO 160"
    assert "标准感光度范围" in "".join(result.validation_notes)
