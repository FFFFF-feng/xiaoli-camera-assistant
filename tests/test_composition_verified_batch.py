"""核验构图卡的上传、版本升级和隔离测试，不证明摄影效果或使用许可。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from camera_assistant.knowledge.importer import import_path, parse_record_file
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeError, KnowledgeStore
from camera_assistant.knowledge.uploads import UploadedRecordFile, commit_preview, preview_uploads

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "data/knowledge_drafts/composition-verified-v2"
PATHS = sorted(BATCH.glob("*.md"))
ORIGINALS = ROOT / "data/knowledge_drafts/expanded-v1/batch-01"


def uploaded_files() -> list[UploadedRecordFile]:
    return [UploadedRecordFile(path.name, path.read_bytes()) for path in PATHS]


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path.stem)
def test_card_contract_and_verification_scope(path: Path) -> None:
    record = parse_record_file(path)
    assert record.library_id == "composition"
    assert record.kind == "guideline"
    assert record.version == 2
    assert record.dataset_split == "reference"
    assert record.source.retrieval_allowed is False
    assert record.payload["previous_version"] == 1
    assert record.payload["core_claim"] in record.content
    assert record.payload["numeric_default"] is None
    assert record.payload["automatic_execution"] is False
    for key in ("requires", "actions", "limitations"):
        assert record.payload[key]
    check = record.payload["verification"]
    assert check["checked_at"] == "2026-10-13"
    assert check["needs_human_review"] is True
    assert check["human_review_status"] == check["field_test_status"] == "not_performed"
    evidence = check["evidence"]
    assert evidence and evidence[0]["url"] == record.source.url
    assert all(item["read_status"] == "body_read" and item["supports"] for item in evidence)
    if check["status"] == "cross_source_agreement":
        publishers = {urlsplit(item["url"]).hostname for item in evidence}
        assert len(publishers) >= 2
    else:
        assert check["status"] == "primary_source_only"


def test_inventory_reuses_existing_identities() -> None:
    assert len(PATHS) == 5
    records = [parse_record_file(path) for path in PATHS]
    previous = {parse_record_file(path).knowledge_id for path in ORIGINALS.glob("*.json")}
    assert len({record.knowledge_id for record in records}) == 5
    assert all(record.knowledge_id in previous for record in records)


def test_dry_run_does_not_create_database(tmp_path: Path) -> None:
    report = import_path(None, BATCH, dry_run=True)
    assert report.success and report.validated_count == 5
    assert report.imported_count == 0 and report.revisions == []
    assert list(tmp_path.iterdir()) == []


def test_upload_import_roundtrip_and_repeat_are_safe(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "isolated.db")
    preview = preview_uploads(uploaded_files())
    assert preview.success and preview.total_files == 5
    assert store.list_revisions() == []
    report = commit_preview(store, preview)
    assert report.success and report.imported_count == 5
    assert all(item.status == "draft" for item in report.revisions)
    for record in preview.records:
        saved = store.get_revision(record.knowledge_id, version=2)
        assert saved is not None and saved.record == record
    repeated = commit_preview(store, preview)
    assert repeated.success and repeated.imported_count == 0 and repeated.unchanged_count == 5
    assert len(store.list_revisions()) == len(store.audit_log()) == 5
    retriever = ManagedKnowledgeRetriever(store)
    assert retriever.search("背景 前景 三分法 取景 视线", libraries=["composition"]) == []
    assert retriever.query_structured("composition") == []


def test_version_two_preserves_originals(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "isolated-versions.db")
    incoming_ids = {parse_record_file(path).knowledge_id for path in PATHS}
    originals = [
        parse_record_file(path) for path in ORIGINALS.glob("*.json")
        if parse_record_file(path).knowledge_id in incoming_ids
    ]
    before = store.save_many_drafts(originals)
    assert len(before) == 5
    assert import_path(store, BATCH).imported_count == 5
    assert len(store.list_revisions()) == 10
    for revision in before:
        saved = store.get_revision(revision.record.knowledge_id, version=1)
        assert saved == revision
        assert store.get_revision(revision.record.knowledge_id).record.version == 2


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path.stem)
def test_unconfirmed_permission_cannot_publish(tmp_path: Path, path: Path) -> None:
    store = KnowledgeStore(tmp_path / "isolated-review.db")
    record = parse_record_file(path)
    store.save_draft(record)
    store.submit(record.knowledge_id)
    store.approve(record.knowledge_id, reviewer="isolated-test-only", note="只测试发布边界")
    with pytest.raises(KnowledgeError, match="检索使用权限"):
        store.publish(record.knowledge_id)
    assert ManagedKnowledgeRetriever(store).search(record.title) == []


@dataclass
class FakeUploadedFile:
    name: str
    data: bytes

    def getvalue(self) -> bytes:
        return self.data


def test_real_batch_in_workbench_requires_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "isolated-ui.db"
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(database))
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("CAMERA_AI_API_KEY", "")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy")
    files = [FakeUploadedFile(path.name, path.read_bytes()) for path in PATHS]
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: files)
    app = AppTest.from_file(ROOT / "knowledge_app.py", default_timeout=20).run()
    store = KnowledgeStore(database)
    assert not app.exception and store.list_revisions() == []
    app.button(key="kb_validate").click().run()
    assert not app.exception and len(app.session_state["kb_preview"].records) == 5
    assert app.button(key="kb_commit").disabled and store.list_revisions() == []
    app.checkbox(key="kb_confirm").check().run()
    app.button(key="kb_commit").click().run()
    assert not app.exception
    assert any("新增 5 个草稿版本" in item.value for item in app.success)
    assert len(store.list_revisions()) == 5
    assert all(item.status == "draft" for item in store.list_revisions())
