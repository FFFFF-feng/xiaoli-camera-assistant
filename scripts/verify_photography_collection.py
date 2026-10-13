"""Validate the versioned photography drafts without writing the project database."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
COLLECTION = PROJECT / "data/knowledge_drafts/photography-20261013"
MAIN_DB = PROJECT / "data/knowledge.db"
sys.dont_write_bytecode = True
sys.path.insert(0, str(PROJECT / "src"))

from camera_assistant.knowledge.importer import import_path, parse_record_file
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.knowledge.uploads import (
    MAX_BATCH_FILES,
    UploadedRecordFile,
    commit_preview,
    preview_uploads,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main_snapshot() -> dict | None:
    if not MAIN_DB.exists():
        return None
    # KnowledgeStore initializes tables; never use it against the main DB here.
    with sqlite3.connect(MAIN_DB.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT knowledge_id,version,record_json,status,content_hash "
            "FROM revisions ORDER BY knowledge_id,version"
        ).fetchall()
        audits = conn.execute("SELECT * FROM audit_entries ORDER BY audit_id").fetchall()
    return {
        "file_sha256": digest(MAIN_DB),
        "logical_sha256": hashlib.sha256(
            json.dumps([rows, audits], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "revisions": len(rows),
        "audits": len(audits),
        "statuses": dict(Counter(row[3] for row in rows)),
    }


def main() -> None:
    before = main_snapshot()
    cards_dir = COLLECTION / "upload_cards"
    paths = sorted(cards_dir.glob("*.json"))
    records = [parse_record_file(path) for path in paths]
    assert len(records) == 121
    assert len({(r.knowledge_id, r.version) for r in records}) == 121
    assert all(r.schema_version == 1 and not r.source.retrieval_allowed for r in records)
    manifest = json.loads((COLLECTION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cards"] == [
        {
            "file": path.relative_to(COLLECTION).as_posix(),
            "sha256": digest(path),
            "knowledge_id": record.knowledge_id,
            "version": record.version,
            "library_id": record.library_id,
            "author": record.author,
        }
        for path, record in zip(paths, records, strict=True)
    ]
    environment = dict(
        os.environ,
        PYTHONPATH=str(PROJECT / "src"),
        PYTHONIOENCODING="utf-8",
        PYTHONDONTWRITEBYTECODE="1",
    )
    process = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "camera_assistant.knowledge",
            "import",
            str(cards_dir),
            "--dry-run",
        ],
        cwd=PROJECT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert process.returncode == 0, process.stderr
    dry_run = json.loads(process.stdout)
    assert dry_run["data"]["validated_count"] == 121
    assert dry_run["data"]["imported_count"] == 0
    assert dry_run["data"]["dry_run"]

    # Process-local workspace temp directory; no configuration file is changed.
    temp_parent = PROJECT / "tmp/photography-collection-verification"
    temp_parent.mkdir(parents=True, exist_ok=True)
    original_tempdir = tempfile.tempdir
    tempfile.tempdir = str(temp_parent)
    try:
        with tempfile.TemporaryDirectory(prefix="isolated-") as directory:
            temporary_path = Path(directory)
            database = temporary_path / "knowledge.db"
            assert database.resolve() != MAIN_DB.resolve()
            store = KnowledgeStore(database)
            assert store.list_revisions() == []
            batch_results = []
            for offset in range(0, len(paths), MAX_BATCH_FILES):
                batch = paths[offset : offset + MAX_BATCH_FILES]
                uploaded = [UploadedRecordFile(p.name, p.read_bytes()) for p in batch]
                preview = preview_uploads(uploaded)
                assert preview.success and len(preview.records) == len(batch)
                committed = commit_preview(store, preview)
                assert committed.success and committed.imported_count == len(batch)
                assert all(item.status == "draft" for item in committed.revisions)
                audit_count = len(store.audit_log())
                repeated = commit_preview(store, preview_uploads(uploaded))
                assert repeated.success and repeated.imported_count == 0
                assert repeated.unchanged_count == len(batch)
                assert len(store.audit_log()) == audit_count
                batch_results.append(
                    {
                        "batch": len(batch_results) + 1,
                        "files": len(batch),
                        "preview": True,
                        "drafts_written": committed.imported_count,
                        "repeat_unchanged": repeated.unchanged_count,
                    }
                )
            revisions = store.list_revisions()
            assert len(revisions) == 121
            assert all(r.status == "draft" for r in revisions)
            assert {
                r.record.knowledge_id: r.record.model_dump() for r in revisions
            } == {r.knowledge_id: r.model_dump() for r in records}
            repeated_directory = import_path(store, cards_dir)
            assert repeated_directory.success
            assert repeated_directory.imported_count == 0
            assert repeated_directory.unchanged_count == 121
            assert len(store.audit_log()) == 121
            retriever = ManagedKnowledgeRetriever(store)
            for record in records:
                conditions = {
                    key: value[0] if isinstance(value, list) and value else value
                    for key, value in record.conditions.items()
                }
                assert retriever.search(
                    record.title, libraries=[record.library_id], conditions=conditions
                ) == []
                assert retriever.query_structured(
                    record.library_id, conditions=conditions
                ) == []
            assert store.list_revisions(status="published") == []
        assert not temporary_path.exists()
    finally:
        tempfile.tempdir = original_tempdir
        temp_parent.rmdir()  # Only the confirmed empty directory.

    after = main_snapshot()
    assert before == after
    report = {
        "date": "2026-10-13",
        "passed": True,
        "validated_cards": 121,
        "library_counts": dict(Counter(r.library_id for r in records)),
        "schema_version": 1,
        "retrieval_allowed_true_count": 0,
        "card_hashes_match_manifest": True,
        "dry_run": dry_run,
        "dry_run_stderr": process.stderr,
        "upload_batches": batch_results,
        "isolated_database": {
            "drafts": 121,
            "published": 0,
            "repeat_directory_imported": 0,
            "repeat_directory_unchanged": 121,
            "keyword_isolation_probes": 121,
            "structured_isolation_probes": 121,
            "all_probe_results_empty": True,
            "temporary_database_removed": True,
        },
        "main_database_before": before,
        "main_database_after": after,
        "main_database_unchanged": before == after,
        "limits": [
            "dry-run validates files and within-batch identities, not main DB version conflicts",
            "isolation checks only the combined draft and retrieval_allowed=false state",
            "historical source checks were not repeated for this repository upload",
            "no browser UI upload, physical device tests, independent factual review, rights verification or publication",
            "source collections with media or local image paths are included as text only; media is not included",
        ],
    }
    report_path = COLLECTION / "reports/repository-upload-validation.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"passed": True, "cards": 121, "main_database_unchanged": True}))


if __name__ == "__main__":
    main()
