from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from camera_assistant.knowledge.models import KnowledgeRecord
from camera_assistant.knowledge.store import KnowledgeStore

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sync_github_knowledge", ROOT / "scripts/sync_github_knowledge.py"
)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


def card(identity="fixture-rule", version=1, **changes) -> KnowledgeRecord:
    data = {
        "knowledge_id": identity,
        "version": version,
        "library_id": "technique",
        "title": "测试摄影规则",
        "kind": "guideline",
        "content": "测试用拍摄规则。",
        "payload": {"limit": "仅测试"},
        "conditions": {"device_type": "phone"},
        "source": {
            "name": "测试自制来源",
            "url": "https://example.com/fixture",
            "license": "仅测试",
            "retrieval_allowed": False,
        },
        "author": "测试整理员",
    }
    return KnowledgeRecord.model_validate(data | changes)


def rows(tmp_path: Path, records: list[KnowledgeRecord]) -> dict:
    database = tmp_path / "knowledge.db"
    KnowledgeStore(database).save_many_drafts(records)
    return sync.read_rows(database)


def test_existing_same_revision_skipped_without_changing_review_state(tmp_path: Path) -> None:
    record = card(source={"name": "测试", "retrieval_allowed": True})
    database = tmp_path / "knowledge.db"
    store = KnowledgeStore(database)
    store.save_draft(record)
    store.submit(record.knowledge_id)
    store.approve(record.knowledge_id, reviewer="独立测试审核员")
    store.publish(record.knowledge_id)
    before = sync.read_rows(database)
    selected, plan = sync.plan_merge([("fixture.json", record)], before)
    assert selected == []
    assert plan["skipped"][0]["reason"] == "same_id_version_identical"
    assert sync.read_rows(database) == before


def test_same_id_version_different_content_is_quarantined(tmp_path: Path) -> None:
    original = card()
    selected, plan = sync.plan_merge(
        [("fixture.json", card(content="不同的新正文"))], rows(tmp_path, [original])
    )
    assert not selected
    assert plan["conflict_count"] == 1
    assert plan["conflicts"][0]["reason"] == "same_id_version_different_database_content"


def test_stale_versions_skipped_and_higher_versions_allowed(tmp_path: Path) -> None:
    before = rows(tmp_path, [card(version=2)])
    selected, plan = sync.plan_merge(
        [("old.json", card(version=1)), ("new.json", card(version=3, content="修订正文"))], before
    )
    assert [item.version for item in selected] == [3]
    assert plan["skipped"][0]["reason"] == "older_than_database_latest_version"


def test_exact_copy_under_different_id_is_skipped(tmp_path: Path) -> None:
    before = rows(tmp_path, [card()])
    selected, plan = sync.plan_merge([("copy.json", card(identity="copy-rule"))], before)
    assert selected == []
    assert plan["skipped"][0]["retained_knowledge_id"] == "fixture-rule"


@pytest.mark.parametrize(
    "change",
    [
        {"conditions": {"device_type": "camera"}},
        {"source": {"name": "不同证据", "retrieval_allowed": False}},
        {"author": "不同作者"},
        {"payload": {"limit": "不同约束"}},
    ],
)
def test_different_conditions_evidence_or_authors_are_not_silently_collapsed(
    tmp_path: Path, change: dict
) -> None:
    selected, plan = sync.plan_merge(
        [("different.json", card(identity="different-rule", **change))], rows(tmp_path, [card()])
    )
    assert len(selected) == 1
    assert plan["related_titles"][0]["automatically_merged"] is False


def test_incoming_duplicates_and_local_file_conflicts() -> None:
    record = card()
    selected, plan = sync.plan_merge([("a.json", record), ("b.json", record)], {})
    assert len(selected) == 1 and plan["skipped_count"] == 1
    selected, plan = sync.plan_merge([("a.json", record), ("b.json", card(content="不同正文"))], {})
    assert selected == [] and plan["conflict_count"] == 1
    selected, plan = sync.plan_merge([("a.json", record)], {}, {"a.json"})
    assert selected == [] and plan["conflict_count"] == 1


