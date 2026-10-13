"""Integration checks for real-mode stage boundaries using synthetic, offline evidence."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from camera_assistant import pipeline as pipeline_module
from camera_assistant.composition_models import CompositionAdvice, CompositionProposal
from camera_assistant.config import Settings
from camera_assistant.knowledge.models import KnowledgeRecord, SourceInfo
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import CameraRecommendation, SceneAnalysis, UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline
from vision_lab_tool.detector_models import (
    DetectionObject,
    MethodResult,
    SemanticObject,
    SubjectSelection,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        demo_mode=False,
        api_key="synthetic-test-key",
        base_url="https://example.invalid/v1",
        vision_model="synthetic-vision",
        text_model="synthetic-advisor",
        timeout_seconds=5,
        max_image_mb=15,
        knowledge_dir=Path(__file__).resolve().parents[1] / "knowledge",
        knowledge_mode="managed",
        knowledge_db_path=tmp_path / "knowledge.db",
        composition_enabled=True,
        detector_enabled=True,
    )


@pytest.fixture
def image_content() -> bytes:
    output = BytesIO()
    Image.new("RGB", (100, 80), (80, 90, 100)).save(output, format="JPEG")
    return output.getvalue()


@pytest.fixture
def user_request() -> UserRequest:
    return UserRequest(
        intent="拍摄快速跑动的人物，保留主体并留白",
        subject_motion="快速",
        camera_profile_id="canon_eos_r50",
        max_aperture=4,
    )


def scene() -> SceneAnalysis:
    return SceneAnalysis(
        scene_type="general_scene",
        subject="person",
        environment="outdoor",
        lighting="available light",
        brightness="medium",
        backlight=False,
        subject_motion="fast",
        dynamic_range="medium",
        desired_effects=["sharp_subject"],
        confidence=.8,
        recognition_evidence=["测试观察：人物在画面中央"],
        objects=[SemanticObject(
            object_id="visual_person", label="人物", query="person",
            target_level="instance", entity_kind="physical",
        )],
        main_subject_ids=["visual_person"],
        subject_status="selected",
        composition_clues=["主体右侧留白"],
        uncertainties=["单帧无法确定实际运动速度"],
    )


def localization(status: str = "selected") -> MethodResult:
    candidate = DetectionObject(
        object_id="detected_person", label_original="person", label_display="人物",
        bbox_native=[20, 10, 70, 75], bbox_postprocessed=[20, 10, 70, 75],
        bbox=[.2, .125, .7, .9375],
        coordinate_basis="orientation_corrected_normalized_xyxy",
        target_level="instance", entity_kind="physical", score=.8,
    )
    return MethodResult(
        method="B1", detector="grounding_dino", status="success", candidates=[candidate],
        selection=SubjectSelection(
            status=status,
            selected_ids=[candidate.object_id] if status == "selected" else [],
            candidate_ids=[candidate.object_id],
            reason="测试用的定位结果，不是真实检测证据",
        ),
    )


class FakeVision:
    def __init__(self) -> None:
        self.calls = []

    def analyze(self, inspection, request, candidates):
        self.calls.append((inspection, request, candidates))
        return scene()


class FakeLocalizer:
    def __init__(self, result: MethodResult | None = None) -> None:
        self.result = result
        self.calls = []

    def localize(self, inspection, request, scene):
        self.calls.append((inspection, request, scene))
        return self.result


class FakeParameterAdvisor:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    def recommend(self, request, scene, hits, camera):
        self.calls.append((request, scene, hits, camera))
        if self.error:
            raise self.error
        return CameraRecommendation(
            shooting_mode="Tv 快门优先", aperture="f/4", shutter_speed="1/800s",
            iso="ISO 400", exposure_compensation="0 EV", focus_mode="Servo AF",
            metering_mode="评价测光", drive_mode="连拍", white_balance="自动白平衡",
            reasons=["测试参数建议"], risks=["需要现场验证"], adjustments=[], confidence=.8,
        )


class FakeCompositionAdvisor:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []
        self.result = None

    def recommend(self, inspection, request, scene, localization, hits, camera):
        self.calls.append((inspection, request, scene, localization, hits, camera))
        if self.error:
            raise self.error
        self.result = CompositionAdvice(
            status="grounded" if hits else "unverified",
            observations=["测试观察：主体右侧有留白"],
            uncertainties=["测试未验证现场效果"],
            proposals=[CompositionProposal(
                action_type="reshoot", goal="保留人物和右侧留白",
                actions=["在现场重新取景"], reasons=["保留主体与背景关系"],
                tradeoffs=["背景范围可能改变"], conditions=["现场允许重新取景"],
                limitations=["需要实拍复核"], knowledge_ids=[hit.document_id for hit in hits],
            )],
        )
        return self.result


def knowledge_record(knowledge_id: str, library: str, **overrides) -> KnowledgeRecord:
    values = {
        "knowledge_id": knowledge_id,
        "library_id": library,
        "title": "自动化测试人物主体留白快门资料",
        "kind": "guideline",
        "content": "合成测试资料：人物 主体 留白 快门。不是正式摄影知识。",
        "conditions": {"motion": "fast"},
        "source": SourceInfo(name="自动化测试来源", retrieval_allowed=True),
        "author": "fixture-author",
    }
    values.update(overrides)
    return KnowledgeRecord(**values)


def publish(store: KnowledgeStore, record: KnowledgeRecord) -> None:
    store.save_draft(record)
    store.submit(record.knowledge_id)
    store.approve(record.knowledge_id, reviewer="fixture-reviewer")
    store.publish(record.knowledge_id)


def make_pipeline(settings, retriever, loc=None, parameter=None, composition=None):
    return CameraAssistantPipeline(
        settings,
        retriever=retriever,
        vision_analyzer=FakeVision(),
        localizer=FakeLocalizer(loc),
        advisor=parameter or FakeParameterAdvisor(),
        composition_advisor=composition or FakeCompositionAdvisor(),
    )


def hit_ids(hits):
    return {hit.metadata["knowledge_id"] for hit in hits}


def test_managed_pipeline_separates_evidence_and_respects_publication_conditions(
    settings, image_content, user_request,
):
    store = KnowledgeStore(settings.knowledge_db_path)
    for library in ("scene", "technique", "equipment", "composition", "style", "case"):
        publish(store, knowledge_record(f"allowed_{library}", library))
    for library in ("technique", "composition"):
        publish(store, knowledge_record(f"wrong_motion_{library}", library,
                                        conditions={"motion": "static"}))
        store.save_draft(knowledge_record(f"draft_{library}", library))
        for prefix, overrides in (
            ("evaluation", {"dataset_split": "evaluation"}),
            ("restricted", {"source": SourceInfo(name="受限测试来源", retrieval_allowed=False)}),
        ):
            record = knowledge_record(f"{prefix}_{library}", library, **overrides)
            store.save_draft(record)
            store.submit(record.knowledge_id)
            store.approve(record.knowledge_id, reviewer="fixture-reviewer")

    parameter = FakeParameterAdvisor()
    composition = FakeCompositionAdvisor()
    loc = localization()
    pipeline = make_pipeline(settings, ManagedKnowledgeRetriever(store), loc, parameter, composition)
    result = pipeline.run(image_content, user_request)

    assert hit_ids(result.knowledge_hits) == {
        "allowed_scene", "allowed_technique", "allowed_equipment",
    }
    assert hit_ids(result.composition_knowledge_hits) == {
        "allowed_composition", "allowed_style", "allowed_case",
    }
    assert parameter.calls[0][2] == result.knowledge_hits
    assert composition.calls[0][4] == result.composition_knowledge_hits
    assert all(hit.metadata["review_status"] == "published"
               for hit in [*result.knowledge_hits, *result.composition_knowledge_hits])
    assert result.localization == loc
    assert composition.calls[0][3] == loc
    assert result.scene.objects == scene().objects
    assert result.scene.main_subject_ids == ["visual_person"]
    assert result.scene.subject_status == "selected"
    assert result.scene.composition_clues == ["主体右侧留白"]
    assert result.scene.uncertainties == ["单帧无法确定实际运动速度"]
    assert composition.calls[0][2] == result.scene
    assert result.camera_profile.profile_id == "canon_eos_r50"
    assert composition.calls[0][1].camera_format == "APS-C"
    assert result.composition == composition.result
    assert result.recommendation.shutter_speed == "1/800s"


@pytest.mark.parametrize("library", ["composition", "technique"])
def test_subject_conditions_use_standard_category_when_model_description_is_chinese(
    settings, image_content, user_request, monkeypatch, library,
):
    store = KnowledgeStore(settings.knowledge_db_path)
    publish(store, knowledge_record("person_rule", library, conditions={"subject": "person"}))
    publish(store, knowledge_record("wrong_rule", library, conditions={"subject": "pet"}))
    model_scene = scene().model_copy(update={"scene_type": "fast_human", "subject": "奔跑的人物"})
    monkeypatch.setattr(FakeVision, "analyze", lambda *args: model_scene)
    result = make_pipeline(settings, ManagedKnowledgeRetriever(store), localization()).run(
        image_content, user_request,
    )
    assert result.scene.subject == "奔跑的人物"
    assert hit_ids([*result.knowledge_hits, *result.composition_knowledge_hits]) == {"person_rule"}


def test_phone_composition_and_parameter_search_share_normalized_device_conditions(
    settings, image_content,
):
    from camera_assistant.models import PhoneProfile

    store = KnowledgeStore(settings.knowledge_db_path)
    for library in ("composition", "technique"):
        publish(store, knowledge_record("phone_" + library, library, conditions={
            "device_type": "phone", "phone_profile_id": "apple_iphone_15",
            "phone_capture_mode": "auto", "phone_lens_id": "main",
            "phone_pro_controls_confirmed": False,
        }))
        publish(store, knowledge_record("camera_" + library, library,
                                        conditions={"device_type": "camera"}))
        publish(store, knowledge_record("unavailable_pro_" + library, library,
                                        conditions={"phone_pro_controls_confirmed": True}))
    composition = FakeCompositionAdvisor()
    result = make_pipeline(
        settings, ManagedKnowledgeRetriever(store), localization(), composition=composition,
    ).run(image_content, UserRequest(
        intent="拍摄快速人物并突出主体留白", device_type="phone",
        phone_profile_id="apple_iphone_15", phone_capture_mode="pro",
        phone_lens_id="unavailable_lens", phone_pro_controls_confirmed=True,
    ))
    assert isinstance(result.camera_profile, PhoneProfile)
    assert hit_ids(result.knowledge_hits) == {"phone_technique"}
    assert hit_ids(result.composition_knowledge_hits) == {"phone_composition"}
    assert composition.calls[0][1].phone_capture_mode == "auto"
    assert composition.calls[0][1].phone_lens_id == "main"
    assert isinstance(composition.calls[0][5], PhoneProfile)
    assert result.recommendation.iso.startswith("自动")


def test_phone_legacy_mode_does_not_consume_camera_composition_cards(
    settings, image_content,
):
    composition = FakeCompositionAdvisor()
    result = make_pipeline(
        replace(settings, knowledge_mode="legacy"), None, localization(),
        composition=composition,
    ).run(image_content, UserRequest(
        intent="手机拍摄人物突出主体", device_type="phone", phone_profile_id="apple_iphone_15",
    ))
    assert result.knowledge_hits == []
    assert result.composition_knowledge_hits == []
    assert composition.calls[0][4] == []


@pytest.mark.parametrize("library", ["composition", "technique"])
def test_pipeline_rejects_evaluation_and_restricted_records_even_if_store_exposes_them(
    settings, image_content, user_request, monkeypatch, library,
):
    store = KnowledgeStore(settings.knowledge_db_path)
    publish(store, knowledge_record("allowed", library))
    published = store.list_revisions(status="published")
    leaked = [
        published[0].model_copy(update={
            "record": knowledge_record("evaluation_leak", library, dataset_split="evaluation"),
        }),
        published[0].model_copy(update={
            "record": knowledge_record(
                "restricted_leak", library,
                source=SourceInfo(name="受限测试来源", retrieval_allowed=False),
            ),
        }),
    ]
    monkeypatch.setattr(store, "list_revisions", lambda **kwargs: [*published, *leaked])
    result = make_pipeline(settings, ManagedKnowledgeRetriever(store), localization()).run(
        image_content, user_request
    )
    assert hit_ids([*result.knowledge_hits, *result.composition_knowledge_hits]) == {"allowed"}


@pytest.mark.parametrize(
    "status", ["selected", "ambiguous", "abstained", "unsupported", "detection_only", None],
)
def test_subject_confirmed_knowledge_requires_selected_localization(
    settings, image_content, user_request, status,
):
    store = KnowledgeStore(settings.knowledge_db_path)
    for library in ("technique", "composition"):
        publish(store, knowledge_record(f"general_{library}", library))
        publish(store, knowledge_record(
            f"confirmed_{library}", library,
            conditions={"motion": "fast", "subject_confirmed": True},
        ))
    loc = localization(status) if status is not None else None
    result = make_pipeline(settings, ManagedKnowledgeRetriever(store), loc).run(
        image_content, user_request
    )
    expected = {"general_technique", "general_composition"}
    if status == "selected":
        expected.update({"confirmed_technique", "confirmed_composition"})
    assert hit_ids([*result.knowledge_hits, *result.composition_knowledge_hits]) == expected
    assert result.scene.subject_status == "selected"
    assert result.localization == loc


@pytest.mark.parametrize("error_type", [ValueError, KeyError, TypeError])
def test_composition_failure_preserves_parameter_recommendation(
    settings, image_content, user_request, error_type,
):
    parameter = FakeParameterAdvisor()
    composition = FakeCompositionAdvisor(error_type("synthetic composition failure"))
    result = make_pipeline(
        settings, ManagedKnowledgeRetriever(KnowledgeStore(settings.knowledge_db_path)),
        localization(), parameter, composition,
    ).run(image_content, user_request)
    assert len(parameter.calls) == 1
    assert len(composition.calls) == 1
    assert result.composition.status == "unavailable"
    assert result.composition.proposals == []
    assert result.recommendation.reasons == ["测试参数建议"]
    assert result.recommendation.shutter_speed == "1/800s"


@pytest.mark.parametrize("error_type", [ValueError, KeyError, TypeError])
def test_parameter_failure_preserves_composition_and_marks_all_settings_unavailable(
    settings, image_content, user_request, error_type,
):
    composition = FakeCompositionAdvisor()
    result = make_pipeline(
        settings, ManagedKnowledgeRetriever(KnowledgeStore(settings.knowledge_db_path)),
        localization(), FakeParameterAdvisor(error_type("synthetic parameter failure")), composition,
    ).run(image_content, user_request)
    assert result.composition == composition.result
    assert result.composition.proposals
    assert result.recommendation.confidence == 0
    assert result.recommendation.reasons == []
    assert "未返回可校验" in result.recommendation.risks[0]
    assert {
        getattr(result.recommendation, name)
        for name in (
            "shooting_mode", "aperture", "shutter_speed", "iso", "exposure_compensation",
            "focus_mode", "metering_mode", "drive_mode", "white_balance",
        )
    } == {"未生成"}


def test_real_mode_without_key_rejects_configuration_before_demo_construction(settings, monkeypatch):
    def forbidden_demo():
        pytest.fail("真实模式缺密钥不能回落到演示识别")

    monkeypatch.setattr(pipeline_module, "DemoVisionAnalyzer", forbidden_demo)
    with pytest.raises(ValueError, match="真实模式配置不完整"):
        CameraAssistantPipeline(replace(settings, api_key=""))


@pytest.mark.parametrize("injected_localizer", [False, True])
def test_demo_mode_never_constructs_or_calls_enabled_detector(
    settings, image_content, user_request, monkeypatch, injected_localizer,
):
    def forbidden_detector(*args, **kwargs):
        pytest.fail("演示模式不能创建或运行检测器")

    monkeypatch.setattr(pipeline_module, "GroundingDinoLocalizer", forbidden_detector)
    localizer = FakeLocalizer(localization()) if injected_localizer else None
    if localizer:
        monkeypatch.setattr(localizer, "localize", forbidden_detector)
    pipeline = CameraAssistantPipeline(
        replace(settings, demo_mode=True, api_key="", vision_model="", text_model=""),
        localizer=localizer,
    )
    result = pipeline.run(image_content, user_request)
    assert result.localization is None
    assert result.composition.status == "demo"
    assert result.recommendation.shutter_speed == "1/800s"
