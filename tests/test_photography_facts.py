"""Regress the concrete prose contradictions in the 2026-10-17 live trials."""
from pathlib import Path

import pytest
import test_real_pipeline as pipeline_fixtures
from test_composition_advisor import proposal, response
from test_validator import recommendation, scene

from camera_assistant.composition_models import CompositionAdvice
from camera_assistant.models import UserRequest
from camera_assistant.services.camera_knowledge import CameraKnowledgeBase
from camera_assistant.services.composition import _validate_advice
from camera_assistant.services.photography_facts import (
    build_photography_facts,
    photography_facts,
    preserve_continuous_framing,
    reconcile_composition_facts,
    semantic_issues,
    use_photography_facts,
)
from camera_assistant.services.validator import RecommendationValidator

# pytest discovers fixture objects bound in this module, including aliases.
# Keep the actual fixture objects; deleting the old F401 imports breaks setup.
pipeline_settings = pipeline_fixtures.settings
pipeline_image_content = pipeline_fixtures.image_content


def camera(identifier="canon_eos_r50"):
    return CameraKnowledgeBase(Path(__file__).resolve().parents[1] / "knowledge/cameras/camera_profiles.yaml").resolve(identifier, "不清楚")


def test_fast_shutter_does_not_reduce_viewfinder_stability():
    result = RecommendationValidator().validate(recommendation(
        risks=["快门速度过高可能影响取景稳定性，建议配合机身防抖。"]),
        UserRequest(intent="凝固奔跑的狗"), scene("fast"), camera())
    assert "过高可能影响取景稳定性" not in " ".join(result.risks)
    assert any("主体运动" in text for text in [*result.risks, *result.adjustments])


def test_r50_cannot_receive_an_ibis_instruction():
    result = RecommendationValidator().validate(recommendation(
        adjustments=["开启机身防抖稳定手持拍摄。"]),
        UserRequest(intent="手持拍摄"), scene(), camera())
    assert "开启机身防抖" not in " ".join(result.adjustments)
    assert any("不具备" in text for text in result.adjustments)


def test_warm_goal_does_not_use_tungsten_preset_as_a_warmth_guarantee():
    result = RecommendationValidator().validate(recommendation(
        white_balance="钨丝灯", reasons=["钨丝灯白平衡可保留咖啡馆暖色氛围。"]),
        UserRequest(intent="保留咖啡馆暖色氛围"), scene(), camera())
    assert "钨丝灯" not in result.white_balance
    assert "锁定" in result.white_balance
    assert "钨丝灯白平衡可保留" not in " ".join(result.reasons)


def test_right_thirds_and_axis_symmetry_cannot_both_be_promised():
    p = proposal()
    p.update(actions=["将拱门置于右侧三分线", "确认左右结构对称"],
             reasons=["右侧三分构图同时保持左右对称。"])
    advice = _validate_advice(CompositionAdvice.model_validate(response([p])), None, [],
        UserRequest(intent="比较居中与三分构图，保留左右主要结构"))
    text = advice.model_dump_json()
    assert "右侧三分构图同时保持左右对称" not in text
    assert "对称" in text and "比较" in text


def test_single_image_board_does_not_claim_it_has_removed_parallax_overlap():
    p = proposal()
    p.update(actions=["向右侧移，让近景树木不再遮挡建筑。"],
             reasons=["推荐图已经消除了遮挡，证明侧移可以改善透视。"])
    advice = _validate_advice(CompositionAdvice.model_validate(response([p])), None, [],
        UserRequest(intent="保留建筑并减少树木遮挡"))
    assert "推荐图已经消除了遮挡" not in advice.model_dump_json()
    assert "现场" in advice.model_dump_json()


@pytest.mark.parametrize("text", [
    "高速快门不会降低取景稳定性。",
    "高速快门能减轻相机抖动，并凝固奔跑主体。",
    "不要依赖机身防抖凝固主体运动。",
    "R50 没有机身防抖。",
    "该机身不具备 IBIS，镜头防抖仅在确认支持时使用。",
    "若镜头支持防抖，可开启镜头防抖；运动仍需高速快门。",
    "不能声称钨丝灯预设可以保留暖色。",
    "钨丝灯预设通常中和暖光，未必保留暖色氛围。",
    "如果现场光源是钨丝灯，应通过试拍比较颜色。",
])
def test_correct_negative_and_conditional_photographic_claims_are_kept(text):
    facts = build_photography_facts(UserRequest(intent="保留暖色氛围"), scene("fast"), camera())
    assert semantic_issues(text, facts) == set()


