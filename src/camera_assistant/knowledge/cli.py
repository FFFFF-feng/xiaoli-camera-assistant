from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from camera_assistant.knowledge.importer import import_path
from camera_assistant.knowledge.store import KnowledgeStore

LIBRARY_IDS = ("scene", "composition", "style", "technique", "equipment", "case")


class _UsageError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(description="小栗多知识库管理（离线，无需模型 API）")
    parser.add_argument("--db", type=Path, help="SQLite 数据库路径，默认读取应用配置")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    commands.add_parser("init", help="创建空数据库并注册六类知识库")
    commands.add_parser("schema", help="输出知识记录 JSON Schema，不访问数据库")
    commands.add_parser("libraries", help="列出已注册知识库")
    commands.add_parser("stats", help="查看六类知识库的审核状态数量")
    importing = commands.add_parser("import", help="导入 JSON／YAML／Markdown 为草稿")
    importing.add_argument("path", type=Path)
    importing.add_argument(
        "--dry-run", action="store_true", help="仅校验格式和同批冲突，不访问或创建数据库"
    )
    listing = commands.add_parser("list", help="列出知识修订")
    listing.add_argument("--library", choices=LIBRARY_IDS)
    listing.add_argument("--status")
    for command in ("show", "submit", "approve", "reject", "publish", "retire"):
        operation = commands.add_parser(command, help=f"{command} 指定知识修订")
        operation.add_argument("knowledge_id")
        operation.add_argument("--version", type=int)
        if command in {"approve", "reject"}:
            operation.add_argument("--reviewer", required=True)
            operation.add_argument("--note", default="")
    commands.add_parser("audit", help="查看审核与发布操作日志")
    search = commands.add_parser("search", help="检索已发布且允许使用的参考资料")
    search.add_argument("query")
    search.add_argument("--library", choices=LIBRARY_IDS, action="append")
    search.add_argument("--top-k", type=int, default=4)
    search.add_argument("--conditions", default="{}", help="场景等适用条件的 JSON 对象")
    structured = commands.add_parser("structured", help="精确查询已发布结构化 payload")
    structured.add_argument("--library", choices=LIBRARY_IDS, required=True)
    structured.add_argument("--filters", default="{}", help="payload 点路径等值过滤 JSON 对象")
    structured.add_argument("--conditions", default="{}", help="场景等适用条件的 JSON 对象")
    return parser


def _db_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    from camera_assistant.config import PROJECT_ROOT, Settings

    return Settings.from_env().knowledge_db_path or PROJECT_ROOT / "data" / "knowledge.db"


def _json_object(value: str, field: str) -> dict[str, Any]:
    from camera_assistant.knowledge.importer import _reject_constant, _unique_json_mapping

    try:
        parsed = json.loads(
            value, object_pairs_hook=_unique_json_mapping, parse_constant=_reject_constant
        )
    except (ValueError, RecursionError):
        raise _UsageError(f"{field} 必须是有效且无重复字段的 JSON 对象。") from None
    if not isinstance(parsed, dict):
        raise _UsageError(f"{field} 必须是 JSON 对象。")
    return parsed


def _serialize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    return value


def _output(data: dict[str, Any]) -> None:
    print(json.dumps(_serialize(data), ensure_ascii=False, indent=2, allow_nan=False))


def main(argv: Sequence[str] | None = None) -> int:
    """JSON 输出；0 成功、1 操作失败、2 输入或使用方式错误。"""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    command = ""
    try:
        args = build_parser().parse_args(argv)
        command = args.command
        if command == "schema":
            from camera_assistant.knowledge.models import KnowledgeRecord

            _output({"ok": True, "command": command, "data": KnowledgeRecord.model_json_schema()})
            return 0
        if command == "import" and args.dry_run:
            report = import_path(None, args.path, dry_run=True)
            _output({"ok": report.success, "command": command, "data": report.to_dict()})
            return 0 if report.success else 1
        database = _db_path(args.db)
        if command not in {"init", "import"} and not database.is_file():
            raise _UsageError("数据库不存在，请先运行 init 或 import；只读命令不会创建数据库。")
        store = KnowledgeStore(database)
        if command == "init":
            data = {"database": str(database), "libraries": store.list_libraries()}
        elif command == "libraries":
            data = store.list_libraries()
        elif command == "stats":
            data = store.library_counts()
        elif command == "import":
            report = import_path(store, args.path)
            _output({"ok": report.success, "command": command, "data": report.to_dict()})
            return 0 if report.success else 1
        elif command == "list":
            data = store.list_revisions(library_id=args.library, status=args.status)
        elif command == "show":
            data = store.get_revision(args.knowledge_id, version=args.version)
            if data is None:
                raise ValueError("知识修订不存在。")
        elif command in {"approve", "reject"}:
            data = getattr(store, command)(
                args.knowledge_id, reviewer=args.reviewer, version=args.version, note=args.note
            )
        elif command in {"submit", "publish", "retire"}:
            data = getattr(store, command)(args.knowledge_id, version=args.version)
        elif command == "audit":
            data = store.audit_log()
        else:
            from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever

            retriever = ManagedKnowledgeRetriever(store)
            if command == "search":
                data = retriever.search(
                    args.query,
                    top_k=args.top_k,
                    libraries=args.library,
                    conditions=_json_object(args.conditions, "conditions"),
                )
            else:
                data = retriever.query_structured(
                    args.library,
                    filters=_json_object(args.filters, "filters"),
                    conditions=_json_object(args.conditions, "conditions"),
                )
        _output({"ok": True, "command": command, "data": data})
        return 0
    except _UsageError as error:
        _output({"ok": False, "command": command, "error": str(error)})
        return 2
    except (ValueError, KeyError, OSError) as error:
        _output({"ok": False, "command": command, "error": str(error)})
        return 1
    except sqlite3.Error:
        _output({"ok": False, "command": command, "error": "数据库读写失败，请检查文件和权限。"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
