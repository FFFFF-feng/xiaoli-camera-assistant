import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from camera_assistant.knowledge.models import KnowledgeRecord, SourceInfo
from camera_assistant.knowledge.store import KnowledgeError, KnowledgeStore


def record(**overrides):
    values = {
        "knowledge_id": "composition.test",
        "library_id": "composition",
        "title": "测试记录",
        "kind": "guideline",
        "content": "仅用于自动化测试，不是摄影知识。",
        "author": "作者A",
        "source": SourceInfo(name="测试资料", retrieval_allowed=True),
    }
    values.update(overrides)
    return KnowledgeRecord(**values)


@pytest.fixture
def store(tmp_path):
    return KnowledgeStore(tmp_path / "knowledge.db")


def reviewed(store, item):
    store.save_draft(item)
    store.submit(item.knowledge_id, item.version)
    return store.approve(item.knowledge_id, "审核B", item.version, note="测试审核")


def test_registers_six_empty_libraries(store):
    assert {item.library_id for item in store.list_libraries()} == {
        "scene",
        "composition",
        "style",
        "technique",
        "equipment",
        "case",
    }
    assert store.list_revisions() == []
    assert all(
        total == 0 for counts in store.library_counts().values() for total in counts.values()
    )
    assert store.audit_log() == []
    with pytest.raises(KnowledgeError):
        store.list_revisions(library_id="unknown")
    with pytest.raises(KnowledgeError):
        store.list_revisions(status="unknown")


def test_strict_models_reject_forged_status_and_invalid_data():
    for overrides in (
        {"status": "published"},
        {"knowledge_id": "../unsafe"},
        {"content": "", "payload": {}},
        {"author": " "},
        {"version": True},
        {"schema_version": True},
        {"schema_version": 2},
        {"payload": {"value": [float("inf")]}},
        {"conditions": {"value": float("nan")}},
    ):
        with pytest.raises(ValidationError):
            record(**overrides)
    for source in (
        {"name": " "},
        {"name": "来源", "url": "file:///private"},
        {"name": "来源", "url": "https://name:secret@example.com"},
        {"name": "来源", "retrieval_allowed": "false"},
    ):
        with pytest.raises(ValidationError):
            SourceInfo(**source)
    assert record(content="", payload={"nested": [None, True, 2.5, {"x": "值"}]})


def test_draft_idempotent_and_versions_increase(store):
    first = store.save_draft(record())
    assert first.status == "draft"
    assert store.save_draft(record()) == first
    assert len(store.audit_log()) == 1
    with pytest.raises(KnowledgeError, match="递增版本"):
        store.save_draft(record(content="changed"))
    with pytest.raises(KnowledgeError, match="所属"):
        store.save_draft(record(library_id="scene", version=2))
    store.save_draft(record(version=3))
    with pytest.raises(KnowledgeError, match="最新版本"):
        store.save_draft(record(version=2))
    assert store.get_revision("composition.test").record.version == 3
    assert store.get_revision("missing") is None


def test_workflow_requires_independent_review(store):
    store.save_draft(record())
    with pytest.raises(KnowledgeError):
        store.approve("composition.test", "审核B")
    with pytest.raises(KnowledgeError):
        store.publish("composition.test")
    assert store.submit("composition.test").status == "pending_review"
    with pytest.raises(KnowledgeError):
        store.approve("composition.test", "作者A")
    with pytest.raises(KnowledgeError):
        store.approve("composition.test", " ")
    approved = store.approve("composition.test", "审核B", note="已核验")
    assert approved.reviewer == "审核B"
    assert approved.review_note == "已核验"
    assert approved.reviewed_at is not None
    assert store.publish("composition.test").status == "published"
    assert len(store.list_revisions(library_id="composition", status="published")) == 1


@pytest.mark.parametrize(
    "item",
    [
        record(dataset_split="evaluation"),
        record(source=SourceInfo(name="无权限来源")),
    ],
)
def test_publication_blocks_evaluation_and_no_permission(store, item):
    reviewed(store, item)
    before = store.audit_log()
    with pytest.raises(KnowledgeError):
        store.publish(item.knowledge_id)
    assert store.get_revision(item.knowledge_id).status == "approved"
    assert store.list_revisions(status="published") == []
    assert store.audit_log() == before


def test_new_draft_keeps_published_and_publish_retires_atomically(store):
    reviewed(store, record())
    store.publish("composition.test")
    store.save_draft(record(version=2, content="新修订"))
    assert store.get_revision("composition.test", 1).status == "published"
    store.submit("composition.test", 2)
    store.approve("composition.test", "审核B", 2)
    store.publish("composition.test", 2)
    assert store.get_revision("composition.test", 1).status == "retired"
    assert [item.record.version for item in store.list_revisions(status="published")] == [2]
    assert store.retire("composition.test", 2).status == "retired"
    assert store.list_revisions(status="published") == []
    assert any(entry["action"] == "retire_superseded" for entry in store.audit_log())