def test_cross_library_conflict_is_never_overwritten(tmp_path: Path) -> None:
    selected, plan = sync.plan_merge(
        [("new.json", card(version=2, library_id="composition"))], rows(tmp_path, [card()])
    )
    assert not selected
    assert plan["conflicts"][0]["reason"] == "library_changed"


@pytest.mark.parametrize(
    "path",
    [
        "../../app.py",
        "/data/knowledge_drafts/starter-v1/a.json",
        "data/knowledge_drafts/starter-v1/../../app.py",
        "data/knowledge_drafts/other/a.json",
        "data/knowledge_drafts/starter-v1/C:/a.json",
        "data\\knowledge_drafts\\starter-v1\\a.json",
    ],
)
def test_only_allowlisted_knowledge_paths_are_accepted(path: str) -> None:
    with pytest.raises(ValueError):
        sync.safe_path(path)


def test_file_sync_preserves_local_edits_and_newlines(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    cache = tmp_path / "cache"
    path = "data/knowledge_drafts/starter-v1/a.md"
    remote = cache / path
    remote.parent.mkdir(parents=True)
    remote.write_bytes(b"original\n")
    local = tmp_path / path
    local.parent.mkdir(parents=True)
    local.write_bytes(b"edited\n")
    conflicts, result = sync.synchronize_files(cache, [{"path": path}], apply=True)
    assert conflicts == {path}
    assert result["local_changes_preserved"] == 1
    assert local.read_bytes() == b"edited\n"
    local.write_bytes(b"original\r\n")
    conflicts, result = sync.synchronize_files(cache, [{"path": path}], apply=True)
    assert not conflicts and result["line_endings_only_preserved"] == 1
    assert local.read_bytes() == b"original\r\n"


def test_safe_writer_never_overwrites_or_escapes_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sync, "ROOT", tmp_path / "workspace")
    path = tmp_path / "workspace/a.json"
    sync.write_new(path, b"original")
    with pytest.raises(ValueError, match="拒绝覆盖"):
        sync.write_new(path, b"changed")
    with pytest.raises(ValueError, match="工作区以外"):
        sync.write_new(tmp_path / "outside.json", b"blocked")


def test_apply_merge_backup_preservation_and_real_database_idempotence(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    database = tmp_path / "knowledge.db"
    store = KnowledgeStore(database)
    store.save_draft(card(identity="old-rule"))
    before = sync.read_rows(database)
    result = sync.apply_merge(
        database, [card(identity="new-rule", content="新增")], before, tmp_path / "reports"
    )
    assert result["records_before"] == 1 and result["records_after"] == 2
    assert result["imported_count"] == 1
    assert result["old_rows_preserved"] and result["new_rows_all_draft"]
    assert result["real_database_repeat_import_new_rows"] == 0
    assert Path(result["backup"]).is_file()
    assert len(sync.read_rows(Path(result["backup"]))) == 1
    assert all(sync.read_rows(database)[key] == value for key, value in before.items())


def test_changed_database_stops_before_import(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    database = tmp_path / "knowledge.db"
    store = KnowledgeStore(database)
    before = sync.read_rows(database)
    store.save_draft(card(identity="concurrent-rule"))
    with pytest.raises(ValueError, match="计划后发生变化"):
        sync.apply_merge(database, [card()], before, tmp_path / "reports")
    assert len(store.list_revisions()) == 1


def test_real_cached_collections_are_parsed_and_manifest_verified() -> None:
    commit = "6e362996ae75977c2c41c183f0f474b0f2536dc6"
    cache = ROOT / "data/source_cache" / f"github-knowledge-{commit}"
    if not cache.exists():
        pytest.skip("本机下载缓存不随 Git 分发")
    tree = json.loads((cache / "tree.json").read_text(encoding="utf-8"))
    files = [
        {"path": item["path"], "is_card": sync.is_card(item["path"])}
        for item in tree["tree"]
        if item["type"] == "blob"
        and item["path"].startswith(sync.PREFIX)
        and (cache / item["path"]).is_file()
    ]
    incoming, manifests = sync.load_cards(cache, files)
    assert len(incoming) == 160
    assert [item["cards"] for item in manifests] == [22, 121]
    assert all(
        not record.source.retrieval_allowed
        for path, record in incoming
        if "/starter-v1/" not in path
    )
