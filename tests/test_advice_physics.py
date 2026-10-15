"""Regressions distilled from the real cat and waterfall trial answers."""
from pathlib import Path

import pytest

from camera_assistant.config import Settings
from camera_assistant.models import (
    ExifInfo,
    ImageInspection,
    ImageMetrics,
    SceneAnalysis,
    UserRequest,
)
from camera_assistant.services import advisor, composition
from camera_assistant.services.advice_safety import screen_parameter_advice
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase

ROOT = Path(__file__).resolve().parents[1]


def settings():
    return Settings(False, "synthetic-test-key", "https://example.invalid/v1", "synthetic-vlm",
                    "synthetic-vlm", 5, 15, ROOT / "knowledge")


def scene():
    return SceneAnalysis(scene_type="pet_portrait", subject="pet", environment="indoor",
                         lighting="available light", brightness="medium", backlight=False,
                         subject_motion="static", dynamic_range="medium", desired_effects=[],
                         confidence=.8)


def image():
    return ImageInspection(exif=ExifInfo(), metrics=ImageMetrics(
        width=1000, height=800, mean_brightness=.5, contrast=.2, shadow_ratio=.1,
        highlight_ratio=.01, sharpness_score=5,
    ), model_image_data_url="data:image/jpeg;base64,TEST")


def proposal(actions, reasons=None, limitations=None, action_type="camera_position"):
    return {"action_type": action_type, "goal": "保留主体并改善构图", "actions": actions,
                "reasons": reasons or ["先检查实际取景"], "tradeoffs": ["需要现场试拍"],
                "conditions": ["现场允许安全调整"], "limitations": limitations or ["效果需实拍确认"],
                "knowledge_ids": [], "crop_bbox": None}


def composition_result(monkeypatch, proposals, max_aperture=4):
    monkeypatch.setattr(composition, "request_json", lambda *args: {
        "status": "unverified", "observations": [], "uncertainties": [], "proposals": proposals, "notes": [],
    })
    request = UserRequest(intent="完整保留猫耳朵和胡须，简化背景", focal_length_mm=50,
                          max_aperture=max_aperture)
    camera = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
        "canon_eos_r50", "APS-C")
    return composition.OpenAICompatibleCompositionAdvisor(settings()).recommend(
        image(), request, scene(), None, [], camera)


def test_rejects_real_trial_claim_retreat_makes_subject_larger(monkeypatch):
    result = composition_result(monkeypatch, [proposal(
        ["保持50mm焦段，后退并调整机位，使猫在画面中占据更大比例"],
        ["后退可放大主体，同时完整保留耳朵和胡须"],
    )])
    assert result.status == "unavailable"
    assert result.proposals == []


def test_preserves_valid_retreat_to_protect_edges_and_safe_alternative(monkeypatch):
    result = composition_result(monkeypatch, [
        proposal(["后退让主体更大"]),
        proposal(["保持50mm焦段，稍后退并检查四边余量，完整保留耳尖和胡须"],
                 ["后退会减小主体占比，能留下边缘余量"]),
    ])
    assert len(result.proposals) == 1
    assert "检查四边余量" in result.proposals[0].actions[0]


def test_rejects_larger_focal_length_claiming_smaller_subject_without_moving(monkeypatch):
    result = composition_result(monkeypatch, [proposal(
        ["保持机位，将焦段从50mm增加到85mm"],
        limitations=["焦段增加可能缩小猫在画面中的占比"], action_type="focal_length",
    )])
    assert result.proposals == []


def test_moving_and_changing_focal_length_is_not_a_fixed_geometry_claim(monkeypatch):
    result = composition_result(monkeypatch, [proposal(
        ["若镜头支持85mm，可后退并改用85mm，现场调整直到画面比例合适"],
        ["焦段与距离同时变化，主体占比须按实际取景判断"],
    )])
    assert len(result.proposals) == 1


def test_rejects_real_trial_wrong_aperture_stop_count(monkeypatch):
    result = composition_result(monkeypatch, [proposal(
        ["光圈设为f/8，比最大光圈f/5.6小2档"], action_type="reshoot",
    )], max_aperture=5.6)
    assert result.proposals == []


@pytest.mark.parametrize("instruction", [
    "保持f/8，ISO从100增加2档到400",
    "光圈在当前值基础上缩小1档至f/8并观察直方图",
])
def test_stop_screen_does_not_invent_current_aperture_or_compare_iso(monkeypatch, instruction):
    result = composition_result(monkeypatch, [proposal([instruction], action_type="reshoot")], max_aperture=5.6)
    assert len(result.proposals) == 1


def test_retreat_contradiction_across_actions_and_reasons_is_rejected(monkeypatch):
    result = composition_result(monkeypatch, [proposal(
        ["保持50mm焦距，向后退一点"], ["这样主体会更大"],
    )])
    assert result.proposals == []


def test_negated_retreat_contradiction_is_preserved(monkeypatch):
    result = composition_result(monkeypatch, [proposal(["保持50mm焦距，不要后退让主体更大"])])
    assert len(result.proposals) == 1


