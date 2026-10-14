import pytest

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


def camera_profile() -> CameraProfile:
    return CameraProfile(
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


def test_validator_respects_camera_native_iso_range() -> None:
    camera = camera_profile()
    request = UserRequest(intent="拍流水拉丝")
    result = RecommendationValidator().validate(
        recommendation(iso="ISO 100"), request, scene(), camera
    )

    assert result.iso == "ISO 160"
    assert "标准感光度范围" in "".join(result.validation_notes)


@pytest.mark.parametrize("shutter", ["1/125 秒", "1/125 sec", "1/125 S", "0.01秒"])
def test_fast_subject_accepts_chinese_and_english_shutter_units(shutter: str) -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), UserRequest(intent="拍运动员"), scene("fast")
    )
    assert result.shutter_speed == "1/500s 或更快"


@pytest.mark.parametrize("shutter", [
    "1/125 - 1/160 秒", "1/1000s - 1/60s", "1/60 sec - 1/1000 sec",
])
def test_fast_subject_checks_slowest_range_endpoint(shutter: str) -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), UserRequest(intent="拍运动员"), scene("fast")
    )
    assert result.shutter_speed == "1/500s 或更快"


@pytest.mark.parametrize("shutter", ["1 - 5秒", "1/125s - 1s", "1/125 - 1 秒"])
def test_handheld_checks_slowest_range_endpoint(shutter: str) -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), UserRequest(intent="拍静物"), scene()
    )
    assert any("手持容易模糊" in warning for warning in result.risks)


@pytest.mark.parametrize("shutter", ["1/125s - 1/64000s", "1/125 - 1/64000 秒"])
def test_camera_shutter_limit_checks_fastest_range_endpoint(shutter: str) -> None:
    request = UserRequest(intent="拍静物").model_copy(update={"shutter_type": "electronic"})
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), request, scene(), camera_profile()
    )
    assert result.shutter_speed == "1/32000s"


@pytest.mark.parametrize("shutter_type", [None, "mechanical", "efcs"])
def test_camera_only_uses_electronic_limit_when_explicitly_selected(shutter_type: str | None) -> None:
    request = UserRequest(intent="拍静物").model_copy(update={"shutter_type": shutter_type})
    result = RecommendationValidator().validate(
        recommendation(shutter_speed="1/8000s"), request, scene(), camera_profile()
    )
    assert result.shutter_speed == "1/4000s"
    assert "机械" in "".join(result.validation_notes)


def test_explicit_electronic_shutter_keeps_supported_speed() -> None:
    request = UserRequest(intent="拍静物").model_copy(update={"shutter_type": "electronic"})
    result = RecommendationValidator().validate(
        recommendation(shutter_speed="1/8000秒"), request, scene(), camera_profile()
    )
    assert result.shutter_speed == "1/8000秒"


def test_unconfirmed_electronic_shutter_uses_known_mechanical_boundary() -> None:
    request = UserRequest(intent="拍静物").model_copy(update={"shutter_type": "electronic"})
    camera = camera_profile().model_copy(update={"max_electronic_shutter": None})
    result = RecommendationValidator().validate(
        recommendation(shutter_speed="1/8000s"), request, scene(), camera
    )
    assert result.shutter_speed == "1/4000s"
    assert "未确认" in "".join(result.validation_notes)


@pytest.mark.parametrize("shutter", ["1/0s", "1/125s - 1/0s", "0秒"])
def test_invalid_shutter_values_do_not_crash_or_claim_verification(shutter: str) -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), UserRequest(intent="拍静物"), scene()
    )
    assert "无法校验" in "".join(result.risks)
    assert "1/0" not in result.shutter_speed


def test_model_validation_notes_are_replaced_by_code_generated_notes() -> None:
    result = RecommendationValidator().validate(
        recommendation(validation_notes=["机械快门4000秒", "已全面核验建议正确"]),
        UserRequest(intent="拍静物"), scene(), camera_profile(),
    )
    assert "机械快门4000秒" not in result.validation_notes
    assert "已全面核验建议正确" not in result.validation_notes
    assert any("机身能力" in note for note in result.validation_notes)


@pytest.mark.parametrize("shutter", ["1/16000", "1/125 - 1/16000", "1/16000–1/125"])
def test_unitless_fraction_shutter_cannot_bypass_camera_limit(shutter: str) -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), UserRequest(intent="拍静物"), scene(),
        camera_profile(),
    )
    assert result.shutter_speed == "1/4000s"


