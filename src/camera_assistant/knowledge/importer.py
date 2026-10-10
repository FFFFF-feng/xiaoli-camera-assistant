from __future__ import annotations

import json
import math
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError
from yaml.tokens import AliasToken

from camera_assistant.knowledge.models import KnowledgeRecord

if TYPE_CHECKING:
    from camera_assistant.knowledge.models import Revision
    from camera_assistant.knowledge.store import KnowledgeStore

MAX_RECORD_BYTES = 2 * 1024 * 1024
SUPPORTED_SUFFIXES = frozenset({".json", ".yaml", ".yml", ".md"})


def _is_link(path: Path) -> bool:
    # Python 3.12+ 可识别 Windows Junction；旧版本保留普通符号链接检查。
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (callable(is_junction) and is_junction())


class RecordFileError(ValueError):
    """可展示的文件错误，不包含原始资料正文或字段值。"""

    def __init__(self, filename: str, message: str) -> None:
        self.filename = filename
        self.message = message
        super().__init__(f"{filename}: {message}")


class _DuplicateKeyError(ValueError):
    pass


class _UniqueSafeLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader: _UniqueSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise TypeError("YAML 对象的字段名必须是字符串。")
        if key in mapping:
            raise _DuplicateKeyError("YAML 不允许重复字段。")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


def _unique_json_mapping(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key, value in pairs:
        if key in mapping:
            raise _DuplicateKeyError("JSON 不允许重复字段。")
        mapping[key] = value
    return mapping


def _reject_constant(value: str) -> None:
    raise ValueError("JSON 不允许 NaN 或 Infinity。")


def _load_yaml(text: str) -> Any:
    # 禁止别名，包括循环与指数展开；资料需展开为普通 JSON 兼容字段。
    if any(isinstance(token, AliasToken) for token in yaml.scan(text)):
        raise ValueError("YAML 不支持别名引用，请展开为普通字段。")
    return yaml.load(text, Loader=_UniqueSafeLoader)


def _parse_markdown(text: str) -> dict[str, Any]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("Markdown 必须以 YAML 前置元数据（---）开头。")
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        raise ValueError("Markdown 前置元数据缺少结束分隔符。")
    metadata = _load_yaml("".join(lines[1:end]))
    if not isinstance(metadata, dict):
        raise TypeError("前置元数据必须是一个对象。")
    if "content" in metadata:
        raise ValueError("Markdown 的 content 由正文生成，不要在前置元数据中重复填写。")
    metadata["content"] = "".join(lines[end + 1 :]).strip()
    return metadata


def _validate_json_shape(value: Any) -> None:
    """限制结构深度和节点量，拒绝日期等非 JSON 类型以及非有限浮点数。"""
    pending: list[tuple[Any, int]] = [(value, 0)]
    seen = 0
    while pending:
        item, depth = pending.pop()
        seen += 1
        if depth > 64 or seen > 100_000:
            raise ValueError("资料结构过深或过大，请拆分知识记录。")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("对象的字段名必须是字符串。")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError("资料包含非 JSON 类型，请将日期等信息填写为字符串。")
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("数值必须是有限数值。")


def _validation_message(error: ValidationError) -> str:
    details = []
    for item in error.errors(include_url=False, include_context=False, include_input=False)[:8]:
        location = ".".join(str(part)[:64] for part in item["loc"][:6]) or "记录"
        reason = "未知字段" if item["type"] == "extra_forbidden" else item["type"]
        details.append(f"{location}：{reason}")
    return "字段校验失败（" + "；".join(details) + "）。"


def parse_record_file(path: Path) -> KnowledgeRecord:
    """读取单条 UTF-8 知识记录；不支持 PDF、图片或未经审核的状态字段。"""
    path = Path(path)
    filename = path.name
    if _is_link(path):
        raise RecordFileError(filename, "不读取符号链接或 Junction。")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise RecordFileError(filename, "仅支持 .json、.yaml、.yml、.md。")
    try:
        if not path.is_file():
            raise RecordFileError(filename, "文件不存在或不是普通文件。")
        if path.stat().st_size > MAX_RECORD_BYTES:
            raise RecordFileError(filename, "单条记录不能超过 2 MiB。")
        with path.open("rb") as stream:
            data = stream.read(MAX_RECORD_BYTES + 1)
        if len(data) > MAX_RECORD_BYTES:
            raise RecordFileError(filename, "单条记录不能超过 2 MiB。")
        text = data.decode("utf-8-sig")
        if path.suffix.lower() == ".json":
            raw = json.loads(
                text, object_pairs_hook=_unique_json_mapping, parse_constant=_reject_constant
            )
        elif path.suffix.lower() == ".md":
            raw = _parse_markdown(text)
        else:
            raw = _load_yaml(text)
        if not isinstance(raw, dict):
            raise TypeError("知识记录顶层必须是一个对象。")
        _validate_json_shape(raw)
        return KnowledgeRecord.model_validate(raw)
    except RecordFileError:
        raise
    except UnicodeDecodeError:
        raise RecordFileError(filename, "文件必须使用 UTF-8 编码（可带 BOM）。") from None
    except json.JSONDecodeError as error:
        raise RecordFileError(
            filename, f"JSON 格式错误，位于第 {error.lineno} 行、第 {error.colno} 列。"
        ) from None
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        suffix = f"，位于第 {mark.line + 1} 行、第 {mark.column + 1} 列" if mark else ""
        raise RecordFileError(filename, f"YAML 格式错误{suffix}。") from None
    except ValidationError as error:
        raise RecordFileError(filename, _validation_message(error)) from None
    except RecursionError:
        raise RecordFileError(filename, "资料结构过深，请拆分知识记录。") from None
    except OSError:
        raise RecordFileError(filename, "无法读取文件，请检查文件权限与路径。") from None
    except (ValueError, TypeError) as error:
        # 本模块产生的这些错误均为固定提示，不附带用户提供的原始字段值。
        raise RecordFileError(filename, str(error)) from None


@dataclass(frozen=True)
class ImportIssue:
    file: str
    message: str


@dataclass
class ImportReport:
    total_files: int = 0
    validated_count: int = 0
    imported_count: int = 0
    unchanged_count: int = 0
    dry_run: bool = False
    validated_only: bool = False
    skipped_files: list[str] = field(default_factory=list)
    errors: list[ImportIssue] = field(default_factory=list)
    revisions: list[Revision] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "total_files": self.total_files,
            "validated_count": self.validated_count,
            "imported_count": self.imported_count,
            "unchanged_count": self.unchanged_count,
            "dry_run": self.dry_run,
            "validated_only": self.validated_only,
            "skipped_files": self.skipped_files,
            "errors": [{"file": item.file, "message": item.message} for item in self.errors],
            "revisions": [
                {
                    "knowledge_id": item.record.knowledge_id,
                    "library_id": item.record.library_id,
                    "version": item.record.version,
                    "status": item.status,
                    "content_hash": item.content_hash,
                }
                for item in self.revisions
            ],
        }


