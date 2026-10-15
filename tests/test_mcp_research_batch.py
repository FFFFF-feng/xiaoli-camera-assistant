"""2026-10-13 MCP采集批次的契约与隔离测试，不证明来源结论或摄影效果。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
import streamlit as st
import yaml
from streamlit.testing.v1 import AppTest

from camera_assistant.knowledge.importer import import_path, parse_record_file
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeError, KnowledgeStore
from camera_assistant.knowledge.uploads import UploadedRecordFile, commit_preview, preview_uploads

ROOT = Path(__file__).resolve().parents[1]
BATCH_ID = "web-research-codex-20261013"
DATA = ROOT / "data/knowledge_drafts" / BATCH_ID
PATHS = sorted(DATA.glob("*.json"))
REGISTRY = json.loads(
    (ROOT / "knowledge_sources" / BATCH_ID / "sources.json").read_text(encoding="utf-8")
)
MANIFEST = json.loads(
    (ROOT / "knowledge_sources" / BATCH_ID / "manifest.json").read_text(encoding="utf-8")
)
SOURCES = {item["source_id"]: item for item in REGISTRY["sources"]}


def uploads() -> list[UploadedRecordFile]:
    return [UploadedRecordFile(path.name, path.read_bytes()) for path in PATHS]


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path.stem)
def test_card_and_registered_evidence(path: Path) -> None:
    record = parse_record_file(path)
    assert record.source.retrieval_allowed is False
    assert record.dataset_split == "reference"
    assert record.payload["batch_id"] == BATCH_ID
    assert record.payload["core_claim"] in record.content
    assert record.payload["numeric_default"] is None
    assert record.payload["automatic_execution"] is False
    for key in ("requires", "actions", "limitations"):
        assert record.payload[key]
    check = record.payload["verification"]
    assert check["checked_at"] == "2026-10-13"
    assert check["human_review_status"] == check["field_test_status"] == "not_performed"
    assert check["needs_human_review"] is True
    assert check["scope"] and check["inference_note"]
    assert check["status"] in {
        "cross_source_agreement", "primary_source_only", "synthesized_guideline"
    }
    publishers = set()
    assert record.source.url == check["evidence"][0]["url"]
    for evidence in check["evidence"]:
        source = SOURCES[evidence["source_id"]]
        assert source["url"] == evidence["url"]
        assert source["read_status"] == evidence["read_status"] == "body_read"
        assert evidence["location"] and evidence["supports"]
        assert source["rights_status"] == "pending"
        assert not any(source[key] for key in (
            "original_text_saved", "images_saved", "video_saved", "retrieval_allowed"
        ))
        publishers.add(source["publisher_group"])
    if check["status"] == "cross_source_agreement":
        assert len(publishers) >= 2
    if record.kind == "manufacturer_fact":
        assert publishers == {"Apple"}
        assert record.library_id == "equipment"
        assert check["status"] == "primary_source_only"
        assert record.conditions["phone_profile_id"] == "apple_iphone_15"


def test_inventory_dedup_and_source_counts() -> None:
    assert len(PATHS) == MANIFEST["record_count"] == 10
    assert REGISTRY["candidate_count"] == len(SOURCES) + len(REGISTRY["excluded"]) == 16
    assert REGISTRY["body_read_count"] == len(SOURCES) == 14
    assert REGISTRY["excluded_count"] == 2
    used = set()
    assert len({item["knowledge_id"] for item in MANIFEST["records"]}) == 10
    existing = {}
    for path in (ROOT / "data/knowledge_drafts").rglob("*"):
        if DATA in path.parents or not path.is_file() or path.suffix not in {".md", ".json"}:
            continue
        # Other batches also contain reports, registries and manifests.
        # Only knowledge cards participate in the cross-batch ID comparison.
        if path.suffix == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or "knowledge_id" not in raw:
                continue
        elif not path.read_text(encoding="utf-8").startswith("---"):
            continue
        record = parse_record_file(path)
        existing[record.knowledge_id] = max(existing.get(record.knowledge_id, 0), record.version)
    for entry in MANIFEST["records"]:
        path = ROOT / entry["path"]
        record = parse_record_file(path)
        assert record.knowledge_id == entry["knowledge_id"]
        assert record.title == entry["title"] and record.version == entry["version"]
        assert record.library_id == entry["library_id"] and record.kind == entry["kind"]
        assert entry["verification_status"] == record.payload["verification"]["status"]
        ids = [item["source_id"] for item in record.payload["verification"]["evidence"]]
        assert entry["source_ids"] == ids
        used.update(ids)
        if entry["dedup_action"] == "same_id_new_revision":
            assert record.version == existing[record.knowledge_id] + 1 == 2
        else:
            assert entry["dedup_action"] == "new_topic" and record.version == 1
            assert record.knowledge_id not in existing
    assert used == set(SOURCES)
    assert sum(entry["version"] == 2 for entry in MANIFEST["records"]) == 5


def test_batch_dry_run() -> None:
    report = import_path(None, DATA, dry_run=True)
    assert report.success and report.validated_count == 10
    assert report.total_files == 10 and report.imported_count == 0
    assert report.revisions == []


def test_upload_versions_roundtrip_and_repeated_import(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "isolated-versions.db")
    records = [parse_record_file(path) for path in PATHS]
    ids = {record.knowledge_id for record in records if record.version == 2}
    previous = [
        parse_record_file(path)
        for path in (ROOT / "data/knowledge_drafts/expanded-v1/batch-01").glob("*.json")
        if parse_record_file(path).knowledge_id in ids
    ]
    before = store.save_many_drafts(previous)
    assert len(before) == 5
    preview = preview_uploads(uploads())
    assert preview.success and len(store.list_revisions()) == 5
    report = commit_preview(store, preview)
    assert report.success and report.imported_count == 10
    assert all(item.status == "draft" for item in report.revisions)
    assert len(store.list_revisions()) == len(store.audit_log()) == 15
    for revision in before:
        assert store.get_revision(revision.record.knowledge_id, version=1) == revision
    for record in records:
        assert store.get_revision(record.knowledge_id, version=record.version).record == record
    repeated = commit_preview(store, preview)
    assert repeated.success and repeated.imported_count == 0 and repeated.unchanged_count == 10
    assert len(store.list_revisions()) == len(store.audit_log()) == 15
    retriever = ManagedKnowledgeRetriever(store)
    context = {"device_type": "phone", "phone_profile_id": "apple_iphone_15"}
    for mode in ("auto", "portrait"):
        assert retriever.search("构图 人像 连拍 实况", conditions={
            **context, "phone_capture_mode": mode
        }) == []
    assert retriever.query_structured("composition") == []


def test_same_version_conflict_preserves_entire_batch(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "isolated-conflict.db")
    assert commit_preview(store, preview_uploads(uploads())).imported_count == 10
    before = store.list_revisions()
    audit_before = store.audit_log()
    files = uploads()
    raw = json.loads(files[-1].data)
    raw["title"] += "（仅测试冲突）"
    files[-1] = UploadedRecordFile(files[-1].filename, json.dumps(raw).encode("utf-8"))
    preview = preview_uploads(files)
    assert preview.success
    report = commit_preview(store, preview)
    assert not report.success and report.imported_count == 0
    assert store.list_revisions() == before and store.audit_log() == audit_before


def test_phone_conditions_use_registered_model_and_modes() -> None:
    profiles = yaml.safe_load((ROOT / "knowledge/devices/phone_profiles.yaml").read_text(
        encoding="utf-8"
    ))["profiles"]
    iphone = next(item for item in profiles if item["profile_id"] == "apple_iphone_15")
    for path in PATHS:
        record = parse_record_file(path)
        if record.library_id != "equipment":
            continue
        assert set(record.conditions) == {"device_type", "phone_profile_id", "phone_capture_mode"}
        assert record.conditions["phone_capture_mode"] in iphone["modes"]
        observed = dict(record.conditions)
        assert ManagedKnowledgeRetriever._applicable(record.conditions, observed)
        assert not ManagedKnowledgeRetriever._applicable(record.conditions, None)
        assert not ManagedKnowledgeRetriever._applicable(record.conditions, {
            **observed, "phone_profile_id": "generic_phone"
        })


def test_permission_blocks_publication_in_isolated_database(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "isolated-permission.db")
    report = commit_preview(store, preview_uploads(uploads()))
    assert report.success
    for revision in report.revisions:
        knowledge_id = revision.record.knowledge_id
        # 仅模拟临时库审核，验证许可边界，不给真实卡片记录人工审核结果。
        store.submit(knowledge_id)
        store.approve(knowledge_id, reviewer="isolated-test-only", note="仅测试许可阻断")
        with pytest.raises(KnowledgeError, match="检索使用权限"):
            store.publish(knowledge_id)
    assert ManagedKnowledgeRetriever(store).search("构图 手机") == []


@dataclass
class FakeUploadedFile:
    name: str
    data: bytes

    def getvalue(self) -> bytes:
        return self.data


def test_ten_files_preview_and_confirm_in_isolated_workbench(
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
    assert not app.exception and len(app.session_state["kb_preview"].records) == 10
    assert app.button(key="kb_commit").disabled and store.list_revisions() == []
    app.checkbox(key="kb_confirm").check().run()
    app.button(key="kb_commit").click().run()
    assert not app.exception
    assert any("新增 10 个草稿版本" in item.value for item in app.success)
    assert len(store.list_revisions()) == len(store.audit_log()) == 10
    assert all(item.status == "draft" for item in store.list_revisions())
