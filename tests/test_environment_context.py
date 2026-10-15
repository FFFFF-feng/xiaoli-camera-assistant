from __future__ import annotations

import json
from pathlib import Path

import pytest

from camera_assistant.models import SceneAnalysis, UserRequest


def make_scene(**updates: object) -> SceneAnalysis:
    payload: dict[str, object] = {
        "scene_type": "daylight_landscape",
        "subject": "landscape",
        "environment": "outdoor",
        "lighting": "自然光线索",
        "brightness": "medium",
        "backlight": False,
        "subject_motion": "static",
        "dynamic_range": "medium",
        "desired_effects": ["层次清楚"],
        "confidence": 0.8,
    }
    payload.update(updates)
    return SceneAnalysis.model_validate(payload)


def test_legacy_scene_separates_content_from_unconfirmed_camera_location() -> None:
    scene = make_scene()
    context = getattr(scene, "environment_context", None)
    assert context is not None, "单个 environment 标签缺少拍摄位置与画面内容的区分"
    assert context.shooting_location == "unknown"


def test_p03_saved_window_view_keeps_legacy_label_and_exposes_uncertainty() -> None:
    from camera_assistant.services.environment import (
        environment_advice_constraints,
        environment_display_lines,
        normalize_scene_environment,
    )

    root = Path(__file__).resolve().parents[1]
    saved = json.loads(
        (root / "data/history/main-fix-final-20261014/P03-pipeline.json").read_text(
            encoding="utf-8"
        )
    )
    original = SceneAnalysis.model_validate(saved["scene"])
    scene = normalize_scene_environment(original, UserRequest(intent="保留整个窗框，让远处树林更有层次"))

    assert scene.environment == original.environment == "outdoor"
    assert scene.environment_context.shooting_location == "unknown"
    assert scene.environment_context.content_environment == "mixed"
    assert scene.environment_context.relationship == "through_window"
    assert any("拍摄位置未确认" in text for text in scene.uncertainties)
    assert any("窗框和室外风景" in text for text in environment_display_lines(scene))
    constraints = environment_advice_constraints(scene)
    assert "不得" in constraints and "照度" in constraints
    assert "拍摄位置未确认" in constraints


def test_indoor_and_outdoor_contents_are_mixed_without_guessing_viewpoint() -> None:
    from camera_assistant.services.environment import normalize_scene_environment

    scene = normalize_scene_environment(
        make_scene(environment="mixed", recognition_evidence=["房间家具与室外庭院同时可见"]),
        UserRequest(intent="让近处家具和远处树木都保留在照片里"),
    )
    assert scene.environment_context.content_environment == "mixed"
    assert scene.environment_context.shooting_location == "unknown"
    assert scene.environment_context.relationship == "mixed_view"
    assert any("拍摄位置未确认" in text for text in scene.uncertainties)


def test_plain_outdoor_scene_does_not_add_window_claim_or_change_old_uncertainties() -> None:
    from camera_assistant.services.environment import normalize_scene_environment

    scene = normalize_scene_environment(
        make_scene(recognition_evidence=["室外山峰、树木和天空"], uncertainties=["远处树种不明"]),
        UserRequest(intent="让山脊的轮廓更醒目"),
    )
    assert scene.environment_context.content_environment == "outdoor"
    assert scene.environment_context.shooting_location == "unknown"
    assert scene.environment_context.relationship == "unknown"
    assert scene.uncertainties == ["远处树种不明"]


def test_window_request_alone_does_not_invent_visible_window() -> None:
    from camera_assistant.services.environment import normalize_scene_environment

    scene = normalize_scene_environment(
        make_scene(recognition_evidence=["山峰与天空"]),
        UserRequest(intent="之后想试着通过窗框拍摄，先看看山峰怎么构图"),
    )
    assert scene.environment_context.relationship == "unknown"
    assert scene.environment_context.content_environment == "outdoor"