@pytest.mark.parametrize("text", [
    "提高快门速度会降低相机抖动。",
    "高速快门会增加取景稳定性。",
    "高速快门可以降低抖动造成的模糊。",
    "提高快门速度不会降低取景稳定性。",
    "高速快门不会增加相机抖动。",
])
def test_shutter_stability_guard_preserves_correct_effect_directions(text):
    facts = build_photography_facts(UserRequest(intent="拍摄清晰的运动主体"), scene("fast"), camera())
    assert "shutter_stability_causality" not in semantic_issues(text, facts)


@pytest.mark.parametrize("text", [
    "提高快门速度会降低取景稳定性。",
    "高速快门会增加相机抖动。",
    "快门速度过高可能影响取景稳定性。",
])
def test_shutter_stability_guard_rejects_wrong_effect_directions(text):
    facts = build_photography_facts(UserRequest(intent="拍摄清晰的运动主体"), scene("fast"), camera())
    assert "shutter_stability_causality" in semantic_issues(text, facts)


@pytest.mark.parametrize("text", [
    "开启机身防抖。", "本机具备 IBIS。", "该相机没有机身防抖。",
])
def test_unknown_camera_does_not_inherit_presence_or_absence_of_ibis(text):
    facts = build_photography_facts(UserRequest(intent="拍摄静物"), scene(), camera("generic_unknown"))
    assert facts.ibis == "unknown"
    assert "ibis_capability_conflict" in semantic_issues(text, facts)


@pytest.mark.parametrize("text", [
    "若机身支持 IBIS，可开启后试拍。",
    "机身防抖能力未确认，请按菜单核对。",
    "不能依赖未经确认的机身防抖。",
    "若该机没有机身防抖，请用稳定支撑。",
])
def test_unknown_camera_keeps_explicit_uncertainty_and_supported_conditions(text):
    facts = build_photography_facts(UserRequest(intent="拍摄静物"), scene(), camera("generic_unknown"))
    assert semantic_issues(text, facts) == set()


def test_ibis_cannot_replace_shutter_for_subject_motion_even_when_available():
    facts = build_photography_facts(UserRequest(intent="拍快速主体"), scene("fast"),
        camera().model_copy(update={"ibis_stops": 7}))
    assert "ibis_subject_motion_causality" in semantic_issues("IBIS 可以凝固主体运动。", facts)
    assert semantic_issues("IBIS 不能凝固主体运动。", facts) == set()


@pytest.mark.parametrize("text", [
    "比较居中与右侧三分：居中保持左右对称，偏置会牺牲中轴对称。",
    "若改右侧三分，则不再保持左右对称；保留原构图也可以。",
    "不要强行放在右侧三分，同时要求左右对称。",
])
def test_center_thirds_comparison_with_explicit_alternatives_remains_valid(text):
    value = CompositionAdvice.model_validate(response([{**proposal(), "reasons": [text]}]))
    facts = build_photography_facts(UserRequest(intent="比较居中与三分构图"), scene(), camera())
    result = reconcile_composition_facts(value, facts)
    assert result.proposals[0].reasons == [text]


def test_parameter_and_composition_warm_goal_share_one_instruction_and_are_idempotent():
    request = UserRequest(intent="保留咖啡馆暖色氛围")
    facts = build_photography_facts(request, scene(), camera())
    parameter = RecommendationValidator().validate(recommendation(white_balance="钨丝灯"), request, scene(), camera())
    value = CompositionAdvice.model_validate(response([{**proposal(),
        "actions": ["单点对焦奶泡，白平衡设为钨丝灯以保留暖色。"]}]))
    first = reconcile_composition_facts(value, facts)
    second = reconcile_composition_facts(first, facts)
    assert facts.white_balance_instruction == parameter.white_balance
    assert facts.white_balance_instruction in first.proposals[0].actions[0]
    assert first == second


def test_shared_fact_scope_is_immutable_and_does_not_leak_between_requests():
    from dataclasses import FrozenInstanceError
    facts = build_photography_facts(UserRequest(intent="保留暖色氛围"), scene(), camera())
    with use_photography_facts(facts):
        assert photography_facts(UserRequest(intent="拍照"), scene(), None) is facts
        with pytest.raises(FrozenInstanceError):
            facts.ibis = "present"
    assert photography_facts(UserRequest(intent="拍照"), scene(), None).ibis == "unknown"


