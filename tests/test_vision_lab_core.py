import io
import json

import pytest
from PIL import Image
from pydantic import ValidationError

from vision_lab_tool.evaluation import iou
from vision_lab_tool.images import prepare_image
from vision_lab_tool.models import Observation, validate_box
from vision_lab_tool.prompts import build_prompt


def image_bytes(size=(80, 40), orientation=None):
    image = Image.new("RGB", size, "green")
    output = io.BytesIO()
    exif = Image.Exif()
    if orientation:
        exif[274] = orientation
    image.save(output, "JPEG", exif=exif)
    return output.getvalue()


@pytest.mark.parametrize(
    "box",
    [
        [-0.1, 0, 1, 1],
        [0, 0, 2, 1],
        [0.8, 0, 0.2, 1],
        [0, 0, 0, 1],
        [0, 1, 2],
        [0, 0, float("nan"), 1],
    ],
)
def test_invalid_coordinates_rejected(box):
    with pytest.raises(ValueError):
        validate_box(box)


def test_orientation_and_identical_input():
    prepared = prepare_image(image_bytes(orientation=6), longest_edge=30, quality=85)
    assert prepared.original_size == (80, 40)
    assert prepared.corrected.size == (40, 80)
    assert prepared.sent_size == (15, 30)
    assert Image.open(io.BytesIO(prepared.sent_bytes)).getexif() == {}
    assert len(prepared.metadata()["sent_sha256"]) == 64


def test_file_validation():
    with pytest.raises(ValueError):
        prepare_image(b"not an image")
    with pytest.raises(ValueError):
        prepare_image(b"x" * (15 * 1024 * 1024 + 1))
    output = io.BytesIO()
    Image.new("RGB", (2, 2)).save(output, "GIF")
    with pytest.raises(ValueError):
        prepare_image(output.getvalue())


def test_prompt_context_isolation():
    context = {
        "goal": "SECRET_GOAL",
        "equipment": "SECRET_CAMERA",
        "reference": "SECRET_REFERENCE",
        "exif": {"iso": 100},
    }
    prompt = build_prompt("recognition", "template", context)
    assert "SECRET" not in prompt and "iso" not in prompt
    advice = build_prompt("advice", "template", context, include_exif=False)
    assert "SECRET_GOAL" in advice and "iso" not in advice
    assert "iso" in build_prompt("advice", "template", context, include_exif=True)
    assert "bbox" in prompt and "0～1" in prompt


def test_required_schema_and_iou():
    with pytest.raises(ValidationError):
        Observation.model_validate({})
    assert iou([0, 0, 1, 1], [0, 0, 1, 1]) == 1
    assert iou([0, 0, 0.5, 0.5], [0.5, 0.5, 1, 1]) == 0
    assert iou([0, 0, 1, 1], [0, 0, 0.5, 0.5]) == 0.25
    assert json.dumps(Observation.model_json_schema())
