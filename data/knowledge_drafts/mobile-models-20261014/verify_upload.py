"""Verify draft files with current project code; write only isolated temporary DBs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    project = (args.project_root or root.parents[2]).resolve()
    assert (project / "src/camera_assistant/knowledge/models.py").is_file()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(project / "src"))
    from camera_assistant.knowledge.importer import import_path, parse_record_file
    from camera_assistant.knowledge.models import KnowledgeRecord
    from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
    from camera_assistant.knowledge.store import KnowledgeStore
    from camera_assistant.knowledge.uploads import UploadedRecordFile, commit_preview, preview_uploads

    main_db = project / "data/knowledge.db"

    def snapshot():
        if not main_db.exists():
            return {"executed": False, "reason": "existing main database absent"}, []
        # KnowledgeStore initialization writes, so do not instantiate it for the main DB.
        with sqlite3.connect(main_db.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            rows = conn.execute("SELECT knowledge_id,version,library_id,record_json,status,content_hash FROM revisions ORDER BY knowledge_id,version").fetchall()
            audit = conn.execute("SELECT * FROM audit_entries ORDER BY audit_id").fetchall()
        records = [KnowledgeRecord.model_validate(json.loads(row[3])) for row in rows]
        return {"executed": True, "access": "sqlite mode=ro", "file_sha256": digest(main_db),
                "logical_sha256": hashlib.sha256(json.dumps([rows, audit], ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                "revision_count": len(rows), "audit_count": len(audit)}, records

    before, main_records = snapshot()
    baseline_files = sorted(path for path in (project / "data/knowledge_drafts").rglob("*")
                            if path.is_file() and not path.resolve().is_relative_to(root)
                            and ("upload_cards" in path.parts or "starter-v1" in path.parts)
                            and path.suffix in {".json", ".yaml", ".yml", ".md"})
    baseline_records = [parse_record_file(path) for path in baseline_files] + main_records
    existing_ids = {record.knowledge_id for record in baseline_records}
    existing_titles = {record.title for record in baseline_records}
    code_files = sorted((project / "src/camera_assistant/knowledge").glob("*.py"))
    protected = baseline_files + code_files
    protected_before = {str(path.relative_to(project)): digest(path) for path in protected}
    paths = sorted((root / "upload_cards").rglob("*.json"))
    cards = [parse_record_file(path) for path in paths]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert len(cards) == manifest["card_count"] == 22
    assert len({card.knowledge_id for card in cards}) == len({card.title for card in cards}) == 22
    assert not existing_ids.intersection(card.knowledge_id for card in cards)
    assert not existing_titles.intersection(card.title for card in cards)
    for item in manifest["cards"]:
        assert digest(root / item["path"]) == item["sha256"]
    registry = json.loads((root / "sources/source_registry.json").read_text(encoding="utf-8"))
    sources = {source["source_id"]: source for source in registry["sources"]}
    assert len(sources) == 24
    models = set()
    used_sources = set()
    related_ids_not_in_current_project = set()
    for card in cards:
        assert card.library_id == "equipment" and card.kind == "manufacturer_fact"
        assert card.author == "符梁" and card.version == 1 and card.schema_version == 1
        assert card.source.retrieval_allowed is False
        assert card.dataset_split == "reference"
        refs = card.payload["sources"]
        ref_ids = {ref["source_id"] for ref in refs}
        assert ref_ids <= sources.keys()
        used_sources.update(ref_ids)
        assert card.source.url in {ref["original_url"] for ref in refs}
        for ref in refs:
            for field in ["original_url", "publisher", "actual_read_scope", "region", "document_version", "tool"]:
                assert ref[field] == sources[ref["source_id"]][field]
            assert ref["retrieval_allowed"] is False and ref["accessed_at"] == "2026-10-14"
        profiles = {profile["model_variant"]: profile for profile in card.payload["equipment_profiles"]}
        names = card.conditions["camera_model"]
        if isinstance(names, str):
            names = [names]
        assert set(profiles) == set(names) and not models.intersection(names)
        models.update(names)
        for profile in profiles.values():
            assert profile["iso_range"] is None and profile["shutter_seconds_range"] is None
            assert profile["actual_firmware"] is None and profile["actual_camera_app_version"] is None
            assert set(profile["evidence_source_ids"]) <= ref_ids
            assert all(module["actual_focal_length_mm"] is None for module in profile["declared_rear_modules"])
        for fact in card.payload["facts"]:
            profile = profiles[fact["conditions"]["model_variant"]]
            module = next(module for module in profile["declared_rear_modules"]
                          if module["module"] == fact["conditions"]["camera_module"])
            assert module[fact["field"]] == fact["value"]
            assert fact["conditions"]["capture_mode"] == "still_photo"
            assert fact["conditions"]["region_scope"] == card.conditions["region_scope"]
            assert set(fact["source_ids"]) == set(profile["evidence_source_ids"])
        assert all(operation["evidence_type"] == "untested_advice" for operation in card.payload["operations"])
        assert not card.payload["verification"]["device_tested"]
        assert not card.payload["verification"]["independent_human_review"]
        related_ids_not_in_current_project.update(set(card.payload["deduplication"]["related_existing_ids"]) - existing_ids)
    assert len(models) == 27
    assert used_sources == {source_id for source_id, source in sources.items() if source["purpose"] == "card"}

    env = dict(os.environ, PYTHONPATH=str(project / "src"), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, "-B", "-m", "camera_assistant.knowledge", "import", str(root / "upload_cards"), "--dry-run"],
                          cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", check=False)
    dry_run = json.loads(proc.stdout)
    assert proc.returncode == 0 and dry_run["data"]["validated_count"] == 22
    assert dry_run["data"]["imported_count"] == 0 and dry_run["data"]["dry_run"]

    temp_parent = root / ".verification-temp"
    temp_parent.mkdir(exist_ok=True)
    old_tempdir = tempfile.tempdir
    tempfile.tempdir = str(temp_parent)
    try:
        groups = [sorted((root / "upload_cards" / batch).glob("*.json")) for batch in ["batch-01", "batch-02"]]
        assert [len(group) for group in groups] == [20, 2]
        batches = [[UploadedRecordFile(path.name, path.read_bytes()) for path in group] for group in groups]
        previews = [preview_uploads(batch) for batch in batches]
        assert all(preview.success for preview in previews)
        with tempfile.TemporaryDirectory(prefix="mobile-upload-") as directory:
            temporary_root = Path(directory).resolve()
            assert temporary_root.is_relative_to(temp_parent.resolve())
            db = temporary_root / "isolated.db"
            assert db != main_db.resolve() and not db.exists()
            store = KnowledgeStore(db)
            assert store.list_revisions() == []
            first = [commit_preview(store, preview) for preview in previews]
            assert all(report.success for report in first) and [report.imported_count for report in first] == [20, 2]
            revisions = store.list_revisions()
            assert len(revisions) == 22
            assert all(revision.status == "draft" and not revision.record.source.retrieval_allowed for revision in revisions)
            assert {revision.record.knowledge_id: revision.record.model_dump() for revision in revisions} == {card.knowledge_id: card.model_dump() for card in cards}
            assert store.list_revisions(status="published") == []
            repeat = [commit_preview(store, preview_uploads(batch)) for batch in batches]
            assert all(report.success and report.imported_count == 0 for report in repeat)
            assert sum(report.unchanged_count for report in repeat) == 22
            repeated_directory = import_path(store, root / "upload_cards")
            assert repeated_directory.success and repeated_directory.imported_count == 0 and repeated_directory.unchanged_count == 22
            assert len(store.list_revisions()) == len(store.audit_log()) == 22
            retriever = ManagedKnowledgeRetriever(store)
            probes = 0
            for card in cards:
                for profile in card.payload["equipment_profiles"]:
                    observed = dict(card.conditions, camera_model=profile["model_variant"])
                    assert retriever._applicable(card.conditions, observed)
                    assert not retriever._applicable(card.conditions, dict(observed, camera_model="uncovered-model"))
                    assert not retriever._applicable(card.conditions, dict(observed, region_scope="unverified-region"))
                    assert not retriever._applicable(card.conditions, None)
                    assert retriever.search(card.title, libraries=["equipment"], conditions=observed) == []
                    assert retriever.query_structured("equipment", filters={"core_conclusion": card.payload["core_conclusion"]}, conditions=observed) == []
                    probes += 1
            assert probes == 27
        cleaned = not temporary_root.exists()
        assert cleaned
    finally:
        tempfile.tempdir = old_tempdir
        temp_parent.rmdir()  # Remove only the empty directory; no recursive deletion.

    after, _ = snapshot()
    assert before == after
    assert protected_before == {str(path.relative_to(project)): digest(path) for path in protected}
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip()
    report = {
        "passed": True, "project_git_head": git_head, "author": "符梁", "cards": 22, "models": 27, "sources": 24,
        "existing_repository_record_files": len(baseline_files), "existing_main_database_records": len(main_records),
        "existing_distinct_knowledge_ids": len(existing_ids), "duplicate_ids": 0, "duplicate_titles": 0,
        "related_ids_not_in_current_project": sorted(related_ids_not_in_current_project),
        "main_database_before": before, "main_database_after": after,
        "main_database_unchanged": True if before["executed"] else None,
        "model_schema_fields": list(KnowledgeRecord.model_fields), "knowledge_code_sha256": {str(path.relative_to(project)): digest(path) for path in code_files},
        "checks": {"strict_model": True, "manifest_card_bytes": True, "source_model_module_region_binding": True,
                   "cli_dry_run": {"returncode": proc.returncode, "validated": 22, "imported": 0, "stderr": proc.stderr},
                   "upload_preview_batch_sizes": [20, 2], "isolated_draft_write": 22, "published": 0,
                   "repeat_upload_added": 0, "repeat_upload_unchanged": 22,
                   "repeat_directory_import_added": 0, "repeat_directory_import_unchanged": 22,
                   "isolated_audit_entries": 22, "model_condition_probes": 27,
                   "keyword_and_structured_hits": 0, "temporary_database_removed": cleaned,
                   "existing_cards_and_knowledge_code_unchanged": True},
        "limits": ["Existing ID/title scans do not prove absence of semantic overlap; independent review is pending.",
                   "Retrieval probes cover draft plus retrieval_allowed=false together, not each independent branch.",
                   "Source linkage checks do not re-open websites or establish firmware, device behavior or rights."],
        "not_executed": ["workbench browser upload", "physical device test", "independent human fact review", "copyright permission verification", "review and publication", "runtime model registration"]
    }
    output = root / "reports/current-repository-validation.json"
    output.parent.mkdir(exist_ok=True)
    output.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({key: report[key] for key in ["passed", "project_git_head", "cards", "models", "sources", "existing_distinct_knowledge_ids", "main_database_unchanged"]}))


if __name__ == "__main__":
    main()
