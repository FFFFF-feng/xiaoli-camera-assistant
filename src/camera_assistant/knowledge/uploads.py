"""界面上传桥接：只预览、经确认后原子导入草稿，不保存原始上传。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from camera_assistant.knowledge.importer import (
    SUPPORTED_SUFFIXES,
    ImportIssue,
    ImportReport,
    RecordFileError,
    parse_record_file,
)
from camera_assistant.knowledge.models import KnowledgeRecord
from camera_assistant.knowledge.store import KnowledgeError, KnowledgeStore

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_BATCH_FILES = 20
MAX_BATCH_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class UploadedRecordFile:
    filename: str
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class PreviewBatch:
    records: list[KnowledgeRecord] = field(repr=False)
    issues: list[ImportIssue]
    fingerprint: str
    total_files: int
    _files: tuple[UploadedRecordFile, ...] = field(default=(), repr=False)
    _records_digest: str = field(default="", repr=False)

    @property
    def success(self) -> bool:
        return bool(self.records) and not self.issues


def uploads_fingerprint(files: list[UploadedRecordFile]) -> str:
    """绑定文件顺序、完整文件名和原始字节，供界面丢弃陈旧预览。"""
    digest = hashlib.sha256(b"camera-assistant-upload-v1\x00")
    for item in files:
        if not isinstance(item, UploadedRecordFile):
            raise TypeError("上传项类型无效。")
        if not isinstance(item.filename, str) or not isinstance(item.data, bytes):
            raise TypeError("上传文件必须提供文件名和不可变字节。")
        name = item.filename.encode("utf-8", errors="surrogatepass")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(item.data).to_bytes(8, "big"))
        digest.update(item.data)
    digest.update(len(files).to_bytes(8, "big"))
    return digest.hexdigest()


def _record_digest(records: list[KnowledgeRecord]) -> str:
    data = json.dumps(
        # Python 模式保留原始字符串；JSON 模式可能替换嵌套键中的无效字符。
        [item.model_dump(mode="python") for item in records],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _safe_filename(filename: str) -> bool:
    if not filename or len(filename) > 240 or filename != filename.strip():
        return False
    if filename.endswith(".") or any(char in filename for char in '/\\<>:"|?*'):
        return False
    if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in filename):
        return False
    stem = filename.split(".", 1)[0].rstrip(" .").casefold()
    reserved = {"con", "prn", "aux", "nul"}
    reserved.update(f"{prefix}{index}" for prefix in ("com", "lpt") for index in range(1, 10))
    return stem not in reserved and filename not in {".", ".."}


def _safe_parse_message(message: str) -> str:
    # Pydantic 的错误位置可能包含用户自定义字段名，不将其回显到 UI。
    if message.startswith("字段校验失败"):
        return "字段校验失败，请检查必填项、字段类型和是否包含未支持的字段。"
    fixed_messages = {
        "文件必须使用 UTF-8 编码（可带 BOM）。",
        "Markdown 必须以 YAML 前置元数据（---）开头。",
        "Markdown 前置元数据缺少结束分隔符。",
        "前置元数据必须是一个对象。",
        "Markdown 的 content 由正文生成，不要在前置元数据中重复填写。",
        "YAML 不支持别名引用，请展开为普通字段。",
        "YAML 不允许重复字段。",
        "YAML 对象的字段名必须是字符串。",
        "JSON 不允许重复字段。",
        "JSON 不允许 NaN 或 Infinity。",
        "知识记录顶层必须是一个对象。",
        "资料结构过深或过大，请拆分知识记录。",
        "对象的字段名必须是字符串。",
        "资料包含非 JSON 类型，请将日期等信息填写为字符串。",
        "数值必须是有限数值。",
        "资料结构过深，请拆分知识记录。",
        "无法读取文件，请检查文件权限与路径。",
        "单条记录不能超过 2 MiB。",
    }
    if message in fixed_messages or re.fullmatch(
        r"(?:JSON 格式错误，位于第 [0-9]+ 行、第 [0-9]+ 列|"
        r"YAML 格式错误(?:，位于第 [0-9]+ 行、第 [0-9]+ 列)?)。",
        message,
    ):
        return message
    return "文件格式或字段内容无效，请检查 JSON／YAML／Markdown 格式。"


def preview_uploads(files: list[UploadedRecordFile]) -> PreviewBatch:
    """全部文件先校验；临时文件在返回前清理，任一错误都禁止提交。"""
    issues: list[ImportIssue] = []
    records: list[KnowledgeRecord] = []
    try:
        fingerprint = uploads_fingerprint(files)
    except (ValueError, TypeError):
        return PreviewBatch([], [ImportIssue("上传批次", "上传文件数据无效。")], "", len(files))
    snapshots = tuple(files)
    if not files:
        issues.append(ImportIssue("上传批次", "请先提供至少一个知识记录文件。"))
    if len(files) > MAX_BATCH_FILES:
        issues.append(ImportIssue("上传批次", "每批最多上传 20 个文件。"))
    if sum(len(item.data) for item in files) > MAX_BATCH_BYTES:
        issues.append(ImportIssue("上传批次", "整个批次不能超过 10 MiB。"))
    names: set[str] = set()
    for index, item in enumerate(files, start=1):
        if not _safe_filename(item.filename):
            issues.append(ImportIssue(f"第 {index} 个文件", "文件名无效，不允许路径或特殊文件名。"))
            continue
        normalized_name = item.filename.casefold()
        if normalized_name in names:
            issues.append(ImportIssue(item.filename, "同批文件名重复，请使用不同文件名。"))
        names.add(normalized_name)
        if Path(item.filename).suffix.lower() not in SUPPORTED_SUFFIXES:
            issues.append(ImportIssue(item.filename, "仅支持 .json、.yaml、.yml、.md。"))
        if len(item.data) > MAX_UPLOAD_BYTES:
            issues.append(ImportIssue(item.filename, "单个文件不能超过 2 MiB。"))
    # 有路径、容量等错误时不将任何输入落盘。
    if issues:
        return PreviewBatch(records, issues, fingerprint, len(files), snapshots)

    identities: set[tuple[str, int]] = set()
    try:
        with tempfile.TemporaryDirectory(prefix="camera-knowledge-preview-") as directory:
            root = Path(directory)
            for item in files:
                try:
                    path = root / item.filename
                    path.write_bytes(item.data)
                    record = parse_record_file(path)
                    # JSON 可转义孤立代理字符；模型接受它们，但不能安全编码到
                    # UTF-8／SQLite。校验完整记录，覆盖元数据与嵌套对象的键和值。
                    _record_digest([record])
                except RecordFileError as error:
                    issues.append(ImportIssue(item.filename, _safe_parse_message(error.message)))
                    continue
                except UnicodeError:
                    issues.append(
                        ImportIssue(
                            item.filename, "知识记录包含无效 Unicode 字符，请修正后重新预览。"
                        )
                    )
                    continue
                except (ValueError, TypeError, KeyError):
                    issues.append(
                        ImportIssue(
                            item.filename,
                            "文件格式或字段内容无效，请检查 JSON／YAML／Markdown 格式。",
                        )
                    )
                    continue
                except OSError:
                    issues.append(
                        ImportIssue(item.filename, "无法创建临时预览，请检查临时目录权限。")
                    )
                    continue
                identity = (record.knowledge_id, record.version)
                if identity in identities:
                    issues.append(
                        ImportIssue(
                            item.filename, "同批存在重复 knowledge_id／version，请保留一个文件。"
                        )
                    )
                    continue
                identities.add(identity)
                records.append(record)
    except OSError:
        issues.append(ImportIssue("上传批次", "临时预览失败，请检查临时目录权限。"))
    return PreviewBatch(
        records, issues, fingerprint, len(files), snapshots, _record_digest(records)
    )


def commit_preview(store: KnowledgeStore, preview: PreviewBatch) -> ImportReport:
    """界面明确确认后调用；重新校验并检查预览完整性，只原子保存草稿。"""
    report = ImportReport(total_files=preview.total_files, validated_count=len(preview.records))
    if not preview.success:
        report.errors = list(preview.issues) or [ImportIssue("上传批次", "没有可导入的预览记录。")]
        return report
    try:
        if not preview._files or preview.total_files != len(preview._files):
            raise ValueError("预览来源不完整。")
        if uploads_fingerprint(list(preview._files)) != preview.fingerprint:
            raise ValueError("预览来源已变化。")
        records = [KnowledgeRecord.model_validate(item.model_dump()) for item in preview.records]
        if _record_digest(records) != preview._records_digest:
            raise ValueError("预览记录已变化。")
        identities = {(item.knowledge_id, item.version) for item in records}
        if len(identities) != len(records) or len(records) != preview.total_files:
            raise ValueError("预览记录数量无效。")
    except (ValueError, ValidationError, TypeError, AttributeError):
        report.errors.append(
            ImportIssue("上传批次", "预览记录已改变或校验失效，请重新预览后再导入。")
        )
        return report

    try:
        existing = {
            (item.record.knowledge_id, item.record.version): item.content_hash
            for item in store.list_revisions()
        }
        records.sort(key=lambda item: (item.knowledge_id, item.version))
        report.revisions = store.save_many_drafts(records)
    except KnowledgeError as error:
        allowed_messages = {
            "同一知识ID及版本已存在不同内容，请递增版本",
            "同一知识ID不能变更所属知识库",
            "新增修订的版本必须大于已有最新版本",
        }
        message = str(error)
        if message not in allowed_messages:
            message = "知识记录存在冲突或不满足保存条件。"
        report.errors.append(ImportIssue("上传批次", f"整批导入失败：{message}"))
        return report
    except (ValueError, TypeError, OSError, sqlite3.Error):
        report.errors.append(ImportIssue("上传批次", "数据库写入失败，整批知识记录未写入。"))
        return report
    report.unchanged_count = sum(
        existing.get((item.record.knowledge_id, item.record.version)) == item.content_hash
        for item in report.revisions
    )
    report.imported_count = len(report.revisions) - report.unchanged_count
    return report
