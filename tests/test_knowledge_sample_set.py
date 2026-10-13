"""对用户实际拿到的上传样本做隔离测试，不操作项目真实数据库。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.knowledge.uploads import UploadedRecordFile, commit_preview, preview_uploads

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data/knowledge_samples/upload-smoke-v1"
VALID = sorted((SAMPLES / "01_valid").iterdir())
INVALID_EXPECTED = [
    ("01_missing_author.json", "字段校验失败"),
    ("02_unknown_library.yaml", "字段校验失败"),
    ("03_no_front_matter.md", "Markdown 必须以 YAML 前置元数据"),
    ("04_broken_json.json", "JSON 格式错误"),
]


def sample_file(path: Path) -> UploadedRecordFile:
    return UploadedRecordFile(path.name, path.read_bytes())


def normal_files() -> list[UploadedRecordFile]:
    return [sample_file(path) for path in VALID]


@pytest.mark.parametrize("path", VALID, ids=lambda path: path.name)
def test_each_valid_sample_previews_without_database_write(tmp_path: Path, path: Path) -> None:
    store = KnowledgeStore(tmp_path / "test.db")
    preview = preview_uploads([sample_file(path)])

    assert preview.success and preview.total_files == 1
    record = preview.records[0]
    assert record.knowledge_id.startswith("upload-smoke-v1-")
    assert record.title.startswith("[上传测试]")
    assert record.payload["test_only"] is True
    assert record.dataset_split == "evaluation"
    assert record.source.retrieval_allowed is False
    assert store.list_revisions() == []
    assert store.audit_log() == []


def test_actual_six_library_samples_import_and_repeat_idempotently(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "test.db")
    preview = preview_uploads(normal_files())
    assert len(VALID) == 6
    assert preview.success and len(preview.records) == 6
    assert {record.library_id for record in preview.records} == {
        "scene", "composition", "style", "technique", "equipment", "case"
    }

    report = commit_preview(store, preview)

    assert report.success and report.imported_count == 6
    assert all(revision.status == "draft" for revision in report.revisions)
    assert len(store.audit_log()) == 6
    repeated = commit_preview(store, preview)
    assert repeated.success and repeated.imported_count == 0 and repeated.unchanged_count == 6
    assert len(store.list_revisions()) == 6
    assert len(store.audit_log()) == 6
    equipment = next(record for record in preview.records if record.library_id == "equipment")
    assert equipment.conditions["device_type"] == "phone"


@pytest.mark.parametrize(("filename", "message"), INVALID_EXPECTED)
def test_invalid_samples_and_mixed_batches_do_not_write(
    tmp_path: Path, filename: str, message: str
) -> None:
    store = KnowledgeStore(tmp_path / "test.db")
    bad = sample_file(SAMPLES / "02_invalid" / filename)
    invalid = preview_uploads([bad])
    assert not invalid.success and invalid.records == []
    assert any(message in issue.message for issue in invalid.issues)

    mixed = preview_uploads([normal_files()[0], bad])
    assert not mixed.success and len(mixed.records) == 1
    assert not commit_preview(store, mixed).success
    assert store.list_revisions() == []
    assert store.audit_log() == []


def test_duplicate_sample_rejects_same_batch_and_existing_content_conflict(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "test.db")
    original = sample_file(SAMPLES / "01_valid/02_composition.yaml")
    conflict = sample_file(SAMPLES / "03_duplicate/01_composition_conflict.yaml")

    duplicate_batch = preview_uploads([original, conflict])
    assert not duplicate_batch.success
    assert any("重复 knowledge_id" in issue.message for issue in duplicate_batch.issues)
    assert not commit_preview(store, duplicate_batch).success
    assert store.list_revisions() == []

    assert commit_preview(store, preview_uploads([original])).success
    conflicting_preview = preview_uploads([conflict])
    assert conflicting_preview.success
    conflict_report = commit_preview(store, conflicting_preview)
    assert not conflict_report.success and conflict_report.imported_count == 0
    saved = store.list_revisions()
    assert len(saved) == 1 and saved[0].record.title == "[上传测试] 主体位置与画面边缘"
    assert len(store.audit_log()) == 1


def test_version_update_adds_v2_without_overwriting_v1(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "test.db")
    assert commit_preview(store, preview_uploads(normal_files())).imported_count == 6
    update = sample_file(SAMPLES / "04_update/01_composition_v2.yaml")
    report = commit_preview(store, preview_uploads([update]))

    assert report.success and report.imported_count == 1
    revisions = store.list_revisions()
    assert len(revisions) == 7
    assert len({revision.record.knowledge_id for revision in revisions}) == 6
    versions = sorted(
        revision.record.version for revision in revisions
        if revision.record.knowledge_id == "upload-smoke-v1-composition-001"
    )
    assert versions == [1, 2]
    assert all(revision.status == "draft" for revision in revisions)
    assert all(not revision.record.source.retrieval_allowed for revision in revisions)
    assert all(revision.record.dataset_split == "evaluation" for revision in revisions)
    assert len(store.audit_log()) == 7


@dataclass
class FakeUploadedFile:
    name: str
    data: bytes

    def getvalue(self) -> bytes:
        return self.data


def test_actual_samples_in_workbench_preview_confirm_and_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "isolated-workbench.db"
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(database))
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("CAMERA_AI_API_KEY", "")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy")
    uploaded = [FakeUploadedFile(path.name, path.read_bytes()) for path in VALID]
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: uploaded)
    app = AppTest.from_file(ROOT / "knowledge_app.py", default_timeout=15).run()
    store = KnowledgeStore(database)

    assert not app.exception
    assert "kb_preview" not in app.session_state
    assert store.list_revisions() == []
    app.button(key="kb_validate").click().run()
    assert not app.exception
    assert app.session_state["kb_preview"].success
    assert len(app.session_state["kb_preview"].records) == 6
    assert app.button(key="kb_commit").disabled
    assert store.list_revisions() == []
    assert any("6 条记录" in item.value for item in app.success)

    app.checkbox(key="kb_confirm").check().run()
    app.button(key="kb_commit").click().run()
    assert not app.exception
    assert any("新增 6 个草稿版本" in item.value for item in app.success)
    assert len(store.list_revisions()) == 6
    assert {revision.record.library_id for revision in store.list_revisions()} == {
        "scene", "composition", "style", "technique", "equipment", "case"
    }
    assert all(revision.status == "draft" for revision in store.list_revisions())
    assert len(store.audit_log()) == 6
