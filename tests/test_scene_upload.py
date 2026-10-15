from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from PIL import Image

from camera_assistant.config import Settings
from camera_assistant.mobile_api import create_app
from camera_assistant.models import SceneSurvey, UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline

TOKEN = "scene-upload-token-for-tests-only"
AUTH = {"Authorization": "Bearer " + TOKEN}


def jpg(color):
    data = BytesIO()
    Image.new("RGB", (120, 80), color).save(data, format="JPEG")
    return data.getvalue()


def settings():
    return Settings(True, "", "https://example.invalid", "", "", 5, 1,
                    Path(__file__).resolve().parents[1] / "knowledge")


def post_scene(client, references, auth=AUTH, consent="true"):
    return client.post("/api/v1/analyze-scene", headers=auth,
        files=[("file", ("main.jpg", jpg("green"), "image/jpeg")),
               *[("reference_files", ("reference.jpg", content, "image/jpeg")) for content in references]],
        data={"consent": consent, "expected_analysis_mode": "demo", "user_request": '{"intent":"比较建筑与树木"}'})


def test_scene_endpoint_passes_all_images_without_exposing_pixels():
    pipeline = CameraAssistantPipeline(settings())
    original = pipeline.run
    pipeline.run = Mock(wraps=original)
    with TestClient(create_app(settings(), TOKEN, pipeline=pipeline)) as client:
        response = post_scene(client, [jpg("blue"), jpg("red")])
    assert response.status_code == 200, response.text
    assert response.json()["scene_photo_count"] == 3
    assert len(pipeline.run.call_args.kwargs["reference_images"]) == 2
    assert "reference_images" not in response.text and "data:image" not in response.text
    assert "model_image_data_url" not in response.text and TOKEN not in response.text


def test_bad_reference_or_too_many_images_never_runs_a_partial_analysis():
    pipeline = CameraAssistantPipeline(settings())
    pipeline.run = Mock()
    with TestClient(create_app(settings(), TOKEN, pipeline=pipeline)) as client:
        assert post_scene(client, [b"bad image"]).status_code == 422
        assert post_scene(client, [jpg("blue")] * 6).status_code == 422
        assert post_scene(client, [jpg("blue")], consent="false").status_code == 422
        assert post_scene(client, [jpg("blue")], auth={}).status_code == 401
        assert client.get("/health").json()["max_scene_images"] == 6
    pipeline.run.assert_not_called()


def test_scene_pipeline_reaches_both_vision_and_composition_with_private_references():
    config = replace(settings(), composition_enabled=True)
    pipeline = CameraAssistantPipeline(config)
    vision = pipeline.vision_analyzer.analyze
    composition = pipeline.composition_advisor.recommend
    pipeline.vision_analyzer.analyze = Mock(wraps=vision)
    pipeline.composition_advisor.recommend = Mock(wraps=composition)
    result = pipeline.run(jpg("green"), UserRequest(intent="比较建筑与树木"), reference_images=[jpg("blue")])
    assert len(pipeline.vision_analyzer.analyze.call_args.args[0].reference_images) == 1
    assert len(pipeline.composition_advisor.recommend.call_args.args[0].reference_images) == 1
    assert "reference_images" not in result.model_dump_json()


def test_mixed_scenes_do_not_generate_a_combined_composition():
    config = replace(settings(), composition_enabled=True)
    pipeline = CameraAssistantPipeline(config)
    original = pipeline.vision_analyzer.analyze
    survey = SceneSurvey(status="mixed", summary="照片环境不一致", preferred_photo_id="photo1",
        selection_reason="保留主图分析", relative_distance="约2米", subject_options=[], foreground_options=[],
        views=[{"image_id": "photo1", "contribution": "建筑"}, {"image_id": "photo2", "contribution": "室内物品"}])
    assert "2米" not in survey.relative_distance
    pipeline.vision_analyzer.analyze = lambda *args: original(*args).model_copy(update={"scene_survey": survey})
    pipeline.composition_advisor.recommend = Mock()
    result = pipeline.run(jpg("green"), UserRequest(intent="比较建筑与树木"), reference_images=[jpg("blue")])
    pipeline.composition_advisor.recommend.assert_not_called()
    assert result.composition.status == "unavailable"
