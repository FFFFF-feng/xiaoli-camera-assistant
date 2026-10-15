"""扩展资料的结构、来源追溯与隔离导入测试；不证明摄影效果或事实正确性。"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest
import streamlit as st
import yaml
from streamlit.testing.v1 import AppTest

from camera_assistant.knowledge.importer import parse_record_file
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeError, KnowledgeStore
from camera_assistant.knowledge.uploads import (
    MAX_BATCH_BYTES,
    MAX_BATCH_FILES,
    MAX_UPLOAD_BYTES,
    UploadedRecordFile,
    commit_preview,
    preview_uploads,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/knowledge_drafts/expanded-v1"
REGISTRY = json.loads(
    (ROOT / "knowledge_sources/expanded-v1/sources.json").read_text(encoding="utf-8")
)
MANIFEST = json.loads(
    (ROOT / "knowledge_sources/expanded-v1/manifest.json").read_text(encoding="utf-8")
)
SOURCES = {item["source_id"]: item for item in REGISTRY["sources"]}
PATHS = sorted(DATA.glob("batch-*/*.json"))
ENTRIES = {entry["path"]: entry for entry in MANIFEST["records"]}
STATUSES = {
    "cross_source_agreement", "primary_source_only",
    "synthesized_guideline", "interpretive_goal",
}
CONTEXT_FIELDS = {
    "scene", "subject", "motion", "camera_profile_id", "camera_format", "device_type",
    "phone_profile_id", "phone_capture_mode", "phone_lens_id",
    "phone_pro_controls_confirmed", "handheld", "tripod",
}


def uploaded(path: Path) -> UploadedRecordFile:
    return UploadedRecordFile(path.name, path.read_bytes())


@pytest.mark.parametrize("path", PATHS, ids=lambda path: path.stem)
def test_card_contract_and_evidence_boundaries(path: Path) -> None:
    record = parse_record_file(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    entry = ENTRIES[path.relative_to(ROOT).as_posix()]
    assert record.knowledge_id == entry["knowledge_id"]
    assert record.library_id == entry["library_id"]
    assert record.title == entry["title"]
    assert record.version == entry["version"] == 1
    assert record.schema_version == 1
    assert record.dataset_split == "reference"
    assert record.kind != "observed_case"
    assert "status" not in raw and "reviewer" not in raw
    assert record.source.retrieval_allowed is False
    assert record.payload["numeric_default"] is None
    assert record.payload["automatic_execution"] is False
    assert record.payload["core_claim"] in record.content
    for field in ("requires", "actions", "limitations"):
        values = record.payload[field]
        assert values and all(isinstance(value, str) and value.strip() for value in values)
    assert set(record.conditions) <= CONTEXT_FIELDS

    check = record.payload["verification"]
    assert check["status"] in STATUSES
    assert check["status"] == entry["verification_status"]
    assert check["needs_human_review"] is True
    assert check["human_review_status"] == "not_performed"
    assert check["field_test_status"] == "not_performed"
    evidence = check["evidence"]
    assert evidence and entry["source_ids"] == [item["source_id"] for item in evidence]
    for item in evidence:
        source = SOURCES[item["source_id"]]
        assert item["url"] == source["url"]
        assert item["location"] == source["location"]
        assert item["supports"].strip()
        assert source["read_status"] == "body_read"
        assert source["original_text_saved"] is False
        assert source["images_saved"] is False
    assert record.source.url == evidence[0]["url"]
    if check["status"] == "cross_source_agreement":
        groups = {SOURCES[item["source_id"]]["publisher_group"] for item in evidence}
        assert len(groups) >= 2  # 同厂商不同域名不能算独立的交叉核对。
    if check["status"] in {"synthesized_guideline", "interpretive_goal"}:
        assert check["inference_note"].strip()
    if record.kind == "manufacturer_fact":
        assert check["status"] == "primary_source_only"
        assert record.conditions["device_type"] == "phone"
        assert record.conditions["phone_profile_id"] != "generic_phone"


def test_inventory_registry_and_manifest_are_consistent() -> None:
    records = [parse_record_file(path) for path in PATHS]
    assert len(PATHS) == len(ENTRIES) == MANIFEST["record_count"] == 80
    assert len({record.knowledge_id for record in records}) == 80
    libraries = Counter(record.library_id for record in records)
    assert dict(libraries) == {
        "composition": 20, "technique": 32, "scene": 10, "style": 6, "equipment": 12,
    }
    assert {**dict(libraries), "case": 0} == MANIFEST["by_library"]
    statuses = Counter(record.payload["verification"]["status"] for record in records)
    assert dict(statuses) == MANIFEST["by_verification_status"]
    assert len(SOURCES) == len(REGISTRY["sources"]) == REGISTRY["source_count"] == 41
    assert len({source["publisher_group"] for source in SOURCES.values()}) == 7
    used = {
        item["source_id"] for record in records
        for item in record.payload["verification"]["evidence"]
    }
    assert used == set(SOURCES)
    assert all(not source["retrieval_allowed"] for source in SOURCES.values())
    assert MANIFEST["human_review_performed"] is False
    assert MANIFEST["field_test_performed"] is False


@pytest.mark.parametrize("batch", MANIFEST["batches"])
def test_batch_fits_real_upload_limits(batch: dict) -> None:
    paths = sorted((ROOT / batch["directory"]).glob("*.json"))
    assert len(paths) == batch["record_count"] == MAX_BATCH_FILES
    assert all(path.stat().st_size <= MAX_UPLOAD_BYTES for path in paths)
    assert sum(path.stat().st_size for path in paths) <= MAX_BATCH_BYTES
    preview = preview_uploads([uploaded(path) for path in paths])
    assert preview.success and len(preview.records) == 20 and not preview.issues


def test_phone_model_and_pro_controls_do_not_leak() -> None:
    profiles = yaml.safe_load(
        (ROOT / "knowledge/devices/phone_profiles.yaml").read_text(encoding="utf-8")
    )["profiles"]
    profiles_by_id = {profile["profile_id"]: profile for profile in profiles}
    for path in PATHS:
        record = parse_record_file(path)
        conditions = record.conditions
        if "phone_profile_id" not in conditions:
            continue
        assert conditions["device_type"] == "phone"
        profile = profiles_by_id[conditions["phone_profile_id"]]
        facts = record.payload.get("manufacturer_facts", {})
        assert facts.get("iso_range") is None
        assert facts.get("shutter_range_seconds") is None
        if conditions.get("phone_capture_mode") == "pro":
            assert "pro" in profile["modes"]
            assert conditions["phone_pro_controls_confirmed"] is True
            assert not ManagedKnowledgeRetriever._applicable(
                conditions, {**conditions, "phone_pro_controls_confirmed": False}
            )
        assert not ManagedKnowledgeRetriever._applicable(
            conditions, {**conditions, "device_type": "camera"}
        )


def test_known_phone_facts_keep_their_qualifications() -> None:
    by_id = {record.knowledge_id: record for record in map(parse_record_file, PATHS)}
    iphone = by_id["expanded-v1-equipment-iphone15-2x"].payload["manufacturer_facts"]
    assert iphone["two_x"]["independent_physical_lens"] is False
    raw = by_id["expanded-v1-equipment-iphone15-no-proraw"].payload["manufacturer_facts"]
    assert raw["native_apple_proraw_supported"] is False
    assert raw["third_party_raw_supported"] is None
    samsung = by_id["expanded-v1-equipment-s24ultra-zoom-quality"].payload["manufacturer_facts"]
    assert samsung["advertised_optical_zoom_levels"] == [3, 5]
    assert samsung["advertised_optical_quality_levels"] == [2, 10]
    xiaomi = by_id["expanded-v1-equipment-xiaomi14-tele-footnotes"].payload["manufacturer_facts"]
    assert xiaomi["distance_reference_plane"] is None
    assert xiaomi["telephoto_photo_output_megapixels"] == 32


def test_four_batches_import_only_into_isolated_drafts_and_repeat_safely(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "isolated-expansion.db")
    for batch in MANIFEST["batches"]:
        files = [uploaded(path) for path in sorted((ROOT / batch["directory"]).glob("*.json"))]
        preview = preview_uploads(files)
        report = commit_preview(store, preview)
        assert report.success and report.imported_count == 20
        repeated = commit_preview(store, preview)
        assert repeated.success and repeated.imported_count == 0
        assert repeated.unchanged_count == 20
    revisions = store.list_revisions()
    assert len(revisions) == len(store.audit_log()) == 80
    assert all(revision.status == "draft" for revision in revisions)
    assert ManagedKnowledgeRetriever(store).search("人像 手机 风景") == []
    # 在临时库模拟审核，仍不得绕过未确认的检索许可；不操作真实审核状态。
    knowledge_id = revisions[0].record.knowledge_id
    store.submit(knowledge_id)
    store.approve(knowledge_id, reviewer="isolated-test-only", note="仅验证许可阻断")
    with pytest.raises(KnowledgeError):
        store.publish(knowledge_id)
    assert ManagedKnowledgeRetriever(store).search("人像 手机 风景") == []


@dataclass
class FakeUploadedFile:
    name: str
    data: bytes

    def getvalue(self) -> bytes:
        return self.data


def test_twenty_real_cards_in_workbench_preview_and_confirm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "isolated-expansion-ui.db"
    monkeypatch.setenv("KNOWLEDGE_DB_PATH", str(database))
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("CAMERA_AI_API_KEY", "")
    monkeypatch.setenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy")
    paths = sorted((DATA / "batch-01").glob("*.json"))
    files = [FakeUploadedFile(path.name, path.read_bytes()) for path in paths]
    monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: files)
    app = AppTest.from_file(ROOT / "knowledge_app.py", default_timeout=20).run()
    store = KnowledgeStore(database)
    assert not app.exception and store.list_revisions() == []
    app.button(key="kb_validate").click().run()
    assert not app.exception and len(app.session_state["kb_preview"].records) == 20
    assert app.button(key="kb_commit").disabled
    assert store.list_revisions() == []
    app.checkbox(key="kb_confirm").check().run()
    app.button(key="kb_commit").click().run()
    assert not app.exception
    assert any("新增 20 个草稿版本" in item.value for item in app.success)
    assert len(store.list_revisions()) == 20
    assert all(revision.status == "draft" for revision in store.list_revisions())
