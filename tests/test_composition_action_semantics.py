"""Movement reviews must preserve kind, object, condition and original evidence."""
import json
from pathlib import Path

import pytest

from camera_assistant.composition_models import CompositionAdvice
from camera_assistant.config import Settings
from camera_assistant.models import (
    CameraProfile,
    CameraRecommendation,
    ImageInspection,
    SceneAnalysis,
    UserRequest,
)
from camera_assistant.services.advice_review import final_composition_review
from camera_assistant.services.composition import _validate_advice

ROOT = Path(__file__).resolve().parents[1]
SAVED = ROOT / "data/history/main-acceptance-20261014/live"


def review_case(case, actions=None, intent=None):
    saved = json.loads((SAVED / f"{case}-pipeline.json").read_text("utf-8"))
    manifest = json.loads((SAVED / "manifest.json").read_text("utf-8"))
    request = UserRequest.model_validate(next(item["request"] for item in manifest["cases"]
                                              if item["id"] == case))
    if intent:
        request = request.model_copy(update={"intent": intent})
    advice = CompositionAdvice.model_validate_json(
        (SAVED / f"{case}-composition-attempt1-parsed.json").read_text("utf-8"))
    if actions is not None:
        advice = advice.model_copy(update={"proposals": [advice.proposals[0].model_copy(
            update={"actions": actions})]})
    return final_composition_review(advice, CameraRecommendation.model_validate(saved["recommendation"]),
                                    request, SceneAnalysis.model_validate(saved["scene"]),
                                    CameraProfile.model_validate(saved["camera_profile"]))


def test_saved_sideways_camera_action_is_not_pitch_and_keeps_exact_source():
    result = review_case("D01")
    item = result.proposals[1]
    assert "俯仰" not in " ".join(item.actions)
    assert any(action.kind == "lateral_translation" and action.target == "camera"
               for action in item.trial_actions)
    assert item.action_evidence == ["略微向侧面移动相机，改变拍摄角度", "保持当前焦距50mm不变"]
    assert all(action.source_text in item.action_evidence for action in item.trial_actions)


@pytest.mark.parametrize(("action", "kind", "target"), [
    ("相机向右横移，比较拍摄角度", "lateral_translation", "camera"),
    ("相机稍微后退，比较前后关系", "depth_translation", "camera"),
    ("抬高相机高度", "height_translation", "camera"),
    ("保持高度，将镜头略向下俯拍", "pitch", "camera"),
    ("保持机位，轻微旋转相机", "rotation", "camera"),
    ("请人物微微转脸", "subject_pose", "subject"),
    ("如果灯具可移动，将灯向左移", "light_position", "light"),
])
def test_distinct_action_kinds_are_not_inferred_from_generic_angle(action, kind, target):
    item = review_case("D01", [action]).proposals[0]
    assert [(move.kind, move.target) for move in item.trial_actions] == [(kind, target)]


def test_negation_and_conditional_moves_do_not_turn_into_unconditional_camera_moves():
    actions = ["不要向左移动相机；如果安全通道允许，才向右横移相机；不要旋转相机",
               "如果人物愿意，才请人物略向左转脸"]
    item = review_case("D01", actions).proposals[0]
    assert {move.kind for move in item.trial_actions} == {"lateral_translation", "subject_pose"}
    assert all(move.condition for move in item.trial_actions)
    assert "向左试取景" not in " ".join(item.actions)
    assert not any(move.kind == "rotation" for move in item.trial_actions)


def test_generic_angle_does_not_invent_pitch_and_unknown_text_stays_evidence():
    result = review_case("D01", ["比较拍摄角度，观察镜片反光与眼睛位置"])
    item = result.proposals[0]
    assert item.action_evidence == ["比较拍摄角度，观察镜片反光与眼睛位置"]
    assert not item.trial_actions
    assert "俯仰" not in " ".join(item.actions)


