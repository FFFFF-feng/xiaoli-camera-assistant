from pathlib import Path

from camera_assistant.candidate_models import CandidateOperation, FactReference
from camera_assistant.composition_models import CompositionAdvice, CompositionProposal
from camera_assistant.models import CameraRecommendation, SceneAnalysis, UserRequest
from camera_assistant.services.advice_review import final_composition_review, review_operations
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase
from camera_assistant.services.validator import RecommendationValidator

ROOT = Path(__file__).resolve().parents[1]


def inputs():
    request = UserRequest(intent="保留猫的耳朵和胡须，简化背景", max_aperture=4,
                          focal_length_mm=50)
    scene = SceneAnalysis(scene_type="pet_portrait", subject="cat", environment="indoor",
                          lighting="available", brightness="medium", backlight=False,
                          subject_motion="static", dynamic_range="medium", desired_effects=[],
                          confidence=.8)
    camera = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
        "canon_eos_r50", "APS-C")
    raw = CameraRecommendation(shooting_mode="M", aperture="f/2", shutter_speed="1/125s",
        iso="100", exposure_compensation="-0.7 EV", focus_mode="AF-S", metering_mode="评价",
        drive_mode="单张", white_balance="自动", reasons=["负补偿可防止过曝"], risks=[],
        adjustments=["过亮时降低曝光补偿"], confidence=.9)
    rec = RecommendationValidator().validate(raw, request, scene, camera)
    return request, scene, camera, rec


def proposal(**changes):
    data = {"action_type": "camera_position", "goal": "简化背景", "actions": ["稍微降低机位，使猫眼更大"],
        "reasons": ["低机位放大眼睛"], "tradeoffs": ["当前光圈f/4会保证背景虚化"],
        "conditions": ["曝光补偿-0.7EV防止过曝", "光圈f/2"], "limitations": ["效果需试拍"]}
    return CompositionProposal(**(data | changes))


def test_final_parameters_replace_stale_composition_conditions_and_viewpoint_claims():
    request, scene, camera, rec = inputs()
    reviewed = final_composition_review(CompositionAdvice(status="unverified", proposals=[proposal()]),
                                        rec, request, scene, camera)
    item = reviewed.proposals[0]
    content = " ".join([*item.actions, *item.reasons, *item.conditions, *item.tradeoffs])
    assert "当前光圈" not in content and "光圈f/2" not in content
    assert "-0.7EV防止过曝" not in content and "猫眼更大" not in content
    assert "f/4" in content and "最终参数" in content and "现场" in content
    assert rec.exposure_state.mode == "M"


def test_reflection_list_or_forged_candidate_evidence_cannot_establish_entity_pair():
    request, scene, camera, rec = inputs()
    pair = proposal(goal="真实人物与倒影左右对称", actions=["向右调整使真实人物与倒影配对"])
    result = final_composition_review(CompositionAdvice(status="unverified", proposals=[pair]),
                                     rec, request, scene, camera)
    assert not result.proposals and result.status == "unavailable"


def test_candidate_json_and_quotes_do_not_prove_physics_or_unobserved_facts():
    request, scene, camera, rec = inputs()
    operations = [
        CandidateOperation(control="iso", target="camera", expected_effect="depth_of_field",
                           preconditions=[FactReference(source="user", key="intent", evidence="简化背景")]),
        CandidateOperation(control="shutter_type", target="camera", expected_effect="camera_shake",
                           preconditions=[FactReference(source="equipment", key="ibis_stops", evidence="0.0")]),
        CandidateOperation(control="shutter", target="camera", expected_effect="motion_blur",
                           preconditions=[FactReference(source="user", key="intent", evidence="并不存在的原文")]),
        CandidateOperation(control="iso", target="camera", expected_effect="recorded_brightness",
                           preconditions=[FactReference(source="image", key="brightness", evidence="medium")]),
    ]
    reviewed, notes = review_operations(operations, request, scene, camera, rec)
    assert reviewed == [] and len(notes) == 4


def test_supported_control_rule_with_actual_input_is_preserved():
    request, scene, camera, rec = inputs()
    operation = CandidateOperation(control="iso", target="iso", expected_effect="noise",
        preconditions=[FactReference(source="user", key="focal_length_mm", evidence="50")])
    reviewed, notes = review_operations([operation], request, scene, camera, rec)
    assert reviewed == [operation] and not notes


def test_valid_crop_geometry_and_action_survive_final_review():
    request, scene, camera, rec = inputs()
    item = proposal(action_type="crop", crop_bbox=[0, 0, 1, 1],
                    actions=["完整保留已选主体，检查耳尖与胡须余量"],
                    reasons=["该框保留主体范围"], conditions=["核对可见部位"])
    result = final_composition_review(CompositionAdvice(status="unverified", proposals=[item]),
                                     rec, request, scene, camera)
    assert result.proposals[0].crop_bbox == [0, 0, 1, 1]
    assert any("裁切框" in action and "可见" in action for action in result.proposals[0].actions)
    assert any("胡须" in condition for condition in result.proposals[0].conditions)


