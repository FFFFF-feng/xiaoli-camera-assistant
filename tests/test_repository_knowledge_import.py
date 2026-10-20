from __future__ import annotations

import gzip
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

from camera_assistant.knowledge.models import KnowledgeRecord
from camera_assistant.knowledge.store import KnowledgeStore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "repository_import", ROOT / "scripts/import_repository_knowledge.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def card(identity="rule-001", **changes):
    return KnowledgeRecord.model_validate({
        "knowledge_id": identity, "library_id": "composition", "title": "测试构图",
        "kind": "guideline", "content": "测试资料，不用于实际推荐。", "author": "test-author",
        "source": {"name": "test-source", "retrieval_allowed": False}, **changes,
    })


def bundle(tmp_path, records):
    values = [r.model_dump(mode="json") for r in records]
    data = {"schema_version": 1, "base_commit": "test", "records": values,
            "records_sha256": module.digest(values)}
    path = tmp_path / "bundle.json.gz"
    path.write_bytes(gzip.compress(json.dumps(data).encode()))
    return path


def test_import_backup_preserves_published_and_repeat_is_noop(tmp_path):
    database = tmp_path / "knowledge.db"
    store = KnowledgeStore(database)
    old = card("published", source={"name": "test", "retrieval_allowed": True})
    store.save_draft(old)
    store.submit(old.knowledge_id)
    store.approve(old.knowledge_id, "independent-reviewer")
    store.publish(old.knowledge_id)
    before = module.read_rows(database)
    path = bundle(tmp_path, [old, card()])
    result = module.merge_bundle(path, database, tmp_path / "first", apply=True)
    assert result["imported_count"] == 1
    assert result["old_rows_preserved"] and result["integrity"] == "ok"
    assert module.read_rows(Path(result["backup"])) == before
    assert store.get_revision("rule-001").status == "draft"
    assert not store.get_revision("rule-001").record.source.retrieval_allowed
    repeat = module.merge_bundle(path, database, tmp_path / "second", apply=True)
    assert repeat["imported_count"] == repeat["repeat_import_added"] == 0
    assert store.get_revision("published").status == "published"


def test_same_revision_conflict_is_quarantined(tmp_path):
    database = tmp_path / "knowledge.db"
    store = KnowledgeStore(database)
    store.save_draft(card())
    before = module.read_rows(database)
    result = module.merge_bundle(
        bundle(tmp_path, [card(content="不同正文")]), database, tmp_path / "report", apply=True
    )
    assert result["merge_plan"]["conflict_count"] == 1
    assert result["imported_count"] == 0
    assert module.read_rows(database) == before


def test_strict_duplicate_different_id_not_inserted(tmp_path):
    database = tmp_path / "knowledge.db"
    result = module.merge_bundle(
        bundle(tmp_path, [card(), card("copy")]), database, tmp_path / "report", apply=True
    )
    assert result["imported_count"] == 1
    assert result["merge_plan"]["skipped_count"] == 1


def test_preview_never_creates_database(tmp_path):
    database = tmp_path / "missing.db"
    result = module.merge_bundle(
        bundle(tmp_path, [card()]), database, tmp_path / "preview"
    )
    assert not database.exists()
    assert result["merge_plan"]["selected_for_import"] == 1


def test_evaluation_record_rejected_even_with_permission(tmp_path):
    path = bundle(tmp_path, [card(dataset_split="evaluation")])
    with pytest.raises(ValueError, match="reference_records_invalid"):
        module.load_bundle(path)


def test_bundle_checksum_failure_does_not_create_database(tmp_path):
    path = bundle(tmp_path, [card()])
    data = json.loads(gzip.decompress(path.read_bytes()))
    data["records"][0]["content"] = "tampered"
    path.write_bytes(gzip.compress(json.dumps(data).encode()))
    with pytest.raises(ValueError, match="checksum"):
        module.merge_bundle(path, tmp_path / "db", tmp_path / "report", apply=True)
    assert not (tmp_path / "db").exists()


def test_batch_failure_rolls_back_all_writes(tmp_path, monkeypatch):
    path = bundle(tmp_path, [card("one"), card("two", content="第二条")])
    original = KnowledgeStore._save_draft

    def fail_second(self, connection, record):
        if record.knowledge_id == "two":
            raise ValueError("simulated_failure")
        return original(self, connection, record)

    monkeypatch.setattr(KnowledgeStore, "_save_draft", fail_second)
    database = tmp_path / "knowledge.db"
    with pytest.raises(ValueError, match="simulated_failure"):
        module.merge_bundle(path, database, tmp_path / "report", apply=True)
    assert module.read_rows(database) == {}


def test_record_discovery_ignores_metadata(tmp_path):
    metadata = tmp_path / "manifest.json"
    metadata.write_text(json.dumps({"cards": [{"knowledge_id": "nested-only"}]}))
    assert not module.is_record(metadata)
    record = tmp_path / "card.json"
    record.write_text(card().model_dump_json(), encoding="utf-8")
    assert module.is_record(record)


def test_archive_reads_knowledge_text_only_and_matches_reviewed_digest(tmp_path):
    path = tmp_path / "source.tar.gz"
    record = card()
    data = record.model_dump_json().encode()
    with tarfile.open(path, "w:gz") as archive:
        for name, body in (("repo/data/knowledge_drafts/set/card.json", data),
                           ("repo/scripts/untrusted.py", b"raise Exception('never executed')")):
            member = tarfile.TarInfo(name)
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
    expected = module.digest([record.model_dump(mode="json")])
    report = module.build_archive(path, tmp_path / "output", "fixed-commit", expected)
    assert report["bundle_records"] == 1 and report["invalid_records"] == []
    with pytest.raises(ValueError, match="differ_from_reviewed"):
        module.build_archive(path, tmp_path / "bad", "fixed-commit", "0" * 64)


def test_archive_rejects_symlink_knowledge(tmp_path):
    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("repo/data/knowledge_drafts/set/card.json")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        archive.addfile(member)
    with pytest.raises(ValueError, match="unsafe_archive"):
        module.build_archive(path, tmp_path / "output", "fixed-commit", "0" * 64)
