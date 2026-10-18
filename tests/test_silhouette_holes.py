
import pytest
from pydantic import ValidationError
from test_observed_composition import observed

from camera_assistant.composition_models import ObservedScene
from camera_assistant.services.drawing_geometry import contained_outline
from camera_assistant.services.pixel_contours import observed_metadata


def test_hole_cannot_cross_or_touch_concave_subject_boundary():
    outer = [[0, 0], [1, 0], [1, 1], [.6, 1], [.6, .4], [.4, .4], [.4, 1], [0, 1]]
    assert contained_outline(outer, [[.1, .1], [.3, .1], [.2, .3]])
    assert not contained_outline(outer, [[.2, .7], [.8, .7], [.5, .2]])
    assert not contained_outline(outer, [[0, .1], [.2, .1], [.1, .3]])


def test_holes_are_optional_but_validated_and_model_supplied_holes_discarded():
    data = observed()
    data['objects'][0]['outline'] = [[0, 0], [1, 0], [1, 1], [0, 1]]
    data['objects'][0]['holes'] = [[[.1, .1], [.3, .1], [.2, .3]]]
    assert ObservedScene.model_validate(data).objects[0].holes
    assert observed_metadata(data).objects[0].holes == []
    data['objects'][0]['holes'] = [[[0, .1], [.3, .1], [.2, .3]]]
    with pytest.raises(ValidationError):
        ObservedScene.model_validate(data)
