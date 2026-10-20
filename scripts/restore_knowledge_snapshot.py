"""校验或恢复仓库内的本地知识库快照；已有数据库绝不覆盖。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "data/knowledge_snapshots/local-v1-20261020"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_summary(path: Path) -> dict:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("知识库完整性检查失败")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("知识库关联完整性检查失败")
        return {
            "schema_version": db.execute("PRAGMA user_version").fetchone()[0],
            "knowledge_ids": db.execute(
                "SELECT COUNT(DISTINCT knowledge_id) FROM revisions"
            ).fetchone()[0],
            "revisions": db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0],
            "audit_entries": db.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0],
            "libraries": db.execute("SELECT COUNT(*) FROM libraries").fetchone()[0],
            "by_library_status": db.execute(
                "SELECT library_id,status,COUNT(*) FROM revisions GROUP BY library_id,status "
                "ORDER BY library_id,status"
            ).fetchall(),
            "by_dataset_split": db.execute(
                "SELECT json_extract(record_json,'$.dataset_split'),COUNT(*) "
                "FROM revisions GROUP BY 1 ORDER BY 1"
            ).fetchall(),
        }


def restore(snapshot: Path, output: Path | None = None) -> dict:
    if output is not None and os.path.lexists(output):
        raise FileExistsError("目标数据库已存在，请使用新路径；不会覆盖现有知识库")
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    archive = snapshot / "knowledge.sqlite3.gz"
    if manifest["snapshot_format"] != 1 or sha256(archive) != manifest["archive_sha256"]:
        raise ValueError("快照压缩文件校验失败")
    expected_size = manifest["database_bytes"]
    if type(expected_size) is not int or not 0 < expected_size <= 512 * 1024 * 1024:
        raise ValueError("快照声明的大小无效")
    # 先在临时目录解压和验证，失败时不创建目标数据库。
    with tempfile.TemporaryDirectory(prefix="xiaoli-knowledge-") as temporary:
        database = Path(temporary) / "knowledge.sqlite3"
        remaining = expected_size
        with gzip.open(archive, "rb") as source, database.open("xb") as target:
            while chunk := source.read(min(1024 * 1024, remaining + 1)):
                if len(chunk) > remaining:
                    raise ValueError("快照解压大小超出声明")
                target.write(chunk)
                remaining -= len(chunk)
        if remaining or sha256(database) != manifest["database_sha256"]:
            raise ValueError("快照数据库校验失败")
        summary = database_summary(database)
        if json.loads(json.dumps(summary)) != manifest["summary"]:
            raise ValueError("快照条目数量或状态不匹配")
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            # x 模式也拒绝校验期间新出现的目标，不覆盖其他进程创建的数据库。
            with output.open("xb") as target:
                try:
                    with database.open("rb") as source:
                        shutil.copyfileobj(source, target)
                except BaseException:
                    target.close()
                    output.unlink()
                    raise
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", type=Path, default=ROOT / "data/knowledge.db")
    parser.add_argument("--check", action="store_true", help="仅解压校验，不恢复数据库")
    args = parser.parse_args()
    try:
        summary = restore(args.snapshot, None if args.check else args.output)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        parser.exit(1, f"快照处理失败：{error}\n")
    print(json.dumps({"checked": True, "restored": not args.check, "summary": summary},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