@pytest.mark.parametrize("shutter", [
    "1/1000 - 1/60", "1/1000s-1/60", "1/1000秒 - 1/60",
])
def test_fraction_range_with_shared_or_omitted_unit_checks_slow_endpoint(shutter: str) -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), UserRequest(intent="拍运动员"), scene("fast")
    )
    assert result.shutter_speed == "1/500s 或更快"


@pytest.mark.parametrize("shutter", ["1/125s - 1", "1/125 sec - 1", "1/125 - 1秒"])
def test_range_unit_on_either_endpoint_checks_handheld_limit(shutter: str) -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), UserRequest(intent="拍静物"), scene()
    )
    assert any("手持容易模糊" in warning for warning in result.risks)


@pytest.mark.parametrize("shutter", [
    "", "自动", "B门", "1/0", "1/125ms", "1/125s -", "1/125s - 未知",
    "ISO 400，f/8", "曝光补偿1/3EV，ISO400", "ISO 400，等待5秒", "1 - 5",
])
def test_unparseable_shutter_is_explicitly_unverified(shutter: str) -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), UserRequest(intent="拍静物"), scene(),
        camera_profile(),
    )
    assert "无法校验" in result.shutter_speed
    assert any("无法校验" in warning for warning in result.risks)


def test_clear_shutter_prefix_and_speed_modifier_are_accepted() -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed="快门：1/125 或更快"), UserRequest(intent="拍运动员"),
        scene("fast"),
    )
    assert result.shutter_speed == "1/500s 或更快"


@pytest.mark.parametrize("shutter", ["快门1/8000s", "建议1/8000s", "建议快门：约1/8000秒"])
def test_chinese_shutter_prefix_cannot_hide_hardware_limit(shutter: str) -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), UserRequest(intent="拍静物"), scene(),
        camera_profile(),
    )
    assert result.shutter_speed == "1/4000s"


def test_chinese_approximate_prefix_cannot_hide_motion_limit() -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed="约1/125秒"), UserRequest(intent="拍运动员"), scene("fast")
    )
    assert result.shutter_speed == "1/500s 或更快"


@pytest.mark.parametrize("shutter", [
    "1/125s (目标，由相机根据测光自动调整)",
    "1/125 秒（目标，由相机根据测光自动调整）",
    "1/125（由相机根据测光自动调整）",
])
def test_non_numeric_trailing_mode_annotation_keeps_valid_shutter(shutter: str) -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), UserRequest(intent="拍静物"), scene(),
        camera_profile(),
    )
    assert result.shutter_speed == shutter
    assert not any("无法校验" in warning for warning in result.risks)


def test_shutter_annotation_does_not_bypass_camera_limit() -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed="1/16000s（目标）"), UserRequest(intent="拍静物"), scene(),
        camera_profile(),
    )
    assert result.shutter_speed == "1/4000s"


def test_shutter_range_annotation_does_not_hide_slow_endpoint() -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed="1/1000s-1/60（由相机根据测光自动调整）"),
        UserRequest(intent="拍运动员"), scene("fast"),
    )
    assert result.shutter_speed == "1/500s 或更快"


@pytest.mark.parametrize("shutter", [
    "1/125s (也可改成1/60)", "1/125s（ISO 400）", "1/125s (EV -1)",
    "1/125s（400）", "1/125s（四百）", "1/125s（ＩＳＯ自动）", "1/125s（快门自动调整）",
    "1/125s（光圈优先）", "1/125s（默认单位为秒）", "1/125s（EV自动）",
    "1/125s（目标(自动)）", "1/125s ()", "1/125s（目标)",
    "1/125s（目标）还有说明", "1/125s 目标，由相机根据测光自动调整",
    "1/0s（目标）", "1 - 5（目标）",
])
def test_unsafe_or_incomplete_shutter_annotations_remain_unverified(shutter: str) -> None:
    result = RecommendationValidator().validate(
        recommendation(shutter_speed=shutter), UserRequest(intent="拍静物"), scene(),
        camera_profile(),
    )
    assert "无法校验" in result.shutter_speed
    assert any("无法校验" in warning for warning in result.risks)
