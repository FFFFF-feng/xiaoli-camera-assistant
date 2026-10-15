import json
from pathlib import Path

import pytest

from camera_assistant.models import (
    CameraRecommendation,
    CurrentCameraSettings,
    ExifInfo,
    SceneAnalysis,
    UserRequest,
)
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase
from camera_assistant.services.exposure import build_exposure_state, classify_iso, normalize_mode
from camera_assistant.services.validator import RecommendationValidator

ROOT = Path(__file__).resolve().parents[1]
SAVED = ROOT / "data" / "history" / "main-round-20261014-105503"


def advice(**changes: object) -> CameraRecommendation:
    values = {
        "shooting_mode": "M", "aperture": "f/8", "shutter_speed": "1/125s", "iso": "ISO 400",
        "exposure_compensation": "-0.7 EV", "focus_mode": "MF", "metering_mode": "评价测光",
        "drive_mode": "单拍", "white_balance": "自动", "reasons": [], "risks": [], "adjustments": [],
        "confidence": .8,
    }
    values.update(changes)
    return CameraRecommendation(**values)


def scene() -> SceneAnalysis:
    return SceneAnalysis(
        scene_type="landscape", subject="窗框", environment="室内", lighting="自然光",
        brightness="medium", backlight=False, subject_motion="static", dynamic_range="high",
        desired_effects=[], confidence=.8,
    )


def r50():
    return CameraKnowledgeBase(ROOT / "knowledge" / "cameras" / "camera_profiles.yaml").resolve(
        "canon_eos_r50", "APS-C",
    )


@pytest.mark.parametrize(("text", "expected"), [
    ("M", "M"), ("手动模式（M）", "M"), ("Ｍ档", "M"),
    ("A/Av 光圈优先", "Av"), ("A", "Av"), ("Tv/S", "Tv"),
    ("S 快门优先", "Tv"), ("P 程序自动", "P"), ("自动", "unknown"),
    ("M 或 Av", "unknown"), ("拍摄模式待定", "unknown"),
])
def test_mode_aliases_and_uncertainty(text: str, expected: str) -> None:
    assert normalize_mode(text) == expected


@pytest.mark.parametrize(("text", "expected"), [
    ("ISO 100", "manual"), ("400-800", "manual"), ("固定ISO100", "manual"),
    ("手动 ISO 400–800", "manual"), ("Auto ISO 100-3200", "auto"),
    ("自动ISO（上限 3200）", "auto"), ("ISO Auto", "auto"), ("ISO 自动", "auto"),
    ("待确认", "unknown"), ("ISO100 或自动", "unknown"), ("自动或手动", "unknown"),
    ("Auto ISO，可改手动 ISO 100", "unknown"),
])
def test_iso_states_do_not_treat_auto_limits_as_fixed(text: str, expected: str) -> None:
    assert classify_iso(text) == expected


def test_fixed_iso_manual_exposure_rebuilds_ev_reasons_and_fallback_steps() -> None:
    result = RecommendationValidator().validate(
        advice(reasons=["负补偿保护夜街灯光。", "ISO 400 可降低进光量。"],
               adjustments=["过亮时调 -0.3 EV。", "若主体对焦不实，请检查对焦点。"]),
        UserRequest(intent="保护夜街灯光与倒影", tripod=True, handheld=False), scene(), r50(),
    )
    assert "不适用" in result.exposure_compensation
    assert result.exposure_state.mode == "M"
    assert result.exposure_state.iso_control == "manual"
    assert result.exposure_state.parameters["exposure_compensation"].role == "not_applicable"
    assert "负补偿保护夜街灯光。" not in result.reasons
    assert "过亮时调 -0.3 EV。" not in result.adjustments
    assert any("对焦点" in item and "合焦" in item for item in result.adjustments)
    assert any("缩短曝光时间" in item for item in result.adjustments)


def test_known_manual_auto_iso_compensation_is_kept_conditionally() -> None:
    result = RecommendationValidator().validate(
        advice(iso="自动 ISO 100-12800"), UserRequest(intent="保护明亮舞台"), scene(), r50(),
    )
    assert result.iso == "自动 ISO 100-3200"
    assert result.exposure_compensation == "-0.7 EV"
    assert result.exposure_state.m_auto_iso_compensation == "supported"
    assert result.exposure_state.capability_source_url.startswith("https://cam.start.canon/")
    assert result.exposure_state.parameters["iso"].role == "auto_target"
    assert any("不使用闪光灯" in item and "是否响应" in item for item in result.adjustments)


def test_unknown_model_capability_is_not_guessed_or_taken_from_model_state() -> None:
    camera = r50().model_copy(update={"profile_id": "unverified_canon_model"})
    result = RecommendationValidator().validate(
        advice(iso="Auto ISO"), UserRequest(intent="拍街景"), scene(), camera,
    )
    assert result.exposure_state.m_auto_iso_compensation == "unknown"
    assert "未核验" in result.exposure_compensation
    assert not any("可增加曝光补偿" in item for item in result.adjustments)


