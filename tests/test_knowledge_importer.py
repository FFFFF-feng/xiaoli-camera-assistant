import json
from pathlib import Path

import pytest
import yaml

from camera_assistant.knowledge.importer import RecordFileError, import_path, parse_record_file
from camera_assistant.knowledge.store import KnowledgeStore


def record_data(knowledge_id: str = "test-composition-001", version: int = 1) -> dict:
    return {
        "knowledge_id": knowledge_id,
        "library_id": "composition",
        "title": "[测试数据]构图规则",
        "kind": "guideline",
        "content": "仅供自动化测试，不是正式摄影知识。",
        "payload": {"nested": {"safe": True}, "numbers": [1, 2]},
        "tags": ["测试", "构图"],
        "conditions": {"scene": ["test-scene"]},
        "source": {
            "name": "自动化测试资料",
            "url": "https://example.com/test-only",
            "location": "测试章节",
            "license": "测试自制资料",
            "retrieval_allowed": True,
        },
        "author": "测试整理员",
        "version": version,
        "schema_version": 1,
        "dataset_split": "reference",
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("suffix", [".json", ".yaml", ".yml", ".md"])
def test_parse_formats_preserve_nested_data_and_utf8_bom(tmp_path: Path, suffix: str) -> None:
    data = record_data()
    path = tmp_path / f"record{suffix}"
    if suffix == ".json":
        text = json.dumps(data, ensure_ascii=False)
    elif suffix == ".md":
        content = data.pop("content")
        text = "---\n" + yaml.safe_dump(data, allow_unicode=True) + "---\n\n" + content
    else:
        text = yaml.safe_dump(data, allow_unicode=True)
    path.write_text(text, encoding="utf-8-sig")

    record = parse_record_file(path)

    assert record.title == "[测试数据]构图规则"
    assert record.payload == {"nested": {"safe": True}, "numbers": [1, 2]}
    assert record.conditions == {"scene": ["test-scene"]}
    assert record.content == "仅供自动化测试，不是正式摄影知识。"


@pytest.mark.parametrize("field", ["status", "reviewer", "unknown_field"])
def test_file_cannot_set_review_state_or_unknown_fields(tmp_path: Path, field: str) -> None:
    path = tmp_path / "record.json"
    data = record_data()
    data[field] = "PRIVATE_VALUE_NEVER_ECHO"
    write_json(path, data)

    with pytest.raises(RecordFileError) as error:
        parse_record_file(path)

    assert path.name in str(error.value)
    assert field in str(error.value)
    assert "PRIVATE_VALUE_NEVER_ECHO" not in str(error.value)


@pytest.mark.parametrize(
    ("suffix", "text"),
    [
        (".json", '{"payload": {"secret": "PRIVATE", "secret": "SECOND"}}'),
        (".yaml", "payload:\n  secret: PRIVATE\n  secret: SECOND\n"),
        (".md", "---\npayload:\n  secret: PRIVATE\n  secret: SECOND\n---\n正文"),
    ],
)
def test_duplicate_keys_are_rejected_without_content_echo(
    tmp_path: Path, suffix: str, text: str
) -> None:
    path = tmp_path / f"duplicate{suffix}"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(RecordFileError, match="重复字段") as error:
        parse_record_file(path)

    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize(
    ("suffix", "text"),
    [
        (".json", '{"secret": "PRIVATE",}'),
        (".yaml", "payload: [ PRIVATE\n"),
        (".md", "PRIVATE WITHOUT FRONTMATTER"),
        (".yaml", "payload: &x [*x]"),
        (".json", '{"payload": {"x": NaN}}'),
    ],
)
def test_bad_syntax_aliases_and_nonfinite_values_are_rejected(
    tmp_path: Path, suffix: str, text: str
) -> None:
    path = tmp_path / f"bad{suffix}"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(RecordFileError) as error:
        parse_record_file(path)

    assert "PRIVATE" not in str(error.value)


def test_markdown_content_must_come_from_body(tmp_path: Path) -> None:
    path = tmp_path / "record.md"
    path.write_text("---\ncontent: duplicated\n---\nbody", encoding="utf-8")
    with pytest.raises(RecordFileError, match="content"):
        parse_record_file(path)


def test_file_limit_and_unsupported_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from camera_assistant.knowledge import importer

    monkeypatch.setattr(importer, "MAX_RECORD_BYTES", 20)
    path = tmp_path / "large.json"
    path.write_text("x" * 21, encoding="utf-8")
    with pytest.raises(RecordFileError, match="2 MiB"):
        parse_record_file(path)
    with pytest.raises(RecordFileError, match="仅支持"):
        parse_record_file(tmp_path / "manual.pdf")


def test_entire_batch_validation_precedes_any_write(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    folder = tmp_path / "records"
    folder.mkdir()
    write_json(folder / "valid.json", record_data())
    write_json(folder / "invalid.json", {"title": "[测试数据]不完整"})

    report = import_path(store, folder)

    assert not report.success
    assert report.total_files == 2
    assert report.validated_count == 1
    assert report.imported_count == 0
    assert store.list_revisions() == []


def test_same_batch_duplicate_revision_rejected(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    folder = tmp_path / "records"
    folder.mkdir()
    write_json(folder / "first.json", record_data())
    write_json(folder / "second.json", record_data())

    report = import_path(store, folder)

    assert not report.success
    assert "重复 knowledge_id" in report.errors[0].message
    assert store.list_revisions() == []


def test_import_is_draft_and_identical_import_is_idempotent(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    path = tmp_path / "record.json"
    write_json(path, record_data())

    first = import_path(store, path)
    second = import_path(store, path)

    assert first.success and second.success
    assert first.imported_count == 1
    assert first.revisions[0].status == "draft"
    assert second.imported_count == 0
    assert second.unchanged_count == 1
    assert len(store.list_revisions()) == 1


def test_database_conflict_rolls_back_other_records(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    old = tmp_path / "old.json"
    write_json(old, record_data("test-existing"))
    assert import_path(store, old).success
    folder = tmp_path / "records"
    folder.mkdir()
    write_json(folder / "new.json", record_data("test-new"))
    conflict = record_data("test-existing")
    conflict["content"] = "[测试数据]同版本不同正文"
    write_json(folder / "conflict.json", conflict)

    report = import_path(store, folder)

    assert not report.success
    assert report.imported_count == 0
    assert {item.record.knowledge_id for item in store.list_revisions()} == {"test-existing"}


def test_dry_run_needs_no_database(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    write_json(path, record_data())

    report = import_path(None, path, dry_run=True)

    assert report.success
    assert report.validated_only
    assert report.validated_count == 1
    assert report.imported_count == 0
    assert report.revisions == []
    assert list(tmp_path.glob("*.db")) == []


def test_directory_does_not_follow_symlinks(tmp_path: Path) -> None:
    folder = tmp_path / "records"
    folder.mkdir()
    outside = tmp_path / "outside.json"
    write_json(outside, record_data("test-outside"))
    write_json(folder / "valid.json", record_data())
    try:
        (folder / "link.json").symlink_to(outside)
    except OSError:
        pytest.skip("本机未授权创建符号链接")

    report = import_path(None, folder, dry_run=True)

    assert report.success
    assert report.total_files == 1
    assert report.skipped_files == ["link.json"]


def test_empty_and_missing_input_return_errors(tmp_path: Path) -> None:
    assert not import_path(None, tmp_path, dry_run=True).success
    assert not import_path(None, tmp_path / "missing", dry_run=True).success


def test_import_reports_database_errors_without_raw_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    store = KnowledgeStore(tmp_path / "knowledge.db")
    path = tmp_path / "record.json"
    write_json(path, record_data())

    def failed_write(records: list) -> None:
        raise sqlite3.OperationalError("PRIVATE_DATABASE_DETAILS")

    monkeypatch.setattr(store, "save_many_drafts", failed_write)

    report = import_path(store, path)

    assert not report.success
    assert report.imported_count == 0
    assert "PRIVATE_DATABASE_DETAILS" not in report.errors[0].message


def test_batch_versions_are_sorted_before_atomic_write(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    folder = tmp_path / "records"
    folder.mkdir()
    write_json(folder / "a-v2.json", record_data(version=2))
    write_json(folder / "z-v1.json", record_data(version=1))

    report = import_path(store, folder)

    assert report.success
    assert [item.record.version for item in report.revisions] == [1, 2]


def test_junction_directories_and_files_are_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "records"
    folder.mkdir()
    blocked = folder / "junction-folder"
    blocked.mkdir()
    write_json(blocked / "hidden.json", record_data("test-hidden"))
    write_json(folder / "junction-file.json", record_data("test-hidden-file"))
    write_json(folder / "valid.json", record_data())
    monkeypatch.setattr(
        Path,
        "is_junction",
        lambda path: path.name in {"junction-folder", "junction-file.json"},
        raising=False,
    )

    report = import_path(None, folder, dry_run=True)

    assert report.success
    assert report.validated_count == 1
    assert report.skipped_files == ["junction-folder/", "junction-file.json"]
    assert not import_path(None, blocked, dry_run=True).success
    with pytest.raises(RecordFileError, match="Junction"):
        parse_record_file(folder / "junction-file.json")