def test_source_and_program_checks_are_not_accepted_from_model_metadata(monkeypatch):
    from camera_assistant.services import composition

    raw = json.loads((SAVED / "D01-composition-attempt1-parsed.json").read_text("utf-8"))["proposals"][0]
    raw.update(action_evidence=["伪造原文"], trial_actions=[{"kind": "pitch"}],
               field_checks=[{"issue": "伪造检查已通过"}])
    saved = json.loads((SAVED / "D01-pipeline.json").read_text("utf-8"))
    monkeypatch.setattr(composition, "request_json", lambda *_: {
        "status": "unverified", "proposals": [raw]})
    advisor = composition.OpenAICompatibleCompositionAdvisor(Settings(
        demo_mode=False, api_key="offline-test-key", base_url="https://example.invalid/v1",
        vision_model="offline", text_model="offline", timeout_seconds=5,
        max_image_mb=15, knowledge_dir=ROOT / "knowledge"))
    result = advisor.recommend(
        ImageInspection.model_validate(saved["inspection"] | {"model_image_data_url": "data:image/jpeg;base64,TEST"}),
        UserRequest(intent="减少眼镜反光"), SceneAnalysis.model_validate(saved["scene"]), None, [],
        CameraProfile.model_validate(saved["camera_profile"]))
    parsed = result.proposals[0]
    assert parsed.action_evidence == [] and parsed.trial_actions == [] and parsed.field_checks == []


def test_saved_program_evidence_and_field_checks_survive_json_roundtrip():
    result = review_case("D01")
    restored = CompositionAdvice.model_validate_json(result.model_dump_json())
    assert restored.proposals[1].action_evidence == ["略微向侧面移动相机，改变拍摄角度", "保持当前焦距50mm不变"]
    assert restored.proposals[1].field_checks == result.proposals[1].field_checks
    assert restored.proposals[1].trial_actions == result.proposals[1].trial_actions


def test_reflection_checks_preserve_eyes_smile_and_compare_geometry_without_asserting_occlusion():
    item = review_case("D01").proposals[1]
    checks = " ".join(check.model_dump_json() for check in item.field_checks)
    assert all(term in checks for term in ("眼睛", "镜片", "脸", "光源", "笑脸", "对焦"))
    assert "遮住眼睛" not in checks and "遮挡眼睛" not in checks
    assert "光源位置未知" in checks
    assert "旋转" in checks and "不保证" in checks


def test_flower_checks_keep_focus_contour_and_black_background_without_moving_light_claim():
    item = review_case("B08").proposals[0]
    actions = " ".join(item.actions)
    checks = " ".join(check.model_dump_json() for check in item.field_checks)
    assert "使光线从侧面照射" not in actions
    assert all(term in checks for term in ("花瓣", "合焦", "轮廓", "黑背景"))
    assert "不会改变" in checks and "光源" in checks
    assert all(check.observe and check.accept_when and check.protect and check.basis
               for check in item.field_checks)


def test_basketball_checks_include_tracking_ball_hand_headroom_limbs_and_unknown_flicker():
    item = review_case("D10").proposals[0]
    checks = " ".join(check.model_dump_json() for check in item.field_checks)
    assert all(term in checks for term in ("跟焦", "球", "手", "上方", "四肢", "附近队员", "频闪未知"))
    assert "轨迹" not in checks and "球速" not in checks
    assert "观众" in checks and "核对" in checks


def test_specific_checks_are_scoped_to_user_goals_not_a_universal_image_checklist():
    item = review_case("D01", ["相机向右横移"], "保留猫的耳朵和胡须，简化背景").proposals[0]
    checks = " ".join(check.model_dump_json() for check in item.field_checks)
    assert "频闪" not in checks and "花瓣" not in checks and "镜片" not in checks


def test_invalid_knowledge_reference_does_not_discard_independent_composition():
    raw = json.loads((SAVED / "D01-composition-attempt1-parsed.json").read_text("utf-8"))
    raw["proposals"][0]["knowledge_ids"] = ["made-up@v99"]
    result = _validate_advice(CompositionAdvice.model_validate(raw), None, [])
    assert len(result.proposals) == 2 and result.proposals[0].knowledge_ids == []
    assert result.status == "unverified"
    assert any("引用" in note and "隔离" in note for note in result.notes)


@pytest.mark.parametrize("action", ["模特向后退", "人物向左移", "请主体稍微靠近"])
def test_subject_translation_is_not_camera_translation(action):
    item = review_case("D01", [action]).proposals[0]
    assert item.trial_actions and all(move.target == "subject" for move in item.trial_actions)


def test_multiple_possible_action_objects_are_not_resolved_by_regex_order():
    result = review_case("D01", ["相机和灯具一起向左移动，比较取景"])
    assert result.proposals[0].trial_actions == []
    assert "相机和灯具一起向左移动，比较取景" in result.proposals[0].action_evidence