def test_photo_warm_tone_cannot_confirm_light_source_or_override_user_color_goal():
    warm_scene = scene().model_copy(update={"lighting": "warm", "desired_effects": ["保留暖色"]})
    request = UserRequest(intent="中和偏黄，还原中性颜色")
    facts = build_photography_facts(request, warm_scene, camera())
    assert facts.white_balance_goal == "neutralize" and facts.declared_light is None
    assert "light_source_unconfirmed" in semantic_issues("现场光源是钨丝灯。", facts)
    assert "不能确认钨丝灯" in facts.prompt()


@pytest.mark.parametrize("intent", ["比较居中与三分构图，保留左右结构", "保留山峰和完整倒影，比较地平线位置"])
def test_continuous_geometry_cannot_keep_provider_movement_claims(intent):
    value = CompositionAdvice.model_validate(response([{**proposal(),
        "actions": ["向右侧移，将主体放在右侧三分线。", "检查可见主体边缘。"],
        "reasons": ["右侧三分使纵深更强。"],
        "composition_intent": {"focus_object_id": "object1", "diagnosis": "改为右三分",
            "placement": "right", "vertical_placement": "upper", "subject_scale": "larger", "aspect": "square"},
    }]))
    facts = build_photography_facts(UserRequest(intent=intent), scene(), camera())
    result = preserve_continuous_framing(value, facts).proposals[0]
    assert [getattr(result.composition_intent, field) for field in
        ("placement", "vertical_placement", "subject_scale", "aspect")] == ["keep"] * 4
    assert not any("右侧三分线" in text for text in result.actions)
    assert "原取景" in result.composition_intent.diagnosis
    assert any("现场" in text for text in result.limitations)
    CompositionAdvice.model_validate({"status": "unverified", "proposals": [result.model_dump()]})


def test_continuous_filter_keeps_required_lists_and_serializes_after_repeated_checks():
    value = CompositionAdvice.model_validate(response([{**proposal(),
        "actions": ["放在右侧三分线。"], "reasons": ["三分构图。"],
        "conditions": ["需要向右侧移。"], "tradeoffs": ["靠近会放大主体。"],
        "limitations": ["后退需小心。"],
        "composition_intent": {"focus_object_id": "object1", "diagnosis": "改为右三分", "placement": "right"},
    }]))
    facts = build_photography_facts(UserRequest(intent="比较居中与三分构图"), scene(), camera())
    result = preserve_continuous_framing(value, facts)
    result = reconcile_composition_facts(result, facts)
    for _ in range(4):
        assert reconcile_composition_facts(result, facts) == result
        result = CompositionAdvice.model_validate(result.model_dump())
    assert all(getattr(result.proposals[0], field) for field in
               ("actions", "reasons", "conditions", "tradeoffs", "limitations"))


def test_parallel_branches_receive_the_same_precomputed_fact_instance(tmp_path, monkeypatch):
    from io import BytesIO
    from threading import Barrier

    from PIL import Image
    from test_real_pipeline import (
        FakeCompositionAdvisor,
        FakeParameterAdvisor,
        localization,
        make_pipeline,
    )

    from camera_assistant.config import PROJECT_ROOT, Settings
    from camera_assistant.services.retriever import LocalKnowledgeRetriever

    settings = Settings(demo_mode=False, api_key="test", base_url="https://example.invalid/v1",
        vision_model="test", text_model="test", knowledge_dir=PROJECT_ROOT / "knowledge",
        knowledge_db_path=tmp_path / "facts.db", detector_enabled=False,
        timeout_seconds=5, max_image_mb=15)
    parameter, composition = FakeParameterAdvisor(), FakeCompositionAdvisor()
    pipeline = make_pipeline(settings, LocalKnowledgeRetriever(settings.knowledge_dir),
                             localization(), parameter, composition)
    rendezvous, received = Barrier(2, timeout=5), []
    for service in (parameter, composition):
        original = service.recommend
        def recommend(*args, _original=original):
            received.append(photography_facts(UserRequest(intent="ignored"), scene(), None))
            rendezvous.wait()
            return _original(*args)
        monkeypatch.setattr(service, "recommend", recommend)
    output = BytesIO()
    Image.new("RGB", (50, 40), "white").save(output, format="JPEG")
    request = UserRequest(intent="保留暖色氛围", camera_profile_id="canon_eos_r50")
    pipeline.run(output.getvalue(), request, parallel_advice=True)
    assert len(received) == 2 and received[0] is received[1]
    assert received[0].ibis == "absent" and received[0].white_balance_goal == "preserve_warmth"


