"""Publish complete local geometry separately from legacy text-only snapshots."""
from copy import deepcopy

import pytest
import test_composition_advisor as fixtures
from test_composition_advisor import proposal
from test_composition_intents import setup_source
from test_composition_progress import staged_provider

from camera_assistant.services import composition

inputs = fixtures.inputs


def live_response(monkeypatch, *, intent=True):
    setup_source(monkeypatch)
    value = {"proposals": [{**proposal(), "composition_intent": {
        "focus_object_id": "object1", "diagnosis": "突出建筑，完整保护边缘",
        "placement": "left", "subject_scale": "larger",
    } if intent else None}]}
    monkeypatch.setattr(composition, "request_json", lambda *_: deepcopy(value))


def run(inputs, text, ready):
    inspection, request, scene, camera, settings = inputs
    with composition.observe_composition(text, on_ready=ready):
        return composition.OpenAICompatibleCompositionAdvisor(settings).recommend(
            inspection, request, scene, None, [], camera)


def test_validated_local_board_arrives_before_return_and_is_an_isolated_snapshot(inputs, monkeypatch):
    live_response(monkeypatch)
    events, complete = [], []

    def text(value):
        assert value.proposals[0].storyboard is None
        events.append("text")

    def ready(value):
        assert events == ["text"]
        assert value.proposals[0].storyboard.layout_engine == "local_v1"
        assert any(d.code == "local_layout_solved" for d in value.diagnostics)
        complete.append(value.model_dump())
        value.proposals[0].goal = "consumer edit"
        value.proposals[0].storyboard.layers[0].bbox[0] = .99
        events.append("ready")

    result = run(inputs, text, ready)
    assert events == ["text", "ready"]
    assert complete == [result.model_dump()]
    assert result.proposals[0].goal != "consumer edit"


@pytest.mark.parametrize("bad_intent", [False, True])
def test_no_ready_board_is_published_for_missing_or_rejected_intent(inputs, monkeypatch, bad_intent):
    live_response(monkeypatch, intent=not bad_intent)
    if not bad_intent:
        monkeypatch.setattr(composition, "solve_layout", lambda *_: (_ for _ in ()).throw(ValueError()))
    complete = []
    result = run(inputs, lambda _: None, complete.append)
    assert result.proposals[0].storyboard is None
    assert complete == []


def test_legacy_geometry_stays_in_final_and_does_not_use_ready_channel(inputs, monkeypatch):
    staged_provider(monkeypatch, lambda: None)
    complete = []
    # The legacy fixture replaces observe_objects directly in other tests; use
    # only the provider boundary established by staged_provider in this case.
    result = run(inputs, lambda _: None, complete.append)
    assert result.proposals[0].storyboard
    assert complete == []


def test_ready_display_failure_does_not_discard_the_final_board(inputs, monkeypatch):
    live_response(monkeypatch)

    def disconnected(_):
        raise RuntimeError("display closed")

    result = run(inputs, lambda _: None, disconnected)
    assert result.proposals[0].storyboard.layout_engine == "local_v1"
