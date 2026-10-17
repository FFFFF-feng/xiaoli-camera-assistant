"""Keep references and validated scene output when streaming the new scene route."""
import json

from fastapi.testclient import TestClient
from test_api_streaming import FakePipeline, Value
from test_scene_upload import AUTH, TOKEN, jpg, settings

from camera_assistant.mobile_api import create_app
from camera_assistant.services.timing import measure_stage


def scene_upload(client, *, stream=True):
    return client.post(
        "/api/v1/analyze-scene", headers=AUTH,
        files=[("file", ("main.jpg", jpg("green"), "image/jpeg")),
               ("reference_files", ("reference.jpg", jpg("blue"), "image/jpeg"))],
        data={"consent": "true", "expected_analysis_mode": "demo",
              "user_request": '{"intent":"比较建筑与树木"}', "stream_events": str(stream).lower()},
    )


def test_stream_scene_preserves_references_count_and_single_execution():
    seen = []

    def run(content, request, **options):
        seen.append((content, options.get("reference_images")))
        return Value()

    pipeline = FakePipeline(run)
    with TestClient(create_app(settings(), TOKEN, pipeline)) as client:
        response = scene_upload(client)
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "result"
    assert events[-1]["scene_photo_count"] == 2
    assert len(seen) == 1 and seen[0] == (jpg("green"), [jpg("blue")])
    assert "data:image" not in response.text and "reference_images" not in response.text


def test_json_scene_preserves_references_count_and_single_execution():
    pipeline = FakePipeline()
    with TestClient(create_app(settings(), TOKEN, pipeline)) as client:
        response = scene_upload(client, stream=False)
    assert response.status_code == 200
    assert response.json()["scene_photo_count"] == 2
    assert len(pipeline.calls) == 1 and pipeline.calls[0]["reference_images"] == [jpg("blue")]


def test_scene_timing_metadata_and_layout_text_arrive_before_final_result():
    def run(content, request, **options):
        with measure_stage("composition_layout"):
            options["on_partial"]({"kind": "composition", "value": {"proposals": []}})
        return Value()

    with TestClient(create_app(settings(), TOKEN, FakePipeline(run))) as client:
        response = scene_upload(client)
    events = [json.loads(line) for line in response.text.splitlines()]
    layout = next(i for i, event in enumerate(events)
                  if event["type"] == "partial" and event["kind"] == "composition")
    timing = next(event for event in events if event["type"] == "timing"
                  and event["stage"] == "composition_layout")
    assert layout < len(events) - 1 and timing["status"] == "complete"
    assert timing["duration_seconds"] >= 0
    assert any(item["stage"] == "composition_layout" for item in events[-1]["timings"])
    assert {item["stage"] for item in events[-1]["timings"]} >= {"upload_validation", "queue"}
