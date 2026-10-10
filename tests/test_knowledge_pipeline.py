from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from camera_assistant.config import Settings
from camera_assistant.knowledge.models import KnowledgeRecord, SourceInfo
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline


def settings_for(db_path: Path, mode: str = "managed") -> Settings:
    return Settings(
        demo_mode=True,
        api_key="",
        base_url="https://example.invalid/v1",
        vision_model="",
        text_model="",
        timeout_seconds=5,
        max_image_mb=15,
        knowledge_dir=Path(__file__).resolve().parents[1] / "knowledge",
        knowledge_mode=mode,
        knowledge_db_path=db_path,
    )


def scene_image() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (100, 80), (40, 40, 40)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_managed_pipeline_empty_library_does_not_use_legacy_content(tmp_path: Path) -> None:
    result = CameraAssistantPipeline(settings_for(tmp_path / "empty.db")).run(
        scene_image(), UserRequest(intent="夜晚拍小狗", subject_motion="快速")
    )
    assert result.knowledge_mode == "managed"
    assert result.knowledge_hits == []
    assert "没有受管知识依据" in result.knowledge_notes[0]
    assert result.recommendation


def test_pipeline_routes_parameter_query_and_keeps_publication_boundary(tmp_path: Path) -> None:
    db_path = tmp_path / "knowledge.db"
    store = KnowledgeStore(db_path)
    for knowledge_id, library, motion in (
        ("tech_fixture", "technique", "fast"),
        ("composition_fixture", "composition", "fast"),
        ("wrong_motion", "technique", "static"),
    ):
        record = KnowledgeRecord(
            knowledge_id=knowledge_id,
            library_id=library,
            title="自动化测试：夜晚拍小狗",
            kind="guideline",
            content="自动化测试文本：夜晚 快速 宠物 快门 ISO。不是正式摄影知识。",
            conditions={"motion": motion},
            source=SourceInfo(name="自动化测试", retrieval_allowed=True),
            author="fixture-author",
        )
        store.save_draft(record)
        store.submit(knowledge_id)
        store.approve(knowledge_id, reviewer="fixture-reviewer")
        store.publish(knowledge_id)
    store.save_draft(
        record.model_copy(update={"knowledge_id": "unreviewed_fixture", "conditions": {}})
    )
    result = CameraAssistantPipeline(settings_for(db_path)).run(
        scene_image(), UserRequest(intent="夜晚拍小狗", subject_motion="快速")
    )
    assert [hit.metadata["knowledge_id"] for hit in result.knowledge_hits] == ["tech_fixture"]
    assert result.knowledge_hits[0].metadata["review_status"] == "published"
    assert result.knowledge_hits[0].metadata["reviewer"] == "fixture-reviewer"


def test_legacy_default_keeps_existing_demo(tmp_path: Path) -> None:
    result = CameraAssistantPipeline(settings_for(tmp_path / "unused.db", "legacy")).run(
        scene_image(), UserRequest(intent="夜晚手持拍摄")
    )
    assert result.knowledge_mode == "legacy"
    assert result.knowledge_hits
    assert not (tmp_path / "unused.db").exists()


def test_invalid_knowledge_mode_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="legacy"):
        settings_for(tmp_path / "unused.db", "invalid")


def test_env_knowledge_db_relative_path_uses_project_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from camera_assistant.config import PROJECT_ROOT

    monkeypatch.setenv("KNOWLEDGE_DB_PATH", "data/test-configuration.db")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "managed")
    settings = Settings.from_env()
    assert settings.knowledge_db_path == (PROJECT_ROOT / "data/test-configuration.db").resolve()
    assert settings.knowledge_mode == "managed"