def _collect_files(path: Path, report: ImportReport) -> list[Path]:
    if _is_link(path):
        report.errors.append(ImportIssue(path.name, "不读取符号链接或 Junction。"))
        return []
    if path.is_file():
        return [path]
    if not path.is_dir():
        report.errors.append(ImportIssue(path.name, "输入路径不存在或不是文件／目录。"))
        return []

    files: list[Path] = []

    def walk_error(error: OSError) -> None:
        filename = Path(error.filename).name if error.filename else path.name
        report.errors.append(ImportIssue(filename, "无法读取目录，请检查权限。"))

    for directory, subdirs, names in os.walk(path, followlinks=False, onerror=walk_error):
        root = Path(directory)
        report.skipped_files.extend(
            str((root / name).relative_to(path)) + "/"
            for name in sorted(subdirs)
            if _is_link(root / name)
        )
        subdirs[:] = sorted(name for name in subdirs if not _is_link(root / name))
        for name in sorted(names):
            candidate = root / name
            if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if _is_link(candidate):
                report.skipped_files.append(str(candidate.relative_to(path)))
                continue
            files.append(candidate)
    return sorted(files, key=lambda item: str(item.relative_to(path)))


def import_path(store: KnowledgeStore | None, path: Path, dry_run: bool = False) -> ImportReport:
    """先校验整批再事务写入草稿；dry-run 只检查格式与同批冲突，不检查数据库。"""
    path = Path(path)
    report = ImportReport(dry_run=dry_run, validated_only=dry_run)
    files = _collect_files(path, report)
    report.total_files = len(files)
    if not files and not report.errors:
        report.errors.append(ImportIssue(path.name, "没有可导入的知识记录文件。"))
    records: list[KnowledgeRecord] = []
    identities: set[tuple[str, int]] = set()
    for filename in files:
        try:
            record = parse_record_file(filename)
        except RecordFileError as error:
            report.errors.append(ImportIssue(error.filename, error.message))
            continue
        identity = (record.knowledge_id, record.version)
        if identity in identities:
            report.errors.append(
                ImportIssue(filename.name, "同批存在重复 knowledge_id／version，请保留一个文件。")
            )
            continue
        identities.add(identity)
        records.append(record)
        report.validated_count += 1
    if report.errors or dry_run:
        return report
    if store is None:
        report.errors.append(ImportIssue(path.name, "正常导入需要知识库存储实例。"))
        return report

    try:
        existing = {
            (item.record.knowledge_id, item.record.version): item.content_hash
            for item in store.list_revisions()
        }
        # 允许目录中同时提供同一知识的多个递增版本，不依赖文件名排序。
        records.sort(key=lambda item: (item.knowledge_id, item.version))
        report.revisions = store.save_many_drafts(records)
    except (ValueError, OSError) as error:
        report.errors.append(ImportIssue(path.name, f"整批导入失败：{error}"))
        return report
    except sqlite3.Error:
        report.errors.append(ImportIssue(path.name, "数据库写入失败，整批知识记录未写入。"))
        return report
    report.unchanged_count = sum(
        existing.get((item.record.knowledge_id, item.record.version)) == item.content_hash
        for item in report.revisions
    )
    report.imported_count = len(report.revisions) - report.unchanged_count
    return report