def test_warm_white_balance_ready_snapshot_matches_final_after_join(
        pipeline_settings, pipeline_image_content, monkeypatch):
    from copy import deepcopy

    from test_observed_composition import observed
    from test_real_pipeline import FakeParameterAdvisor, make_pipeline

    from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
    from camera_assistant.knowledge.store import KnowledgeStore
    from camera_assistant.services import composition, observed_composition

    source = observed_composition.parse_observed_scene(observed())
    monkeypatch.setattr(composition, "observe_objects", lambda *_: source)
    answer = {"proposals": [{**proposal(),
        "actions": ["对焦主体细节，白平衡设为钨丝灯保留暖色。"],
        "composition_intent": {"focus_object_id": "object1", "diagnosis": "保留可见主体", "placement": "keep"},
    }]}
    monkeypatch.setattr(composition, "request_json", lambda *_: deepcopy(answer))
    pipeline = make_pipeline(pipeline_settings,
        ManagedKnowledgeRetriever(KnowledgeStore(pipeline_settings.knowledge_db_path)),
        None, FakeParameterAdvisor(), composition.OpenAICompatibleCompositionAdvisor(pipeline_settings))
    ready = []
    result = pipeline.run(pipeline_image_content, UserRequest(intent="保留暖色氛围"),
        parallel_advice=True, on_partial=lambda event: ready.append(event["value"])
        if event["kind"] == "composition_ready" else None)
    assert len(ready) == 1 and ready[0] == result.composition
    CompositionAdvice.model_validate(ready[0].model_dump())
    assert result.recommendation.white_balance in " ".join(result.composition.proposals[0].actions)


@pytest.mark.parametrize("field", ["goal", "intent_diagnosis", "framing_placement", "board_instruction", "board_benefit"])
def test_visible_nested_prose_cannot_bypass_equipment_and_parallax_guards(field):
    from test_composition_advisor import target_board
    incorrect = "开启机身防抖以凝固主体运动。"
    value = proposal()
    value["composition_intent"] = {"focus_object_id": "object1", "diagnosis": "检查可见主体"}
    value["storyboard"] = target_board()
    value["framing_plan"] = dict.fromkeys(["diagnosis", "visual_priority", "placement", "scale",
        "negative_space", "edge_check", "background_control", "success_check"], "检查可见主体")
    if field == "goal":
        value["goal"] = incorrect
    elif field == "intent_diagnosis":
        value["composition_intent"]["diagnosis"] = incorrect
    elif field == "framing_placement":
        value["framing_plan"]["placement"] = incorrect
    elif field == "board_instruction":
        value["storyboard"]["distance_instruction"] = incorrect
    else:
        value["storyboard"]["changes"][0]["benefit"] = "推荐图已经消除了遮挡。"
    advice = CompositionAdvice.model_validate(response([value]))
    facts = build_photography_facts(UserRequest(intent="拍摄清晰主体"), scene(), camera())
    result = reconcile_composition_facts(advice, facts)
    assert incorrect not in result.model_dump_json()
    assert "推荐图已经消除了遮挡" not in result.model_dump_json()
    assert result.proposals[0].storyboard.layers == advice.proposals[0].storyboard.layers
    CompositionAdvice.model_validate(result.model_dump())
    assert reconcile_composition_facts(result, facts) == result


@pytest.mark.parametrize("text", [
    "若机身支持 IBIS，可开启机身防抖后试拍。",
    "如果已经确认该机具备机身防抖，可以配合 IBIS 稳定手持。",
    "不能确认机身是否支持 IBIS，请先核对菜单。",
    "不能说高速快门会降低取景稳定性。",
    "不要声称提高快门速度会增加相机抖动。",
    "在钨丝灯下用自动白平衡的氛围优先保留暖色。",
    "钨丝灯预设不保证保留暖色氛围。",
    "如果现场光源是钨丝灯，可试拍核对白平衡。",
])
def test_supported_conditions_and_scoped_negatives_survive(text):
    facts = build_photography_facts(UserRequest(intent="保留暖色"), scene(), camera("generic_unknown"))
    assert semantic_issues(text, facts) == set()