def test_model_viewpoint_is_not_confirmation_of_actual_shooting_location() -> None:
    from camera_assistant.services.environment import normalize_scene_environment

    scene = normalize_scene_environment(
        make_scene(
            environment_context={
                "shooting_location": "indoor",
                "content_environment": "mixed",
                "relationship": "through_window",
                "evidence": ["窗框与室外树林同时可见"],
            }
        ),
        UserRequest(intent="窗框要完整，树林不要挤在一起"),
    )
    assert scene.environment_context.shooting_location == "unknown"
    assert scene.environment_context.shooting_location_source == "unknown"
    assert any("拍摄位置未确认" in text for text in scene.uncertainties)


@pytest.mark.parametrize("location", ["indoor", "outdoor"])
def test_user_confirmed_location_is_preserved_for_window_scene(location: str) -> None:
    from camera_assistant.services.environment import normalize_scene_environment

    scene = normalize_scene_environment(
        make_scene(recognition_evidence=["画面可见窗框与室外风景"]),
        UserRequest(intent="窗框要完整，树木有层次", shooting_location=location),
    )
    assert scene.environment_context.shooting_location == location
    assert scene.environment_context.shooting_location_source == "user"
    assert not any("拍摄位置未确认" in text for text in scene.uncertainties)


def test_normalization_is_idempotent_and_does_not_mutate_saved_scene() -> None:
    from camera_assistant.services.environment import normalize_scene_environment

    original = make_scene(recognition_evidence=["画面可见窗框与室外风景"])
    original_dump = original.model_dump()
    request = UserRequest(intent="保留窗框，远处更有层次")
    first = normalize_scene_environment(original, request)
    second = normalize_scene_environment(first, request)
    assert second.model_dump() == first.model_dump()
    assert original.model_dump() == original_dump


def test_absent_window_frame_does_not_add_mixed_content() -> None:
    from camera_assistant.services.environment import normalize_scene_environment

    scene = normalize_scene_environment(
        make_scene(recognition_evidence=["窗外景物，画面没有窗框，也没有室内家具"]),
        UserRequest(intent="远山要有轮廓，天空的云也想留住"),
    )
    assert scene.environment_context.content_environment == "outdoor"
    assert scene.environment_context.relationship == "unknown"


@pytest.mark.parametrize("intent", [
    "如果我在室内，能这样拍吗", "我在室内还是室外不确定", "我在室内？",
    "我在室内吗？请保留整个窗框", "我在室内还是室外？请根据照片判断",
])
def test_question_or_hypothesis_does_not_confirm_camera_location(intent: str) -> None:
    from camera_assistant.services.environment import normalize_scene_environment

    scene = normalize_scene_environment(make_scene(), UserRequest(intent=intent))
    assert scene.environment_context.shooting_location == "unknown"


def test_explicit_user_location_does_not_change_visual_lighting_or_brightness() -> None:
    from camera_assistant.services.environment import normalize_scene_environment

    scene = normalize_scene_environment(
        make_scene(recognition_evidence=["画面可见窗框与室外风景"]),
        UserRequest(intent="我站在室内，请保留整个窗框"),
    )
    assert scene.environment_context.shooting_location == "indoor"
    assert scene.environment == "outdoor"
    assert scene.lighting == "自然光线索"
    assert scene.brightness == "medium"


def test_reflection_does_not_locate_camera_in_reflected_scene() -> None:
    from camera_assistant.services.environment import normalize_scene_environment

    scene = normalize_scene_environment(
        make_scene(environment_context={
            "content_environment": "outdoor",
            "shooting_location": "outdoor",
            "relationship": "reflection",
            "evidence": ["玻璃上可见室外树木倒影"],
        }),
        UserRequest(intent="倒影和主体之间要有一点空间"),
    )
    assert scene.environment_context.shooting_location == "unknown"
    assert scene.environment_context.content_environment == "outdoor"
    assert scene.environment_context.relationship == "reflection"
    assert any("拍摄位置未确认" in text for text in scene.uncertainties)