@pytest.mark.parametrize(("mode", "manual", "automatic"), [
    ("Av", "aperture", "shutter_speed"), ("Tv", "shutter_speed", "aperture"),
])
def test_priority_mode_identifies_user_control_and_automatic_target(mode, manual, automatic):
    result = RecommendationValidator().validate(
        advice(shooting_mode=mode), UserRequest(intent="拍人像"), scene(), r50(),
    )
    assert result.exposure_state.parameters[manual].role == "manual_setting"
    assert result.exposure_state.parameters[automatic].role == "auto_target"
    assert result.exposure_state.parameters["exposure_compensation"].role == "manual_setting"
    assert any("相机" in reason and "自动" in reason for reason in result.reasons)


def test_unknown_mode_and_iso_have_no_claimed_compensation_control() -> None:
    for mode, iso in (("自动场景", "ISO 400"), ("Av", "按现场决定")):
        result = RecommendationValidator().validate(
            advice(shooting_mode=mode, iso=iso), UserRequest(intent="拍窗景"), scene(), r50(),
        )
        assert "先确认" in result.exposure_compensation
        assert result.exposure_state.parameters["exposure_compensation"].role == "unknown"


def test_reference_exif_and_max_aperture_do_not_become_current_user_settings() -> None:
    request = UserRequest(intent="拍猫", max_aperture=4,
                          current_settings=CurrentCameraSettings(mode="Av", aperture="f/8"))
    state = build_exposure_state(advice(aperture="f/5.6"), request, r50(),
                                 ExifInfo(aperture=2.8, iso=200))
    assert state.lens_max_aperture == 4
    assert state.current_settings.aperture == "f/8"
    assert state.reference_observations["aperture"].value == "2.8"
    assert state.reference_observations["aperture"].source == "reference_exif"
    assert state.parameters["aperture"].value == "f/5.6"
    empty = build_exposure_state(advice(), UserRequest(intent="拍猫", max_aperture=4), r50())
    assert empty.current_settings is None


def test_all_parameter_explanations_rebuilt_after_numeric_corrections() -> None:
    fast = scene().model_copy(update={"subject_motion": "fast"})
    result = RecommendationValidator().validate(
        advice(aperture="f/1.8 - f/2.8", shutter_speed="1/60s", iso="ISO 50",
               reasons=["f/1.8 保证背景分离，1/60秒足够清晰，ISO50确保曝光。"],
               risks=["ISO50可能偏暗。"], adjustments=["模糊时改1/125秒。"]),
        UserRequest(intent="冻结骑车的人", max_aperture=4), fast, r50(),
    )
    assert "f/1.8" not in " ".join([*result.reasons, *result.risks, *result.adjustments])
    assert "1/60" not in " ".join([*result.reasons, *result.risks, *result.adjustments])
    assert "ISO50" not in " ".join([*result.reasons, *result.risks, *result.adjustments])
    assert result.shutter_speed == "1/500s 或更快"
    assert result.iso == "ISO 100"
    assert result.exposure_state.parameters["shutter_speed"].value == result.shutter_speed


@pytest.mark.parametrize("photo", ["P02", "P03", "P08", "P10"])
def test_saved_real_parameter_candidates_offline_regression(photo: str) -> None:
    raw = json.loads((SAVED / f"{photo}-parameters-structured.json").read_text(encoding="utf-8"))
    pipeline = json.loads((SAVED / f"{photo}-pipeline.json").read_text(encoding="utf-8"))
    request = UserRequest(intent="重拍时检查完整主体与高光", max_aperture=4,
                          tripod=photo in {"P08", "P10"}, handheld=photo not in {"P08", "P10"})
    result = RecommendationValidator().validate(
        CameraRecommendation.model_validate(raw), request,
        SceneAnalysis.model_validate(pipeline["scene"]), r50(),
    )
    assert result.exposure_state.mode == "M"
    assert result.exposure_state.iso_control == "manual"
    assert "不适用" in result.exposure_compensation
    for field in ("reasons", "risks", "adjustments"):
        for text in getattr(result, field):
            assert "略微减小景深" not in text
            assert "负向曝光补偿，有助于" not in text
            assert "负曝光补偿（例如" not in text
            assert "进一步降低进光量" not in text


