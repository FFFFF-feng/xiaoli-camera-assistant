"""Build a tracked-record bundle; merge drafts with backup, never approve/publish."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sync_github_knowledge import canonical, plan_merge, read_rows

from camera_assistant.knowledge.importer import (
    SUPPORTED_SUFFIXES,
    RecordFileError,
    _load_yaml,
    _parse_markdown,
    parse_record_file,
)
from camera_assistant.knowledge.models import KnowledgeRecord
from camera_assistant.knowledge.store import KnowledgeStore

MAX_BUNDLE_BYTES = 96 * 1024 * 1024


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def is_record(path):
    text = path.read_text(encoding="utf-8-sig")
    try:
        if path.suffix.lower() == ".json":
            raw = json.loads(text)
        elif path.suffix.lower() == ".md":
            if not text.startswith("---"):
                return False
            raw = _parse_markdown(text)
        else:
            raw = _load_yaml(text)
    except (ValueError, TypeError):
        return "knowledge_id" in text
    return isinstance(raw, dict) and "knowledge_id" in raw


def build_bundle(root, output, *, tracked=None, commit=None, expected_digest=None):
    if tracked is None:
        tracked = subprocess.check_output(
            ["git", "ls-files", "-z", "data/knowledge_drafts"], cwd=root
        ).decode("utf-8").split("\0")
    incoming, invalid, excluded, sources, skipped = [], [], [], [], []
    for name in sorted(filter(None, tracked)):
        path = root / name
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("tracked_source_link_rejected")
        if not is_record(path):
            skipped.append(name)
            continue
        try:
            record = parse_record_file(path)
        except RecordFileError as error:
            invalid.append({"path": name, "error": error.message})
            continue
        if record.dataset_split != "reference":
            excluded.append({"path": name, "reason": "evaluation_not_production_knowledge"})
            continue
        incoming.append((name, record))
        sources.append({"path": name, "knowledge_id": record.knowledge_id,
                        "version": record.version, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    selected, plan = plan_merge(incoming, {})
    records = [item.model_dump(mode="json") for item in selected]
    if commit is None:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if expected_digest is not None and digest(records) != expected_digest:
        raise ValueError("repository_records_differ_from_reviewed_local_bundle")
    bundle = {"schema_version": 1, "repository": "FFFFF-feng/xiaoli-camera-assistant",
              "base_commit": commit, "records_sha256": digest(records), "records": records,
              "sources": sources}
    output.mkdir(parents=True, exist_ok=True)
    bundle_path = output / "repository-knowledge.json.gz"
    with bundle_path.open("xb") as stream:
        stream.write(gzip.compress(canonical(bundle).encode("utf-8"), mtime=0))
    report = {"bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
              "base_commit": commit, "tracked_reference_records": len(incoming),
              "bundle_records": len(records), "bundle_by_library": dict(Counter(r.library_id for r in selected)),
              "invalid_records": invalid, "excluded_evaluation": excluded,
              "non_record_documents_skipped": skipped, "deduplication": plan}
    write_json(output / "bundle-report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in {
        "invalid_records", "excluded_evaluation", "non_record_documents_skipped", "deduplication"
    }}, ensure_ascii=True))
    return report


def build_archive(archive, output, commit, expected_digest):
    # Extract only supported knowledge text, never upstream executable code or archives.
    with tempfile.TemporaryDirectory(prefix="knowledge-text-") as temporary:
        root = Path(temporary)
        tracked, size = [], 0
        with tarfile.open(archive, "r:gz") as source:
            for member in source:
                parts = PurePosixPath(member.name).parts
                if len(parts) < 4 or parts[1:3] != ("data", "knowledge_drafts"):
                    continue
                relative = PurePosixPath(*parts[1:])
                if relative.suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                if (not member.isfile() or ".." in parts or relative.is_absolute()
                        or member.size > 2 * 1024 * 1024):
                    raise ValueError("unsafe_archive_knowledge_member")
                size += member.size
                if size > 256 * 1024 * 1024 or len(tracked) >= 20000:
                    raise ValueError("archive_knowledge_limit_exceeded")
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as original, path.open("xb") as target:
                    target.write(original.read())
                tracked.append(relative.as_posix())
        return build_bundle(root, output, tracked=tracked, commit=commit,
                            expected_digest=expected_digest)


def load_bundle(path):
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError("compressed_bundle_too_large")
    with gzip.open(path, "rb") as stream:
        data = stream.read(MAX_BUNDLE_BYTES + 1)
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValueError("expanded_bundle_too_large")
    bundle = json.loads(data)
    if bundle.get("schema_version") != 1 or digest(bundle["records"]) != bundle["records_sha256"]:
        raise ValueError("bundle_content_checksum_mismatch")
    records = [KnowledgeRecord.model_validate(item) for item in bundle["records"]]
    if not records or len(records) > 20000 or any(r.dataset_split != "reference" for r in records):
        raise ValueError("bundle_reference_records_invalid")
    return bundle, records


def merge_bundle(bundle_path, database, report_dir, *, apply=False):
    bundle, records = load_bundle(bundle_path)
    before = read_rows(database)
    incoming = [(f"{r.knowledge_id}@v{r.version}", r) for r in records]
    selected, plan = plan_merge(incoming, before)
    report = {"apply": apply, "base_commit": bundle["base_commit"],
              "records_sha256": bundle["records_sha256"], "database": str(database.resolve()),
              "records_before": len(before), "merge_plan": plan}
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(report_dir / "plan.json", report)
    if not apply:
        return report
    backup = None
    if database.exists():
        backup = report_dir / "before-import.db"
        with (
            closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(backup)) as target,
        ):
            source.backup(target)
        backup.chmod(0o600)
    if read_rows(database) != before:
        raise ValueError("database_changed_since_plan")
    store = KnowledgeStore(database)
    # Recheck the snapshot while holding SQLite's write lock; the whole batch rolls back on error.
    with store._connection(write=True) as connection:
        locked_rows = {(row[0], row[1]): tuple(row)
                       for row in connection.execute("SELECT * FROM revisions")}
        if locked_rows != before:
            raise ValueError("database_changed_before_transaction")
        for record in selected:
            store._save_draft(connection, record)
    after = read_rows(database)
    keys = {(r.knowledge_id, r.version) for r in selected}
    preserved = all(after.get(key) == value for key, value in before.items())
    if not preserved or set(after) - set(before) != keys or any(after[k][4] != "draft" for k in keys):
        raise ValueError("post_import_preservation_check_failed")
    audits = len(store.audit_log())
    repeat, repeat_plan = plan_merge(incoming, after)
    if repeat:
        raise ValueError("repeat_import_would_add_records")
    store.save_many_drafts(repeat)
    if read_rows(database) != after or len(store.audit_log()) != audits:
        raise ValueError("repeat_import_changed_database")
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        counts = connection.execute(
            "SELECT library_id,status,count(*) FROM revisions GROUP BY library_id,status"
        ).fetchall()
    if integrity != "ok":
        raise ValueError("database_integrity_failed")
    # Review checklist is metadata only; source permissions and authors are never changed.
    review = [{"knowledge_id": r.knowledge_id, "version": r.version, "library_id": r.library_id,
               "title": r.title, "source": r.source.model_dump(), "author": r.author,
               "status": "draft", "checks_required": ["source_rights", "fact_check", "independent_review"]}
              for r in selected]
    write_json(report_dir / "review-checklist.json", review)
    report.update({"backup": str(backup) if backup else None, "imported_count": len(selected),
                   "records_after": len(after), "old_rows_preserved": preserved,
                   "new_records_all_draft": True, "integrity": integrity,
                   "repeat_import_added": len(repeat), "repeat_conflicts": repeat_plan["conflict_count"],
                   "counts": counts, "runtime_mode_unchanged": True})
    write_json(report_dir / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    build = operations.add_parser("build")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--archive", type=Path)
    build.add_argument("--commit")
    build.add_argument("--expected-digest")
    importing = operations.add_parser("import")
    importing.add_argument("--bundle", type=Path, required=True)
    importing.add_argument("--db", type=Path, required=True)
    importing.add_argument("--report-dir", type=Path, required=True)
    importing.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.operation == "build":
        if args.archive:
            if not args.commit or not args.expected_digest:
                parser.error("archive build requires --commit and --expected-digest")
            build_archive(args.archive, args.output, args.commit, args.expected_digest)
        else:
            build_bundle(ROOT, args.output)
    else:
        report = merge_bundle(args.bundle, args.db, args.report_dir, apply=args.apply)
        summary = {k: v for k, v in report.items() if k != "merge_plan"}
        summary["merge_counts"] = {k: v for k, v in report["merge_plan"].items()
                                   if k not in {"skipped", "conflicts", "related_titles"}}
        summary["completed_at"] = datetime.now(UTC).isoformat()
        print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    main()