@pytest.mark.parametrize(("text", "code"), [
    ("若镜头支持 IS，可开启机身防抖。", "ibis_capability_conflict"),
    ("不能降低 ISO，但可以开启 IBIS。", "ibis_capability_conflict"),
    ("若机身支持 IBIS，可开启防抖；本机已经具备 IBIS。", "ibis_capability_conflict"),
    ("IBIS 已开启。", "ibis_capability_conflict"),
    ("可以开启镜头防抖。", "lens_is_unconfirmed"),
    ("镜头防抖能够凝固主体运动。", "ibis_subject_motion_causality"),
])
def test_unknown_capability_conditions_do_not_license_other_claims(text, code):
    facts = build_photography_facts(UserRequest(intent="拍摄清晰主体"), scene(), camera("generic_unknown"))
    assert code in semantic_issues(text, facts)


@pytest.mark.parametrize("light", [None, "natural", "continuous_artificial", "mixed", "flickering_artificial"])
def test_broad_lighting_category_never_confirms_a_specific_bulb(light):
    facts = build_photography_facts(UserRequest(intent="拍照", lighting_type=light), scene(), camera())
    assert "light_source_unconfirmed" in semantic_issues("现场光源是钨丝灯。", facts)
    assert "light_source_unconfirmed" in semantic_issues("照片偏暖说明现场使用钨丝灯。", facts)
    assert semantic_issues("若现场光源是钨丝灯，可试拍检查颜色。", facts) == set()


@pytest.mark.parametrize(("intent", "goal"), [
    ("不要中和暖色，保留温暖氛围", "preserve_warmth"),
    ("无需去除偏黄，保持暖调", "preserve_warmth"),
    ("不想保留暖色，要还原中性颜色", "neutralize"),
    ("比较保留暖色与中和偏黄的效果", "unspecified"),
])
def test_white_balance_goal_respects_negation_and_unselected_alternatives(intent, goal):
    assert build_photography_facts(UserRequest(intent=intent), scene(), camera()).white_balance_goal == goal


def test_warm_goal_correction_keeps_focus_and_risk_context():
    from camera_assistant.services.photography_facts import reconcile_parameter_facts
    facts = build_photography_facts(UserRequest(intent="保留暖色"), scene(), camera())
    result = reconcile_parameter_facts(recommendation(
        reasons=["单点对焦奶泡，钨丝灯白平衡可保留暖色。"],
        adjustments=["检查杯沿，白平衡向冷调整以中和暖色。"]), facts)
    assert "单点对焦奶泡" in " ".join(result.reasons)
    assert "检查杯沿" in " ".join(result.adjustments)
    assert "向冷调整以中和暖色" not in " ".join(result.adjustments)
    assert result.white_balance == facts.white_balance_instruction
    assert reconcile_parameter_facts(result, facts) == result


def test_nested_white_balance_correction_keeps_focus_instruction():
    value = proposal()
    value["composition_intent"] = {"focus_object_id": "object1", "diagnosis": "对焦奶泡，白平衡设为钨丝灯保留暖色。"}
    facts = build_photography_facts(UserRequest(intent="保留暖色"), scene(), camera())
    result = reconcile_composition_facts(CompositionAdvice.model_validate(response([value])), facts)
    assert "对焦奶泡" in result.proposals[0].composition_intent.diagnosis
    assert facts.white_balance_instruction in result.proposals[0].composition_intent.diagnosis


@pytest.mark.parametrize("text", [
    "方案一居中保持左右对称，方案二采用右侧三分强调方向。",
    "主体放在右侧三分线，主体自身左右对称。",
    "无需强行三分，检查左右中轴对称。",
])
def test_alternatives_local_symmetry_and_negative_thirds_do_not_reset_layout(text):
    value = proposal()
    value["reasons"] = [text]
    facts = build_photography_facts(UserRequest(intent="比较居中与三分构图"), scene(), camera())
    result = reconcile_composition_facts(CompositionAdvice.model_validate(response([value])), facts)
    assert result.proposals[0].reasons == [text]


def test_explicit_motion_overrides_scene_guess_and_unknown_stays_unknown():
    request = UserRequest(intent="拍摄静物", subject_motion="静止")
    assert build_photography_facts(request, scene("fast"), camera()).motion == "static"
    assert build_photography_facts(UserRequest(intent="拍摄主体"), scene("fast"), camera()).motion == "unknown"