def test_ordinary_glasses_goal_does_not_invent_hat_or_lateral_camera_motion():
    item = review_case("D01", ["抬高相机高度"]).proposals[0]
    checks = " ".join(check.model_dump_json() for check in item.field_checks)
    assert "帽子" not in checks and "横移前后" not in checks


@pytest.mark.parametrize("action", ["别向左移动相机", "勿旋转相机", "不向右横移相机"])
def test_alternate_negative_instructions_never_turn_into_positive_moves(action):
    result = review_case("D01", [action + "；只比较取景"])
    assert not result.proposals[0].trial_actions


@pytest.mark.parametrize(("intent", "forbidden"), [
    ("保留镜片反光，不要减少眼镜反光，眼睛保持可见", "相对角度"),
    ("这朵花的花瓣轮廓不要更锐利，只要保留朦胧的黑背景花影", "合焦"),
    ("不要凝固动作，不必跟焦，拍成模糊篮球拖影", "连续跟焦"),
])
def test_negated_user_goals_do_not_generate_the_opposite_field_trial(intent, forbidden):
    item = review_case("D01", ["相机向右横移，比较取景"], intent).proposals[0]
    assert forbidden not in " ".join(check.model_dump_json() for check in item.field_checks)


def test_negative_distance_instruction_does_not_suppress_independent_positive_goal():
    item = review_case("B08", ["向右横移相机"],
        "不要靠近这朵花，我还是想让花瓣边缘更分明，并保持黑背景").proposals[0]
    assert any("合焦" in check.observe for check in item.field_checks)


def test_only_explicitly_conditional_user_goal_stays_conditional_in_program_checks():
    item = review_case("D01", ["相机向右横移，比较取景"],
        "如果人物愿意并且现场能安全移动，才试试减少眼镜反光，否则保留原样").proposals[0]
    assert item.field_checks
    assert all("如果人物愿意并且现场能安全移动" in check.accept_when
               for check in item.field_checks)


@pytest.mark.parametrize(("intent", "forbidden"), [
    ("戴眼镜的人像，我想减少镜片反光", "笑脸"),
    ("白花的花瓣边缘更分明，并保持黑背景", "红花"),
    ("拍一个篮球运动员，持续跟焦并保留他的完整动作", "两位争球者"),
    ("拍一个篮球运动员，持续跟焦并保留他的完整动作", "附近队员"),
])
def test_subject_details_not_named_in_user_goal_are_not_invented(intent, forbidden):
    item = review_case("D01", ["向右横移相机，比较取景"], intent).proposals[0]
    assert forbidden not in " ".join(check.model_dump_json() for check in item.field_checks)


def test_postverb_subject_object_is_not_a_camera_instruction():
    item = review_case("D01", ["向右移动人物，保持相机不动"]).proposals[0]
    assert all(move.target == "subject" for move in item.trial_actions)
    assert item.action_evidence == ["向右移动人物，保持相机不动"]


def test_advisory_negation_is_not_an_executable_direction():
    item = review_case("D01", ["不宜向左移动相机，只比较取景"]).proposals[0]
    assert not item.trial_actions


def test_unresolved_otherwise_branch_is_preserved_without_inheriting_wrong_condition():
    result = review_case("D01", ["如果现场空间不足，就不要后退，否则稍微靠近"])
    assert not result.proposals
    assert any("模型动作原文待确认" in note and "如果现场空间不足，就不要后退，否则稍微靠近" in note
               for note in result.notes)


@pytest.mark.parametrize("action", [
    "向人物右侧移动约15-30度，改变反光角度", "相机向人物右侧移动，比较反光",
])
def test_person_as_spatial_reference_is_not_the_actor_being_moved(action):
    item = review_case("D01", [action]).proposals[0]
    assert [(move.kind, move.target) for move in item.trial_actions] == [("lateral_translation", "camera")]
    assert "15" not in " ".join(item.actions)
    assert item.action_evidence == [action]


def test_pitch_action_with_a_height_description_does_not_invent_height_translation():
    item = review_case("D01", ["将相机向上倾斜约5-10度，从略高于眼睛水平拍摄"]).proposals[0]
    assert [(move.kind, move.target) for move in item.trial_actions] == [("pitch", "camera")]
