import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from camera_assistant.knowledge import uploads
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.knowledge.uploads import (
    UploadedRecordFile,
    commit_preview,
    preview_uploads,
    uploads_fingerprint,
)


def record_data(knowledge_id: str = "upload-test-001", version: int = 1) -> dict:
    return {
        "knowledge_id": knowledge_id,
        "library_id": "composition",
        "title": "[测试数据]上传桥接",
        "kind": "guideline",
        "content": "仅用于自动化测试，非正式摄影知识。",
        "source": {"name": "自制测试数据"},
        "author": "测试整理员",
        "version": version,
    }


def upload(filename: str = "record.json", data: dict | None = None) -> UploadedRecordFile:
    return UploadedRecordFile(
        filename, json.dumps(data if data is not None else record_data(), ensure_ascii=False).encode()
    )


@pytest.mark.parametrize("suffix", [".json", ".yaml", ".yml", ".md"])
def test_preview_supports_all_formats_without_writing_database(tmp_path: Path, suffix: str) -> None:
    data = record_data()
    if suffix == ".json":
        text = json.dumps(data, ensure_ascii=False)
    elif suffix == ".md":
        content = data.pop("content")
        text = "---\n" + yaml.safe_dump(data, allow_unicode=True) + "---\n\n" + content
    else:
        text = yaml.safe_dump(data, allow_unicode=True)

    preview = preview_uploads([UploadedRecordFile("知识记录" + suffix, text.encode("utf-8-sig"))])

    assert preview.success
    assert preview.total_files == 1
    assert preview.records[0].knowledge_id == "upload-test-001"
    assert not preview.records[0].source.retrieval_allowed
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "filename",
    ["", " ", "../escape.json", "sub/record.json", r"sub\record.json", "C:record.json",
     "CON.json", "nul.md", "record.json ", "record.json.", "bad\x00.json", "../PRIVATE.json"],
)
def test_unsafe_filenames_rejected_without_temp_write(
    filename: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_temp(*args, **kwargs):
        pytest.fail("无效路径不得创建临时目录")

    monkeypatch.setattr(uploads.tempfile, "TemporaryDirectory", forbidden_temp)

    preview = preview_uploads([upload(filename)])

    assert not preview.success
    assert preview.records == []
    assert "文件名无效" in preview.issues[0].message
    assert "PRIVATE" not in str(preview.issues)


def test_duplicate_filenames_are_case_insensitive() -> None:
    preview = preview_uploads([upload("record.json"), upload("RECORD.JSON", record_data("other"))])

    assert not preview.success
    assert "文件名重复" in preview.issues[0].message


def test_unsupported_upload_and_empty_input() -> None:
    assert not preview_uploads([]).success
    assert "至少一个" in preview_uploads([]).issues[0].message
    assert "仅支持" in preview_uploads([upload("manual.pdf")]).issues[0].message


def test_upload_limits_fail_before_temp_write(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 4)
    assert "2 MiB" in preview_uploads([UploadedRecordFile("large.json", b"12345")]).issues[0].message
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 10)
    monkeypatch.setattr(uploads, "MAX_BATCH_BYTES", 8)
    assert "10 MiB" in preview_uploads([
        UploadedRecordFile("a.json", b"12345"), UploadedRecordFile("b.json", b"12345")
    ]).issues[0].message
    monkeypatch.setattr(uploads, "MAX_BATCH_FILES", 1)
    assert "20 个" in preview_uploads([upload("a.json"), upload("b.json")]).issues[0].message


