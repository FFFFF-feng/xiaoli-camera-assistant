"""Scene snapshots distinguish visual estimates from shared confirmed facts."""

from __future__ import annotations

from threading import Barrier

import pytest
import test_real_pipeline as fixtures

from camera_assistant import pipeline as pipeline_module
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import UserRequest
from camera_assistant.services.photography_facts import photography_facts

settings = fixtures.settings
image_content = fixtures.image_content


def pipeline_for(settings, monkeypatch):
    pipeline = fixtures.make_pipeline(
        settings, ManagedKnowledgeRetriever(KnowledgeStore(settings.knowledge_db_path)),
    )
    scene = fixtures.scene().model_copy(update={
        "subject_motion": "fast", "lighting": "warm indoor light", "uncertainties": [],
    })
    monkeypatch.setattr(pipeline.vision_analyzer, "analyze", lambda *_: scene.model_copy(deep=True))
    return pipeline


def test_scene_partial_already_explains_unconfirmed_estimates_and_matches_final(
    settings, image_content, monkeypatch,
):
    pipeline = pipeline_for(settings, monkeypatch)
    original = pipeline_module.build_photography_facts
    built, snapshots = [], []

    def build(*args):
        value = original(*args)
        built.append(value)
        return value

    monkeypatch.setattr(pipeline_module, "build_photography_facts", build)

    def partial(event):
        if event["kind"] == "scene":
            snapshot = event["value"]
            assert any("运动" in note and "视觉估计" in note for note in snapshot.uncertainties)
            assert any("光源" in note and "视觉估计" in note for note in snapshot.uncertainties)
            assert len(built) == 1, "shared facts must exist before scene publication"
            snapshots.append(snapshot.model_dump())

    result = pipeline.run(
        image_content, UserRequest(intent="突出人物并留白"),
        parallel_advice=True, on_partial=partial,
    )

    assert snapshots == [result.scene.model_dump()]
    assert result.scene.subject_motion == "fast"
    assert result.scene.lighting == "warm indoor light"
    assert len(result.scene.uncertainties) == 2
    assert len(built) == 1
    assert built[0].motion == "unknown"
    assert built[0].declared_light is None


def test_parallel_advisors_receive_the_single_facts_instance_built_before_scene(
    settings, image_content, monkeypatch,
):
    pipeline = pipeline_for(settings, monkeypatch)
    original = pipeline_module.build_photography_facts
    built, received = [], {}
    rendezvous = Barrier(2, timeout=5)

    def build(*args):
        value = original(*args)
        built.append(value)
        return value

    monkeypatch.setattr(pipeline_module, "build_photography_facts", build)
    for name, advisor in (("parameters", pipeline.advisor),
                          ("composition", pipeline.composition_advisor)):
        recommend = advisor.recommend

        def observed(*args, _name=name, _recommend=recommend):
            request, scene, camera = (args[1], args[2], args[5]) if _name == "composition" else (
                args[0], args[1], args[3],
            )
            received[_name] = photography_facts(request, scene, camera)
            rendezvous.wait()
            return _recommend(*args)

        monkeypatch.setattr(advisor, "recommend", observed)

    def partial(event):
        if event["kind"] == "scene":
            assert len(built) == 1
            assert received == {}

    pipeline.run(
        image_content, UserRequest(intent="突出人物"),
        parallel_advice=True, on_partial=partial,
    )

    assert len(built) == 1
    assert received["parameters"] is built[0]
    assert received["composition"] is built[0]


@pytest.mark.parametrize("user_input, confirmed_motion", [
    (UserRequest(intent="突出人物", subject_motion="静止", lighting_type="natural"), "static"),
    (UserRequest(intent="人物正在快速奔跑，现场使用LED灯"), "fast"),
])
def test_user_confirmed_motion_and_light_are_not_labeled_unconfirmed(
    settings, image_content, monkeypatch, user_input, confirmed_motion,
):
    pipeline = pipeline_for(settings, monkeypatch)
    facts_seen = []
    recommend = pipeline.advisor.recommend

    def capture(*args):
        facts_seen.append(photography_facts(args[0], args[1], args[3]))
        return recommend(*args)

    monkeypatch.setattr(pipeline.advisor, "recommend", capture)
    snapshots = []
    result = pipeline.run(image_content, user_input, on_partial=lambda event: snapshots.append(event)
                          if event["kind"] == "scene" else None)

    assert result.scene.uncertainties == []
    assert snapshots[0]["value"] == result.scene
    assert result.scene.lighting == "warm indoor light"
    assert facts_seen[0].motion == confirmed_motion
    assert facts_seen[0].declared_light in {"natural", "led"}