def test_motion_estimate_only_gets_conditional_parameter_guidance():
    request = UserRequest(intent="拍摄静物", subject_motion="静止")
    result = RecommendationValidator().validate(recommendation(shutter_speed="1/125s"), request, scene("fast"), camera())
    assert result.shutter_speed == "1/125s"
    uncertain = RecommendationValidator().validate(recommendation(), UserRequest(intent="拍摄主体"), scene("fast"), camera())
    assert any("若" in text and "快速" in text for text in uncertain.validation_notes)


@pytest.mark.parametrize("text", [
    "若主体正在快速运动，试用较快快门。",
    "静态照片不能确认主体正在高速奔跑。",
])
def test_motion_conditions_and_uncertainty_are_not_facts(text):
    facts = build_photography_facts(UserRequest(intent="拍摄主体"), scene("fast"), camera())
    assert semantic_issues(text, facts) == set()


def test_unknown_motion_cannot_be_promoted_to_affirmative_fact():
    facts = build_photography_facts(UserRequest(intent="拍摄主体"), scene("fast"), camera())
    assert "motion_unconfirmed" in semantic_issues("主体正在高速奔跑。", facts)


@pytest.mark.parametrize("text", [
    "推荐图已改善透视并减少遮挡。",
    "示意图已恢复未拍到的杯底。",
    "向右侧移 2 米消除遮挡。",
])
def test_visible_prose_never_promises_unmeasured_geometry(text):
    value = proposal()
    value["actions"] = [text]
    facts = build_photography_facts(UserRequest(intent="检查可见杯沿"), scene(), camera())
    result = reconcile_composition_facts(CompositionAdvice.model_validate(response([value])), facts)
    assert text not in result.proposals[0].actions
    assert any("现场" in item or "画外" in item for item in result.proposals[0].actions)


@pytest.mark.parametrize("text", [
    "若机身支持 IBIS，可开启机身防抖，本机已具备 IBIS。",
    "开启机身防抖可能提高拍摄成功率。",
    "机身防抖可开启。",
])
def test_conditions_and_hedged_benefits_do_not_confirm_unknown_hardware(text):
    facts = build_photography_facts(UserRequest(intent="拍摄主体"), scene(), camera("generic_unknown"))
    assert "ibis_capability_conflict" in semantic_issues(text, facts)


def test_comparison_does_not_license_an_independent_simultaneous_directive():
    value = proposal()
    value.update(actions=["拱门置于右侧三分线，同时保持画面左右中轴对称。"],
                 reasons=["方案一居中保持左右对称，方案二右侧三分。"],
                 composition_intent={"focus_object_id": "object1", "diagnosis": "偏置", "placement": "right"})
    facts = build_photography_facts(UserRequest(intent="比较居中与三分"), scene(), camera())
    result = reconcile_composition_facts(CompositionAdvice.model_validate(response([value])), facts)
    assert result.proposals[0].composition_intent.placement == "keep"


def test_continuous_framing_keeps_negative_boundaries_and_corrects_nested_claims():
    from test_composition_advisor import target_board
    value = proposal()
    value.update(actions=["不要靠近，以免截断杯沿。"], reasons=["不必强行三分，保留原取景。"],
                 composition_intent={"focus_object_id": "object1", "diagnosis": "调整", "placement": "right"},
                 storyboard=target_board())
    value["storyboard"]["distance_instruction"] = "向右侧移后，推荐图已消除遮挡。"
    facts = build_photography_facts(UserRequest(intent="保留原构图"), scene(), camera())
    result = preserve_continuous_framing(CompositionAdvice.model_validate(response([value])), facts)
    assert "不要靠近，以免截断杯沿。" in result.proposals[0].actions
    assert "不必强行三分，保留原取景。" in result.proposals[0].reasons
    assert "已消除遮挡" not in result.model_dump_json()
    assert result.proposals[0].storyboard.layers == CompositionAdvice.model_validate(response([value])).proposals[0].storyboard.layers
    assert preserve_continuous_framing(result, facts) == result


def test_demo_respects_explicit_static_motion_and_warm_goal():
    from camera_assistant.services.advisor import DemoRecommendationAdvisor
    request = UserRequest(intent="保留咖啡暖色", subject_motion="静止")
    facts = build_photography_facts(request, scene("fast"), camera())
    result = DemoRecommendationAdvisor().recommend(request, scene("fast"), [], camera())
    assert result.shooting_mode != camera().shutter_priority_name
    assert result.white_balance == facts.white_balance_instruction


