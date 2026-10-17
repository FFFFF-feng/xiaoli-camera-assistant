"""Offline integration of validated streaming with the full line-art advice schema."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
import test_real_pipeline as fixtures
from fastapi.testclient import TestClient
from test_api_streaming import AUTH, TOKEN, decoded
from test_real_pipeline import FakeParameterAdvisor, localization, make_pipeline

from camera_assistant import mobile_api
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.services import composition as composition_service

settings = fixtures.settings
image_content = fixtures.image_content
user_request = fixtures.user_request


@pytest.fixture
def model_advice():
    """Synthetic model JSON, deliberately including fields from the latest schema."""
    return {
        "status": "unverified",
        "observations": ["合成观察：人物右侧有留白"],
        "uncertainties": ["合成离线输入，不代表真实视觉证据"],
        "proposals": [{
            "action_type": "reshoot",
            "goal": "保留人物的完整轮廓和右侧方向空间",
            "actions": ["保持当前机位，重新取景", "检查头顶与手臂均在画幅内"],
            "reasons": ["让人物轮廓更易辨认"],
            "tradeoffs": ["右侧背景会占用更多画面"],
            "conditions": ["现场允许重新取景"],
            "limitations": ["需要现场试拍确认"],
            "knowledge_ids": [],
            "framing_plan": {
                "diagnosis": "合成观察：保留人物完整性和右侧空间",
                "visual_priority": "先看人物，再看右侧背景",
                "placement": "未校验的模型位置",
                "scale": "未校验的模型比例",
                "negative_space": "未校验的模型余量",
                "edge_check": "检查头顶、双臂与脚部均有余量",
                "background_control": "保留可见背景，避免人物轮廓与边缘重叠",
                "success_check": "人物轮廓完整，右侧仍保留可见背景",
            },
            "sketch": {
                "aspect": "landscape",
                "caption": "人物放在左侧，右侧保留背景",
                "elements": [{
                    "kind": "person", "label": "人物", "role": "main",
                    "bbox": [.1, .15, .5, .9],
                    "appearance": "walking", "facing": "right",
                    "description": "抬臂行走的完整人物轮廓",
                    "source_bbox": [.2, .125, .7, .9375],
                    "identity_features": ["抬起的手臂", "浅色上衣轮廓"],
                }],
                "horizon_y": None,
                "camera_action": "stay",
                "camera_instruction": "保持机位，检查人物四周余量后重新取景",
                "theme": "行走人物与环境",
                "mood": "简洁清晰",
                "narration": "保留人物完整轮廓，用右侧可见背景形成方向空间。",
                "space_note": "右侧保留可见背景，为人物的朝向留出空间",
            },
        }],
    }


class SlowShutterModel(FakeParameterAdvisor):
    def recommend(self, *args):
        # Real validation must correct both values before either API mode serializes them.
        return super().recommend(*args).model_copy(update={
            "shutter_speed": "1/30s", "aperture": "f/1.8",
        })


@pytest.fixture
def pipeline_factory(settings, monkeypatch, model_advice):
    # Only the model boundary is replaced. Schema parsing, composition checks,
    # line-art geometry, parameter validation and pipeline assembly are real.
    monkeypatch.setattr(
        composition_service, "request_json", lambda *_: deepcopy(model_advice),
    )
    located_subject = localization()

    def make():
        return make_pipeline(
            settings,
            ManagedKnowledgeRetriever(KnowledgeStore(settings.knowledge_db_path)),
            located_subject, SlowShutterModel(),
            composition_service.OpenAICompatibleCompositionAdvisor(settings),
        )

    return make


def assert_complete_line_art(result, model_advice):
    advice = result["composition"]
    assert advice["status"] == "unverified"
    assert len(advice["proposals"]) == 1
    proposal = advice["proposals"][0]
    original = model_advice["proposals"][0]
    assert proposal["sketch"] == original["sketch"]
    assert proposal["sketch"]["elements"][0]["source_bbox"] == [.2, .125, .7, .9375]
    assert proposal["sketch"]["elements"][0]["identity_features"] == [
        "抬起的手臂", "浅色上衣轮廓",
    ]
    plan = proposal["framing_plan"]
    assert set(plan) == set(original["framing_plan"])
    assert all(plan.values())
    # These three instructions come from validated photo geometry, so preserving
    # only the unprocessed model object would fail this integration assertion.
    for key in ("placement", "scale", "negative_space"):
        assert plan[key] != original["framing_plan"][key]
    for key in ("diagnosis", "visual_priority", "edge_check",
                "background_control", "success_check"):
        assert plan[key] == original["framing_plan"][key]


def post_photo(client, image_content, user_request, *, stream_events=None):
    data = {
        "user_request": user_request.model_dump_json(),
        "consent": "true", "expected_analysis_mode": "cloud",
    }
    if stream_events is not None:
        data["stream_events"] = str(stream_events).lower()
    return client.post(
        "/api/v1/analyze", headers=AUTH,
        files={"file": ("synthetic.jpg", image_content, "image/jpeg")}, data=data,
    )


def test_parallel_and_serial_keep_identical_validated_line_art(
    pipeline_factory, image_content, user_request, model_advice,
):
    serial = pipeline_factory().run(image_content, user_request)
    partials = []
    parallel = pipeline_factory().run(
        image_content, user_request, parallel_advice=True, on_partial=partials.append,
    )

    assert parallel.model_dump(mode="json") == serial.model_dump(mode="json")
    assert_complete_line_art(parallel.model_dump(mode="json"), model_advice)
    assert partials[0]["kind"] == "scene"
    assert {event["kind"] for event in partials} == {"scene", "parameters", "composition"}
    assert next(event["value"] for event in partials if event["kind"] == "parameters") == parallel.recommendation
    assert parallel.recommendation.shutter_speed == "1/500s 或更快"
    assert parallel.recommendation.aperture == "f/4（镜头最大光圈）"
    assert parallel.recommendation.validation_notes


def test_stream_publishes_validated_snapshots_and_only_final_line_art(
    settings, pipeline_factory, image_content, user_request, model_advice,
):
    with TestClient(mobile_api.create_app(settings, TOKEN, pipeline_factory())) as client:
        response = post_photo(client, image_content, user_request, stream_events=True)
    events = decoded(response)
    assert response.headers["content-type"].startswith("application/x-ndjson")
    partials = [event for event in events if event["type"] == "partial"]
    assert partials[0]["kind"] == "scene"
    assert {event["kind"] for event in partials} == {"scene", "parameters", "composition"}
    assert events[-1]["type"] == "result"
    assert sum(event["type"] == "result" for event in events) == 1
    result = events[-1]["result"]
    assert partials[0]["value"] == result["scene"]
    parameters = next(event["value"] for event in partials if event["kind"] == "parameters")
    assert parameters == result["recommendation"]
    assert parameters["shutter_speed"] == "1/500s 或更快"
    assert parameters["aperture"] == "f/4（镜头最大光圈）"
    assert parameters["validation_notes"]
    layout = next(event["value"] for event in partials if event["kind"] == "composition")
    assert layout["proposals"][0]["framing_plan"] == result["composition"]["proposals"][0]["framing_plan"]
    assert layout["proposals"][0]["sketch"] is None
    assert layout["proposals"][0]["storyboard"] is None
    assert layout["proposals"][0]["crop_bbox"] is None
    # Text may arrive early, while geometry remains exclusive to the final result.
    for event in events[:-1]:
        serialized = json.dumps(event, ensure_ascii=False)
        assert all(field not in serialized for field in (
            '"source_bbox"', '"identity_features"',
        ))
    assert "未校验的模型" not in response.text
    assert "1/30s" not in response.text and "f/1.8" not in response.text
    assert "data:image" not in response.text and TOKEN not in response.text
    assert_complete_line_art(result, model_advice)


@pytest.mark.parametrize("stream_events", [None, False])
def test_default_and_explicit_json_preserve_the_same_line_art_payload(
    settings, pipeline_factory, image_content, user_request, model_advice, stream_events,
):
    expected = pipeline_factory().run(image_content, user_request).model_dump(mode="json")
    with TestClient(mobile_api.create_app(settings, TOKEN, pipeline_factory())) as client:
        response = post_photo(
            client, image_content, user_request, stream_events=stream_events,
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    envelope = response.json()
    assert {"request_id", "analysis_mode", "image_provenance", "result"} <= envelope.keys()
    assert envelope["scene_photo_count"] == 1 and envelope["timings"]
    assert envelope["analysis_mode"] == "cloud"
    assert envelope["result"] == expected
    assert_complete_line_art(envelope["result"], model_advice)