def test_cannot_publish_an_older_approved_version(store):
    reviewed(store, record())
    reviewed(store, record(version=2))
    store.publish("composition.test", 2)
    store.retire("composition.test", 2)
    with pytest.raises(KnowledgeError, match="更旧"):
        store.publish("composition.test", 1)
    assert store.get_revision("composition.test", 1).status == "approved"


def test_bulk_save_rolls_back_both_records_and_audit(store):
    store.save_draft(record())
    before = store.audit_log()
    with pytest.raises(KnowledgeError):
        store.save_many_drafts(
            [
                record(knowledge_id="new-record"),
                record(content="冲突内容"),
            ]
        )
    assert store.get_revision("new-record") is None
    assert store.audit_log() == before
    assert (
        len(
            store.save_many_drafts(
                [
                    record(knowledge_id="new-record"),
                    record(version=2),
                ]
            )
        )
        == 2
    )


def test_resaving_mutated_object_is_revalidated(store):
    item = record()
    item.payload["bad"] = float("nan")
    with pytest.raises(ValidationError):
        store.save_draft(item)
    assert store.list_revisions() == []


def test_database_version_is_checked(tmp_path):
    db_path = tmp_path / "future.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(KnowledgeError, match="版本"):
        KnowledgeStore(db_path)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )


def test_database_rejects_unrelated_unversioned_schema(tmp_path):
    db_path = tmp_path / "unrelated.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE existing (value TEXT)")
    with pytest.raises(KnowledgeError, match="独立"):
        KnowledgeStore(db_path)


def test_file_store_can_be_reopened_and_used_by_threads(store):
    def save_one(index):
        return store.save_draft(record(knowledge_id=f"thread-{index}"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(list(pool.map(save_one, range(8)))) == 8
    reopened = KnowledgeStore(store.db_path)
    assert len(reopened.list_revisions()) == 8
    assert len(reopened.audit_log()) == 8


def test_reject_requires_new_revision_and_preserves_body(store):
    original = store.save_draft(record())
    store.submit("composition.test")
    rejected = store.reject("composition.test", " 审核B ", note="  缺少规则例外  ")
    assert rejected.status == "needs_revision"
    assert rejected.reviewer == "审核B"
    assert rejected.review_note == "缺少规则例外"
    assert rejected.reviewed_at is not None
    assert rejected.record == original.record
    assert rejected.content_hash == original.content_hash
    assert store.library_counts()["composition"]["needs_revision"] == 1
    assert store.list_revisions(status="needs_revision") == [rejected]
    assert store.audit_log()[-1]["action"] == "reject"
    assert store.audit_log()[-1]["details"] == {"note": "缺少规则例外"}
    with pytest.raises(KnowledgeError):
        store.submit("composition.test")
    with pytest.raises(KnowledgeError):
        store.save_draft(record(content="同版本修复"))
    fixed = store.save_draft(record(version=2, content="新版本修复"))
    assert fixed.status == "draft"
    assert store.get_revision("composition.test", 1) == rejected


@pytest.mark.parametrize(
    ("reviewer", "note"),
    [
        ("审核B", ""),
        ("审核B", "  "),
        (" 作者a ", "退回原因"),
        (" ", "退回原因"),
        ("x" * 129, "退回原因"),
    ],
)
def test_reject_checks_reviewer_and_reason_without_changes(store, reviewer, note):
    store.save_draft(record())
    store.submit("composition.test")
    before = store.audit_log()
    with pytest.raises(KnowledgeError):
        store.reject("composition.test", reviewer, note=note)
    assert store.get_revision("composition.test").status == "pending_review"
    assert store.audit_log() == before


@pytest.mark.parametrize("state", ["draft", "approved", "published", "retired", "needs_revision"])
def test_reject_only_pending_review(store, state):
    store.save_draft(record())
    if state != "draft":
        store.submit("composition.test")
        if state == "needs_revision":
            store.reject("composition.test", "审核B", note="首次退回")
        else:
            store.approve("composition.test", "审核B")
            if state in {"published", "retired"}:
                store.publish("composition.test")
            if state == "retired":
                store.retire("composition.test")
    before = store.audit_log()
    with pytest.raises(KnowledgeError, match="待审核"):
        store.reject("composition.test", "审核C", note="状态不适用")
    assert store.get_revision("composition.test").status == state
    assert store.audit_log() == before


def test_reject_new_revision_does_not_retire_published_version(store):
    reviewed(store, record())
    store.publish("composition.test", 1)
    store.save_draft(record(version=2, content="待核验新版本"))
    store.submit("composition.test", 2)
    assert (
        store.reject("composition.test", "审核B", 2, note="待补充来源").status == "needs_revision"
    )
    assert store.get_revision("composition.test", 1).status == "published"
    assert [item.record.version for item in store.list_revisions(status="published")] == [1]
