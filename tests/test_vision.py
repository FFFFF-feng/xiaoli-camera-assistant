from types import SimpleNamespace

import pytest

from camera_assistant.models import (
    ExifInfo,
    ImageInspection,
    ImageMetrics,
    SceneCandidate,
    UserRequest,
)
from camera_assistant.services.vision import OpenAICompatibleVisionAnalyzer


def inspection_with_references(count=5):
    image = ImageInspection(
        exif=ExifInfo(),
        metrics=ImageMetrics(
            width=120,
            height=80,
            mean_brightness=0.5,
            contrast=20,
            shadow_ratio=0.1,
            highlight_ratio=0.1,
            sharpness_score=10,
        ),
        model_image_data_url="data:image/jpeg;base64,MAIN",
    )
    image.reference_images = [
        image.model_copy(update={
            "model_image_data_url": f"data:image/jpeg;base64,REF{index}",
            "reference_images": [],
        })
        for index in range(count)
    ]
    return image


def candidate():
    return SceneCandidate(
        profile_id="generic_scene",
        label="通用场景",
        description="测试场景",
        subject="主体",
        environment="环境",
        default_motion="unknown",
    )


def invalid_scene_with_valid_mixed_survey():
    return {
        "scene_type": "generic_scene",
        "scene_label": "通用场景",
        "subject": "",
        "environment": "",
        "lighting": "",
        "brightness": "medium",
        "backlight": False,
        "subject_motion": "mixed",
        "dynamic_range": "medium",
        "desired_effects": [],
        "confidence": 0.5,
        "notes": [],
        "recognition_evidence": [],
        "candidate_scenes": [],
        "retrieval_terms": [],
        "objects": [],
        "main_subject_ids": [],
        "subject_status": "abstained",
        "composition_clues": [],
        "uncertainties": [],
        "scene_survey": {
            "status": "mixed",
            "summary": "照片来自不同场景",
            "views": [
                {"image_id": f"photo{index}", "contribution": "独立场景"}
                for index in range(1, 7)
            ],
            "preferred_photo_id": "photo1",
            "selection_reason": "主图作为保守起点",
            "relative_distance": "无法比较不同场景的距离",
        },
    }


def test_mixed_multiphoto_validation_error_degrades_to_safe_survey(monkeypatch):
    payload = invalid_scene_with_valid_mixed_survey()
    monkeypatch.setattr(
        "camera_assistant.services.vision.request_json",
        lambda _settings, _payload: payload,
    )
    analyzer = OpenAICompatibleVisionAnalyzer(SimpleNamespace(vision_model="test"))

    result = analyzer.analyze(
        inspection_with_references(),
        UserRequest(intent="比较这组照片的场景关系"),
        [candidate()],
    )

    assert result.scene_survey is not None
    assert result.scene_survey.status == "mixed"
    assert {view.image_id for view in result.scene_survey.views} == {
        f"photo{index}" for index in range(1, 7)
    }
    assert result.objects == []
    assert result.main_subject_ids == []
    assert result.subject_status == "abstained"
    assert result.confidence == 0
    assert any("结构校验" in note for note in result.uncertainties)


def test_invalid_multiphoto_survey_still_raises_validation_error(monkeypatch):
    payload = invalid_scene_with_valid_mixed_survey()
    payload["scene_survey"]["views"][-1]["image_id"] = "photo7"
    monkeypatch.setattr(
        "camera_assistant.services.vision.request_json",
        lambda _settings, _payload: payload,
    )
    analyzer = OpenAICompatibleVisionAnalyzer(SimpleNamespace(vision_model="test"))

    with pytest.raises(ValueError):
        analyzer.analyze(
            inspection_with_references(),
            UserRequest(intent="比较这组照片的场景关系"),
            [candidate()],
        )
