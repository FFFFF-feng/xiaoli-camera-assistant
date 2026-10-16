"""Validated layout text is usable before the optional geometry request finishes."""
from copy import deepcopy

import pytest
import test_composition_advisor as fixtures
from test_composition_advisor import proposal, response, target_board

from camera_assistant.services import composition, target_drawing

inputs = fixtures.inputs


def staged_provider(monkeypatch, before_drawing):
    board = target_board()
    layout = response([{**proposal(), "storyboard": board}])
    monkeypatch.setattr(composition, "request_json", lambda *_: deepcopy(layout))

    def draw(*_):
        before_drawing()
        return {"layers": [{"proposal_index": 0, "layer_index": 0,
                            "outline": board["layers"][0]["outline"],
                            "details": board["layers"][0]["details"]}]}

    monkeypatch.setattr(target_drawing, "request_json", draw)


def test_validated_text_precedes_geometry_and_cannot_mutate_final_advice(inputs, monkeypatch):
    observed = []

    def before_drawing():
        assert len(observed) == 1
        text = observed[0]
        assert text.proposals[0].goal == "减少边缘干扰"
        assert text.proposals[0].storyboard is None
        assert text.proposals[0].sketch is None and text.proposals[0].crop_bbox is None
        text.proposals[0].goal = "UI snapshot edited"

    staged_provider(monkeypatch, before_drawing)
    inspection, request, scene, camera, settings = inputs
    with composition.observe_composition(observed.append):
        result = composition.OpenAICompatibleCompositionAdvisor(settings).recommend(
            inspection, request, scene, None, [], camera)
    assert result.proposals[0].goal == "减少边缘干扰"
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
    monkeypatch.setattr(target_drawing, "request_json", lambda *_: pytest.fail("invalid layout drawn"))
    inspection, request, scene, camera, settings = inputs
    with composition.observe_composition(observed.append), pytest.raises(ValueError):
        composition.OpenAICompatibleCompositionAdvisor(settings).recommend(
            inspection, request, scene, None, [], camera)
    assert observed == []