@pytest.mark.parametrize("text", [
    "若机身不支持 IBIS，可开启机身防抖。",
    "如果机身支持 IBIS，可开启镜头防抖。",
])
def test_review_negative_or_other_hardware_condition_never_licenses_activation(text):
    facts = build_photography_facts(UserRequest(intent="拍摄主体"), scene(), camera("generic_unknown"))
    assert semantic_issues(text, facts)


def test_review_comparison_does_not_license_separate_conflicting_actions():
    value = proposal()
    value.update(actions=["拱门置于右侧三分线。", "保持画面左右中轴对称。"],
                 reasons=["方案一居中保持左右对称，方案二右侧三分。"],
                 composition_intent={"focus_object_id": "object1", "diagnosis": "偏置", "placement": "right"})
    facts = build_photography_facts(UserRequest(intent="比较居中与三分"), scene(), camera())
    result = reconcile_composition_facts(CompositionAdvice.model_validate(response([value])), facts)
    assert result.proposals[0].composition_intent.placement == "keep"


@pytest.mark.parametrize("intent", ["我不想保留暖色，要还原中性颜色", "不要中和暖色而是保留暖色氛围"])
def test_review_embedded_goal_negation_is_scoped_to_the_rejected_goal(intent):
    facts = build_photography_facts(UserRequest(intent=intent), scene(), camera())
    assert facts.white_balance_goal == ("neutralize" if "中性" in intent else "preserve_warmth")


def test_review_food_demo_uses_one_color_goal_in_parameters_and_adjustments():
    from camera_assistant.services.advisor import DemoRecommendationAdvisor
    request = UserRequest(intent="保留咖啡馆暖色氛围", subject_motion="静止")
    source = scene().model_copy(update={"scene_type": "food_closeup"})
    result = DemoRecommendationAdvisor().recommend(request, source, [], camera())
    assert not any("钨丝灯" in text for text in result.adjustments)
    assert any("保留暖色" in text for text in result.adjustments)


def test_review_correcting_a_separate_error_preserves_the_condition_scope():
    from camera_assistant.services.photography_facts import reconcile_parameter_facts
    facts = build_photography_facts(UserRequest(intent="拍摄主体"), scene(), camera("generic_unknown"))
    source = recommendation(adjustments=["若机身支持 IBIS，可开启机身防抖；高速快门会降低取景稳定性。"])
    first = reconcile_parameter_facts(source, facts)
    assert "可开启机身防抖" in first.adjustments[0]
    assert reconcile_parameter_facts(first, facts) == first


def test_review_negative_effect_does_not_negate_positive_ibis_activation():
    facts = build_photography_facts(UserRequest(intent="拍摄主体"), scene(), camera())
    text = "开启机身防抖不能替代高速快门，但有助于稳定机身。"
    assert "ibis_capability_conflict" in semantic_issues(text, facts)


@pytest.mark.parametrize("intent", ["现场光源是钨丝灯，保留暖色", "现场使用白炽灯，保留暖色"])
def test_user_declared_specific_light_is_evidence_but_scene_guess_is_not(intent):
    facts = build_photography_facts(UserRequest(intent=intent), scene(), camera())
    assert semantic_issues("现场光源是钨丝灯。", facts) == set()
    assert "light_source_unconfirmed" in semantic_issues("现场光源是 LED。", facts)


@pytest.mark.parametrize("intent", ["如果现场光源是钨丝灯怎样保暖", "现场光源是钨丝灯吗？", "现场并不是钨丝灯，想保暖"])
def test_question_condition_or_negative_is_not_a_light_declaration(intent):
    facts = build_photography_facts(UserRequest(intent=intent), scene(), camera())
    assert "light_source_unconfirmed" in semantic_issues("现场光源是钨丝灯。", facts)


def test_user_explicit_motion_sentence_is_evidence_with_structured_status_priority():
    request = UserRequest(intent="狗正在快速奔跑，我想凝固动作")
    assert build_photography_facts(request, scene("static"), camera()).motion == "fast"
    assert build_photography_facts(request.model_copy(update={"subject_motion": "静止"}), scene("fast"), camera()).motion == "static"
