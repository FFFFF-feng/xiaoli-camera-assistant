"""Offline production recovery: only transport and visual/DINO evidence are supplied."""
import json
from pathlib import Path

import pytest
import test_real_pipeline as fixtures
from test_real_pipeline import (
    FakeCompositionAdvisor,
    FakeLocalizer,
    FakeVision,
    localization,
)

from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services import cloud
from camera_assistant.services.advisor import OpenAICompatibleRecommendationAdvisor

settings = fixtures.settings
image_content = fixtures.image_content
user_request = fixtures.user_request


def answer(**updates):
    value = {"shooting_mode": "Av 光圈优先", "aperture": "f/4", "shutter_speed": "1/250s",
             "iso": "Auto ISO 上限1600", "exposure_compensation": "0 EV", "focus_mode": "AF-S",
             "metering_mode": "评价测光", "drive_mode": "单张", "white_balance": "自动白平衡",
             "reasons": ["加快快门会减小景深"], "risks": [], "adjustments": [], "confidence": .7}
    value.update(updates)
    return value


def run(settings, image_content, user_request, monkeypatch, responses):
    payloads = []
    pending = iter(responses)

    def content(config, body):
        payloads.append(body)
        response = next(pending)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)

    monkeypatch.setattr(cloud, "_request_content", content)
    vision, detector, composition = FakeVision(), FakeLocalizer(localization()), FakeCompositionAdvisor()
    pipeline = CameraAssistantPipeline(settings, vision_analyzer=vision, localizer=detector,
                                       composition_advisor=composition,
                                       advisor=OpenAICompatibleRecommendationAdvisor(settings))
    result = pipeline.run(image_content, user_request)
    assert len(vision.calls) == len(detector.calls) == len(composition.calls) == 1
    return result, payloads


def test_recover_incomplete_parameters_and_resynchronize_all_explanations(
    settings, image_content, user_request, monkeypatch,
):
    result, payloads = run(settings, image_content, user_request, monkeypatch, [
        answer(shutter_speed="相机自动决定", iso="自动或手动"), answer(),
    ])
    assert len(payloads) == 2
    assert "shutter_speed" in payloads[1]["messages"][0]["content"]
    assert "iso" in payloads[1]["messages"][0]["content"]
    assert result.parameter_recovery.status == "complete"
    assert result.parameter_recovery.correction_attempted
    assert result.recommendation.exposure_state.parameters["shutter_speed"].role == "auto_target"
    assert result.recommendation.shutter_speed == "1/500s 或更快"
    assert not any("快门会减小景深" in x for x in result.recommendation.reasons)
    assert any("1/500s" in x for x in result.composition.proposals[0].conditions)


def test_second_failure_lists_missing_fields_without_third_call(
    settings, image_content, user_request, monkeypatch,
):
    result, payloads = run(settings, image_content, user_request, monkeypatch, [
        answer(shutter_speed="不明确", iso="自动或手动"),
        answer(shutter_speed="不明确", iso="自动或手动"),
    ])
    assert len(payloads) == 2
    assert result.parameter_recovery.status == "incomplete"
    assert set(result.parameter_recovery.missing_parameters) >= {"shutter_speed", "iso"}
    assert result.parameter_recovery.user_confirmations


def test_format_retry_spends_shared_budget_and_cannot_stack_correction(
    settings, image_content, user_request, monkeypatch,
):
    result, payloads = run(settings, image_content, user_request, monkeypatch, [
        "not json", answer(iso="自动或手动"), answer(),
    ])
    assert len(payloads) == 2
    assert not result.parameter_recovery.correction_attempted
    assert result.parameter_recovery.api_calls == 2
    assert result.parameter_recovery.status == "incomplete"


def test_schema_omission_is_recoverable(
    settings, image_content, user_request, monkeypatch,
):
    missing = answer()
    missing.pop("shutter_speed")
    result, payloads = run(settings, image_content, user_request, monkeypatch, [missing, answer()])
    assert len(payloads) == 2
    assert result.parameter_recovery.status == "complete"
    assert "shutter_speed" in payloads[1]["messages"][0]["content"]


def test_unknown_equipment_capability_requires_confirmation_without_retry(
    settings, image_content, user_request, monkeypatch,
):
    request = user_request.model_copy(update={"camera_profile_id": "generic_unknown"})
    result, payloads = run(settings, image_content, request, monkeypatch, [
        answer(shooting_mode="M 手动模式", iso="Auto ISO"), answer(),
    ])
    assert len(payloads) == 1
    assert result.parameter_recovery.status == "needs_confirmation"
    assert any("机型" in x for x in result.parameter_recovery.user_confirmations)


@pytest.mark.parametrize("error", ["模型服务请求超时", "无法连接模型服务"])
def test_transport_errors_never_trigger_parameter_correction(
    settings, image_content, user_request, monkeypatch, error,
):
    result, payloads = run(settings, image_content, user_request, monkeypatch, [
        cloud.ModelServiceError(error), answer(),
    ])
    assert len(payloads) == 1
    assert result.parameter_recovery.status == "incomplete"
    assert not result.parameter_recovery.correction_attempted
    assert result.composition.proposals


def test_correction_format_failure_does_not_get_its_own_retry(
    settings, image_content, user_request, monkeypatch,
):
    result, payloads = run(settings, image_content, user_request, monkeypatch, [
        answer(iso="自动或手动"), "not json", answer(),
    ])
    assert len(payloads) == 2
    assert result.parameter_recovery.status == "incomplete"


