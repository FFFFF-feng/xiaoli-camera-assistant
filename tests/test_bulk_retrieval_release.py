import importlib.util
import sqlite3
from pathlib import Path

import pytest

from camera_assistant.knowledge.models import KnowledgeRecord
from camera_assistant.knowledge.store import KnowledgeStore

SPEC = importlib.util.spec_from_file_location("bulk_release", Path(__file__).resolve().parents[1]
                                           / "scripts/enable_repository_retrieval.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture_db(tmp_path):
    path = tmp_path / "knowledge.db"
    store = KnowledgeStore(path)
    for identity, split in (("reference", "reference"), ("test-sample", "evaluation")):
        store.save_draft(KnowledgeRecord.model_validate({
            "knowledge_id": identity, "library_id": "technique", "kind": "guideline",
            "title": "测试", "content": "测试", "author": "original-author",
            "dataset_split": split,
            "source": {"name": "original-source", "license": "待确认", "retrieval_allowed": False},
            "payload": {"verification": {"expert_reviewed": False}},
        }))
    return path, store


def test_explicit_confirmation_required(tmp_path):
    path, store = fixture_db(tmp_path)
    with pytest.raises(ValueError, match="confirmation"):
        module.enable(path, tmp_path / "release", "user")
    assert len(store.list_revisions()) == 2
    assert not (tmp_path / "release").exists()


def test_bulk_preserves_original_and_evaluation_and_repeat_is_noop(tmp_path):
    path, store = fixture_db(tmp_path)
    old = store.get_revision("reference")
    result = module.enable(path, tmp_path / "release", "user", confirmed=True)
    assert result["enabled"] == result["excluded_evaluation"] == 1
    published = store.get_revision("reference")
    assert published.status == "published" and published.record.version == 2
    assert published.reviewer == "user"
    assert published.record.source.license == "待确认"
    assert not published.record.payload["retrieval_release"]["expert_reviewed"]
    assert store.get_revision("reference", 1) == old
    assert store.get_revision("test-sample").status == "draft"
    with sqlite3.connect(path) as connection:
        audit_before = connection.execute("select count(*) from audit_entries").fetchone()[0]
    repeat = module.enable(path, tmp_path / "repeat", "user", confirmed=True)
    assert repeat["enabled"] == 0 and repeat["already_published"] == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from audit_entries").fetchone()[0] == audit_before
    backup = KnowledgeStore(tmp_path / "release/before-enable.db")
    assert backup.get_revision("reference") == old


def test_author_cannot_self_approve(tmp_path):
    path, store = fixture_db(tmp_path)
    with pytest.raises(ValueError, match="own_record"):
        module.enable(path, tmp_path / "release", "original-author", confirmed=True)
    assert store.get_revision("reference").status == "draft"
    assert not (tmp_path / "release").exists()
