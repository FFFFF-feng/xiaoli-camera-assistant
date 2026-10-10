"""SQLite知识库与审核工作流，不自动采集资料或保存上传图片。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from camera_assistant.knowledge.models import (
    DEFAULT_LIBRARIES,
    KnowledgeRecord,
    LibraryDefinition,
    LibraryId,
    ReviewStatus,
    Revision,
)

DATABASE_SCHEMA_VERSION = 1


class KnowledgeError(ValueError):
    """知识记录或审核状态不满足操作条件。"""


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(record: KnowledgeRecord) -> str:
    return json.dumps(
        record.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class KnowledgeStore:
    """文件型存储：每次操作单独连接，写入使用BEGIN IMMEDIATE事务。"""

    def __init__(self, db_path: str | Path):
        if str(db_path) == ":memory:":
            raise KnowledgeError("KnowledgeStore需要文件型数据库，不支持:memory:")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.db_path, timeout=30)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                if write:
                    connection.execute("BEGIN IMMEDIATE")
                yield connection
                if write:
                    connection.commit()
            except BaseException:
                if write:
                    connection.rollback()
                raise

    def _initialize(self) -> None:
        with self._connection(write=True) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, DATABASE_SCHEMA_VERSION):
                raise KnowledgeError(f"不支持的知识库数据库版本：{version}")
            # 未标注版本的现有数据库不能被当成新库覆盖。
            if version == 0:
                existing = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if existing:
                    raise KnowledgeError("现有数据库未标注知识库版本，请使用独立的新数据库文件")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS libraries (library_id TEXT PRIMARY KEY, "
                "name TEXT NOT NULL, description TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS revisions (knowledge_id TEXT NOT NULL, "
                "version INTEGER NOT NULL, library_id TEXT NOT NULL REFERENCES libraries(library_id), "
                "record_json TEXT NOT NULL, status TEXT NOT NULL, content_hash TEXT NOT NULL, "
                "created_at TEXT NOT NULL, reviewer TEXT, reviewed_at TEXT, review_note TEXT, "
                "PRIMARY KEY (knowledge_id, version))"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS one_published_revision "
                "ON revisions(knowledge_id) WHERE status='published'"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS audit_entries (audit_id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "knowledge_id TEXT NOT NULL, version INTEGER NOT NULL, action TEXT NOT NULL, "
                "actor TEXT, occurred_at TEXT NOT NULL, details_json TEXT NOT NULL)"
            )
            for library in DEFAULT_LIBRARIES:
                connection.execute(
                    "INSERT OR IGNORE INTO libraries VALUES (?, ?, ?)",
                    (library.library_id, library.name, library.description),
                )
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")

    @staticmethod
    def _revision(row: sqlite3.Row) -> Revision:
        return Revision(
            record=KnowledgeRecord.model_validate_json(row["record_json"]),
            status=row["status"],
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            reviewer=row["reviewer"],
            reviewed_at=row["reviewed_at"],
            review_note=row["review_note"],
        )

    @staticmethod
    def _get(
        connection: sqlite3.Connection,
        knowledge_id: str,
        version: int | None,
    ) -> sqlite3.Row | None:
        if version is None:
            return connection.execute(
                "SELECT * FROM revisions WHERE knowledge_id=? ORDER BY version DESC LIMIT 1",
                (knowledge_id,),
            ).fetchone()
        return connection.execute(
            "SELECT * FROM revisions WHERE knowledge_id=? AND version=?",
            (knowledge_id, version),
        ).fetchone()

    @classmethod
    def _require(
        cls,
        connection: sqlite3.Connection,
        knowledge_id: str,
        version: int | None,
    ) -> sqlite3.Row:
        row = cls._get(connection, knowledge_id, version)
        if row is None:
            raise KnowledgeError(f"知识记录不存在：{knowledge_id}，版本：{version or '最新'}")
        return row

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        knowledge_id: str,
        version: int,
        action: str,
        *,
        actor: str | None = None,
        details: dict | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO audit_entries "
            "(knowledge_id, version, action, actor, occurred_at, details_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                knowledge_id,
                version,
                action,
                actor,
                _timestamp(),
                json.dumps(details or {}, ensure_ascii=False, allow_nan=False),
            ),
        )

    def _save_draft(self, connection: sqlite3.Connection, record: KnowledgeRecord) -> Revision:
        serialized = _canonical(record)
        content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        existing = self._get(connection, record.knowledge_id, record.version)
        if existing is not None:
            if existing["content_hash"] == content_hash:
                return self._revision(existing)
            raise KnowledgeError("同一知识ID及版本已存在不同内容，请递增版本")
        latest = self._get(connection, record.knowledge_id, None)
        if latest is not None:
            if latest["library_id"] != record.library_id:
                raise KnowledgeError("同一知识ID不能变更所属知识库")
            if record.version <= latest["version"]:
                raise KnowledgeError("新增修订的版本必须大于已有最新版本")
        connection.execute(
            "INSERT INTO revisions (knowledge_id, version, library_id, record_json, status, "
            "content_hash, created_at) VALUES (?, ?, ?, ?, 'draft', ?, ?)",
            (
                record.knowledge_id,
                record.version,
                record.library_id,
                serialized,
                content_hash,
                _timestamp(),
            ),
        )
        self._audit(
            connection, record.knowledge_id, record.version, "save_draft", actor=record.author
        )
        return self._revision(self._require(connection, record.knowledge_id, record.version))

    def save_draft(self, record: KnowledgeRecord) -> Revision:
        return self.save_many_drafts([record])[0]

    def save_many_drafts(self, records: Iterable[KnowledgeRecord]) -> list[Revision]:
        # 重新校验可变Pydantic对象，全部校验完成后才进入数据库事务。
        validated = [KnowledgeRecord.model_validate(item.model_dump()) for item in records]
        with self._connection(write=True) as connection:
            return [self._save_draft(connection, record) for record in validated]

    def list_libraries(self) -> list[LibraryDefinition]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM libraries ORDER BY rowid").fetchall()
        return [LibraryDefinition(**dict(row)) for row in rows]

    def library_counts(self) -> dict[str, dict[str, int]]:
        counts = {
            library.library_id: {status: 0 for status in get_args(ReviewStatus)}
            for library in DEFAULT_LIBRARIES
        }
        with self._connection() as connection:
            for row in connection.execute(
                "SELECT library_id, status, COUNT(*) AS total FROM revisions GROUP BY library_id, status"
            ):
                counts[row["library_id"]][row["status"]] = row["total"]
        return counts

    def list_revisions(
        self,
        library_id: LibraryId | None = None,
        status: ReviewStatus | None = None,
    ) -> list[Revision]:
        if library_id is not None and library_id not in get_args(LibraryId):
            raise KnowledgeError(f"未知知识库：{library_id}")
        if status is not None and status not in get_args(ReviewStatus):
            raise KnowledgeError(f"未知审核状态：{status}")
        clauses, arguments = [], []
        if library_id is not None:
            clauses.append("library_id=?")
            arguments.append(library_id)
        if status is not None:
            clauses.append("status=?")
            arguments.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM revisions" + where + " ORDER BY knowledge_id, version",
                arguments,
            ).fetchall()
        return [self._revision(row) for row in rows]

    def get_revision(self, knowledge_id: str, version: int | None = None) -> Revision | None:
        with self._connection() as connection:
            row = self._get(connection, knowledge_id, version)
        return self._revision(row) if row is not None else None

    def submit(self, knowledge_id: str, version: int | None = None) -> Revision:
        with self._connection(write=True) as connection:
            row = self._require(connection, knowledge_id, version)
            if row["status"] != "draft":
                raise KnowledgeError("仅草稿可以提交审核")
            connection.execute(
                "UPDATE revisions SET status='pending_review' WHERE knowledge_id=? AND version=?",
                (knowledge_id, row["version"]),
            )
            self._audit(connection, knowledge_id, row["version"], "submit")
            return self._revision(self._require(connection, knowledge_id, row["version"]))

    def approve(
        self,
        knowledge_id: str,
        reviewer: str,
        version: int | None = None,
        note: str = "",
    ) -> Revision:
        reviewer = reviewer.strip()
        if not reviewer or len(reviewer) > 128:
            raise KnowledgeError("审核人必须非空且不超过128个字符")
        with self._connection(write=True) as connection:
            row = self._require(connection, knowledge_id, version)
            record = self._revision(row).record
            if row["status"] != "pending_review":
                raise KnowledgeError("仅待审核记录可以批准")
            if reviewer.casefold() == record.author.casefold():
                raise KnowledgeError("作者不能审核自己的知识记录")
            connection.execute(
                "UPDATE revisions SET status='approved', reviewer=?, reviewed_at=?, review_note=? "
                "WHERE knowledge_id=? AND version=?",
                (reviewer, _timestamp(), note, knowledge_id, row["version"]),
            )
            self._audit(connection, knowledge_id, row["version"], "approve", actor=reviewer)
            return self._revision(self._require(connection, knowledge_id, row["version"]))

    def publish(self, knowledge_id: str, version: int | None = None) -> Revision:
        with self._connection(write=True) as connection:
            row = self._require(connection, knowledge_id, version)
            record = self._revision(row).record
            if row["status"] != "approved":
                raise KnowledgeError("仅审核通过的知识可以发布")
            if not record.source.retrieval_allowed:
                raise KnowledgeError("资料未获得检索使用权限，不能发布")
            if record.dataset_split != "reference":
                raise KnowledgeError("评测记录禁止进入发布检索区")
            previous_max = connection.execute(
                "SELECT MAX(version) FROM revisions WHERE knowledge_id=? "
                "AND status IN ('published', 'retired')",
                (knowledge_id,),
            ).fetchone()[0]
            if previous_max is not None and record.version < previous_max:
                raise KnowledgeError("不能发布比历史发布版本更旧的修订")
            previous = connection.execute(
                "SELECT version FROM revisions WHERE knowledge_id=? AND status='published'",
                (knowledge_id,),
            ).fetchall()
            for old in previous:
                connection.execute(
                    "UPDATE revisions SET status='retired' WHERE knowledge_id=? AND version=?",
                    (knowledge_id, old["version"]),
                )
                self._audit(
                    connection,
                    knowledge_id,
                    old["version"],
                    "retire_superseded",
                    details={"replacement_version": record.version},
                )
            connection.execute(
                "UPDATE revisions SET status='published' WHERE knowledge_id=? AND version=?",
                (knowledge_id, row["version"]),
            )
            self._audit(connection, knowledge_id, row["version"], "publish", actor=row["reviewer"])
            return self._revision(self._require(connection, knowledge_id, row["version"]))

    def reject(
        self,
        knowledge_id: str,
        reviewer: str,
        version: int | None = None,
        note: str = "",
    ) -> Revision:
        """退回审核；保留原修订，修复内容需另存递增版本的草稿。"""
        reviewer = reviewer.strip()
        note = note.strip()
        if not reviewer or len(reviewer) > 128:
            raise KnowledgeError("审核人必须非空且不超过128个字符")
        if not note:
            raise KnowledgeError("退回原因不能为空")
        with self._connection(write=True) as connection:
            row = self._require(connection, knowledge_id, version)
            record = self._revision(row).record
            if row["status"] != "pending_review":
                raise KnowledgeError("仅待审核记录可以退回")
            if reviewer.casefold() == record.author.casefold():
                raise KnowledgeError("作者不能审核自己的知识记录")
            connection.execute(
                "UPDATE revisions SET status='needs_revision', reviewer=?, reviewed_at=?, review_note=? "
                "WHERE knowledge_id=? AND version=?",
                (reviewer, _timestamp(), note, knowledge_id, row["version"]),
            )
            self._audit(
                connection,
                knowledge_id,
                row["version"],
                "reject",
                actor=reviewer,
                details={"note": note},
            )
            return self._revision(self._require(connection, knowledge_id, row["version"]))

    def retire(self, knowledge_id: str, version: int | None = None) -> Revision:
        with self._connection(write=True) as connection:
            row = self._require(connection, knowledge_id, version)
            if row["status"] != "published":
                raise KnowledgeError("仅已发布记录可以停用")
            connection.execute(
                "UPDATE revisions SET status='retired' WHERE knowledge_id=? AND version=?",
                (knowledge_id, row["version"]),
            )
            self._audit(connection, knowledge_id, row["version"], "retire")
            return self._revision(self._require(connection, knowledge_id, row["version"]))

    def audit_log(self) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM audit_entries ORDER BY audit_id").fetchall()
        return [
            {
                "audit_id": row["audit_id"],
                "knowledge_id": row["knowledge_id"],
                "version": row["version"],
                "action": row["action"],
                "actor": row["actor"],
                "occurred_at": row["occurred_at"],
                "details": json.loads(row["details_json"]),
            }
            for row in rows
        ]