def test_missing_actual_lens_capability_is_not_guessed_by_retry(
    settings, image_content, user_request, monkeypatch,
):
    request = user_request.model_copy(update={"max_aperture": None})
    result, payloads = run(settings, image_content, request, monkeypatch, [
        answer(aperture="镜头可用光圈需要用户确认"), answer(),
    ])
    assert len(payloads) == 1
    assert "aperture" in result.parameter_recovery.missing_parameters
    assert any("镜头" in x for x in result.parameter_recovery.user_confirmations)


def test_missing_compensation_in_av_is_recovered_without_making_auto_shutter_manual(
    settings, image_content, user_request, monkeypatch,
):
    result, payloads = run(settings, image_content, user_request, monkeypatch, [
        answer(exposure_compensation="不明确"), answer(exposure_compensation="+0.3 EV"),
    ])
    assert len(payloads) == 2
    assert result.recommendation.exposure_compensation == "+0.3 EV"
    assert result.parameter_recovery.status == "complete"
    assert result.recommendation.exposure_state.parameters["shutter_speed"].role == "auto_target"


def test_independent_iso_omission_is_corrected_while_lens_fact_stays_unknown(
    settings, image_content, user_request, monkeypatch,
):
    request = user_request.model_copy(update={"max_aperture": None})
    result, payloads = run(settings, image_content, request, monkeypatch, [
        answer(aperture="镜头可用光圈需要用户确认", iso="自动或手动"), answer(),
    ])
    assert len(payloads) == 2
    assert "不得补猜" in payloads[1]["messages"][0]["content"]
    assert result.parameter_recovery.status == "needs_confirmation"
    assert result.parameter_recovery.missing_parameters == ["aperture"]
    assert result.recommendation.exposure_state.parameters["aperture"].role == "unknown"
    assert result.recommendation.exposure_state.iso_control == "auto"


def test_second_invalid_compensation_keeps_unknown_role_and_removes_ev_actions(
    settings, image_content, user_request, monkeypatch,
):
    result, payloads = run(settings, image_content, user_request, monkeypatch, [
        answer(exposure_compensation="不明确"), answer(exposure_compensation="不明确"),
    ])
    assert len(payloads) == 2
    assert result.parameter_recovery.missing_parameters == ["exposure_compensation"]
    assert result.recommendation.exposure_state.parameters["exposure_compensation"].role == "unknown"
    assert not any("可增加曝光补偿" in item for item in result.recommendation.adjustments)
    assert any("补偿建议未校验" in item for item in result.recommendation.adjustments)


def test_compensation_outside_verified_r50_range_is_corrected(
    settings, image_content, user_request, monkeypatch,
):
    result, payloads = run(settings, image_content, user_request, monkeypatch, [
        answer(exposure_compensation="+999 EV"), answer(exposure_compensation="0 EV"),
    ])
    assert len(payloads) == 2
    assert result.recommendation.exposure_compensation == "0 EV"
    assert result.parameter_recovery.status == "complete"


def test_twice_omitted_white_balance_is_explicitly_listed_in_failed_plan(
    settings, image_content, user_request, monkeypatch,
):
    omitted = answer()
    omitted.pop("white_balance")
    result, payloads = run(settings, image_content, user_request, monkeypatch, [omitted, omitted])
    assert len(payloads) == 2
    assert "white_balance" in result.parameter_recovery.missing_parameters
    assert result.recommendation.white_balance == "未生成"


def test_saved_d17_correction_stops_after_two_requests_with_actionable_confirmation(
    settings, monkeypatch,
):
    from camera_assistant.models import CameraProfile, SceneAnalysis, UserRequest

    saved = Path(__file__).resolve().parents[1] / "data/history/main-acceptance-20261014/live"
    prior = json.loads((saved / "D17-pipeline.json").read_text(encoding="utf-8"))
    summary = json.loads((saved / "D17-summary.json").read_text(encoding="utf-8"))
    responses = iter([
        (saved / "D17-parameters-attempt1-parsed.json").read_text(encoding="utf-8"),
        (saved / "D17-parameters-attempt2-parsed.json").read_text(encoding="utf-8"),
    ])
    payloads = []

    def content(config, body):
        payloads.append(body)
        return next(responses)

    monkeypatch.setattr(cloud, "_request_content", content)
    pipeline = CameraAssistantPipeline(settings)
    result, recovery = pipeline._parameter_stage(
        UserRequest.model_validate(summary["submitted_request"]),
        SceneAnalysis.model_validate(prior["scene"]), [],
        CameraProfile.model_validate(prior["camera_profile"]), lambda _: None,
    )
    assert len(payloads) == recovery.api_calls == 2
    assert recovery.correction_attempted
    assert recovery.status == "incomplete"
    assert recovery.missing_parameters == ["shutter_speed"]
    assert result.exposure_state.parameters["shutter_speed"].role == "unknown"
    assert result.exposure_state.parameters["aperture"].role == "manual_setting"
    assert result.exposure_state.iso_control == "auto"
    assert "1/60" not in result.shutter_speed
    assert not any("1/60" in text for field in ("reasons", "risks", "adjustments")
                   for text in getattr(result, field))
    assert any("先补充" in text and "目标" in text for text in recovery.user_confirmations)
    assert any("半按" in text and "实际快门" in text for text in recovery.user_confirmations)