def test_correct_non_exposure_guidance_and_usable_exposure_action_survive() -> None:
    result = RecommendationValidator().validate(
        advice(adjustments=["颜色偏黄时按现场色温调整白平衡。", "对焦后放大检查眼睛。",
                            "高光过曝时先缩短曝光时间。"]),
        UserRequest(intent="拍夜景", handheld=False, tripod=True), scene(), r50(),
    )
    assert any("白平衡" in item and "现场光源" in item for item in result.adjustments)
    assert any("放大检查眼睛" in item for item in result.adjustments)
    assert any("缩短曝光时间" in text for text in result.adjustments)
    assert not any("颜色偏黄" in note for note in result.safety_notes)


@pytest.mark.parametrize("iso", [
    "Auto ISO (实际固定100)", "自动 ISO 100（手动）", "Auto ISO，固定 ISO 400",
    "自动 ISO 上限100，下限400", "Auto ISO (min 6400, max 3200)",
    "Auto ISO 上限3200，上限6400", "ISO Auto 上限3200，下限0",
    "ISO 800-100", "ISO 0",
])
def test_conflicting_iso_control_or_limits_cannot_enable_manual_auto_iso_ev(iso: str) -> None:
    assert classify_iso(iso) == "unknown"
    result = RecommendationValidator().validate(
        advice(iso=iso), UserRequest(intent="保护夜景灯光"), scene(), r50(),
    )
    assert result.exposure_state.iso_control == "unknown"
    assert result.exposure_state.parameters["exposure_compensation"].role == "unknown"
    assert "先确认" in result.exposure_compensation
    assert not any("确认正在使用 Auto ISO" in item for item in result.adjustments)


@pytest.mark.parametrize("iso", [
    "Auto ISO (min 100, max 3200)", "自动ISO 上限3200，下限100",
    "自动 ISO（范围为100–3200）", "ISO Auto max 3200", "Auto ISO 100-3200",
])
def test_coherent_auto_iso_limits_preserve_verified_manual_auto_compensation(iso: str) -> None:
    result = RecommendationValidator().validate(
        advice(iso=iso), UserRequest(intent="保护夜景灯光"), scene(), r50(),
    )
    assert result.exposure_state.iso_control == "auto"
    assert result.exposure_compensation == "-0.7 EV"
    assert any("不使用闪光灯" in item for item in result.adjustments)


@pytest.mark.parametrize("mode", ["Av", "Tv", "P"])
def test_priority_manual_iso_reason_accounts_for_automatic_exposure_response(mode: str) -> None:
    result = RecommendationValidator().validate(
        advice(shooting_mode=mode, iso="ISO400"), UserRequest(intent="拍窗景"), scene(), r50(),
    )
    iso_reasons = [reason for reason in result.reasons if reason.startswith("ISO ")]
    assert iso_reasons
    assert any("自动" in reason and "维持测光目标" in reason for reason in iso_reasons)
    assert not any("调整 ISO 可改变记录亮度" in reason for reason in iso_reasons)
    assert any("增加曝光补偿" in step for step in result.adjustments)


def test_manual_fixed_iso_underexposure_adjustment_survives_final_screen() -> None:
    result = RecommendationValidator().validate(
        advice(), UserRequest(intent="冻结运动时拍亮主体"), scene(), r50(),
    )
    assert any("若过暗" in step and "提高 ISO" in step for step in result.adjustments)


@pytest.mark.parametrize("bad_step", [
    "降低相机高度就让双眼占比更大。", "把相机放到地面一定能夸大眼部比例。",
    "向右挪动以后肯定让背景更简洁。", "使用MF绝对保证对焦准确。",
    "锁焦后肯定眼部锐利。",
])
def test_viewpoint_and_focus_guarantees_become_verifiable_trial_steps(bad_step: str) -> None:
    result = RecommendationValidator().validate(
        advice(adjustments=[bad_step]), UserRequest(intent="保留猫的完整身体"), scene(), r50(),
    )
    assert bad_step not in result.adjustments
    assert not any("一定能" in step or "肯定让" in step or "绝对保证" in step
                   for step in result.adjustments)
    assert any("试取景" in step or "合焦" in step for step in result.adjustments)


def test_all_reasons_are_generated_and_do_not_preserve_model_success_claims() -> None:
    bad_reasons = [
        "One-Shot确保对焦准确。", "评价测光总能平衡窗内外亮度。", "单拍确保所有照片锐利。",
        "自动白平衡一定正确。", "蹲下会放大猫双眼比例。",
    ]
    result = RecommendationValidator().validate(
        advice(reasons=bad_reasons), UserRequest(intent="保留猫的完整身体"), scene(), r50(),
    )
    assert all(reason not in result.reasons for reason in bad_reasons)
    assert any("对焦" in reason and "检查" in reason for reason in result.reasons)
    assert any("测光" in reason and "高动态范围" in reason for reason in result.reasons)
    assert any("连拍" in reason and "不能保证" in reason for reason in result.reasons)
    assert any("白平衡" in reason and "试拍" in reason for reason in result.reasons)