def test_reflection_only_plan_with_explicitly_negated_pair_is_preserved():
    request, scene, camera, rec = inputs()
    item = proposal(goal="保留倒影", actions=["不要求真实人物与倒影配对，仅保留倒影并检查边缘"])
    result = final_composition_review(CompositionAdvice(status="unverified", proposals=[item]),
                                     rec, request, scene, camera)
    assert len(result.proposals) == 1


def test_optional_candidate_metadata_does_not_discard_valid_proposal():
    item = proposal().model_dump()
    item["candidate_operations"] = [
        {"control": "camera_position", "target": "camera", "expected_effect": "framing",
         "preconditions": [{"source": "localization", "key": "bbox", "evidence": "cat"}]},
        {"control": "iso"},
    ]
    item["reviewed_operations"] = [{"model_claim": "全部正确"}]
    parsed = CompositionProposal.model_validate(item)
    request, scene, camera, rec = inputs()
    result = final_composition_review(CompositionAdvice(status="unverified", proposals=[parsed]),
                                     rec, request, scene, camera)
    assert len(result.proposals) == 1
    assert result.proposals[0].reviewed_operations == []
    assert any("未计为已审核" in note for note in result.notes)


def test_automatic_targets_cannot_be_reviewed_as_direct_manual_controls():
    request, scene, camera, _ = inputs()
    raw = CameraRecommendation(shooting_mode="Av", aperture="f/4", shutter_speed="1/125s",
        iso="100", exposure_compensation="0 EV", focus_mode="AF-S", metering_mode="评价",
        drive_mode="单张", white_balance="自动", reasons=[], risks=[], adjustments=[], confidence=.8)
    rec = RecommendationValidator().validate(raw, request, scene, camera)
    operations = [CandidateOperation(control="shutter", target="shutter_speed", expected_effect="motion_blur",
        preconditions=[FactReference(source="user", key="focal_length_mm", evidence="50")]),
        CandidateOperation(control="iso", target="iso", expected_effect="recorded_brightness",
        preconditions=[FactReference(source="user", key="focal_length_mm", evidence="50")])]
    reviewed, notes = review_operations(operations, request, scene, camera, rec)
    assert not reviewed and len(notes) == 2


def test_camera_position_claims_are_not_left_in_secondary_explanations():
    request, scene, camera, rec = inputs()
    item = proposal(actions=["向右挪即可消除背景干扰"],
        tradeoffs=["窗框框架感会更强"], conditions=["自然光下曝光可维持当前设置"],
        limitations=["仅能改善视觉密度，并确保层次效果"])
    reviewed = final_composition_review(CompositionAdvice(status="unverified", proposals=[item]),
                                        rec, request, scene, camera)
    content = " ".join([line for field in ("actions", "tradeoffs", "conditions", "limitations")
                        for line in getattr(reviewed.proposals[0], field)])
    assert "即可消除" not in content and "会更强" not in content
    assert "仅能改善" not in content and "确保层次" not in content
    assert "右" in content and "比较" in content


def test_wrong_focal_length_type_with_only_aperture_action_becomes_reshoot():
    request, scene, camera, rec = inputs()
    item = proposal(action_type="focal_length", goal="确保窗框植物风景全部清晰",
        actions=["保持35mm，将光圈缩小至f/8，确保全部清晰"], reasons=["小光圈保证全部清晰"])
    reviewed = final_composition_review(CompositionAdvice(status="unverified", proposals=[item]),
                                        rec, request, scene, camera)
    result = reviewed.proposals[0]
    assert result.action_type == "reshoot"
    assert "确保" not in result.goal and "保证" not in " ".join(result.reasons)


def test_eye_level_and_reflection_approach_keep_relative_movement_information():
    request, scene, camera, rec = inputs()
    for action, direction in [("将相机降低至与猫眼睛平齐，以保证眼睛比例更大", "降低相机高度"),
                              ("向玻璃方向微近，使反射细节必然更清楚", "靠近")]:
        item = proposal(actions=[action])
        reviewed = final_composition_review(CompositionAdvice(status="unverified", proposals=[item]),
                                            rec, request, scene, camera)
        content = " ".join(reviewed.proposals[0].actions)
        assert direction in content and "必然" not in content and "保证眼睛" not in content


def test_crop_output_only_certifies_visible_extent_and_labels_context_sources():
    request, scene, camera, rec = inputs()
    item = proposal(action_type="crop", crop_bbox=[0, 0, 1, 1],
        actions=["确保完整保留鸟身体，裁切必然不会损失任何部位"],
        conditions=["主体完整无截断，裁切会保留所有身体"],
        limitations=["裁切即可改善背景"], reasons=["主体完整"])
    advice = CompositionAdvice(status="unverified", proposals=[item],
        observations=["主体完整，没有截断", "当前使用35mm焦段，手持，无三脚架"])
    reviewed = final_composition_review(advice, rec, request, scene, camera)
    text = " ".join([*reviewed.proposals[0].actions, *reviewed.proposals[0].conditions,
                     *reviewed.observations])
    assert "必然不会" not in text and "主体完整，没有截断" not in text
    assert "当前使用35mm" not in text and "可见" in text