def test_current_equipment_prompt_contains_measured_constraints_not_guessed_distance(monkeypatch):
    captured = {}
    def reply(_settings, payload):
        captured.update(payload)
        return {"status": "unverified", "observations": [], "uncertainties": [],
                    "proposals": [proposal(["保持50mm镜头，调整机位并检查四边余量"])], "notes": []}
    monkeypatch.setattr(composition, "request_json", reply)
    request = UserRequest(intent="保留猫耳朵胡须", focal_length_mm=50, max_aperture=5.6)
    camera = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
        "canon_eos_r50", "APS-C")
    composition.OpenAICompatibleCompositionAdvisor(settings()).recommend(
        image(), request, scene(), None, [], camera)
    text = captured["messages"][0]["content"][0]["text"]
    assert "后退" in text and "减小" in text
    assert "最近对焦距离" in text
    assert "先使用当前" in text


def parameter_result(monkeypatch, *, risks, adjustments=None):
    model_answer = {
        "shooting_mode": "S 快门优先", "aperture": "f/8", "shutter_speed": "1秒", "iso": "ISO 100",
        "exposure_compensation": "0 EV", "focus_mode": "AF-S", "metering_mode": "矩阵测光",
        "drive_mode": "单张", "white_balance": "自动", "reasons": ["先试拍检查高光"],
        "risks": risks, "adjustments": adjustments or ["观察直方图后调整"], "confidence": .9,
        "validation_notes": [],
    }
    monkeypatch.setattr(advisor, "request_json", lambda *args: model_answer)
    candidate = advisor.OpenAICompatibleRecommendationAdvisor(settings()).recommend(
        UserRequest(intent="三脚架拍瀑布拉丝", focal_length_mm=24, max_aperture=5.6), scene(), [],
        CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
            "nikon_z50", "APS-C"),
    )
    # These unit tests exercise legacy prose triage; production invokes this
    # reviewer after the final validator has resolved all parameter values.
    return screen_parameter_advice(candidate, UserRequest(
        intent="三脚架拍瀑布拉丝", focal_length_mm=24, max_aperture=5.6))


def test_removes_real_trial_wrong_underexposure_fix(monkeypatch):
    result = parameter_result(monkeypatch, risks=[
        "小光圈需配合低ISO或负曝光补偿，否则可能导致欠曝",
        "无ND镜时需要检查高光是否过曝",
    ])
    assert len(result.risks) == 1
    assert "无ND" in result.risks[0]
    assert result.confidence <= .6


def test_does_not_remove_legitimate_low_iso_to_avoid_overexposure(monkeypatch):
    result = parameter_result(monkeypatch, risks=["若过曝，降低ISO或曝光补偿并重新检查高光"])
    assert result.risks == ["若过曝，降低ISO或曝光补偿并重新检查高光"]


def test_rejects_iso_claimed_to_change_incident_light(monkeypatch):
    result = composition_result(monkeypatch, [proposal(
        ["降低ISO至100并检查高光"], ["降低ISO（100）减少进光量"], action_type="reshoot",
    )])
    assert result.proposals == []


def test_keeps_iso_brightness_explanation(monkeypatch):
    result = composition_result(monkeypatch, [proposal(
        ["降低ISO至100并检查高光"], ["降低ISO可降低记录亮度，仍需按直方图试拍"], action_type="reshoot",
    )])
    assert len(result.proposals) == 1


def test_removes_small_aperture_claimed_to_cause_overexposure(monkeypatch):
    result = parameter_result(monkeypatch, risks=[
        "选择f/8以避免因光圈过小导致过曝或快门过慢",
        "无ND时请检查慢门是否过曝",
    ])
    assert result.risks == ["无ND时请检查慢门是否过曝"]
    assert result.safety_notes


def test_keeps_small_aperture_correctly_reducing_light(monkeypatch):
    text = "缩小光圈不会导致过曝；固定快门和ISO时可减少进光量"
    result = parameter_result(monkeypatch, risks=[text])
    assert result.risks == [text]


def test_unmeasured_precise_distance_is_not_shown_as_an_instruction(monkeypatch):
    result = parameter_result(monkeypatch, risks=[], adjustments=[
        "50mm焦段下建议拍摄距离0.5-1米，靠近主体以突出眼睛",
        "对焦猫眼后试拍，并检查耳尖和胡须四周的余量",
    ])
    assert len(result.adjustments) == 1
    assert "检查耳尖" in result.adjustments[0]


def test_user_context_input_is_optional_but_invalid_values_are_rejected():
    from pydantic import ValidationError

    request = UserRequest(intent="摄影需求", target_model_name=" Sony A7 IV ",
                          target_lens_name=" RF50mm F1.8 STM ", os_major=18,
                          shutter_type="efcs", drive_mode="single", focus_mode="MF")
    assert request.target_model_name == "Sony A7 IV"
    assert request.target_lens_name == "RF50mm F1.8 STM"
    with pytest.raises(ValidationError):
        UserRequest(intent="摄影需求", os_major=-1)
    with pytest.raises(ValidationError):
        UserRequest(intent="摄影需求", shutter_type="invented-shutter")
