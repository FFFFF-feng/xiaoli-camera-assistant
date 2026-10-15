"""Offline checks of complete target fields, mode roles and bounded recovery."""
import json
from pathlib import Path

import pytest

from camera_assistant.models import CameraRecommendation, SceneAnalysis, UserRequest
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase
from camera_assistant.services.parameter_recovery import assess_parameters
from camera_assistant.services.validator import RecommendationValidator

ROOT = Path(__file__).resolve().parents[1]
SAVED = ROOT / "data/history/main-acceptance-20261014/live"


def camera():
    return CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
        "canon_eos_r50", "APS-C",
    )


def candidate(**updates):
    values = {
        "shooting_mode": "Av", "aperture": "f/8", "shutter_speed": "1/125s",
        "iso": "Auto ISO 上限3200", "exposure_compensation": "0 EV", "focus_mode": "AF-S",
        "metering_mode": "评价测光", "drive_mode": "单拍", "white_balance": "自动",
        "reasons": [], "risks": [], "adjustments": [], "confidence": .8,
    }
    values.update(updates)
    return CameraRecommendation(**values)


def review(**updates):
    source = candidate(**updates)
    request = UserRequest(intent="交代通道、玻璃棚和果实", max_aperture=4, focal_length_mm=35)
    scene = SceneAnalysis(
        scene_type="landscape", subject="通道", environment="unknown", lighting="unknown",
        brightness="medium", backlight=False, subject_motion="static", dynamic_range="high",
        desired_effects=[], confidence=.8,
    )
    result = RecommendationValidator().validate(source, request, scene, camera())
    return result, assess_parameters(result, request, camera(), source)


@pytest.mark.parametrize(("text", "expected"), [
    ("不慢于1/60 s", "1/60s 或更快"),
    ("快门速度>=1/60 s", "1/60s 或更快"),
    ("自动（目标1/60～1/125 秒）", "1/60s–1/125s"),
    ("由相机自动控制（需确保不低于安全快门约1/60s）", "1/60s 或更快"),
    ("8ms", "0.008s"), ("8–16ms", "0.008s–0.016s"),
])
def test_explicit_auto_shutter_targets_have_numeric_values_and_actual_readout_checks(text, expected):
    result, recovery = review(shutter_speed=text)
    assert result.shutter_speed == expected
    assert recovery.status == "complete"
    assert result.exposure_state.parameters["shutter_speed"].role == "auto_target"
    assert result.exposure_state.current_settings is None
    assert any("半按" in step and "实际快门" in step and expected in step
               for step in result.adjustments)
    assert not any("设置建议快门" in step for step in result.adjustments)
    assert any("绝对照度" in risk for risk in result.risks)


@pytest.mark.parametrize("text", ["1/60～1/125 秒", "0.008秒", "1/60s–1/125s"])
def test_existing_numeric_units_and_fraction_ranges_remain_valid(text):
    result, recovery = review(shutter_speed=text)
    assert result.shutter_speed == text
    assert recovery.status == "complete"


@pytest.mark.parametrize("text", [
    "自动", "自动（目标待定）", ">=1/60s", "自动（当前1/125s）",
    "自动（目标1/125s，手动固定1/60s）", "1/125s（手动固定）", "1/125s（保证清晰）",
    "1/0s", "-1/125s", "8ms秒", "1/125s ms", "1/125ms", "1/60s–1/0s",
    "1/60s–", "1/60s–1/125s–1/250s",
])
def test_invalid_ambiguous_or_conflicting_shutter_is_not_completed_from_prose(text):
    result, recovery = review(
        shutter_speed=text, reasons=["目标不慢于1/60s"],
        adjustments=["半按查看实际快门，低于1/60s时提高ISO至1600"],
    )
    assert recovery.status == "incomplete"
    assert recovery.missing_parameters == ["shutter_speed"]
    assert result.exposure_state.parameters["shutter_speed"].role == "unknown"
    assert "1/60" not in result.shutter_speed
    assert any("先" in item and "目标" in item for item in recovery.user_confirmations)
    assert any("半按" in item and "实际快门" in item for item in recovery.user_confirmations)
    assert not any("低于1/60s" in item for item in result.adjustments)


@pytest.mark.parametrize(("mode", "field", "value"), [
    ("M", "shutter_speed", "自动（目标1/125s）"),
    ("M", "aperture", "自动（目标f/8）"),
    ("Av", "aperture", "自动（目标f/8）"),
    ("Tv", "shutter_speed", "自动（目标1/125s）"),
])
def test_auto_target_declaration_cannot_become_manual_control(mode, field, value):
    result, recovery = review(shooting_mode=mode, iso="ISO 100", **{field: value})
    assert recovery.status == "incomplete"
    assert field in recovery.missing_parameters
    assert result.exposure_state.parameters[field].role == "unknown"


def test_tv_auto_aperture_target_keeps_manual_shutter_separate():
    result, recovery = review(shooting_mode="Tv", aperture="自动（目标f/4–f/8）")
    assert recovery.status == "complete"
    assert result.aperture == "f/4–f/8"
    assert result.exposure_state.parameters["aperture"].role == "auto_target"
    assert result.exposure_state.parameters["shutter_speed"].role == "manual_setting"


def test_manual_iso_control_wrapper_is_unambiguous_but_mixed_control_stays_unknown():
    result, recovery = review(iso="手动控制（100-400）")
    assert recovery.status == "complete"
    assert result.exposure_state.iso_control == "manual"
    result, recovery = review(iso="手动控制（100-400，或自动）")
    assert recovery.status == "incomplete"
    assert result.exposure_state.iso_control == "unknown"


def test_saved_d17_initial_target_and_corrected_omission_have_different_causes():
    initial = json.loads((SAVED / "D17-parameters-attempt1-parsed.json").read_text(encoding="utf-8"))
    corrected = json.loads((SAVED / "D17-parameters-attempt2-parsed.json").read_text(encoding="utf-8"))
    first, first_recovery = review(**initial)
    final, final_recovery = review(**corrected)
    assert first.shutter_speed == "1/60s 或更快"
    assert first.exposure_state.iso_control == "manual"
    assert "shutter_speed" not in first_recovery.missing_parameters
    assert final_recovery.status == "incomplete"
    assert final_recovery.missing_parameters == ["shutter_speed"]
    assert final.exposure_state.parameters["shutter_speed"].role == "unknown"


def test_interval_second_endpoint_is_seconds_not_an_invented_denominator():
    result, _ = review(shutter_speed="1/60–125s")
    assert result.shutter_speed == "1/60–125s"
    assert any("慢门" in risk and "手持" in risk for risk in result.risks)


@pytest.mark.parametrize("text", [
    "自动（需确保不低于1/60s）", "自动（需确保不慢于1/60s）",
    "自动（需确保快门速度不低于1/60s）",
])
def test_explicit_automatic_speed_check_does_not_require_the_word_safety(text):
    result, recovery = review(shutter_speed=text, iso="100")
    assert result.shutter_speed == "1/60s 或更快"
    assert recovery.status == "complete"
    assert result.exposure_state.parameters["shutter_speed"].role == "auto_target"


@pytest.mark.parametrize("text", [
    "自动（需确保曝光时间不低于1/60s）", "自动（需确保不低于1/0s）",
    "自动（需确保不低于1/60s，ISO800）",
])
def test_speed_check_cannot_swallow_time_dimension_or_other_parameter_prose(text):
    result, recovery = review(shutter_speed=text)
    assert recovery.status == "incomplete"
    assert result.exposure_state.parameters["shutter_speed"].role == "unknown"
