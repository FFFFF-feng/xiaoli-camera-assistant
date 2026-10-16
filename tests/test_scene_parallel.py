"""Offline regressions for scene references combined with overlapping advice."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from threading import Event

import pytest
import test_real_pipeline as fixtures
from PIL import Image

from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import SceneSurvey

settings = fixtures.settings
image_content = fixtures.image_content
user_request = fixtures.user_request


def references(count=2):
    images = []
    for index in range(count):
        output = BytesIO()
        Image.new("RGB", (110 + index * 10, 80), (20 * index, 80, 160)).save(
            output, format="JPEG",
        )
        images.append(output.getvalue())
    return images


def survey(status="consistent", ids=("photo1", "photo2", "photo3"), preferred="photo2"):
    return SceneSurvey(
        status=status, summary="同一场景的不同取景", preferred_photo_id=preferred,
        selection_reason="主体占比清楚", relative_distance="请按取景边缘调整",
        views=[{"image_id": image_id, "contribution": "主体和背景取景"} for image_id in ids],
    )


def make_pipeline(settings):
    return fixtures.make_pipeline(
        settings, ManagedKnowledgeRetriever(KnowledgeStore(settings.knowledge_db_path)),
        fixtures.localization(),
    )


def test_scene_references_reach_vision_and_composition_while_advice_overlaps(
    settings, image_content, user_request, monkeypatch,
):
    # Removing third-positional reference support, reference preprocessing, or
    # independent advice workers must all break this regression.
    pipeline = make_pipeline(settings)
    composition_started, parameters_started = Event(), Event()
    observed_widths = {}
    original_composition = pipeline.composition_advisor.recommend
    original_parameters = pipeline.advisor.recommend

    def vision(inspection, request, candidates):
        observed_widths["vision"] = [item.metrics.width for item in inspection.reference_images]
        return fixtures.scene().model_copy(update={"scene_survey": survey()})

    def composition(inspection, *args):
        observed_widths["composition"] = [
            item.metrics.width for item in inspection.reference_images
        ]
        composition_started.set()
        assert parameters_started.wait(5), "parameter generation did not overlap composition"
        return original_composition(inspection, *args)

    def parameters(*args):
        parameters_started.set()
        assert composition_started.wait(5), "composition did not overlap parameter generation"
        return original_parameters(*args)

    monkeypatch.setattr(pipeline.vision_analyzer, "analyze", vision)
    monkeypatch.setattr(pipeline.composition_advisor, "recommend", composition)
    monkeypatch.setattr(pipeline.advisor, "recommend", parameters)
    partials = []
    result = pipeline.run(
        image_content, user_request, references(),
        parallel_advice=True, on_partial=partials.append,
    )

    assert observed_widths == {"vision": [110, 120], "composition": [110, 120]}
    assert result.scene.scene_survey.preferred_photo_id == "photo2"
    assert partials[0]["value"] == result.scene
    assert partials[-1]["value"] == result.recommendation
    assert result.composition.proposals
    assert "reference_images" not in result.model_dump_json()


def test_scene_serial_and_parallel_results_match_with_five_references(
    settings, image_content, user_request, monkeypatch,
):
    pipeline = make_pipeline(settings)
    complete_survey = survey(ids=tuple(f"photo{i}" for i in range(1, 7)))
    monkeypatch.setattr(pipeline.vision_analyzer, "analyze", lambda *args:
        fixtures.scene().model_copy(update={"scene_survey": complete_survey}))
    images = references(5)

    serial = pipeline.run(image_content, user_request, images)
    parallel = pipeline.run(image_content, user_request, images, parallel_advice=True)

    assert serial.model_dump() == parallel.model_dump()
    assert len(parallel.inspection.reference_images) == 5
    assert parallel.scene.scene_survey == complete_survey


@pytest.mark.parametrize("parallel", [False, True])
def test_mixed_scenes_skip_composition_retrieval_and_generation(
    settings, image_content, user_request, monkeypatch, parallel,
):
    pipeline = make_pipeline(settings)
    monkeypatch.setattr(pipeline.vision_analyzer, "analyze", lambda *args:
        fixtures.scene().model_copy(update={"scene_survey": survey("mixed")}))
    searched_libraries = []
    original_search = pipeline.retriever.search

    def search(*args, **kwargs):
        searched_libraries.append(kwargs.get("libraries", []))
        return original_search(*args, **kwargs)

    def forbidden_composition(*args):
        pytest.fail("mixed scene must not generate a combined composition")

    monkeypatch.setattr(pipeline.retriever, "search", search)
    monkeypatch.setattr(pipeline.composition_advisor, "recommend", forbidden_composition)
    partials = []
    result = pipeline.run(
        image_content, user_request, references(),
        parallel_advice=parallel, on_partial=partials.append,
    )

    assert searched_libraries == [["scene", "technique", "equipment"]]
    assert result.composition.status == "unavailable"
    assert result.composition.proposals == []
    assert result.composition_knowledge_hits == []
    assert result.recommendation.shutter_speed == "1/800s"
    assert [event["kind"] for event in partials] == ["scene", "parameters"]


@pytest.mark.parametrize("ids, preferred", [
    (("photo1", "photo2"), "photo2"),
    (("photo1", "photo2", "photo2"), "photo2"),
    (("photo1", "photo2", "photo4"), "photo2"),
    (("photo1", "photo2", "photo3"), "photo4"),
])
def test_incomplete_duplicate_or_unknown_survey_images_are_rejected_before_partial(
    settings, image_content, user_request, monkeypatch, ids, preferred,
):
    pipeline = make_pipeline(settings)
    monkeypatch.setattr(pipeline.vision_analyzer, "analyze", lambda *args:
        fixtures.scene().model_copy(update={"scene_survey": survey(ids=ids, preferred=preferred)}))
    partials = []

    result = pipeline.run(
        image_content, user_request, references(), parallel_advice=True, on_partial=partials.append,
    )

    assert result.scene.scene_survey is None
    assert any("图号" in note for note in result.scene.uncertainties)
    assert any("未返回完整逐图比较" in note for note in result.scene.uncertainties)
    assert partials[0]["value"] == result.scene


def test_demo_multiphoto_scene_partial_includes_the_final_uncertainty(
    settings, image_content, user_request,
):
    pipeline = make_pipeline(replace(settings, demo_mode=True))
    partials = []

    result = pipeline.run(
        image_content, user_request, references(), parallel_advice=True, on_partial=partials.append,
    )

    assert any("规则演示不识别多图空间关系" in note for note in result.scene.uncertainties)
    assert partials[0]["value"] == result.scene


def test_six_references_are_rejected_before_image_preprocessing(
    settings, image_content, user_request, monkeypatch,
):
    pipeline = make_pipeline(settings)

    def forbidden_analyze(*args):
        pytest.fail("too many scene images must be rejected before preprocessing")

    monkeypatch.setattr(pipeline.image_analyzer, "analyze", forbidden_analyze)
    with pytest.raises(ValueError, match="最多6张"):
        pipeline.run(image_content, user_request, references(6), parallel_advice=True)