def test_duplicate_record_id_and_version_prevents_commit(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    preview = preview_uploads([upload("first.json"), upload("second.json")])

    report = commit_preview(store, preview)

    assert not preview.success
    assert "重复 knowledge_id" in preview.issues[0].message
    assert not report.success
    assert store.list_revisions() == []


def test_any_bad_record_prevents_entire_batch_commit(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    preview = preview_uploads([upload(), UploadedRecordFile("bad.json", b"PRIVATE_BAD_CONTENT")])

    report = commit_preview(store, preview)

    assert len(preview.records) == 1
    assert not preview.success and not report.success
    assert report.imported_count == 0
    assert "PRIVATE_BAD_CONTENT" not in str(report.errors)
    assert store.list_revisions() == []


def test_import_only_drafts_and_does_not_change_permission(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    preview = preview_uploads([upload()])

    report = commit_preview(store, preview)

    assert report.success
    assert report.imported_count == 1
    assert report.revisions[0].status == "draft"
    assert not report.revisions[0].record.source.retrieval_allowed
    assert store.list_revisions(status="published") == []


def test_repeat_commit_is_idempotent(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    preview = preview_uploads([upload()])
    assert commit_preview(store, preview).imported_count == 1

    second = commit_preview(store, preview)

    assert second.success
    assert second.imported_count == 0
    assert second.unchanged_count == 1
    assert len(store.audit_log()) == 1


def test_conflicting_version_rolls_back_new_records(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    assert commit_preview(store, preview_uploads([upload(data=record_data("z-existing"))])).success
    conflict = record_data("z-existing")
    conflict["content"] = "PRIVATE_NEW_CONFLICT_CONTENT"
    preview = preview_uploads([
        upload("new.json", record_data("a-new")), upload("conflict.json", conflict)
    ])

    report = commit_preview(store, preview)

    assert not report.success
    assert report.imported_count == 0
    assert "PRIVATE_NEW_CONFLICT_CONTENT" not in str(report.errors)
    assert store.get_revision("a-new") is None
    assert len(store.audit_log()) == 1


def test_versions_sorted_before_import(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    preview = preview_uploads([
        upload("a-v2.json", record_data(version=2)), upload("z-v1.json", record_data(version=1))
    ])

    report = commit_preview(store, preview)

    assert report.success
    assert [item.record.version for item in report.revisions] == [1, 2]


def test_temporary_sources_cleaned_after_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed_paths: list[Path] = []
    actual_parse = uploads.parse_record_file

    def tracked_parse(path: Path):
        parsed_paths.append(path)
        assert path.is_file()
        return actual_parse(path)

    monkeypatch.setattr(uploads, "parse_record_file", tracked_parse)

    assert preview_uploads([upload()]).success
    assert not preview_uploads([UploadedRecordFile("bad.yaml", b"payload: [PRIVATE")]).success
    assert len(parsed_paths) == 2
    assert all(not path.exists() and not path.parent.exists() for path in parsed_paths)


def test_preview_errors_never_echo_private_values_or_unknown_keys() -> None:
    data = record_data()
    data["PRIVATE_FIELD"] = "PRIVATE_VALUE"
    preview = preview_uploads([upload(data=data)])

    assert not preview.success
    assert "字段校验失败" in preview.issues[0].message
    assert "PRIVATE" not in str(preview.issues)


def test_database_errors_are_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")

    def fail(records):
        raise sqlite3.OperationalError("PRIVATE_DATABASE_ERROR")

    monkeypatch.setattr(store, "save_many_drafts", fail)

    report = commit_preview(store, preview_uploads([upload()]))

    assert not report.success
    assert report.imported_count == 0
    assert "PRIVATE_DATABASE_ERROR" not in str(report.errors)


@pytest.mark.parametrize("invalid", [False, True])
def test_mutated_preview_cannot_be_committed(tmp_path: Path, invalid: bool) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    preview = preview_uploads([upload()])
    preview.records[0].title = "" if invalid else "PRIVATE_CHANGED_VALID_TITLE"

    report = commit_preview(store, preview)

    assert not report.success
    assert "重新预览" in report.errors[0].message
    assert "PRIVATE" not in str(report.errors)
    assert store.list_revisions() == []


def test_changed_preview_collection_cannot_be_committed(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    preview = preview_uploads([upload()])
    preview.records.append(preview.records[0])

    assert not commit_preview(store, preview).success
    assert store.list_revisions() == []


def test_fingerprint_binds_name_bytes_order_and_file_count() -> None:
    first = upload("first.json")
    second = upload("second.json", record_data("second"))
    assert uploads_fingerprint([first, second]) == preview_uploads([first, second]).fingerprint
    fingerprints = {
        uploads_fingerprint([first]),
        uploads_fingerprint([second]),
        uploads_fingerprint([first, second]),
        uploads_fingerprint([second, first]),
        uploads_fingerprint([UploadedRecordFile(first.filename, first.data + b" ")]),
        uploads_fingerprint([UploadedRecordFile("renamed.json", first.data)]),
    }
    assert len(fingerprints) == 6


def test_upload_representations_hide_raw_content() -> None:
    data = record_data()
    data["content"] = "PRIVATE_UPLOAD_BYTES"
    item = upload(data=data)
    preview = preview_uploads([item])
    assert "PRIVATE_UPLOAD_BYTES" not in repr(item)
    assert ", _files=" not in repr(preview)
    assert "PRIVATE_UPLOAD_BYTES" not in repr(preview)


UNICODE_TARGETS = [
    "content", "title", "author", "tags", "source.name", "source.location", "source.license",
    "payload.key", "payload.value", "conditions.key", "conditions.value",
]


def inject_unicode(data: dict, target: str, character: str) -> dict:
    private_text = "PRIVATE_UNICODE_VALUE_" + character
    if target in {"content", "title", "author"}:
        data[target] = private_text
    elif target == "tags":
        data["tags"] = [private_text]
    elif target.startswith("source."):
        data["source"][target.split(".")[1]] = private_text
    else:
        field, part = target.split(".")
        data[field] = (
            {"nested": {private_text: "value"}}
            if part == "key"
            else {"nested": {"items": [private_text]}}
        )
    return data


@pytest.mark.parametrize("target", UNICODE_TARGETS)
@pytest.mark.parametrize("character", [chr(0xD800), chr(0xDFFF)])
def test_preview_rejects_isolated_surrogates_anywhere_without_echo_or_partial_write(
    tmp_path: Path, target: str, character: str
) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    bad_data = inject_unicode(record_data("bad-unicode"), target, character)
    bad_file = UploadedRecordFile("bad.json", json.dumps(bad_data, ensure_ascii=True).encode())

    preview = preview_uploads([upload(), bad_file])
    report = commit_preview(store, preview)

    assert not preview.success
    assert preview.total_files == 2
    assert len(preview.records) == 1
    assert len(preview.issues) == 1
    assert preview.issues[0].message in {
        "知识记录包含无效 Unicode 字符，请修正后重新预览。",
        "字段校验失败，请检查必填项、字段类型和是否包含未支持的字段。",
    }
    assert "PRIVATE" not in str(preview.issues)
    assert not report.success
    assert report.imported_count == 0
    assert store.list_revisions() == []
    assert store.audit_log() == []


@pytest.mark.parametrize("target", UNICODE_TARGETS)
def test_commit_rejects_surrogate_mutation_without_content_echo_or_writes(
    tmp_path: Path, target: str
) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    preview = preview_uploads([upload()])
    altered_data = inject_unicode(preview.records[0].model_dump(), target, chr(0xD800))
    # 模拟预览后可变 Pydantic 模型被调用方修改，提交时必须重新检查。
    for field, value in altered_data.items():
        if field == "source":
            for source_field, source_value in value.items():
                setattr(preview.records[0].source, source_field, source_value)
        else:
            setattr(preview.records[0], field, value)

    report = commit_preview(store, preview)

    assert not report.success
    assert "重新预览" in report.errors[0].message
    assert "PRIVATE" not in str(report.errors)
    assert report.imported_count == 0
    assert store.list_revisions() == []
    assert store.audit_log() == []


def test_valid_non_bmp_unicode_is_supported(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    data = record_data()
    data["content"] = "[测试数据]摄影助手 📷🦊"
    file = UploadedRecordFile("valid.json", json.dumps(data, ensure_ascii=True).encode())

    preview = preview_uploads([file])
    report = commit_preview(store, preview)

    assert preview.success and report.success
    assert report.revisions[0].record.content == data["content"]


@pytest.mark.parametrize("yaml_type", ["int", "float", "bool"])
def test_yaml_constructor_errors_never_echo_private_source_or_write(
    tmp_path: Path, yaml_type: str
) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    bad_file = UploadedRecordFile(
        "bad.yaml", f"payload: {{value: !!{yaml_type} PRIVATE_TEST_VALUE}}".encode()
    )

    preview = preview_uploads([upload(), bad_file])
    report = commit_preview(store, preview)

    assert not preview.success and not report.success
    assert len(preview.records) == 1
    assert preview.issues[0].message == (
        "文件格式或字段内容无效，请检查 JSON／YAML／Markdown 格式。"
    )
    assert "PRIVATE_TEST_VALUE" not in str(preview.issues)
    assert store.list_revisions() == []
    assert store.audit_log() == []
