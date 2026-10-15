"""开源设备卡的离线转换边界和实际上传契约回归。"""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

from camera_assistant.knowledge.importer import import_path, parse_record_file
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.knowledge.uploads import (
    UploadedRecordFile,
    commit_preview,
    preview_uploads,
)

ROOT = Path(__file__).resolve().parents[1]
BATCH = "opensource-equipment-20261014"
SPEC = importlib.util.spec_from_file_location(
    "prepare_open_equipment", ROOT / "scripts/prepare_open_equipment.py"
)
converter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(converter)


def test_sensor_parser_never_converts_optical_format_inches() -> None:
    assert converter.sensor_dimensions('1/2.3"') is None
    assert converter.sensor_dimensions('1/2.3" (~ 6.16 x 4.62 mm)') == (6.16, 4.62)
    assert converter.sensor_dimensions("22.3 × 14.9 mm") == (22.3, 14.9)
    assert converter.sensor_dimensions("unknown") is None


def test_complete_model_match_never_merges_adjacent_variants() -> None:
    widths = {converter.normalized("Canon EOS R50"): [["Canon EOS R50", 22.3]]}
    assert (
        converter.consistency_check("Canon EOS R50", "22.3 x 14.9 mm", widths)["status"]
        == "consistent"
    )
    assert (
        converter.consistency_check("Canon EOS R50 V", "22.3 x 14.9 mm", widths)["status"]
        == "not_comparable"
    )
    assert converter.normalized("X-S20") != converter.normalized("EX-S20")
    assert converter.full_model("Canon", "Canon EOS R50") == "Canon EOS R50"


@pytest.mark.parametrize("reference, expected", [(22.35, "consistent"), (5.33, "conflict")])
def test_cross_source_consistency_is_not_official_verification(reference, expected) -> None:
    widths = {converter.normalized("Canon EOS R50"): [["Canon EOS R50", reference]]}
    check = converter.consistency_check("Canon EOS R50", "22.3 x 14.9 mm", widths)
    assert check["status"] == expected
    assert check["independent_evidence"] is False


def test_save_once_preserves_manual_edits(tmp_path: Path) -> None:
    target = tmp_path / "record.json"
    converter.save_once(target, b"original")
    converter.save_once(target, b"original")
    with pytest.raises(ValueError, match="拒绝覆盖"):
        converter.save_once(target, b"changed")
    assert target.read_bytes() == b"original"


def test_converted_files_match_report_and_draft_safety() -> None:
    report = json.loads(
        (ROOT / "knowledge_sources" / BATCH / "conversion-report.json").read_text(encoding="utf-8")
    )
    directory = ROOT / "data/knowledge_drafts" / BATCH
    files = sorted(directory.rglob("*.json"))
    assert len(files) == report["total_cards"] == 7546
    assert sum(report["by_source_and_entity"].values()) == len(files)
    assert report["officially_verified_cards"] == 0
    assert report["phone_cards"] == 0
    assert report["sensor_sources_independent"] is False
    counts = Counter()
    for item in report["index"]:
        path = directory / item["file"]
        raw = path.read_bytes()
        assert converter.sha256(raw) == item["sha256"]
        record = parse_record_file(path)
        assert record.library_id == "equipment"
        assert record.kind == "guideline"
        assert record.source.retrieval_allowed is False
        assert record.payload["verification"]["officially_verified"] is False
        assert record.payload["usage"]["controls_hardware_limits"] is False
        assert record.conditions["device_type"] == "camera"
        assert record.payload["provenance"]["commit"]
        if item["entity_type"] == "camera":
            assert record.conditions["camera_model"]
        counts[path.parent] += 1
    assert max(counts.values()) <= 20


def test_real_ui_batch_import_idempotence_and_retrieval_isolation(tmp_path: Path) -> None:
    paths = sorted((ROOT / "data/knowledge_samples" / BATCH).glob("*.json"))
    assert len(paths) == 20
    preview = preview_uploads([UploadedRecordFile(path.name, path.read_bytes()) for path in paths])
    assert preview.success, preview.issues
    assert {record.payload["entity_type"] for record in preview.records} == {
        "camera",
        "lens",
        "adapter",
    }
    store = KnowledgeStore(tmp_path / "preview.db")
    imported = commit_preview(store, preview)
    assert imported.success
    assert imported.imported_count == 20
    duplicate = import_path(store, ROOT / "data/knowledge_samples" / BATCH)
    assert duplicate.success and duplicate.unchanged_count == 20
    assert all(item.status == "draft" for item in store.list_revisions())
    assert ManagedKnowledgeRetriever(store).search("Canon 18-55") == []


def test_licenses_are_retained_separately_from_import_cards() -> None:
    directory = ROOT / "knowledge_sources" / BATCH
    assert (directory / "licenses/cameradatabase/LICENSE").is_file()
    assert (directory / "licenses/opensfm/LICENSE").is_file()
    assert (directory / "licenses/zmount/CC-BY-4.0.txt").is_file()
    assert (directory / "licenses/lensfun/COPYING.CC_BY-SA_3.0").is_file()
    assert len(list((directory / "lensfun-original").glob("*.xml"))) == 56


def sample_card() -> dict:
    path = next((ROOT / "data/knowledge_samples" / BATCH).glob("*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def test_batch_helper_backs_up_and_preserves_existing_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(converter, "ROOT", tmp_path)
    monkeypatch.setattr(converter, "REPORTS", tmp_path / "reports")
    database = tmp_path / "existing.db"
    store = KnowledgeStore(database)
    from camera_assistant.knowledge.models import KnowledgeRecord

    original = sample_card() | {"knowledge_id": "existing-equipment-record"}
    previous = store.save_draft(KnowledgeRecord.model_validate(original))
    result = converter.import_drafts(database, [sample_card()])
    assert result["imported_count"] == 1
    assert result["old_rows_preserved"]
    assert Path(result["backup"]).is_file()
    assert store.get_revision(previous.record.knowledge_id) == previous
    repeat = converter.import_drafts(database, [sample_card()])
    assert repeat["imported_count"] == 0 and repeat["unchanged_count"] == 1


def test_batch_helper_conflict_is_atomic(tmp_path: Path, monkeypatch) -> None:
    from camera_assistant.knowledge.models import KnowledgeRecord

    monkeypatch.setattr(converter, "ROOT", tmp_path)
    monkeypatch.setattr(converter, "REPORTS", tmp_path / "reports")
    database = tmp_path / "conflict.db"
    store = KnowledgeStore(database)
    card = sample_card()
    before = store.save_draft(KnowledgeRecord.model_validate(card))
    incoming = card | {"knowledge_id": "new-equipment-record"}
    conflicting = card | {"content": "同版本的不同内容"}
    with pytest.raises(ValueError, match="同一知识ID及版本已存在不同内容"):
        converter.import_drafts(database, [incoming, conflicting])
    assert store.list_revisions() == [before]


def test_batch_helper_rejects_retrieval_enabled_records(tmp_path: Path) -> None:
    card = sample_card()
    card["source"]["retrieval_allowed"] = True
    with pytest.raises(ValueError, match="不允许检索"):
        converter.import_drafts(tmp_path / "must-not-exist.db", [card])
    assert not (tmp_path / "must-not-exist.db").exists()
