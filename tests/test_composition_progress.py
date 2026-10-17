"""Observation precedes planning; only resolved text enters progressive snapshots."""
from copy import deepcopy

import pytest
import test_composition_advisor as fixtures
from test_composition_advisor import proposal, response, target_board

from camera_assistant.services import composition, observed_composition

inputs = fixtures.inputs


def staged_provider(monkeypatch, before_drawing):
    board = target_board()
    layout = response([{**proposal(), "storyboard": board}])
    monkeypatch.setattr(composition, "request_json", lambda *_: deepcopy(layout))

    source = {"objects": [{**board["layers"][0], "object_id": "object1"}],
              "limitations": ["测试轮廓"]}
    monkeypatch.setattr(observed_composition, "request_json", lambda *_: deepcopy(source))
    monkeypatch.setattr(observed_composition, "trace_observed_scene",
                        lambda answer, _: observed_composition.parse_observed_scene(answer))
    original = composition.apply_observed_layout

    def draw(*args):
        before_drawing()
        return original(*args)

    monkeypatch.setattr(composition, "apply_observed_layout", draw)


def test_resolved_text_is_published_and_cannot_mutate_final_advice(inputs, monkeypatch):
    observed = []

    def before_drawing():
        assert observed == []  # Source projection must finish before publishing proportions.

    def display(text):
        observed.append(text)
        assert text.proposals[0].goal == "减少边缘干扰"
        assert text.proposals[0].storyboard is None
        assert text.proposals[0].sketch is None and text.proposals[0].crop_bbox is None
        text.proposals[0].goal = "UI snapshot edited"

    staged_provider(monkeypatch, before_drawing)
    inspection, request, scene, camera, settings = inputs
    with composition.observe_composition(display):
        result = composition.OpenAICompatibleCompositionAdvisor(settings).recommend(
            inspection, request, scene, None, [], camera)
    assert result.proposals[0].goal == "减少边缘干扰"
    assert len(observed) == 1
    assert result.proposals[0].storyboard.layers[0].details


def test_display_failure_cannot_abort_the_pending_drawing_request(inputs, monkeypatch):
    staged_provider(monkeypatch, lambda: None)

    def broken_display(_):
        raise RuntimeError("detached display")

    inspection, request, scene, camera, settings = inputs
    with composition.observe_composition(broken_display):
        result = composition.OpenAICompatibleCompositionAdvisor(settings).recommend(
            inspection, request, scene, None, [], camera)
    assert result.proposals[0].storyboard.layers[0].details


def test_unvalidated_layout_is_never_published(inputs, monkeypatch):
    observed = []
    monkeypatch.setattr(composition, "request_json", lambda *_: {"proposals": "invalid"})
    monkeypatch.setattr(observed_composition, "request_json", lambda *_: {"objects": []})
    monkeypatch.setattr(composition, "apply_observed_layout", lambda *_: pytest.fail("invalid layout drawn"))
    inspection, request, scene, camera, settings = inputs
    with composition.observe_composition(observed.append), pytest.raises(ValueError):
        composition.OpenAICompatibleCompositionAdvisor(settings).recommend(
            inspection, request, scene, None, [], camera)
    assert observed == []
