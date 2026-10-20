import gzip
import importlib.util
import json
from pathlib import Path

import pytest

from camera_assistant.knowledge.store import KnowledgeStore

spec = importlib.util.spec_from_file_location(
    "restore_knowledge_snapshot", Path(__file__).resolve().parents[1]
    / "scripts/restore_knowledge_snapshot.py"
)
snapshot_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot_tool)


def make_snapshot(tmp_path):
    from camera_assistant.knowledge.models import KnowledgeRecord, SourceInfo

    database = tmp_path / "original.db"
    store = KnowledgeStore(database)
    record = KnowledgeRecord(
        knowledge_id="snapshot-rule", library_id="composition", title="构图快照测试",
        kind="guideline", content="保留主体边缘", author="author",
        source=SourceInfo(name="测试来源", retrieval_allowed=True),
    )
    store.save_draft(record)
    store.submit(record.knowledge_id)
    store.approve(record.knowledge_id, "reviewer")
    store.publish(record.knowledge_id)
    store.save_draft(record.model_copy(update={"version": 2, "content": "修订草稿"}))
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    archive = snapshot / "knowledge.sqlite3.gz"
    archive.write_bytes(gzip.compress(database.read_bytes(), mtime=0))
    manifest = {
        "snapshot_format": 1, "archive_sha256": snapshot_tool.sha256(archive),
        "database_sha256": snapshot_tool.sha256(database),
        "database_bytes": database.stat().st_size,
        "summary": snapshot_tool.database_summary(database),
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return snapshot


def test_restore_preserves_published_draft_and_audit_history(tmp_path):
    snapshot = make_snapshot(tmp_path)
    output = tmp_path / "restored.db"
    summary = snapshot_tool.restore(snapshot, output)
    store = KnowledgeStore(output)
    assert store.get_revision("snapshot-rule", 1).status == "published"
    assert store.get_revision("snapshot-rule", 2).status == "draft"
    assert len(store.audit_log()) == summary["audit_entries"] == 5
    assert snapshot_tool.restore(snapshot) == summary


def test_restore_never_overwrites_existing_database(tmp_path):
    snapshot = make_snapshot(tmp_path)
    output = tmp_path / "existing.db"
    output.write_bytes(b"preserve existing database")
    with pytest.raises(FileExistsError):
        snapshot_tool.restore(snapshot, output)
    assert output.read_bytes() == b"preserve existing database"


def test_corrupted_archive_creates_no_database(tmp_path):
    snapshot = make_snapshot(tmp_path)
    with (snapshot / "knowledge.sqlite3.gz").open("ab") as stream:
        stream.write(b"corrupted")
    output = tmp_path / "restored.db"
    with pytest.raises(ValueError, match="压缩文件校验失败"):
        snapshot_tool.restore(snapshot, output)
    assert not output.exists()


def test_wrong_uncompressed_hash_creates_no_database(tmp_path):
    snapshot = make_snapshot(tmp_path)
    path = snapshot / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["database_sha256"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "restored.db"
    with pytest.raises(ValueError, match="数据库校验失败"):
        snapshot_tool.restore(snapshot, output)
    assert not output.exists()
