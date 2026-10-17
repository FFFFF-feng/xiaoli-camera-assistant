"""Offline stage overlap, validated snapshots, and unchanged result semantics."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
from threading import Barrier, Event, get_ident

import pytest
import test_real_pipeline as fixtures
from test_real_pipeline import (
    FakeCompositionAdvisor,
    FakeParameterAdvisor,
    knowledge_record,
    localization,
    make_pipeline,
    publish,
)

from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import CameraRecommendation, SceneAnalysis, UserRequest
from camera_assistant.services import cloud, timing
from camera_assistant.services import composition as composition_service

settings = fixtures.settings
image_content = fixtures.image_content
user_request = fixtures.user_request


def retriever(settings):
    return ManagedKnowledgeRetriever(KnowledgeStore(settings.knowledge_db_path))


def test_parallel_branches_really_overlap_and_receive_independent_contexts(
    settings, image_content, user_request, monkeypatch,
):
    rendezvous = Barrier(2, timeout=5)
    marker = ContextVar("advice_context_marker", default="unset")
    marker_token = marker.set("caller")
    composition, parameter = FakeCompositionAdvisor(), FakeParameterAdvisor()
    pipeline = make_pipeline(settings, retriever(settings), localization(), parameter, composition)
    workers = {}
    responses, streams = [], []
    monkeypatch.setattr(cloud, "_request_content_observed", lambda *args: "{}")

    for service, stage in ((composition, "composition"), (parameter, "parameters")):
        original = service.recommend

        def recommend(*args, _stage=stage, _original=original):
            workers[_stage] = get_ident()
            assert marker.get() == "caller"
            marker.set(_stage)
            # Sequential execution cannot pass this rendezvous. Its timeout
            # prevents a broken implementation from hanging the offline suite.
            rendezvous.wait()
            assert marker.get() == _stage
            assert cloud.request_json(settings, {"model": _stage, "messages": []}) == {}
            return _original(*args)

        monkeypatch.setattr(service, "recommend", recommend)

    try:
        with cloud.observe_responses(responses.append), cloud.observe_stream(streams.append):
            result = pipeline.run(image_content, user_request, parallel_advice=True)
        assert marker.get() == "caller"
    finally:
        marker.reset(marker_token)

    assert len(set(workers.values())) == 2
    assert len(responses) == 2
    assert sum(event["phase"] == "request_started" for event in streams) == 2
    assert sum(event["phase"] == "finished" for event in streams) == 2
    assert result.recommendation.shutter_speed == "1/800s"


def test_default_serial_and_parallel_results_are_identical(
    settings, image_content, user_request,
):
    store = KnowledgeStore(settings.knowledge_db_path)
    for library in ("scene", "technique", "composition"):
        publish(store, knowledge_record("parallel_" + library, library))
    search, loc = ManagedKnowledgeRetriever(store), localization()
    serial = make_pipeline(settings, search, loc).run(image_content, user_request)
    parallel = make_pipeline(settings, search, loc).run(
        image_content, user_request, parallel_advice=True,
    )

    assert parallel.model_dump() == serial.model_dump()
    assert parallel.knowledge_hits and parallel.composition_knowledge_hits


def test_validated_phone_parameters_arrive_while_composition_is_still_running(
    settings, image_content, monkeypatch,
):
    composition_started, parameters_published, composition_finished = Event(), Event(), Event()
    pipeline = make_pipeline(settings, retriever(settings), localization())
    recommend = pipeline.composition_advisor.recommend
    partials = []

    def blocked_composition(*args):
        composition_started.set()
        assert parameters_published.wait(5)
        result = recommend(*args)
        composition_finished.set()
        return result

    monkeypatch.setattr(pipeline.composition_advisor, "recommend", blocked_composition)

    def partial(event):
        partials.append(event)
        assert event["stage"] == "intermediate"
        if event["kind"] == "scene":
            assert isinstance(event["value"], SceneAnalysis)
            assert event["value"].subject_motion == "fast"
            assert not composition_started.is_set()
        else:
            assert isinstance(event["value"], CameraRecommendation)
            assert composition_started.wait(5)
            assert not composition_finished.is_set()
            assert event["value"].iso.startswith("自动")
            assert event["value"].validation_notes
            parameters_published.set()

    result = pipeline.run(
        image_content, UserRequest(
            intent="手机拍摄快速人物并突出主体", subject_motion="快速", device_type="phone",
            phone_profile_id="apple_iphone_15", phone_capture_mode="pro",
            phone_lens_id="unavailable_lens", phone_pro_controls_confirmed=True,
        ), parallel_advice=True, on_partial=partial,
    )

    assert [event["kind"] for event in partials] == ["scene", "parameters"]
    assert partials[0]["value"] == result.scene
    assert partials[1]["value"] == result.recommendation
    assert composition_finished.is_set()
    assert result.composition.proposals


def test_partial_snapshots_cannot_mutate_pipeline_inputs_or_final_result(
    settings, image_content, user_request,
):
    pipeline = make_pipeline(settings, retriever(settings), localization())

    def mutate(event):
        value = event["value"]
        if event["kind"] == "scene":
            value.subject = "consumer edit"
            value.composition_clues.clear()
        else:
            value.shutter_speed = "consumer edit"
            value.validation_notes.clear()

    result = pipeline.run(image_content, user_request, on_partial=mutate)

    assert result.scene.subject == "person"
    assert result.scene.composition_clues == ["主体右侧留白"]
    assert result.recommendation.shutter_speed == "1/800s"


@pytest.mark.parametrize("error_type", [ValueError, KeyError, TypeError, cloud.ModelServiceError])
def test_parallel_composition_failure_still_validates_and_publishes_parameters(
    settings, image_content, user_request, monkeypatch, error_type,
):
    parameter = FakeParameterAdvisor()
    composition = FakeCompositionAdvisor(error_type("synthetic composition failure"))
    pipeline = make_pipeline(settings, retriever(settings), localization(), parameter, composition)
    validations, partials = [], []
    validate = pipeline.validator.validate

    def observed_validate(*args):
        validations.append(args)
        return validate(*args)

    monkeypatch.setattr(pipeline.validator, "validate", observed_validate)
    result = pipeline.run(
        image_content, user_request, parallel_advice=True, on_partial=partials.append,
    )

    assert len(parameter.calls) == len(composition.calls) == len(validations) == 1
    assert result.composition.status == "unavailable"
    assert result.composition.proposals == []
    assert result.recommendation.shutter_speed == "1/800s"
    assert partials[-1]["kind"] == "parameters"
    assert partials[-1]["value"] == result.recommendation


@pytest.mark.parametrize("error_type", [ValueError, KeyError, TypeError, cloud.ModelServiceError])
def test_parameter_failure_keeps_composition_without_publishing_unvalidated_parameters(
    settings, image_content, user_request, error_type,
):
    composition = FakeCompositionAdvisor()
    pipeline = make_pipeline(
        settings, retriever(settings), localization(),
        FakeParameterAdvisor(error_type("synthetic parameter failure")), composition,
    )
    partials = []
    result = pipeline.run(
        image_content, user_request, parallel_advice=True, on_partial=partials.append,
    )

    assert result.composition == composition.result
    assert result.recommendation.confidence == 0
    assert result.recommendation.shutter_speed == "未生成"
    assert [event["kind"] for event in partials] == ["scene"]


def test_parameter_failure_without_composition_keeps_original_exception_semantics(
    settings, image_content, user_request,
):
    pipeline = make_pipeline(settings, retriever(settings), localization())
    pipeline.composition_advisor = None
    failure = ValueError("synthetic parameter failure")
    pipeline.advisor = FakeParameterAdvisor(failure)
    partials = []

    with pytest.raises(ValueError) as error:
        pipeline.run(image_content, user_request, parallel_advice=True, on_partial=partials.append)

    assert error.value is failure
    assert [event["kind"] for event in partials] == ["scene"]


def test_progress_precedes_each_expensive_serial_stage(
    settings, image_content, user_request, monkeypatch,
):
    pipeline = make_pipeline(settings, retriever(settings), localization())
    events = []
    for service, method, stage in (
        (pipeline.image_analyzer, "analyze", "图片"),
        (pipeline.vision_analyzer, "analyze", "识别"),
        (pipeline.localizer, "localize", "定位"),
        (pipeline.composition_advisor, "recommend", "构图"),
        (pipeline.advisor, "recommend", "拍摄参数"),
        (pipeline.validator, "validate", "校验"),
    ):
        original = getattr(service, method)

        def observed(*args, _original=original, _stage=stage):
            assert events and events[-1][0] == "progress" and _stage in events[-1][1]
            events.append(("service", _stage))
            return _original(*args)

        monkeypatch.setattr(service, method, observed)

    pipeline.run(
        image_content, user_request, on_progress=lambda value: events.append(("progress", value)),
    )

    assert [value for kind, value in events if kind == "service"] == [
        "图片", "识别", "定位", "构图", "拍摄参数", "校验",
    ]
    assert any(kind == "progress" and "查阅" in value for kind, value in events)
    assert events[-1] == ("progress", "分析完成。")


def test_localizer_warmup_overlaps_vision_and_uses_the_request_context(
    settings, image_content, user_request, monkeypatch,
):
    warmup_started, vision_started, warmup_finished = Event(), Event(), Event()
    marker = ContextVar("warmup_context_marker", default="unset")
    pipeline = make_pipeline(settings, retriever(settings), localization())
    analyze, localize = pipeline.vision_analyzer.analyze, pipeline.localizer.localize

    def warmup():
        assert marker.get() == "caller"
        warmup_started.set()
        assert vision_started.wait(5)
        warmup_finished.set()

    def observed_vision(*args):
        assert warmup_started.wait(5)
        vision_started.set()
        return analyze(*args)

    def observed_localize(*args):
        assert warmup_finished.wait(5)
        return localize(*args)

    monkeypatch.setattr(pipeline.localizer, "warmup", warmup, raising=False)
    monkeypatch.setattr(pipeline.vision_analyzer, "analyze", observed_vision)
    monkeypatch.setattr(pipeline.localizer, "localize", observed_localize)
    token = marker.set("caller")
    try:
        result = pipeline.run(image_content, user_request)
    finally:
        marker.reset(token)

    assert warmup_started.is_set() and vision_started.is_set() and warmup_finished.is_set()
    assert result.localization is pipeline.localizer.result


def test_optional_warmup_failure_does_not_skip_normal_localization(
    settings, image_content, user_request, monkeypatch,
):
    attempted = Event()
    pipeline = make_pipeline(settings, retriever(settings), localization())
    analyze = pipeline.vision_analyzer.analyze

    def warmup():
        attempted.set()
        raise RuntimeError("synthetic preload failure")

    def observed_vision(*args):
        assert attempted.wait(5)
        return analyze(*args)

    monkeypatch.setattr(pipeline.localizer, "warmup", warmup, raising=False)
    monkeypatch.setattr(pipeline.vision_analyzer, "analyze", observed_vision)
    result = pipeline.run(image_content, user_request)

    assert len(pipeline.localizer.calls) == 1
    assert result.localization is pipeline.localizer.result


@pytest.mark.parametrize("updates", [
    {"demo_mode": True}, {"detector_enabled": False}, {"detector_warmup": False},
    {"demo_mode": True, "api_key": "", "vision_model": "", "text_model": ""},
])
def test_warmup_never_runs_when_detector_or_warmup_is_disabled(
    settings, image_content, user_request, monkeypatch, updates,
):
    configured = replace(settings, **updates)
    pipeline = make_pipeline(configured, retriever(configured), localization())
    calls = []
    monkeypatch.setattr(pipeline.localizer, "warmup", lambda: calls.append(True), raising=False)
    pipeline.run(image_content, user_request)

    assert calls == []


def test_parallel_flag_without_composition_preserves_parameter_only_path(
    settings, image_content, user_request,
):
    pipeline = make_pipeline(settings, retriever(settings), localization())
    pipeline.composition_advisor = None
    partials = []
    result = pipeline.run(
        image_content, user_request, parallel_advice=True, on_partial=partials.append,
    )

    assert result.composition is None
    assert result.recommendation.shutter_speed == "1/800s"
    assert [event["kind"] for event in partials] == ["scene", "parameters"]


def test_validated_composition_text_is_published_before_target_drawing_finishes(
    settings, image_content, user_request, monkeypatch,
):
    from test_composition_advisor import proposal, response, target_board

    layout_published = Event()
    pipeline = make_pipeline(settings, retriever(settings), localization())
    pipeline.composition_advisor = composition_service.OpenAICompatibleCompositionAdvisor(settings)
    monkeypatch.setattr(composition_service, "request_json", lambda *args:
        response([{**proposal(), "storyboard": target_board()}]))
    partials = []

    def drawing(config, advice, inspection):
        assert layout_published.wait(1), "validated layout text was not published before drawing"
        assert advice.proposals[0].storyboard is not None
        return advice

    monkeypatch.setattr(composition_service, "refine_target_drawings", drawing)

    def partial(event):
        partials.append(event)
        if event["kind"] == "composition":
            value = event["value"]
            assert value.proposals[0].goal == "减少边缘干扰"
            assert value.proposals[0].storyboard is None
            assert value.proposals[0].sketch is None
            assert value.proposals[0].crop_bbox is None
            value.proposals[0].goal = "consumer edit"
            layout_published.set()

    result = pipeline.run(
        image_content, user_request, parallel_advice=True, on_partial=partial,
    )

    assert layout_published.is_set()
    assert {event["kind"] for event in partials} == {"scene", "parameters", "composition"}
    assert result.composition.proposals[0].goal == "减少边缘干扰"
    assert result.composition.proposals[0].storyboard is not None


@pytest.mark.parametrize("parallel", [False, True])
def test_stage_timings_cover_services_and_propagate_into_advice_workers(
    settings, image_content, user_request, monkeypatch, parallel,
):
    pipeline = make_pipeline(settings, retriever(settings), localization())
    measured = []
    for service, method, stage in (
        (pipeline.image_analyzer, "analyze", "image_preprocessing"),
        (pipeline.vision_analyzer, "analyze", "vision"),
        (pipeline.localizer, "localize", "localization"),
        (pipeline.composition_advisor, "recommend", "composition"),
        (pipeline.advisor, "recommend", "parameters"),
        (pipeline.validator, "validate", "parameter_validation"),
    ):
        original = getattr(service, method)

        def observed(*args, _original=original, _stage=stage):
            assert timing.current_stage() == _stage
            return _original(*args)

        monkeypatch.setattr(service, method, observed)

    search = pipeline.retriever.search

    def observed_search(*args, **kwargs):
        expected = ("composition_retrieval" if "composition" in kwargs["libraries"]
                    else "parameter_retrieval")
        assert timing.current_stage() == expected
        return search(*args, **kwargs)

    monkeypatch.setattr(pipeline.retriever, "search", observed_search)
    with timing.observe_timings(measured.append):
        result = pipeline.run(image_content, user_request, parallel_advice=parallel)

    assert result.recommendation.shutter_speed == "1/800s"
    assert {event["stage"] for event in measured} == {
        "image_preprocessing", "vision", "localization", "parameter_retrieval",
        "composition_retrieval", "composition", "parameters", "parameter_validation", "total",
    }
    assert measured[-1]["stage"] == "total"
    assert all(event["status"] == "complete" for event in measured)
    assert all(event["duration_seconds"] >= 0 for event in measured)
    assert timing.current_stage() is None


def test_parameter_failure_is_measured_without_marking_fallback_result_as_failed(
    settings, image_content, user_request,
):
    pipeline = make_pipeline(
        settings, retriever(settings), localization(),
        FakeParameterAdvisor(ValueError("synthetic parameter failure")),
    )
    measured = []

    with timing.observe_timings(measured.append):
        result = pipeline.run(image_content, user_request, parallel_advice=True)

    assert result.recommendation.confidence == 0
    statuses = {event["stage"]: event["status"] for event in measured}
    assert statuses["parameters"] == "failed"
    assert "parameter_validation" not in statuses
    assert statuses["composition"] == statuses["total"] == "complete"
